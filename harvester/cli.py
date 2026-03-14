"""
cli.py - Interactive command-line interface for Paper Harvester.

Presents the user with a text-based menu to:
  • Select a journal list or custom set of journals
  • Choose a time range / issue range
  • Configure output options (Excel, PDFs, Zotero)
  • Run the full scraping pipeline
  • Manage journal configurations and settings
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    _COLOR = True
except ImportError:
    _COLOR = False


def _c(text: str, color: str = "") -> str:
    """Apply a colorama color code if available."""
    if not _COLOR or not color:
        return text
    return f"{color}{text}{Style.RESET_ALL}"


class CLI:
    """
    Interactive command-line interface for the Paper Harvester application.

    Guides the user through journal selection, time range configuration,
    output options, and then orchestrates the scraping pipeline.
    """

    BANNER = r"""
  ____                           _   _                           _
 |  _ \ __ _ _ __   ___ _ __   | | | | __ _ _ ____   _____  ___| |_ ___ _ __
 | |_) / _` | '_ \ / _ \ '__|  | |_| |/ _` | '__\ \ / / _ \/ __| __/ _ \ '__|
 |  __/ (_| | |_) |  __/ |     |  _  | (_| | |   \ V /  __/\__ \ ||  __/ |
 |_|   \__,_| .__/ \___|_|     |_| |_|\__,_|_|    \_/ \___||___/\__\___|_|
            |_|
    """

    def __init__(self):
        """Initialize the CLI, loading config and settings."""
        from .config_manager import JournalConfigManager, UserSettings

        self.config = JournalConfigManager()
        self.settings = UserSettings()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the interactive CLI loop."""
        print(_c(self.BANNER, Fore.CYAN if _COLOR else ""))
        print(_c("  Academic Paper Harvester v1.0", Fore.GREEN if _COLOR else ""))
        print(_c("  Supported lists: UTD24 · FT50 · ABS4 · Custom\n", Fore.WHITE if _COLOR else ""))

        while True:
            self._main_menu()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------

    def _main_menu(self) -> None:
        """Display and handle the main menu."""
        print(_c("\n========== MAIN MENU ==========", Fore.YELLOW if _COLOR else ""))
        print("  1. Scrape articles")
        print("  2. Manage journal list")
        print("  3. Settings")
        print("  4. Exit")

        choice = self._prompt("Select an option [1-4]").strip()
        if choice == "1":
            self._scrape_menu()
        elif choice == "2":
            self._journal_manage_menu()
        elif choice == "3":
            self._settings_menu()
        elif choice == "4":
            print(_c("Goodbye!", Fore.GREEN if _COLOR else ""))
            sys.exit(0)
        else:
            print(_c("Invalid choice. Please enter 1-4.", Fore.RED if _COLOR else ""))

    # ------------------------------------------------------------------
    # Scrape menu
    # ------------------------------------------------------------------

    def _scrape_menu(self) -> None:
        """Guide the user through scraping options and run the pipeline."""
        print(_c("\n--- Scrape Articles ---", Fore.CYAN if _COLOR else ""))

        # 1. Choose journals
        journals = self._select_journals()
        if not journals:
            print("No journals selected. Returning to main menu.")
            return

        # 2. Choose time range
        date_range, max_results, mode = self._select_time_range()

        # 3. Choose output options
        output_opts = self._select_output_options()

        # 4. Confirm and run
        print(_c("\n--- Summary ---", Fore.YELLOW if _COLOR else ""))
        print(f"  Journals : {len(journals)} selected")
        print(f"  Time mode: {mode}")
        if date_range.get('from_date'):
            print(f"  From date: {date_range['from_date']}")
        if date_range.get('until_date'):
            print(f"  Until date: {date_range['until_date']}")
        print(f"  Max results per journal: {max_results}")
        print(f"  Save path  : {output_opts['save_path']}")
        print(f"  Excel      : {output_opts['excel']}")
        print(f"  Download PDFs: {output_opts['download_pdf']}")
        print(f"  Save to Zotero: {output_opts['zotero']}")

        if not self._confirm("Proceed with scraping?"):
            return

        self._run_pipeline(journals, date_range, max_results, mode, output_opts)

    def _select_journals(self) -> List[Dict]:
        """
        Prompt the user to choose a journal selection method and return
        the list of journal metadata dicts.

        Returns:
            List of journal metadata dicts.
        """
        print(_c("\n-- Select Journals --", Fore.CYAN if _COLOR else ""))
        print("  1. UTD24 (24 UTD journals)")
        print("  2. FT50  (Financial Times 50 journals)")
        print("  3. ABS4  (ABS Guide 4/4* journals)")
        print("  4. Preset (marketing, finance, etc.)")
        print("  5. Custom selection (enter journal IDs)")
        print("  6. All configured journals")

        choice = self._prompt("Select [1-6]").strip()

        if choice == "1":
            journals = self.config.get_journals_by_list("utd24")
        elif choice == "2":
            journals = self.config.get_journals_by_list("ft50")
        elif choice == "3":
            journals = self.config.get_journals_by_list("abs4")
        elif choice == "4":
            journals = self._select_preset()
        elif choice == "5":
            journals = self._select_custom_journals()
        elif choice == "6":
            journals = self.config.get_all_journals()
        else:
            print(_c("Invalid choice.", Fore.RED if _COLOR else ""))
            return []

        if not journals:
            print(_c("No journals found for that selection.", Fore.RED if _COLOR else ""))
            return []

        print(f"\nSelected {len(journals)} journal(s):")
        for j in journals:
            print(f"  • {j['name']} ({j.get('issn_print', 'N/A')})")
        return journals

    def _select_preset(self) -> List[Dict]:
        """
        List available presets and let the user pick one.

        Returns:
            List of journal metadata dicts for the chosen preset.
        """
        presets = self.config.get_all_presets()
        if not presets:
            print("No presets configured.")
            return []

        print(_c("\n-- Available Presets --", Fore.CYAN if _COLOR else ""))
        preset_ids = list(presets.keys())
        for idx, pid in enumerate(preset_ids, 1):
            p = presets[pid]
            print(f"  {idx}. {p['name']} - {p['description']}")

        raw = self._prompt(f"Select preset [1-{len(preset_ids)}]").strip()
        try:
            idx = int(raw) - 1
            preset_id = preset_ids[idx]
            return self.config.get_journals_by_preset(preset_id)
        except (ValueError, IndexError):
            print(_c("Invalid selection.", Fore.RED if _COLOR else ""))
            return []

    def _select_custom_journals(self) -> List[Dict]:
        """
        Let the user type journal IDs manually.

        Returns:
            List of journal metadata dicts.
        """
        all_journals = self.config.get_all_journals()
        print(_c("\n-- All Available Journals --", Fore.CYAN if _COLOR else ""))
        for j in all_journals:
            print(f"  {j['id']:12s} {j['name']}")

        raw = self._prompt("Enter journal IDs separated by commas").strip()
        if not raw:
            return []
        ids = [x.strip() for x in raw.split(",") if x.strip()]
        journals = self.config.get_journals_by_ids(ids)
        unknown = [i for i in ids if not self.config.get_journal(i)]
        if unknown:
            print(_c(f"Unknown journal IDs ignored: {', '.join(unknown)}", Fore.YELLOW if _COLOR else ""))
        return journals

    def _select_time_range(self) -> Tuple[Dict, int, str]:
        """
        Prompt the user for a time range mode and parameters.

        Returns:
            Tuple of (date_range_dict, max_results, mode_name).
        """
        from .scrapers.crossref_scraper import build_date_range

        print(_c("\n-- Time Range --", Fore.CYAN if _COLOR else ""))
        print("  1. Latest issue only")
        print("  2. Last N months")
        print("  3. Last N years")
        print("  4. Custom date range (YYYY-MM-DD)")
        print("  5. All available articles")

        choice = self._prompt("Select [1-5]").strip()

        if choice == "1":
            max_results = int(self._prompt("Max articles per journal to examine [30]").strip() or "30")
            return build_date_range("latest_issue"), max_results, "latest_issue"

        elif choice == "2":
            n = int(self._prompt("Number of months [6]").strip() or "6")
            max_results = int(self._prompt("Max articles per journal [100]").strip() or "100")
            return build_date_range("last_n_months", n=n), max_results, f"last_{n}_months"

        elif choice == "3":
            n = int(self._prompt("Number of years [1]").strip() or "1")
            max_results = int(self._prompt("Max articles per journal [100]").strip() or "100")
            return build_date_range("last_n_years", n=n), max_results, f"last_{n}_years"

        elif choice == "4":
            from_date = self._prompt("From date (YYYY-MM-DD) [leave blank for no limit]").strip() or None
            until_date = self._prompt("Until date (YYYY-MM-DD) [leave blank for today]").strip() or None
            max_results = int(self._prompt("Max articles per journal [100]").strip() or "100")
            return build_date_range("custom", from_date=from_date, until_date=until_date), max_results, "custom"

        elif choice == "5":
            max_results = int(self._prompt("Max articles per journal [200]").strip() or "200")
            return build_date_range("all"), max_results, "all"

        else:
            print(_c("Invalid choice. Using latest issue.", Fore.YELLOW if _COLOR else ""))
            return build_date_range("latest_issue"), 30, "latest_issue"

    def _select_output_options(self) -> Dict:
        """
        Ask the user about output destinations.

        Returns:
            Dict with keys: save_path, excel, download_pdf, zotero, zotero_collection.
        """
        print(_c("\n-- Output Options --", Fore.CYAN if _COLOR else ""))

        # Save path
        default_path = self.settings.get("save_path")
        raw_path = self._prompt(f"Save directory [{default_path}]").strip()
        save_path = raw_path if raw_path else default_path
        self.settings.set("save_path", save_path)

        # Excel
        excel = self._confirm("Save article metadata to Excel?", default=True)

        # PDFs
        download_pdf = self._confirm("Attempt to download PDF files?", default=True)

        # Zotero
        zotero = False
        zotero_collection = None
        if self._confirm("Save articles to Zotero?", default=False):
            zotero = True
            zotero_collection = self._prompt("Zotero collection name [PaperHarvester]").strip() or "PaperHarvester"

        return {
            "save_path": save_path,
            "excel": excel,
            "download_pdf": download_pdf,
            "zotero": zotero,
            "zotero_collection": zotero_collection,
        }

    # ------------------------------------------------------------------
    # Pipeline orchestration
    # ------------------------------------------------------------------

    def _run_pipeline(
        self,
        journals: List[Dict],
        date_range: Dict,
        max_results: int,
        mode: str,
        output_opts: Dict,
    ) -> None:
        """
        Execute the full scraping pipeline for the selected journals.

        Steps:
          1. Scrape metadata via CrossRef
          2. Download PDFs (if requested)
          3. Export to Excel (if requested)
          4. Save to Zotero (if requested)

        Args:
            journals: List of journal metadata dicts.
            date_range: Dict with 'from_date' / 'until_date'.
            max_results: Max articles per journal.
            mode: Human-readable time-range mode string.
            output_opts: Dict of output configuration options.
        """
        from .scrapers.crossref_scraper import CrossRefScraper
        from .downloader import PDFDownloader
        from .exporter import Exporter

        save_path = output_opts["save_path"]
        os.makedirs(save_path, exist_ok=True)

        # Ensure Unpaywall email is set
        email = self.settings.get("unpaywall_email") or "paper-harvester@example.com"

        # ---- Step 1: Scrape ----
        scraper = CrossRefScraper(email=email)
        all_articles = []

        print(_c(f"\n[1/4] Scraping {len(journals)} journal(s)...", Fore.CYAN if _COLOR else ""))
        for journal in journals:
            print(f"\n  → {journal['name']}")
            try:
                if mode == "latest_issue":
                    articles = scraper.fetch_latest_issue(journal, max_results=max_results)
                else:
                    articles = scraper.fetch_articles(
                        journal,
                        max_results=max_results,
                        from_date=date_range.get("from_date"),
                        until_date=date_range.get("until_date"),
                    )
                print(f"    Found {len(articles)} article(s).")
                all_articles.extend(articles)
            except Exception as exc:
                print(_c(f"    [ERROR] Failed to scrape {journal['name']}: {exc}", Fore.RED if _COLOR else ""))

        print(f"\n  Total articles collected: {len(all_articles)}")

        if not all_articles:
            print(_c("No articles found. Nothing to save.", Fore.YELLOW if _COLOR else ""))
            return

        # ---- Step 2: Download PDFs ----
        if output_opts["download_pdf"]:
            print(_c(f"\n[2/4] Downloading PDFs...", Fore.CYAN if _COLOR else ""))
            pdf_dir = os.path.join(save_path, "pdfs")
            creds = {}
            if self.settings.get("institutional_login_enabled"):
                creds = {
                    "org": self.settings.get("institutional_org"),
                    "username": self.settings.get("institutional_username"),
                    "password": self.settings.get("institutional_password"),
                }
            downloader = PDFDownloader(
                save_dir=pdf_dir,
                institutional_credentials=creds,
                use_google_scholar=self.settings.get("google_scholar_fallback", True),
            )
            all_articles = downloader.download(all_articles)
        else:
            print(_c("\n[2/4] PDF download skipped.", Fore.YELLOW if _COLOR else ""))

        # ---- Step 3: Excel export ----
        if output_opts["excel"]:
            print(_c(f"\n[3/4] Exporting to Excel...", Fore.CYAN if _COLOR else ""))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"papers_{timestamp}.xlsx"
            exporter = Exporter(save_dir=save_path)
            exporter.to_excel(all_articles, filename=filename)
            exporter.organise_pdfs(all_articles)
        else:
            print(_c("\n[3/4] Excel export skipped.", Fore.YELLOW if _COLOR else ""))

        # ---- Step 4: Zotero ----
        if output_opts["zotero"]:
            print(_c(f"\n[4/4] Saving to Zotero...", Fore.CYAN if _COLOR else ""))
            self._save_to_zotero(all_articles, output_opts.get("zotero_collection"))
        else:
            print(_c("\n[4/4] Zotero saving skipped.", Fore.YELLOW if _COLOR else ""))

        print(_c(f"\n✓ Done! Results saved to: {save_path}", Fore.GREEN if _COLOR else ""))

    def _save_to_zotero(self, articles: List[Dict], collection_name: Optional[str]) -> None:
        """
        Initialise the Zotero client using stored credentials and save articles.

        Prompts the user for missing credentials.

        Args:
            articles: Articles to save.
            collection_name: Optional Zotero collection name.
        """
        from .zotero_client import ZoteroClient

        lib_id = self.settings.get("zotero_library_id")
        api_key = self.settings.get("zotero_api_key")
        lib_type = self.settings.get("zotero_library_type", "user")

        if not lib_id:
            lib_id = self._prompt("Zotero library ID (numeric user or group ID)").strip()
            self.settings.set("zotero_library_id", lib_id)
        if not api_key:
            api_key = self._prompt("Zotero API key").strip()
            self.settings.set("zotero_api_key", api_key)

        if not lib_id or not api_key:
            print(_c("Zotero credentials incomplete. Skipping.", Fore.YELLOW if _COLOR else ""))
            return

        try:
            client = ZoteroClient(lib_id, api_key, lib_type, collection_name)
            stats = client.save_articles(articles)
            print(
                f"  Zotero: {stats['saved']} saved, "
                f"{stats['skipped']} skipped (duplicates), "
                f"{stats['failed']} failed."
            )
        except ImportError as exc:
            print(_c(f"  [ERROR] {exc}", Fore.RED if _COLOR else ""))
        except Exception as exc:
            print(_c(f"  [ERROR] Zotero save failed: {exc}", Fore.RED if _COLOR else ""))

    # ------------------------------------------------------------------
    # Journal management menu
    # ------------------------------------------------------------------

    def _journal_manage_menu(self) -> None:
        """Manage the journal configuration database."""
        print(_c("\n--- Manage Journal List ---", Fore.CYAN if _COLOR else ""))
        print("  1. View all journals")
        print("  2. Add a journal")
        print("  3. Remove a journal")
        print("  4. View presets")
        print("  5. Add a custom preset")
        print("  6. Back")

        choice = self._prompt("Select [1-6]").strip()

        if choice == "1":
            self._list_all_journals()
        elif choice == "2":
            self._add_journal()
        elif choice == "3":
            self._remove_journal()
        elif choice == "4":
            self._list_presets()
        elif choice == "5":
            self._add_preset()
        elif choice == "6":
            return
        else:
            print(_c("Invalid choice.", Fore.RED if _COLOR else ""))

    def _list_all_journals(self) -> None:
        """Print all configured journals in a table."""
        journals = self.config.get_all_journals()
        print(f"\n{'ID':<12} {'Name':<45} {'ISSN':<12} {'Lists'}")
        print("-" * 90)
        for j in journals:
            lists = ", ".join(j.get("lists", []))
            print(f"  {j['id']:<10} {j['name']:<45} {j.get('issn_print', 'N/A'):<12} {lists}")

    def _add_journal(self) -> None:
        """Interactively add a new journal to the database."""
        print(_c("\n-- Add Journal --", Fore.CYAN if _COLOR else ""))
        jid = self._prompt("Journal ID (short code, e.g. 'jm')").strip()
        if not jid:
            return
        name = self._prompt("Full journal name").strip()
        issn_print = self._prompt("Print ISSN").strip()
        issn_elec = self._prompt("Electronic ISSN (optional)").strip()
        publisher = self._prompt("Publisher").strip()
        website = self._prompt("Website URL").strip()
        lists_raw = self._prompt("Lists (comma-separated: utd24, ft50, abs4)").strip()
        lists = [x.strip() for x in lists_raw.split(",") if x.strip()]

        journal = {
            "id": jid,
            "name": name,
            "issn_print": issn_print,
            "issn_electronic": issn_elec,
            "publisher": publisher,
            "website": website,
            "lists": lists,
        }
        self.config.add_journal(journal)
        self.config.save_journals()
        print(_c(f"  ✓ Journal '{name}' added.", Fore.GREEN if _COLOR else ""))

    def _remove_journal(self) -> None:
        """Remove a journal from the database by ID."""
        jid = self._prompt("Journal ID to remove").strip()
        if self.config.remove_journal(jid):
            self.config.save_journals()
            print(_c(f"  ✓ Journal '{jid}' removed.", Fore.GREEN if _COLOR else ""))
        else:
            print(_c(f"  Journal '{jid}' not found.", Fore.RED if _COLOR else ""))

    def _list_presets(self) -> None:
        """Print all available presets."""
        presets = self.config.get_all_presets()
        print(f"\n{'ID':<25} {'Name':<25} Description")
        print("-" * 90)
        for pid, p in presets.items():
            print(f"  {pid:<23} {p['name']:<25} {p.get('description','')}")

    def _add_preset(self) -> None:
        """Interactively create a custom preset."""
        pid = self._prompt("Preset ID (unique key)").strip()
        if not pid:
            return
        name = self._prompt("Preset name").strip()
        desc = self._prompt("Description").strip()
        ids_raw = self._prompt("Journal IDs (comma-separated)").strip()
        ids = [x.strip() for x in ids_raw.split(",") if x.strip()]

        self.config.add_preset(pid, name, desc, ids)
        self.config.save_presets()
        print(_c(f"  ✓ Preset '{name}' saved.", Fore.GREEN if _COLOR else ""))

    # ------------------------------------------------------------------
    # Settings menu
    # ------------------------------------------------------------------

    def _settings_menu(self) -> None:
        """Allow the user to view and update application settings."""
        print(_c("\n--- Settings ---", Fore.CYAN if _COLOR else ""))
        print("  1. View current settings")
        print("  2. Set save directory")
        print("  3. Set Unpaywall email")
        print("  4. Configure Zotero")
        print("  5. Configure institutional login")
        print("  6. Toggle Google Scholar fallback")
        print("  7. Back")

        choice = self._prompt("Select [1-7]").strip()

        if choice == "1":
            self.settings.display()
        elif choice == "2":
            path = self._prompt("Save directory").strip()
            if path:
                self.settings.set("save_path", path)
                print(_c(f"  ✓ Save directory updated to: {path}", Fore.GREEN if _COLOR else ""))
        elif choice == "3":
            email = self._prompt("Your email address (for Unpaywall API)").strip()
            if email:
                self.settings.set("unpaywall_email", email)
                print(_c("  ✓ Unpaywall email updated.", Fore.GREEN if _COLOR else ""))
        elif choice == "4":
            self._configure_zotero()
        elif choice == "5":
            self._configure_institutional_login()
        elif choice == "6":
            current = self.settings.get("google_scholar_fallback", True)
            self.settings.set("google_scholar_fallback", not current)
            state = "enabled" if not current else "disabled"
            print(_c(f"  ✓ Google Scholar fallback {state}.", Fore.GREEN if _COLOR else ""))
        elif choice == "7":
            return
        else:
            print(_c("Invalid choice.", Fore.RED if _COLOR else ""))

    def _configure_zotero(self) -> None:
        """Prompt for and save Zotero API credentials."""
        print(_c("\n-- Zotero Configuration --", Fore.CYAN if _COLOR else ""))
        print("  (Get your API key at https://www.zotero.org/settings/keys)")
        lib_type = self._prompt("Library type: 'user' or 'group' [user]").strip() or "user"
        lib_id = self._prompt("Library ID (numeric)").strip()
        api_key = self._prompt("API key").strip()

        if lib_id:
            self.settings.set("zotero_library_id", lib_id)
        if api_key:
            self.settings.set("zotero_api_key", api_key)
        self.settings.set("zotero_library_type", lib_type)
        self.settings.set("zotero_enabled", bool(lib_id and api_key))
        print(_c("  ✓ Zotero settings saved.", Fore.GREEN if _COLOR else ""))

    def _configure_institutional_login(self) -> None:
        """Prompt for and save institutional login credentials."""
        print(_c("\n-- Institutional Login --", Fore.CYAN if _COLOR else ""))
        print("  Used for EZProxy/Shibboleth login when downloading PDFs.")
        org = self._prompt("Institution name (e.g. 'Harvard University')").strip()
        username = self._prompt("Username / email").strip()
        password = self._prompt("Password (stored locally in settings file)").strip()

        self.settings.set("institutional_org", org)
        self.settings.set("institutional_username", username)
        self.settings.set("institutional_password", password)
        self.settings.set("institutional_login_enabled", bool(org and username and password))
        print(_c("  ✓ Institutional login settings saved.", Fore.GREEN if _COLOR else ""))

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt(message: str) -> str:
        """
        Display a prompt and return the user's input.

        Args:
            message: Prompt text to display.

        Returns:
            Raw input string from the user.
        """
        try:
            return input(f"  → {message}: ")
        except (EOFError, KeyboardInterrupt):
            print("\n  (Interrupted)")
            sys.exit(0)

    @staticmethod
    def _confirm(message: str, default: bool = True) -> bool:
        """
        Ask a yes/no question and return the boolean answer.

        Args:
            message: Question to display.
            default: Default value if user presses Enter.

        Returns:
            True for yes, False for no.
        """
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            raw = input(f"  → {message} {suffix}: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return default
        if not raw:
            return default
        return raw in ("y", "yes")
