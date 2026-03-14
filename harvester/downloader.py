"""
downloader.py - Downloads full-text PDFs for academic articles.

Download strategy (in order of preference):
  1. Open-access PDF via Unpaywall URL (populated during scraping).
  2. Institutional login via EZProxy/Shibboleth (requires org credentials).
  3. Google Scholar fallback via the `scholarly` library.

If all strategies fail, the article is recorded with no local PDF path
so the metadata is still saved to Excel / Zotero.
"""

import os
import re
import time
from typing import Dict, List, Optional, Tuple

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
            use_google_scholar: Whether to try Google Scholar as a last resort.
            request_timeout: HTTP request timeout in seconds.
            delay_between_requests: Seconds to wait between download attempts
                to avoid rate-limiting.
        """
        self.save_dir = save_dir
        self.institutional_credentials = institutional_credentials or {}
        self.use_google_scholar = use_google_scholar
        self.request_timeout = request_timeout
        self.delay = delay_between_requests

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        os.makedirs(save_dir, exist_ok=True)

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

        # 1. Try the Unpaywall / open-access URL discovered during scraping
        if article.oa_pdf_url:
            path = self._download_url(article.oa_pdf_url, filename)
            if path:
                return path

        # 2. Try the article's canonical DOI URL directly
        if article.doi_url:
            path = self._try_doi_redirect(article.doi_url, filename)
            if path:
                return path

        # 3. Institutional login (EZProxy)
        if self.institutional_credentials.get("username") and article.doi_url:
            path = self._try_institutional(article, filename)
            if path:
                return path

        # 4. Google Scholar fallback
        if self.use_google_scholar:
            path = self._try_google_scholar(article, filename)
            if path:
                return path

        return None

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
            resp = self.session.get(url, timeout=self.request_timeout, stream=True)
            if resp.status_code == 200 and self._is_pdf(resp):
                return self._save_pdf(resp, filename)
        except requests.RequestException as exc:
            print(f"    [WARN] Direct download failed ({url[:60]}): {exc}")
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
            resp = self.session.get(doi_url, timeout=self.request_timeout, allow_redirects=True)
            if resp.status_code == 200 and self._is_pdf(resp):
                return self._save_pdf(resp, filename)
            # Try to find a PDF link in the HTML body
            if "text/html" in resp.headers.get("Content-Type", ""):
                pdf_url = self._extract_pdf_link(resp.text, resp.url)
                if pdf_url:
                    return self._download_url(pdf_url, filename)
        except requests.RequestException:
            pass
        return None

    def _try_institutional(self, article: Article, filename: str) -> Optional[str]:
        """
        Attempt PDF download via institutional EZProxy authentication.

        This method uses Selenium to automate the Shibboleth/EZProxy login flow
        for the institution specified in ``institutional_credentials``.

        Args:
            article: Article whose PDF we want to download.
            filename: Base filename for saving.

        Returns:
            Full path to saved PDF, or None on failure.
        """
        creds = self.institutional_credentials
        org = creds.get("org", "")
        username = creds.get("username", "")
        password = creds.get("password", "")

        if not (org and username and password and article.doi_url):
            return None

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError:
            print("    [INFO] Selenium not available - skipping institutional login.")
            return None

        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Tell Chrome to download PDFs automatically instead of opening viewer
        prefs = {
            "download.default_directory": os.path.abspath(self.save_dir),
            "download.prompt_for_download": False,
            "plugins.always_open_pdf_externally": True,
        }
        options.add_experimental_option("prefs", prefs)

        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(60)

            # Navigate to the article DOI
            driver.get(article.doi_url)
            time.sleep(3)

            # Detect if there's an institutional login page and handle it
            current_url = driver.current_url
            if "shibboleth" in current_url or "login" in current_url or "ezproxy" in current_url:
                self._fill_login_form(driver, username, password)
                time.sleep(5)

            # After login, look for a PDF download link
            pdf_url = self._selenium_find_pdf_link(driver)
            if pdf_url:
                # Use the authenticated session's cookies to download the PDF
                cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
                resp = self.session.get(pdf_url, cookies=cookies, timeout=self.request_timeout, stream=True)
                if resp.status_code == 200 and self._is_pdf(resp):
                    return self._save_pdf(resp, filename)

        except Exception as exc:
            print(f"    [WARN] Institutional login failed: {exc}")
        finally:
            if driver:
                driver.quit()

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
            from scholarly import scholarly as sch
        except ImportError:
            print("    [INFO] scholarly not installed - skipping Google Scholar fallback.")
            return None

        query = f"{article.title} {' '.join(article.authors[:2]) if article.authors else ''}"
        try:
            results = sch.search_pubs(query)
            pub = next(results, None)
            if pub and pub.get("eprint_url"):
                return self._download_url(pub["eprint_url"], filename)
        except Exception as exc:
            print(f"    [WARN] Google Scholar search failed: {exc}")
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fill_login_form(self, driver, username: str, password: str) -> None:
        """
        Attempt to fill a username/password login form using common field selectors.

        Args:
            driver: Selenium WebDriver instance.
            username: Institutional username.
            password: Institutional password.
        """
        from selenium.webdriver.common.by import By

        selectors = [
            ("input[name='username']", "input[name='password']"),
            ("input[id='username']", "input[id='password']"),
            ("input[type='text']", "input[type='password']"),
        ]
        for user_sel, pass_sel in selectors:
            try:
                user_field = driver.find_element(By.CSS_SELECTOR, user_sel)
                pass_field = driver.find_element(By.CSS_SELECTOR, pass_sel)
                user_field.clear()
                user_field.send_keys(username)
                pass_field.clear()
                pass_field.send_keys(password)
                pass_field.submit()
                return
            except Exception:
                continue

    def _selenium_find_pdf_link(self, driver) -> Optional[str]:
        """
        Look for a PDF download link in the current Selenium page.

        Args:
            driver: Selenium WebDriver instance.

        Returns:
            Absolute URL of the PDF, or None.
        """
        from selenium.webdriver.common.by import By

        try:
            links = driver.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href") or ""
                text = link.text.lower()
                if href.endswith(".pdf") or "pdf" in text or "/pdf/" in href:
                    return href
        except Exception:
            pass
        return None

    def _extract_pdf_link(self, html: str, base_url: str) -> Optional[str]:
        """
        Parse HTML and return the first href that looks like a PDF link.

        Args:
            html: HTML page source string.
            base_url: Base URL used to resolve relative links.

        Returns:
            Absolute URL string or None.
        """
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin

            soup = BeautifulSoup(html, "lxml")
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                if href.lower().endswith(".pdf") or "/pdf" in href.lower():
                    return urljoin(base_url, href)
        except Exception:
            pass
        return None

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
            return path
        except OSError as exc:
            print(f"    [ERROR] Could not save PDF: {exc}")
        return None

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
