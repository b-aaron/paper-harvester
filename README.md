# Paper Harvester

A Python tool for scraping the latest academic papers from top business and management journals (UTD24, FT50, ABS4 and custom lists).

## Features

- **Comprehensive journal coverage** – Pre-configured with all UTD24 and FT50 journals, and a selection of ABS4 journals. Full metadata database in `config/journals.json`.
- **Flexible time ranges** – Scrape the latest issue, the last N months/years, a custom date range, or everything available.
- **Rich metadata** – Retrieves title, authors, journal, year, volume/issue, pages, DOI, abstract, keywords, and publisher via the CrossRef REST API (free, no login required).
- **PDF download cascade** –
  1. Open-access PDF via [Unpaywall](https://unpaywall.org/api/v2) (legal, free).
  2. Institutional EZProxy / Shibboleth login (Selenium-powered, optional).
  3. Google Scholar fallback via the `scholarly` library.
- **Excel export** – All metadata saved to a `.xlsx` workbook (one sheet per journal or combined), with PDFs renamed `Author Year Journal Title.pdf`.
- **Zotero integration** – Automatically create items in your personal or group Zotero library, with optional PDF attachment.
- **Fully interactive CLI** – Menu-driven interface; no command-line flags required.
- **Custom journal lists** – Add/remove journals and create custom presets via the interactive menu or by editing the JSON config files.
- **Persistent settings** – Credentials, save path, and preferences stored in `~/.paper_harvester_settings.json`.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run

```bash
python main.py
```

You will be presented with the main menu:

```
========== MAIN MENU ==========
  1. Scrape articles
  2. Manage journal list
  3. Settings
  4. Exit
```

### 3. Headless mode (for skills/agents)

For non-interactive, evidence-grounded workflows (for proposal/literature-review writing), use:

```bash
python grounded_harvest.py \
  --preset marketing_comprehensive \
  --mode last_n_months \
  --n 12 \
  --max-results 120 \
  --require-doi \
  --citation-formats apa,gbt,ieee \
  --zotero \
  --zotero-collection "LitReview-Seed" \
  --save-path "D:\Research\paper_harvest"
```

This command generates:

- `verified_references_*.json` – machine-readable verified citation candidates
- `verified_references_*.md` – quick reference list for drafting
- `verified_references_apa_*.txt` – APA-style references
- `verified_references_gbt7714_*.txt` – GB/T 7714-style references
- `verified_references_ieee_*.txt` – IEEE-style references
- optional Excel/PDF outputs and Zotero library items (when enabled)

To see all options:

```bash
python grounded_harvest.py --help
```

## Project Structure

```
paper-harvester/
├── main.py                         # Entry point
├── requirements.txt                # Python dependencies
├── config/
│   ├── journals.json               # Journal database (name, ISSN, publisher, URL, list membership)
│   └── presets.json                # Named journal presets (utd24, ft50, marketing_utd, …)
└── harvester/
    ├── __init__.py
    ├── cli.py                      # Interactive CLI
    ├── config_manager.py           # Journal config & user settings management
    ├── downloader.py               # PDF downloader (Unpaywall → institutional → Scholar)
    ├── exporter.py                 # Excel export & PDF file organisation
    ├── zotero_client.py            # Zotero Web API integration
    └── scrapers/
        ├── __init__.py
        ├── base_scraper.py         # Abstract base class & Article dataclass
        └── crossref_scraper.py     # CrossRef REST API scraper + Unpaywall lookup
```

## Configuration

### Journal database (`config/journals.json`)

Each entry contains:

| Field | Description |
|---|---|
| `id` | Short unique key (e.g. `"ms"`) |
| `name` | Full journal name |
| `issn_print` / `issn_electronic` | ISSNs used to query CrossRef |
| `publisher` | Publisher name |
| `website` | Journal homepage |
| `lists` | Array of list memberships: `"utd24"`, `"ft50"`, `"abs4"` |
| `field` | Research area (e.g. `"marketing"`) |

### Presets (`config/presets.json`)

Named groups of journals for quick selection. Edit this file or use the "Manage journal list" menu to add custom presets.

Built-in presets:

| Preset ID | Description |
|---|---|
| `utd24` | UTD 24 journals |
| `ft50` | Financial Times 50 journals |
| `abs4` | ABS Guide 4/4* journals (selection) |
| `marketing_utd` | Marketing journals in UTD24 |
| `marketing_comprehensive` | All marketing journals across all lists |
| `finance` | Finance journals |
| `accounting` | Accounting journals |
| `management` | Management journals |
| `information_systems` | IS journals in UTD24 |
| `operations` | Operations & MS journals |

### User settings (`~/.paper_harvester_settings.json`)

Updated via the Settings menu. Includes:

- `save_path` – Where Excel files and PDFs are saved.
- `unpaywall_email` – Your email for Unpaywall API polite-pool access.
- `zotero_library_id`, `zotero_api_key`, `zotero_library_type` – Zotero credentials.
- `institutional_org`, `institutional_username`, `institutional_password` – For institutional login.
- `google_scholar_fallback` – Enable/disable Google Scholar as a PDF fallback.

## PDF Download

PDFs are attempted in this order:

1. **Unpaywall** – Free, legal open-access versions discovered during metadata scraping.
2. **Institutional login** – If you provide your institution's EZProxy/Shibboleth credentials in Settings, Selenium will automate the login.
3. **Google Scholar** – Last resort; uses the `scholarly` library to search for freely available versions.

If no PDF is found, the article metadata is still saved to Excel and Zotero.

## Zotero Integration

1. Go to [https://www.zotero.org/settings/keys](https://www.zotero.org/settings/keys) and create an API key with read/write access.
2. Find your numeric library ID at [https://www.zotero.org/settings/keys](https://www.zotero.org/settings/keys) (shown next to "Your userID for use in API calls").
3. Enter these in **Settings → Configure Zotero** when running the app.

## Extending

- **Add a journal**: Use the "Manage journal list → Add a journal" menu, or directly edit `config/journals.json`.
- **Add a scraper**: Subclass `harvester.scrapers.base_scraper.BaseScraper` and implement `fetch_articles`.
- **Add a new list**: Add entries to `journals.json` with a new value in the `lists` array, and add a preset in `presets.json`.

## License

MIT
