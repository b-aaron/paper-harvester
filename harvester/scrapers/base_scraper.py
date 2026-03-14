"""
base_scraper.py - Abstract base class for all journal scrapers.

Defines the common interface that every scraper must implement so that
the rest of the application can interact with them uniformly.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Article:
    """
    Represents a single scraped academic article with all available metadata.

    All fields are optional so that partial results can be stored even when
    some metadata is unavailable from a particular source.
    """

    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    journal_id: str = ""
    issn: str = ""
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    abstract: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    publisher: Optional[str] = None
    # Paths to downloaded files (populated after download)
    pdf_path: Optional[str] = None
    html_path: Optional[str] = None
    # Open-access PDF URL (from Unpaywall or other sources)
    oa_pdf_url: Optional[str] = None
    # Raw metadata from the source API (for debugging / future use)
    raw: Optional[Dict] = None

    def to_dict(self) -> Dict:
        """Return a plain-dict representation suitable for Excel / JSON export."""
        return {
            "title": self.title,
            "authors": "; ".join(self.authors),
            "journal": self.journal,
            "year": self.year,
            "month": self.month,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
            "url": self.url,
            "abstract": self.abstract,
            "keywords": "; ".join(self.keywords),
            "publisher": self.publisher,
            "pdf_path": self.pdf_path,
            "oa_pdf_url": self.oa_pdf_url,
        }

    @property
    def doi_url(self) -> Optional[str]:
        """Return a full DOI URL if DOI is available."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return None


class BaseScraper(ABC):
    """
    Abstract base class for all paper scrapers.

    Subclasses must implement `fetch_articles` to retrieve article metadata
    for a given journal and time filter.
    """

    @abstractmethod
    def fetch_articles(
        self,
        journal: Dict,
        max_results: int = 50,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
    ) -> List[Article]:
        """
        Fetch articles for a given journal.

        Args:
            journal: Journal metadata dict (from journals.json).
            max_results: Maximum number of articles to return.
            from_date: ISO date string (YYYY-MM-DD) for the earliest publication date.
            until_date: ISO date string (YYYY-MM-DD) for the latest publication date.

        Returns:
            List of Article objects.
        """
