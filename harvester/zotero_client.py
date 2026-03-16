"""
zotero_client.py - Integrates with the Zotero API to save scraped articles.

Supports both personal user libraries and group libraries.
Full Zotero API documentation: https://www.zotero.org/support/dev/web_api/v3/start

Requires the `pyzotero` package: pip install pyzotero
"""

import html
import os
import re
from typing import Callable, Dict, List, Optional, TypeVar
from urllib.parse import quote

import certifi
import httpx

from .scrapers.base_scraper import Article


class ZoteroClient:
    """
    Saves Article objects to a Zotero library via the Zotero Web API.

    Each article is saved as a 'journalArticle' item.  If a local PDF is
    available it is attached as a file attachment.
    """

    def __init__(
        self,
        library_id: str,
        api_key: str,
        library_type: str = "user",
        collection_name: Optional[str] = None,
    ):
        """
        Initialize the Zotero client.

        Args:
            library_id: Numeric Zotero user ID or group ID (string).
            api_key: Zotero API key with write access.
            library_type: 'user' for personal library, 'group' for shared group.
            collection_name: Optional name of a Zotero collection to save items
                into (created if it does not exist).

        Raises:
            ImportError: If the pyzotero package is not installed.
        """
        try:
            from pyzotero import zotero
        except ImportError as exc:
            raise ImportError(
                "pyzotero is required for Zotero integration. "
                "Install it with: pip install pyzotero"
            ) from exc

        self._zotero_ctor = zotero.Zotero
        self._library_id = library_id
        self._api_key = api_key
        self._library_type = library_type
        self._using_direct_transport = False
        self._abstract_cache: Dict[str, Optional[str]] = {}

        # First try environment transport (default behavior). If it fails with
        # SSL/proxy transport issues, we transparently fail over to direct TLS.
        self.zot = self._build_zotero_client(trust_env=True)
        self._probe_connection()
        self.collection_key: Optional[str] = None

        if collection_name:
            self.collection_key = self._get_or_create_collection(collection_name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_articles(self, articles: List[Article]) -> Dict[str, int]:
        """
        Save a list of articles to the Zotero library.

        Args:
            articles: List of Article objects to save.

        Returns:
            Dict with keys 'saved', 'failed', 'skipped' (duplicate check).
        """
        stats = {"saved": 0, "failed": 0, "skipped": 0}
        total = len(articles)

        for idx, article in enumerate(articles, 1):
            print(f"  [{idx}/{total}] Saving to Zotero: {article.title[:60]}...")
            try:
                item_key = self._save_article(article)
                if item_key:
                    stats["saved"] += 1
                    # Attach PDF if available
                    if article.pdf_path and os.path.isfile(article.pdf_path):
                        self._attach_pdf(item_key, article.pdf_path)
                else:
                    stats["skipped"] += 1
            except Exception as exc:
                print(f"    [ERROR] Could not save article to Zotero: {exc}")
                stats["failed"] += 1

        return stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _T = TypeVar("_T")

    def _build_zotero_client(self, trust_env: bool):
        """Create a pyzotero client backed by a tuned httpx transport."""
        zot = self._zotero_ctor(
            self._library_id,
            self._library_type,
            self._api_key,
        )
        headers = zot.default_headers()

        # Replace pyzotero's default client so we can control proxy/env usage.
        try:
            if getattr(zot, "client", None) is not None:
                zot.client.close()
        except Exception:
            pass

        zot.client = httpx.Client(
            headers=headers,
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
            verify=certifi.where(),
            trust_env=trust_env,
            http2=False,
        )
        return zot

    def _close_http_client(self) -> None:
        """Close underlying httpx client if available."""
        client = getattr(self.zot, "client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _exception_chain(exc: BaseException):
        current = exc
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = current.__cause__ or current.__context__

    def _is_transport_error(self, exc: BaseException) -> bool:
        """
        Detect SSL/proxy transport failures where retrying with trust_env=False
        is appropriate.
        """
        if self._using_direct_transport:
            return False

        text = " | ".join(str(e) for e in self._exception_chain(exc)).lower()
        markers = (
            "eof occurred in violation of protocol",
            "ssleoferror",
            "ssl",
            "tls",
            "proxyerror",
            "http_proxy",
            "connecterror",
            "max retries exceeded",
            "wrong version number",
            "connection reset",
        )
        return any(marker in text for marker in markers)

    def _switch_to_direct_transport(self) -> None:
        """Rebuild client with trust_env=False to bypass broken system proxy settings."""
        self._close_http_client()
        self.zot = self._build_zotero_client(trust_env=False)
        self._using_direct_transport = True

    def _api_call(self, call: Callable[[], _T]) -> _T:
        """
        Execute a Zotero API call. If transport fails due to SSL/proxy issues,
        transparently retry once using direct TLS transport.
        """
        try:
            return call()
        except Exception as exc:
            if self._is_transport_error(exc):
                print(
                    "  [WARN] Zotero HTTPS transport failed; retrying with "
                    "direct TLS (trust_env=False)."
                )
                self._switch_to_direct_transport()
                return call()
            raise

    def _probe_connection(self) -> None:
        """Warm-up API call so transport fallback is applied before writes."""
        self._api_call(lambda: self.zot.collections(limit=1))

    def _save_article(self, article: Article) -> Optional[str]:
        """
        Create a Zotero 'journalArticle' item from an Article object.

        Checks for an existing item with the same DOI to avoid duplicates.

        Args:
            article: Article to save.

        Returns:
            Zotero item key string on success, or None on duplicate / failure.
        """
        # Duplicate check by DOI
        if article.doi:
            existing = self._find_existing_item_by_doi(article.doi)
            if existing:
                print(f"    [SKIP] DOI already in Zotero: {article.doi}")
                self._update_existing_item(existing, article)
                return None

        item = self._api_call(lambda: self.zot.item_template("journalArticle"))
        item["title"] = article.title
        item["creators"] = [
            {
                "creatorType": "author",
                "firstName": " ".join(name.split()[:-1]) if len(name.split()) > 1 else "",
                "lastName": name.split()[-1] if name.split() else name,
            }
            for name in article.authors
        ]
        item["publicationTitle"] = article.journal
        item["volume"] = article.volume or ""
        item["issue"] = article.issue or ""
        item["pages"] = article.pages or ""
        item["date"] = str(article.year) if article.year else ""
        item["DOI"] = article.doi or ""
        item["url"] = article.url or ""
        item["abstractNote"] = self._resolve_abstract(article) or ""
        item["tags"] = [{"tag": kw} for kw in article.keywords]
        item["ISSN"] = article.issn or ""

        if self.collection_key:
            item["collections"] = [self.collection_key]

        resp = self._api_call(lambda: self.zot.create_items([item]))
        created = resp.get("successful", {})
        if created:
            key = list(created.values())[0].get("key")
            print(f"    ✓ Saved (key: {key})")
            return key

        return None

    @staticmethod
    def _normalize_doi(doi: Optional[str]) -> str:
        if not doi:
            return ""
        return doi.strip().lower()

    def _find_existing_item_by_doi(self, doi: str) -> Optional[Dict]:
        """
        Find existing Zotero item by DOI with an exact normalized DOI match.
        Falls back to first search hit when strict match metadata is missing.
        """
        hits = self._api_call(lambda: self.zot.items(q=doi))
        if not hits:
            return None

        target = self._normalize_doi(doi)
        for hit in hits:
            data = hit.get("data", {})
            if self._normalize_doi(data.get("DOI")) == target:
                return hit

        return hits[0]

    def _resolve_abstract(self, article: Article) -> Optional[str]:
        """
        Return abstract text for Zotero sync.

        Priority:
        1) article.abstract from scraper payload
        2) Crossref DOI lookup fallback (for lightweight/derived imports)
        """
        if article.abstract and article.abstract.strip():
            return article.abstract.strip()

        doi = self._normalize_doi(article.doi)
        if not doi:
            return None

        if doi in self._abstract_cache:
            return self._abstract_cache[doi]

        fetched = self._fetch_crossref_abstract(doi)
        self._abstract_cache[doi] = fetched
        if fetched:
            print(f"    ↳ Abstract enriched from Crossref for DOI: {doi}")
        return fetched

    def _fetch_crossref_abstract(self, doi: str) -> Optional[str]:
        """
        Fetch abstract from Crossref when local article metadata is missing it.

        Uses trust_env=False to avoid proxy/TLS interference seen in this
        environment.
        """
        url = f"https://api.crossref.org/works/{quote(doi)}"
        try:
            with httpx.Client(
                timeout=httpx.Timeout(20.0),
                verify=certifi.where(),
                trust_env=False,
                follow_redirects=True,
                http2=False,
            ) as client:
                resp = client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "paper-harvester-grounded-zotero/1.0",
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
            raw = payload.get("message", {}).get("abstract")
            if not raw:
                return None
            return self._strip_jats(raw)
        except Exception as exc:
            print(f"    [WARN] Could not fetch abstract from Crossref for DOI {doi}: {exc}")
            return None

    @staticmethod
    def _strip_jats(text: str) -> str:
        """Remove JATS/XML tags and normalize whitespace."""
        plain = re.sub(r"<[^>]+>", " ", text or "")
        plain = html.unescape(plain)
        plain = re.sub(r"\s+", " ", plain).strip()
        return plain

    def _update_existing_item(self, existing_item: Dict, article: Article) -> None:
        """
        For duplicate DOI items, keep collection membership and abstractNote in
        sync when needed.
        """
        try:
            data = dict(existing_item.get("data", {}))
            collections = list(data.get("collections", []))
            payload = dict(existing_item)
            changed = False

            if self.collection_key and self.collection_key not in collections:
                data["collections"] = collections + [self.collection_key]
                changed = True

            if not (data.get("abstractNote") or "").strip():
                resolved_abstract = self._resolve_abstract(article)
                if resolved_abstract:
                    data["abstractNote"] = resolved_abstract
                    changed = True

            if not changed:
                return

            payload["data"] = data
            resp = self._api_call(lambda: self.zot.update_item(payload))
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            print(f"    ↳ Updated existing DOI metadata: {article.doi or article.title}")
        except Exception as exc:
            print(f"    [WARN] Could not update existing DOI metadata: {exc}")

    def _attach_pdf(self, item_key: str, pdf_path: str) -> None:
        """
        Attach a local PDF file to an existing Zotero item.

        Args:
            item_key: Zotero item key to attach the PDF to.
            pdf_path: Absolute local path to the PDF file.
        """
        try:
            self._api_call(lambda: self.zot.attachment_simple([pdf_path], parentid=item_key))
            print(f"    ✓ PDF attached: {os.path.basename(pdf_path)}")
        except Exception as exc:
            print(f"    [WARN] Could not attach PDF: {exc}")

    def _get_or_create_collection(self, name: str) -> str:
        """
        Return the key of a Zotero collection with the given name, creating
        it if it does not already exist.

        Args:
            name: Human-readable collection name.

        Returns:
            Zotero collection key string.
        """
        collections = self._api_call(lambda: self.zot.collections())
        for col in collections:
            if col["data"]["name"] == name:
                return col["key"]

        # Create new collection
        resp = self._api_call(
            lambda: self.zot.create_collections([{"name": name, "parentCollection": False}])
        )
        created = resp.get("successful", {})
        if created:
            col_key = list(created.values())[0].get("key")
            print(f"  ✓ Created Zotero collection: '{name}' (key: {col_key})")
            return col_key

        raise RuntimeError(f"Failed to create Zotero collection '{name}'.")
