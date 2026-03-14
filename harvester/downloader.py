"""
downloader.py - Downloads full-text PDFs for academic articles.

Download strategy (in order of preference):
    1. Open-access links from hints / scraper / Unpaywall / OpenAlex.
    2. Publisher and ResearchGate link heuristics.
    3. Google Scholar fallback via the `scholarly` library.

If all strategies fail, the article is recorded with no local PDF path
so the metadata is still saved to Excel / Zotero.
"""

import os
import re
import time
import importlib
import json
import random
from typing import Any, Dict, List, Optional, cast

from urllib.parse import quote
from urllib.parse import urlparse
from urllib.parse import parse_qs, unquote

import requests

from .scrapers.base_scraper import Article


class PDFDownloader:
    """
    Downloads PDFs for Article objects using a cascade of strategies.

    Usage::

        downloader = PDFDownloader(save_dir="/path/to/pdfs")
        downloader.download(articles)
    """

    def __init__(
        self,
        save_dir: str = ".",
        institutional_credentials: Optional[Dict] = None,
        unpaywall_email: Optional[str] = None,
        debug: bool = True,
        use_google_scholar: bool = True,
        request_timeout: int = 60,
        delay_between_requests: float = 2.0,
    ):
        """
        Initialize the PDF downloader.

        Args:
            save_dir: Directory where PDFs will be saved.
            institutional_credentials: Dict with keys 'org', 'username', 'password'
                for institutional EZProxy login. Pass None to skip.
            unpaywall_email: Email used to query Unpaywall as a download fallback.
            debug: Whether to print per-strategy debug logs for PDF download.
            use_google_scholar: Whether to try Google Scholar as a last resort.
            request_timeout: HTTP request timeout in seconds.
            delay_between_requests: Seconds to wait between download attempts
                to avoid rate-limiting.
        """
        self.save_dir = save_dir
        self.institutional_credentials = institutional_credentials or {}
        self.unpaywall_email = (unpaywall_email or "").strip()
        self.debug = debug
        self.use_google_scholar = use_google_scholar
        self.request_timeout = request_timeout
        self.delay = delay_between_requests
        self._url_hints = self._load_url_hints()

        self.session = requests.Session()
        # Avoid inheriting broken system proxy settings that can cause SSL EOF.
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
            }
        )
        os.makedirs(save_dir, exist_ok=True)
        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(self, articles: List[Article]) -> List[Article]:
        """
        Attempt to download PDFs for a list of articles, updating each
        Article's ``pdf_path`` attribute on success.

        Args:
            articles: List of Article objects (modified in-place).

        Returns:
            The same list with ``pdf_path`` populated where download succeeded.
        """
        total = len(articles)
        for idx, article in enumerate(articles, 1):
            print(f"  [{idx}/{total}] Downloading: {article.title[:70]}...")
            path = self._download_one(article)
            if path:
                article.pdf_path = path
                print(f"    ✓ Saved to {path}")
            else:
                print(f"    ✗ Could not obtain PDF for this article.")
            time.sleep(self.delay)
        return articles

    # ------------------------------------------------------------------
    # Strategy cascade
    # ------------------------------------------------------------------

    def _download_one(self, article: Article) -> Optional[str]:
        """
        Try each download strategy in order and return the local file path
        on the first success.

        Args:
            article: Article to download.

        Returns:
            Local path to the saved PDF, or None on failure.
        """
        filename = self._build_filename(article)
        self._debug(
            f"Start article: doi={article.doi or 'N/A'}, journal={article.journal or 'N/A'}"
        )
        self._debug(f"Target filename: {filename}")

        # 1. Try known / resolved open-access URLs first.
        oa_candidates = self._resolve_oa_candidates(article)
        self._debug(f"OA candidate count: {len(oa_candidates)}")
        for source, url in oa_candidates:
            if self._should_skip_candidate(source, url):
                continue
            self._debug(f"Trying OA source={source}: {self._short_url(url)}")
            if self._looks_like_direct_pdf_url(url):
                path = self._download_url(url, filename)
            else:
                path = self._try_doi_redirect(url, filename)
            if path:
                self._debug(f"Success via OA source={source}")
                return path
        self._debug("OA candidates exhausted")

        # 2. Try the article's canonical DOI URL directly
        if article.doi_url:
            self._debug(f"Trying DOI URL: {self._short_url(article.doi_url)}")
            path = self._try_doi_redirect(article.doi_url, filename)
            if path:
                self._debug("Success via DOI URL")
                return path
            self._debug("DOI URL strategy failed")

        # 2b. Try article URL from metadata if different from DOI URL.
        if article.url and article.url != article.doi_url:
            self._debug(f"Trying metadata URL: {self._short_url(article.url)}")
            path = self._try_doi_redirect(article.url, filename)
            if path:
                self._debug("Success via metadata URL")
                return path
            self._debug("Metadata URL strategy failed")

        # 3. Google Scholar fallback
        if self.use_google_scholar:
            self._debug("Trying Google Scholar fallback")
            path = self._try_google_scholar(article, filename)
            if path:
                self._debug("Success via Google Scholar")
                return path
            self._debug("Google Scholar fallback failed")

        # 4. Sci-Hub fallback
        self._debug("Trying Sci-Hub fallback")
        path = self._try_scihub(article, filename)
        if path:
            self._debug("Success via Sci-Hub")
            return path
        self._debug("Sci-Hub fallback failed")

        self._debug("All PDF strategies failed")
        return None

    def _resolve_oa_candidates(self, article: Article) -> List[tuple[str, str]]:
        """Build candidate OA URLs using scraped metadata and OA resolvers."""
        seen = set()
        candidates: List[tuple[str, str]] = []

        def _add(source: str, url: Optional[str]) -> bool:
            if not url:
                return False
            clean = url.strip()
            if not clean or clean in seen:
                if clean in seen:
                    self._debug(f"Skip duplicate OA URL from {source}: {self._short_url(clean)}")
                return False
            seen.add(clean)
            candidates.append((source, clean))
            return True

        def _add_many(source: str, urls: List[str]) -> None:
            added = 0
            for u in urls:
                if _add(source, u):
                    added += 1
            if urls:
                self._debug(f"Resolved {source} links: raw={len(urls)}, added={added}")

        _add_many("url_hint", self._hinted_urls(article))
        _add("scraper", article.oa_pdf_url)
        _add_many("researchgate", self._researchgate_urls(article))
        _add_many("researchgate_pdf", self._researchgate_pdf_urls(article))
        _add_many("unpaywall", self._unpaywall_oa_urls(article.doi))
        _add_many("openalex", self._openalex_oa_urls(article.doi))

        for link in self._crossref_pdf_links(article):
            _add("crossref_link", link)

        for link in self._publisher_heuristic_pdf_links(article):
            _add("publisher_heuristic", link)

        return candidates

    def _load_url_hints(self) -> Dict[str, Any]:
        """Load optional DOI/title URL hints from config/url_hints.json."""
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "config", "url_hints.json")
        )
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _hinted_urls(self, article: Article) -> List[str]:
        """Return user-provided URL hints for a specific DOI/title."""
        urls: List[str] = []
        by_doi = self._url_hints.get("doi", {}) if isinstance(self._url_hints, dict) else {}
        by_title = self._url_hints.get("title", {}) if isinstance(self._url_hints, dict) else {}

        if article.doi and isinstance(by_doi, dict):
            value = by_doi.get(article.doi)
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
            elif isinstance(value, list):
                urls.extend([x.strip() for x in value if isinstance(x, str) and x.strip()])

        if article.title and isinstance(by_title, dict):
            value = by_title.get(article.title)
            if isinstance(value, str) and value.strip():
                urls.append(value.strip())
            elif isinstance(value, list):
                urls.extend([x.strip() for x in value if isinstance(x, str) and x.strip()])

        return urls

    def _publisher_heuristic_pdf_links(self, article: Article) -> List[str]:
        """Generate publisher-specific PDF URL guesses for known URL patterns."""
        links: List[str] = []
        article_url = (article.url or "").strip()
        if not article_url:
            return links

        parsed = urlparse(article_url)
        host = parsed.netloc.lower()

        # Oxford Academic (OUP) common pattern:
        # /<journal>/advance-article/doi/<doi>/<id>
        # -> /<journal>/advance-article-pdf/doi/<doi>/<id>/<doi_suffix>.pdf
        if "academic.oup.com" in host and "/advance-article/doi/" in parsed.path and article.doi:
            doi_suffix = article.doi.split("/")[-1]
            base_pdf_path = parsed.path.replace("/advance-article/doi/", "/advance-article-pdf/doi/")
            links.append(f"https://{host}{base_pdf_path}/{doi_suffix}.pdf")
            links.append(f"https://{host}{base_pdf_path}/{doi_suffix}.pdf?login=false")

        return links

    def _researchgate_urls(self, article: Article) -> List[str]:
        """Discover candidate ResearchGate publication URLs via search."""
        candidates: List[str] = []
        queries: List[str] = []

        if article.doi:
            queries.append(f'site:researchgate.net/publication "{article.doi}"')
        if article.title:
            queries.append(f'site:researchgate.net/publication "{article.title}"')

        seen = set()
        for query in queries:
            for url in self._duckduckgo_result_urls(query):
                low = url.lower()
                if "researchgate.net" not in low:
                    continue
                if "/publication/" not in low and ".pdf" not in low:
                    continue
                clean = url.split("#", 1)[0]
                if clean in seen:
                    continue
                seen.add(clean)
                candidates.append(clean)
                # Keep it conservative; first few search hits are enough.
                if len(candidates) >= 3:
                    return candidates
        return candidates

    def _researchgate_pdf_urls(self, article: Article) -> List[str]:
        """Resolve likely direct PDF URLs from ResearchGate candidate pages."""
        results: List[str] = []
        seen = set()

        def _add(url: Optional[str]) -> None:
            if not isinstance(url, str):
                return
            clean = url.strip()
            if not clean:
                return
            low = clean.lower()
            if "researchgate.net" not in low:
                return
            if clean in seen:
                return
            seen.add(clean)
            results.append(clean)

        for rg_url in self._researchgate_urls(article):
            low = rg_url.lower()

            # Direct file links often come with long tracking query params.
            # Prefer stripped URL first to avoid anti-bot signed-query churn.
            if ".pdf" in low:
                _add(rg_url.split("?", 1)[0])
                _add(rg_url)
                continue

            try:
                resp = self.session.get(
                    rg_url,
                    timeout=min(self.request_timeout, 20),
                    headers={"Referer": "https://www.researchgate.net/"},
                )
                if resp.status_code != 200 or "text/html" not in resp.headers.get("Content-Type", ""):
                    continue
                for link in self._extract_pdf_links(resp.text, resp.url):
                    if "researchgate.net" in link.lower() and ".pdf" in link.lower():
                        _add(link.split("?", 1)[0])
                        _add(link)
            except Exception:
                continue

        return results

    def _should_skip_candidate(self, source: str, url: str) -> bool:
        """Short-circuit candidates that are very likely invalid or blocked."""
        if source not in ("researchgate_pdf", "url_hint"):
            return False

        low = url.lower()
        if "researchgate.net" not in low:
            return False

        if self._looks_like_direct_pdf_url(url):
            return not self._preflight_pdf_candidate(url)
        return False

    def _preflight_pdf_candidate(self, url: str) -> bool:
        """Use a lightweight HEAD (and fallback GET probe) to avoid dead PDF links."""
        probe_headers = self._random_request_headers(url)
        probe_timeout = min(8, self.request_timeout)

        candidates = [url]
        if "?" in url:
            stripped = url.split("?", 1)[0]
            if stripped and stripped not in candidates:
                candidates.insert(0, stripped)

        for probe_url in candidates:
            try:
                head = self.session.head(
                    probe_url,
                    timeout=probe_timeout,
                    allow_redirects=True,
                    headers=probe_headers,
                )
                ctype = (head.headers.get("Content-Type") or "").lower()
                if head.status_code == 200 and ("pdf" in ctype or ".pdf" in probe_url.lower()):
                    return True
                if head.status_code in (401, 403, 404, 410):
                    self._debug(
                        f"Preflight skip {self._short_url(probe_url)} "
                        f"(status={head.status_code}, content-type={ctype or 'N/A'})"
                    )
                    continue
            except requests.RequestException:
                pass

            # Some hosts don't support HEAD properly; use tiny GET probe.
            try:
                get_resp = self.session.get(
                    probe_url,
                    timeout=probe_timeout,
                    stream=True,
                    headers=probe_headers,
                )
                ctype = (get_resp.headers.get("Content-Type") or "").lower()
                ok_pdf = get_resp.status_code == 200 and ("pdf" in ctype or ".pdf" in probe_url.lower())
                get_resp.close()
                if ok_pdf:
                    return True
                if get_resp.status_code in (401, 403, 404, 410):
                    self._debug(
                        f"Preflight GET skip {self._short_url(probe_url)} "
                        f"(status={get_resp.status_code}, content-type={ctype or 'N/A'})"
                    )
            except requests.RequestException:
                continue

        return False

    def _duckduckgo_result_urls(self, query: str) -> List[str]:
        """Get result URLs from DuckDuckGo HTML results page."""
        urls: List[str] = []
        try:
            resp = self.session.get(
                "https://duckduckgo.com/html/",
                params={"q": query},
                timeout=min(self.request_timeout, 20),
                headers={"Referer": "https://duckduckgo.com/"},
            )
            if resp.status_code != 200:
                return urls

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup.select("a.result__a[href]"):
                href = (tag.get("href") or "").strip()
                if not href:
                    continue

                # DuckDuckGo redirect format: /l/?uddg=<url_encoded>
                if "uddg=" in href:
                    parsed = urlparse(href)
                    q = parse_qs(parsed.query)
                    uddg = q.get("uddg", [""])[0]
                    if uddg:
                        href = unquote(uddg)

                if href.startswith("http"):
                    urls.append(href)
                if len(urls) >= 8:
                    break
        except Exception:
            return urls
        return urls

    def _crossref_pdf_links(self, article: Article) -> List[str]:
        """Extract publisher-provided PDF links from raw CrossRef metadata."""
        results: List[str] = []
        raw = article.raw or {}
        links = raw.get("link", []) if isinstance(raw, dict) else []
        if not isinstance(links, list):
            return results

        for item in links:
            if not isinstance(item, dict):
                continue
            href = item.get("URL") or item.get("url")
            ctype = (item.get("content-type") or "").lower()
            intent = (item.get("content-version") or "").lower()
            if not isinstance(href, str) or not href.strip():
                continue
            if "pdf" in ctype or "vor" in intent or href.lower().endswith(".pdf"):
                results.append(href.strip())
        return results

    @staticmethod
    def _looks_like_direct_pdf_url(url: str) -> bool:
        """Heuristic for whether a URL is likely to be a direct PDF endpoint."""
        low = url.lower()
        parsed = urlparse(url)
        path = parsed.path.lower()
        return path.endswith(".pdf") or ".pdf" in low or "/pdf" in path or "download" in low

    def _unpaywall_oa_urls(self, doi: Optional[str]) -> List[str]:
        """Query Unpaywall for OA URLs using the unpywall library."""
        urls: List[str] = []
        if not doi or not self.unpaywall_email or "@" not in self.unpaywall_email:
            return urls
        self._debug(f"Querying unpaywall for DOI: {doi}")

        # On Windows, requests reads proxy settings from the registry even when
        # HTTP_PROXY env vars are absent.  The only reliable way to bypass this
        # for a third-party library (unpywall) that owns its own session is to:
        #   1. Clear all proxy env vars.
        #   2. Set NO_PROXY=* so requests treats every host as proxy-exempt.
        # requests explicitly supports "*" as a wildcard in NO_PROXY.
        proxy_vars = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
        no_proxy_vars = ("NO_PROXY", "no_proxy")
        saved: Dict[str, str] = {}
        for var in (*proxy_vars, *no_proxy_vars):
            val = os.environ.get(var)
            if val is not None:
                saved[var] = val
        for var in proxy_vars:
            os.environ.pop(var, None)
        os.environ["NO_PROXY"] = "*"
        os.environ["no_proxy"] = "*"
        try:
            from unpywall import Unpywall
            from unpywall.utils import UnpywallCredentials

            UnpywallCredentials(self.unpaywall_email)

            # Best PDF link first
            pdf_link = Unpywall.get_pdf_link(doi=doi)
            if isinstance(pdf_link, str) and pdf_link.strip():
                urls.append(pdf_link.strip())

            # All OA links from Unpaywall
            all_links = Unpywall.get_all_links(doi=doi)
            if isinstance(all_links, list):
                for link in all_links:
                    if isinstance(link, str) and link.strip() and link.strip() not in urls:
                        urls.append(link.strip())
            self._debug(f"unpywall returned links: {len(urls)}")
        except ImportError:
            self._debug("unpywall not installed; falling back to direct Unpaywall API")
            urls = self._unpaywall_oa_urls_direct(doi)
        except Exception as exc:
            self._debug(f"unpywall query failed: {exc}")
            urls = self._unpaywall_oa_urls_direct(doi)
        finally:
            for var in (*proxy_vars, *no_proxy_vars):
                if var in saved:
                    os.environ[var] = saved[var]
                else:
                    os.environ.pop(var, None)

        if not urls:
            # If unpywall returns nothing, retry via direct API using our own
            # session that already has trust_env=False.
            urls = self._unpaywall_oa_urls_direct(doi)
            self._debug(f"direct unpaywall API fallback links: {len(urls)}")
        return urls

    def _unpaywall_oa_urls_direct(self, doi: str) -> List[str]:
        """Fallback: direct Unpaywall API query when unpywall library is not installed."""
        urls: List[str] = []
        try:
            resp = self.session.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": self.unpaywall_email},
                timeout=min(self.request_timeout, 20),
            )
            if resp.status_code != 200:
                return urls
            data = resp.json()
            best = data.get("best_oa_location") or {}
            for field in ("url_for_pdf", "url"):
                value = best.get(field)
                if isinstance(value, str) and value.strip():
                    urls.append(value.strip())
            for loc in data.get("oa_locations") or []:
                if not isinstance(loc, dict):
                    continue
                for field in ("url_for_pdf", "url"):
                    value = loc.get(field)
                    if isinstance(value, str) and value.strip():
                        urls.append(value.strip())
        except Exception:
            pass
        return urls

    def _openalex_oa_urls(self, doi: Optional[str]) -> List[str]:
        """Use OpenAlex as an additional OA resolver for DOI-based papers."""
        urls: List[str] = []
        if not doi:
            return urls
        try:
            quoted_doi = quote(f"https://doi.org/{doi}", safe="")
            url = f"https://api.openalex.org/works/{quoted_doi}"
            resp = self.session.get(url, timeout=min(self.request_timeout, 20))
            if resp.status_code != 200:
                return urls
            data = resp.json()
            location = data.get("best_oa_location") or {}
            for field in ("pdf_url", "landing_page_url"):
                value = location.get(field)
                if isinstance(value, str) and value.strip():
                    urls.append(value.strip())

            for loc in data.get("locations") or []:
                if not isinstance(loc, dict) or not loc.get("is_oa"):
                    continue
                for field in ("pdf_url", "landing_page_url"):
                    value = loc.get(field)
                    if isinstance(value, str) and value.strip():
                        urls.append(value.strip())
        except Exception:
            return urls
        return urls

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _download_url(self, url: str, filename: str) -> Optional[str]:
        """
        Download a file from a direct URL.

        Args:
            url: URL pointing to a PDF.
            filename: Base filename (without directory) to save as.

        Returns:
            Full path to saved PDF, or None on failure.
        """
        try:
            resp = None
            # Inspired by resilient downloader patterns: rotate a few user agents
            # before escalating to heavier fallbacks.
            for attempt in range(3):
                headers = self._random_request_headers(url)
                resp = self.session.get(
                    url,
                    timeout=self.request_timeout,
                    stream=True,
                    headers=headers,
                )
                if resp.status_code != 403:
                    break
                self._debug(
                    f"Direct attempt {attempt + 1}/3 got 403 for {self._short_url(url)}"
                )
                time.sleep(0.5)

            if resp is None:
                return None
            self._debug(
                "HTTP "
                f"{resp.status_code}, content-type={resp.headers.get('Content-Type', 'N/A')} "
                f"for {self._short_url(url)}"
            )
            if resp.status_code == 200 and self._is_pdf(resp):
                return self._save_pdf(resp, filename)

            if resp.status_code == 403 and "researchgate.net" in url and "?" in url:
                stripped = url.split("?", 1)[0]
                self._debug("ResearchGate link blocked with query params; retry stripped URL")
                resp2 = self.session.get(stripped, timeout=self.request_timeout, stream=True)
                self._debug(
                    "HTTP "
                    f"{resp2.status_code}, content-type={resp2.headers.get('Content-Type', 'N/A')} "
                    f"for {self._short_url(stripped)}"
                )
                if resp2.status_code == 200 and self._is_pdf(resp2):
                    return self._save_pdf(resp2, filename)

            if resp.status_code == 403:
                self._debug("Got 403; trying Cloudflare-friendly fallback")
                cf_path = self._download_url_via_cloudscraper(url, filename)
                if cf_path:
                    return cf_path
                curl_path = self._download_url_via_curl_cffi(url, filename)
                if curl_path:
                    return curl_path
                browser_path = self._download_url_via_browser(url, filename)
                if browser_path:
                    return browser_path
            if resp.status_code == 200 and not self._is_pdf(resp):
                self._debug("Response is not a PDF, skip")
        except requests.RequestException as exc:
            print(f"    [WARN] Direct download failed ({url[:60]}): {exc}")
        return None

    def _random_request_headers(self, url: str) -> Dict[str, str]:
        """Build request headers with randomized UA and contextual referer."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "researchgate.net" in host:
            referer = "https://www.researchgate.net/"
        elif "academic.oup.com" in host:
            referer = "https://academic.oup.com/"
        else:
            referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else "https://doi.org/"

        return {
            "User-Agent": random.choice(self._user_agents),
            "Referer": referer,
            "Accept": "application/pdf,application/x-pdf;q=0.9,text/html;q=0.5,*/*;q=0.1",
        }

    def _download_url_via_cloudscraper(self, url: str, filename: str) -> Optional[str]:
        """Retry blocked URLs using cloudscraper to handle JS/challenge pages."""
        try:
            cloudscraper = importlib.import_module("cloudscraper")
        except ImportError:
            self._debug("cloudscraper not installed; skip CF fallback")
            return None

        try:
            scraper = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "desktop": True}
            )
            scraper.trust_env = False
            resp = scraper.get(url, timeout=self.request_timeout)
            ctype = resp.headers.get("Content-Type", "")
            self._debug(
                "cloudscraper HTTP "
                f"{resp.status_code}, content-type={ctype} for {self._short_url(url)}"
            )
            if resp.status_code == 200 and (
                "application/pdf" in ctype or "application/x-pdf" in ctype
            ):
                path = os.path.join(self.save_dir, filename)
                with open(path, "wb") as f:
                    f.write(resp.content)
                return path
        except Exception as exc:
            self._debug(f"cloudscraper fallback failed: {exc}")
        return None

    def _download_url_via_curl_cffi(self, url: str, filename: str) -> Optional[str]:
        """Retry blocked URLs using curl_cffi browser impersonation."""
        try:
            curl_requests = importlib.import_module("curl_cffi.requests")
        except ImportError:
            self._debug("curl_cffi not installed; skip curl fallback")
            return None

        try:
            resp = curl_requests.get(
                url,
                impersonate="chrome124",
                timeout=self.request_timeout,
                headers={"Referer": "https://academic.oup.com/"},
            )
            ctype = resp.headers.get("Content-Type", "")
            self._debug(
                "curl_cffi HTTP "
                f"{resp.status_code}, content-type={ctype} for {self._short_url(url)}"
            )
            if resp.status_code == 200 and (
                "application/pdf" in ctype or "application/x-pdf" in ctype
            ):
                path = os.path.join(self.save_dir, filename)
                with open(path, "wb") as f:
                    f.write(resp.content)
                return path
        except Exception as exc:
            self._debug(f"curl_cffi fallback failed: {exc}")
        return None

    def _download_url_via_browser(self, url: str, filename: str) -> Optional[str]:
        """Retry blocked URLs using a real browser (DrissionPage) to bypass Cloudflare."""
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError:
            self._debug("DrissionPage not installed; skip browser fallback. To enable, run: pip install DrissionPage")
            return None

        self._debug("Starting browser to bypass Cloudflare verification...")
        page = None
        try:
            co = ChromiumOptions()
            co.set_argument('--headless=new')
            co.set_argument('--mute-audio')
            # Force PDF to download instead of opening in the built-in viewer
            co.set_pref('plugins.always_open_pdf_externally', True)
            
            page = ChromiumPage(co)
            page.set.download_path(self.save_dir)
            
            self._debug(f"Browser navigating to: {self._short_url(url)}")
            page.get(url)
            
            # Wait for download to start (gives CF Turnstile up to 20 seconds to process)
            mission = page.wait.download_begin(timeout=20)
            if mission:
                self._debug("Browser challenge passed, downloading file...")
                mission.wait()
                
                downloaded_file = mission.path
                if downloaded_file and os.path.exists(downloaded_file):
                    final_path = os.path.join(self.save_dir, filename)
                    import shutil
                    if os.path.abspath(downloaded_file) != os.path.abspath(final_path):
                        shutil.move(downloaded_file, final_path)
                    
                    page.quit()
                    page = None
                    
                    if self._is_valid_saved_pdf(final_path):
                        return final_path
                    else:
                        self._debug("Downloaded file is not a valid PDF.")
                        return None
            else:
                self._debug("No download triggered. Extracting cookies to retry...")
                user_agent = page.user_agent
                cookies_dict = page.cookies(as_dict=True)
                
                if cookies_dict:
                    self._debug("Retrying request with browser cookies...")
                    headers = {
                        "User-Agent": user_agent,
                        "Referer": "https://academic.oup.com/",
                        "Accept": "application/pdf,application/x-pdf;q=0.9,text/html;q=0.5,*/*;q=0.1",
                    }
                    resp = self.session.get(
                        url, headers=headers, cookies=cookies_dict, 
                        timeout=self.request_timeout, stream=True
                    )
                    if resp.status_code == 200 and self._is_pdf(resp):
                        if page:
                            page.quit()
                        return self._save_pdf(resp, filename)
                        
        except Exception as exc:
            self._debug(f"Browser fallback failed: {exc}")
        finally:
            if page:
                try:
                    page.quit()
                except Exception:
                    pass
        return None

    def _try_doi_redirect(self, doi_url: str, filename: str) -> Optional[str]:
        """
        Follow a DOI redirect and attempt to download the resolved PDF.

        Many open-access articles resolve to a page with a direct PDF link.
        We follow the redirect and try to find an embedded PDF URL.

        Args:
            doi_url: https://doi.org/{doi} URL.
            filename: Base filename for saving.

        Returns:
            Full path to saved PDF, or None on failure.
        """
        try:
            # Some publishers honor content negotiation and return the PDF directly.
            pdf_headers = {
                "Accept": "application/pdf,application/x-pdf;q=0.9,text/html;q=0.5,*/*;q=0.1"
            }
            resp = self.session.get(
                doi_url,
                headers=pdf_headers,
                timeout=self.request_timeout,
                allow_redirects=True,
                stream=True,
            )
            if resp.status_code == 200 and self._is_pdf(resp):
                return self._save_pdf(resp, filename)
            self._debug(
                "DOI content-negotiation did not return PDF: "
                f"status={resp.status_code}, content-type={resp.headers.get('Content-Type', 'N/A')}"
            )

            resp = self.session.get(
                doi_url,
                timeout=self.request_timeout,
                allow_redirects=True,
                headers={
                    "Referer": "https://scholar.google.com/",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            self._debug(
                f"DOI resolved URL: {self._short_url(resp.url)} "
                f"(status={resp.status_code}, content-type={resp.headers.get('Content-Type', 'N/A')})"
            )
            if resp.status_code == 200 and self._is_pdf(resp):
                return self._save_pdf(resp, filename)
            # Try to find a PDF link in the HTML body
            if "text/html" in resp.headers.get("Content-Type", ""):
                pdf_urls = self._extract_pdf_links(resp.text, resp.url)
                self._debug(f"Extracted PDF links from landing page: {len(pdf_urls)}")
                for pdf_url in pdf_urls:
                    self._debug(f"Trying extracted link: {self._short_url(pdf_url)}")
                    path = self._download_url(pdf_url, filename)
                    if path:
                        return path
            else:
                self._debug("Resolved page is neither HTML nor PDF, skip extraction")
        except requests.RequestException:
            pass
        return None

    def _try_google_scholar(self, article: Article, filename: str) -> Optional[str]:
        """
        Use the `scholarly` library to search Google Scholar for a PDF link.

        Args:
            article: Article to search for.
            filename: Base filename for saving.

        Returns:
            Full path to saved PDF, or None on failure.
        """
        try:
            scholarly_mod = importlib.import_module("scholarly")
        except ImportError:
            print("    [INFO] scholarly not installed - skipping Google Scholar fallback.")
            return None

        search_pubs = getattr(scholarly_mod, "search_pubs", None)
        if not callable(search_pubs):
            sch_obj = getattr(scholarly_mod, "scholarly", None)
            search_pubs = getattr(sch_obj, "search_pubs", None)
        if not callable(search_pubs):
            print("    [INFO] scholarly search function unavailable - skipping Google Scholar fallback.")
            return None

        query = f"{article.title} {' '.join(article.authors[:2]) if article.authors else ''}"
        try:
            results = cast(Any, search_pubs(query))
            pub = next(results, None)
            if isinstance(pub, dict):
                eprint_url = pub.get("eprint_url")
                if isinstance(eprint_url, str) and eprint_url:
                    return self._download_url(eprint_url, filename)
        except Exception as exc:
            print(f"    [WARN] Google Scholar search failed: {exc}")
        return None

    def _try_scihub(self, article: Article, filename: str) -> Optional[str]:
        """
        Attempt to download from Sci-Hub using various mirrors if DOI is available.
        This provides a fallback similar to RecursiveScholarCrawler.
        """
        if not article.doi:
            self._debug("Skipping Sci-Hub fallback: no DOI available.")
            return None
            
        SCIHUB_MIRRORS = [
            "https://sci-hub.se", "https://sci-hub.st", "https://sci-hub.ru",
            "https://www.sci-hub.ren", "https://www.sci-hub.ee",
        ]
        
        from urllib.parse import quote_plus

        mirrors = list(SCIHUB_MIRRORS)
        random.shuffle(mirrors)
        
        for mirror in mirrors:
            try:
                url = f"{mirror}/{quote_plus(article.doi)}"
                self._debug(f"Trying Sci-Hub mirror: {url}")
                
                resp = self.session.get(url, timeout=min(self.request_timeout, 30))
                if resp.status_code != 200:
                    self._debug(f"Cannot access {mirror}, status: {resp.status_code}")
                    continue

                pdf_link = None
                try:
                    from bs4 import BeautifulSoup
                    from urllib.parse import urljoin
                    # Using lxml parser if available, fallback to html.parser
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for tag in soup.find_all(['embed', 'iframe']):
                        src = tag.get('src')
                        if src:
                            if src.startswith('//'):
                                pdf_link = f"https:{src}"
                            elif not src.startswith('http'):
                                pdf_link = urljoin(mirror, src)
                            else:
                                pdf_link = src
                            break
                    if not pdf_link:
                        for link in soup.find_all('a', href=True):
                            if 'pdf' in link['href'].lower() or (link.get('id') == 'download'):
                                href = link['href']
                                if href.startswith('//'):
                                    pdf_link = f"https:{href}"
                                elif not href.startswith('http'):
                                    pdf_link = urljoin(mirror, href)
                                else:
                                    pdf_link = href
                                break
                except Exception as e:
                    self._debug(f"Error parsing HTML on {mirror}: {e}")
                    continue

                if pdf_link:
                    self._debug(f"Found Sci-Hub PDF link: {self._short_url(pdf_link)}")
                    # Download the pdf link using our robust download_url tool
                    path = self._download_url(pdf_link, filename)
                    if path:
                        return path
            except requests.RequestException as e:
                self._debug(f"Error during Sci-Hub download from {mirror}: {e}")
                time.sleep(1)

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_pdf_links(self, html: str, base_url: str) -> List[str]:
        """
        Parse HTML and return candidate PDF links ordered by confidence.

        Args:
            html: HTML page source string.
            base_url: Base URL used to resolve relative links.

        Returns:
            List of absolute URL candidates (possibly empty).
        """
        candidates: List[str] = []
        seen = set()

        def _add(url: Optional[str]) -> None:
            if not url:
                return
            clean = url.strip()
            if not clean:
                return
            if clean.startswith("//"):
                clean = f"https:{clean}"
            if clean in seen:
                return
            seen.add(clean)
            candidates.append(clean)

        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            soup = BeautifulSoup(html, "lxml")

            # High-confidence metadata fields used by major publishers.
            for key in ("citation_pdf_url", "dc.identifier", "dc.relation"):
                meta = soup.find("meta", attrs={"name": key})
                if meta and meta.get("content"):
                    content = meta["content"]
                    if ".pdf" in content.lower() or "/pdf" in content.lower():
                        _add(urljoin(base_url, content))

            # Also check by content type declaration in metadata.
            for meta in soup.find_all("meta"):
                content = (meta.get("content") or "").strip()
                m_type = (meta.get("type") or "").lower()
                if "application/pdf" in m_type and content:
                    _add(urljoin(base_url, content))

            for prop in ("og:url", "og:see_also"):
                meta = soup.find("meta", attrs={"property": prop})
                if meta and meta.get("content") and "pdf" in meta["content"].lower():
                    _add(urljoin(base_url, meta["content"]))

            # link tags commonly used for machine-readable PDF references.
            for tag in soup.find_all("link", href=True):
                href = tag.get("href")
                rel = " ".join(tag.get("rel") or []).lower()
                typ = (tag.get("type") or "").lower()
                if (
                    (href and (href.lower().endswith(".pdf") or "/pdf" in href.lower()))
                    or "application/pdf" in typ
                    or ("alternate" in rel and href and "pdf" in href.lower())
                ):
                    _add(urljoin(base_url, href))

            # Common embedded viewer patterns (iframe/embed/object)
            for tag in soup.find_all(["embed", "iframe", "object"]):
                src = (tag.get("src") or tag.get("data") or "").strip()
                if not src:
                    continue
                low = src.lower()
                if low.endswith(".pdf") or ".pdf" in low or "/pdf" in low:
                    _add(urljoin(base_url, src))

            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                hlow = href.lower()
                if (
                    hlow.endswith(".pdf")
                    or ".pdf" in hlow
                    or "/pdf" in hlow
                    or (tag.get("id") or "").lower() == "download"
                ):
                    _add(urljoin(base_url, href))
        except Exception:
            return candidates
        return candidates

    def _debug(self, message: str) -> None:
        """Print debug logs for the PDF downloader."""
        if self.debug:
            print(f"    [DEBUG] {message}")

    @staticmethod
    def _short_url(url: str, max_len: int = 110) -> str:
        """Return a truncated URL for readable console output."""
        if len(url) <= max_len:
            return url
        return url[: max_len - 3] + "..."

    @staticmethod
    def _is_pdf(response: requests.Response) -> bool:
        """
        Check whether an HTTP response contains a PDF.

        Args:
            response: requests.Response object.

        Returns:
            True if the response content type is PDF.
        """
        content_type = response.headers.get("Content-Type", "")
        return "application/pdf" in content_type or "application/x-pdf" in content_type

    def _save_pdf(self, response: requests.Response, filename: str) -> Optional[str]:
        """
        Write PDF bytes from a streaming response to disk.

        Args:
            response: Streaming requests.Response containing a PDF.
            filename: Target filename (without directory path).

        Returns:
            Full local path to the saved file, or None on write error.
        """
        path = os.path.join(self.save_dir, filename)
        try:
            with open(path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            if not self._is_valid_saved_pdf(path):
                self._debug(f"Downloaded file failed PDF validation, removed: {path}")
                try:
                    os.remove(path)
                except OSError:
                    pass
                return None
            return path
        except OSError as exc:
            print(f"    [ERROR] Could not save PDF: {exc}")
        return None

    @staticmethod
    def _is_valid_saved_pdf(path: str) -> bool:
        """Lightweight PDF validation to avoid saving HTML/challenge pages."""
        try:
            if not os.path.exists(path) or os.path.getsize(path) < 8:
                return False
            with open(path, "rb") as f:
                header = f.read(8)
                return header.startswith(b"%PDF-")
        except OSError:
            return False

    @staticmethod
    def _build_filename(article: Article) -> str:
        """
        Generate a descriptive filename for a PDF: 'Author Year Journal Title.pdf'.

        Characters that are illegal in filenames are removed/replaced.

        Args:
            article: Article whose metadata is used for naming.

        Returns:
            Safe filename string ending in '.pdf'.
        """
        first_author = article.authors[0].split()[-1] if article.authors else "Unknown"
        year = str(article.year) if article.year else "0000"
        journal = article.journal[:20] if article.journal else "Journal"
        title = article.title[:50] if article.title else "NoTitle"

        name = f"{first_author} {year} {journal} {title}"
        # Replace characters illegal in most filesystems
        name = re.sub(r'[\\/:*?"<>|]', "_", name)
        # Collapse multiple spaces/underscores
        name = re.sub(r"[\s_]+", "_", name).strip("_")
        return name + ".pdf"
