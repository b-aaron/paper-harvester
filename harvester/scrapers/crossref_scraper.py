"""
crossref_scraper.py - Retrieves article metadata via the CrossRef REST API.

CrossRef (https://api.crossref.org) provides free access to academic metadata
for tens of millions of DOI-registered articles.  No authentication is required,
but providing a contact e-mail address in the User-Agent header grants access
to the "polite pool" with higher rate limits.

Unpaywall (https://unpaywall.org/api/v2) is used as a secondary call to locate
legal open-access PDF URLs for each article.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

from .base_scraper import Article, BaseScraper


class CrossRefScraper(BaseScraper):
    """
    Fetches article metadata from the CrossRef REST API.

    For each article, an optional secondary call is made to Unpaywall to
    resolve an open-access PDF URL.
    """

    CROSSREF_BASE = "https://api.crossref.org"
    UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

    def __init__(self, email: str = "paper-harvester@example.com", rate_limit: float = 0.5):
        """
        Initialize the CrossRef scraper.

        Args:
            email: Contact email sent in User-Agent for polite-pool access.
            rate_limit: Minimum seconds to wait between successive API calls
                        (both CrossRef and Unpaywall respect 1 req/s for polite usage).
        """
        self.email = email
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": f"paper-harvester/1.0 (mailto:{email})"}
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch_articles(
        self,
        journal: Dict,
        max_results: int = 50,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
    ) -> List[Article]:
        """
        Fetch articles for a journal using the CrossRef works endpoint.

        Args:
            journal: Journal metadata dict containing at least 'issn_print' or
                     'issn_electronic', 'name', and 'id'.
            max_results: Maximum number of articles to retrieve (up to 1000).
            from_date: ISO date string YYYY-MM-DD (inclusive lower bound).
            until_date: ISO date string YYYY-MM-DD (inclusive upper bound).

        Returns:
            List of Article objects sorted newest-first.
        """
        issn = journal.get("issn_electronic") or journal.get("issn_print")
        if not issn:
            print(f"[WARNING] No ISSN for journal '{journal.get('name')}' - skipping.")
            return []

        params: Dict = {
            "rows": min(max_results, 1000),
            "sort": "published",
            "order": "desc",
            "mailto": self.email,
        }
        if from_date:
            params["filter"] = f"from-pub-date:{from_date}"
        if until_date:
            existing = params.get("filter", "")
            params["filter"] = f"{existing},until-pub-date:{until_date}" if existing else f"until-pub-date:{until_date}"

        url = f"{self.CROSSREF_BASE}/journals/{issn}/works"
        raw_items = self._paginate(url, params, max_results)

        articles: List[Article] = []
        for item in raw_items:
            article = self._parse_item(item, journal)
            # Try to find open-access PDF via Unpaywall
            if article.doi:
                article.oa_pdf_url = self._unpaywall_oa_url(article.doi)
            articles.append(article)
            time.sleep(self.rate_limit)

        return articles

    def fetch_latest_issue(self, journal: Dict, max_results: int = 30) -> List[Article]:
        """
        Fetch articles from the most recent issue of a journal.

        Retrieves the latest articles sorted by publication date and groups
        them by the most recent volume/issue combination found.

        Args:
            journal: Journal metadata dict.
            max_results: Number of candidate articles to examine.

        Returns:
            List of Article objects from the latest issue.
        """
        articles = self.fetch_articles(journal, max_results=max_results)
        if not articles:
            return []

        # Group by (volume, issue) and return the newest group
        latest_vi = (articles[0].volume, articles[0].issue)
        return [a for a in articles if (a.volume, a.issue) == latest_vi]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paginate(self, url: str, params: Dict, max_results: int) -> List[Dict]:
        """
        Request CrossRef works endpoint, following cursor-based pagination if
        more results are needed than a single page delivers.

        Args:
            url: CrossRef works URL for a specific journal ISSN.
            params: Query parameters dict.
            max_results: Total number of items to collect.

        Returns:
            List of raw CrossRef work item dicts.
        """
        items: List[Dict] = []
        cursor = "*"

        while len(items) < max_results:
            try:
                resp = self.session.get(
                    url, params={**params, "cursor": cursor}, timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                print(f"[ERROR] CrossRef request failed: {exc}")
                break

            message = data.get("message", {})
            batch = message.get("items", [])
            if not batch:
                break

            items.extend(batch)
            cursor = message.get("next-cursor")
            if not cursor:
                break

            time.sleep(self.rate_limit)

        return items[:max_results]

    def _parse_item(self, item: Dict, journal: Dict) -> Article:
        """
        Convert a raw CrossRef work dict into an Article object.

        Args:
            item: Raw CrossRef work metadata dict.
            journal: Journal metadata dict for extra context.

        Returns:
            Populated Article object.
        """
        # --- Authors ---
        authors: List[str] = []
        for author in item.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            name = f"{given} {family}".strip() if given or family else author.get("name", "")
            if name:
                authors.append(name)

        # --- Title ---
        titles = item.get("title", [])
        title = titles[0] if titles else ""

        # --- Publication date ---
        year = month = None
        pub_date = item.get("published") or item.get("published-print") or item.get("published-online")
        if pub_date:
            date_parts = pub_date.get("date-parts", [[]])
            parts = date_parts[0] if date_parts else []
            if parts:
                year = parts[0] if len(parts) > 0 else None
                month = parts[1] if len(parts) > 1 else None

        # --- Abstract ---
        abstract = item.get("abstract", "")
        # CrossRef wraps abstracts in JATS XML tags; strip them
        if abstract:
            abstract = self._strip_jats(abstract)

        # --- Keywords ---
        keywords = item.get("subject", [])

        # --- Journal name (prefer configured name) ---
        journal_name = journal.get("name") or (
            (item.get("container-title") or [""])[0]
        )

        # --- Volume / Issue / Pages ---
        volume = item.get("volume")
        issue = item.get("issue")
        pages = item.get("page")

        # --- DOI & URL ---
        doi = item.get("DOI")
        url = item.get("URL") or (f"https://doi.org/{doi}" if doi else None)

        return Article(
            title=title,
            authors=authors,
            journal=journal_name,
            journal_id=journal.get("id", ""),
            issn=journal.get("issn_print", ""),
            volume=volume,
            issue=issue,
            pages=pages,
            year=year,
            month=month,
            doi=doi,
            url=url,
            abstract=abstract,
            keywords=keywords,
            publisher=journal.get("publisher", item.get("publisher", "")),
            raw=item,
        )

    def _unpaywall_oa_url(self, doi: str) -> Optional[str]:
        """
        Query the Unpaywall API to find a legal open-access PDF URL for a DOI.

        Args:
            doi: Article DOI string.

        Returns:
            URL string for the best open-access PDF, or None if not found.
        """
        if not self.email or "@" not in self.email:
            return None
        try:
            resp = self.session.get(
                f"{self.UNPAYWALL_BASE}/{doi}",
                params={"email": self.email},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                best_oa = data.get("best_oa_location")
                if best_oa:
                    return best_oa.get("url_for_pdf") or best_oa.get("url")
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def _strip_jats(text: str) -> str:
        """
        Remove JATS XML tags (e.g. <jats:p>) from abstract text.

        Args:
            text: Raw abstract string possibly containing XML tags.

        Returns:
            Plain-text abstract.
        """
        import re
        return re.sub(r"<[^>]+>", "", text).strip()


def build_date_range(mode: str, **kwargs) -> Dict[str, Optional[str]]:
    """
    Compute from_date / until_date strings for common time-range modes.

    Args:
        mode: One of 'latest_issue', 'last_n_months', 'last_n_years',
              'custom', or 'all'.
        **kwargs: Mode-specific parameters:
            - n (int): Number of months or years for 'last_n_months' / 'last_n_years'.
            - from_date (str): YYYY-MM-DD for 'custom'.
            - until_date (str): YYYY-MM-DD for 'custom'.

    Returns:
        Dict with 'from_date' and 'until_date' keys (both may be None).
    """
    today = datetime.today()
    result: Dict[str, Optional[str]] = {"from_date": None, "until_date": None}

    if mode == "latest_issue":
        # No date filter — we sort by newest and group by issue in the scraper
        pass

    elif mode == "last_n_months":
        n = kwargs.get("n", 6)
        delta = timedelta(days=30 * n)
        result["from_date"] = (today - delta).strftime("%Y-%m-%d")
        result["until_date"] = today.strftime("%Y-%m-%d")

    elif mode == "last_n_years":
        n = kwargs.get("n", 1)
        result["from_date"] = f"{today.year - n}-{today.month:02d}-{today.day:02d}"
        result["until_date"] = today.strftime("%Y-%m-%d")

    elif mode == "custom":
        result["from_date"] = kwargs.get("from_date")
        result["until_date"] = kwargs.get("until_date")

    return result
