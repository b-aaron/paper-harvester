"""
zotero_client.py - Integrates with the Zotero API to save scraped articles.

Supports both personal user libraries and group libraries.
Full Zotero API documentation: https://www.zotero.org/support/dev/web_api/v3/start

Requires the `pyzotero` package: pip install pyzotero
"""

import os
from typing import Dict, List, Optional

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

        self.zot = zotero.Zotero(library_id, library_type, api_key)
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
            existing = self.zot.items(q=article.doi)
            if existing:
                print(f"    [SKIP] DOI already in Zotero: {article.doi}")
                return None

        item = self.zot.item_template("journalArticle")
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
        item["abstractNote"] = article.abstract or ""
        item["tags"] = [{"tag": kw} for kw in article.keywords]
        item["ISSN"] = article.issn or ""

        if self.collection_key:
            item["collections"] = [self.collection_key]

        resp = self.zot.create_items([item])
        created = resp.get("successful", {})
        if created:
            key = list(created.values())[0].get("key")
            print(f"    ✓ Saved (key: {key})")
            return key

        return None

    def _attach_pdf(self, item_key: str, pdf_path: str) -> None:
        """
        Attach a local PDF file to an existing Zotero item.

        Args:
            item_key: Zotero item key to attach the PDF to.
            pdf_path: Absolute local path to the PDF file.
        """
        try:
            self.zot.attachment_simple([pdf_path], parentid=item_key)
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
        collections = self.zot.collections()
        for col in collections:
            if col["data"]["name"] == name:
                return col["key"]

        # Create new collection
        resp = self.zot.create_collections([{"name": name, "parentCollection": False}])
        created = resp.get("successful", {})
        if created:
            col_key = list(created.values())[0].get("key")
            print(f"  ✓ Created Zotero collection: '{name}' (key: {col_key})")
            return col_key

        raise RuntimeError(f"Failed to create Zotero collection '{name}'.")
