"""
grounded_harvest.py - Non-interactive, evidence-grounded paper harvesting.

This script wraps the existing paper-harvester modules so an agent (or user)
can run literature retrieval without stepping through interactive menus.

Primary goals:
1. Harvest real papers from configured journals/presets.
2. Export a verified reference artifact (JSON + Markdown) for writing tasks.
3. Optionally export Excel/PDFs and push results to Zotero.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from harvester.config_manager import JournalConfigManager, UserSettings
from harvester.downloader import PDFDownloader
from harvester.exporter import Exporter
from harvester.scrapers.base_scraper import Article
from harvester.scrapers.crossref_scraper import CrossRefScraper, build_date_range
from harvester.zotero_client import ZoteroClient

SUPPORTED_CITATION_FORMATS = {"apa", "gbt", "ieee"}
CITATION_FORMAT_ALIASES = {
    "apa": "apa",
    "apa7": "apa",
    "gbt": "gbt",
    "gb/t": "gbt",
    "gbt7714": "gbt",
    "gbt-7714": "gbt",
    "ieee": "ieee",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run paper harvesting in non-interactive mode and emit verified "
            "reference artifacts for grounded proposal/literature-review writing."
        )
    )
    parser.add_argument("--preset", default="marketing_comprehensive", help="Preset ID from config/presets.json.")
    parser.add_argument(
        "--journal-ids",
        default="",
        help="Comma-separated journal IDs. If provided, overrides --preset.",
    )
    parser.add_argument(
        "--mode",
        choices=["latest_issue", "last_n_months", "last_n_years", "custom", "all"],
        default="last_n_months",
        help="Time range mode.",
    )
    parser.add_argument("--n", type=int, default=12, help="N for last_n_months/last_n_years.")
    parser.add_argument("--from-date", default=None, help="Custom range start date (YYYY-MM-DD).")
    parser.add_argument("--until-date", default=None, help="Custom range end date (YYYY-MM-DD).")
    parser.add_argument("--max-results", type=int, default=100, help="Max articles per journal.")
    parser.add_argument("--save-path", default=None, help="Output directory. Defaults to user settings.")
    parser.add_argument("--unpaywall-email", default=None, help="Email for CrossRef/Unpaywall polite pool.")
    parser.add_argument(
        "--require-doi",
        action="store_true",
        help="Keep only records with DOI (recommended for anti-hallucination workflows).",
    )
    parser.add_argument("--excel", action="store_true", help="Export Excel workbook.")
    parser.add_argument("--download-pdf", action="store_true", help="Attempt PDF download.")
    parser.add_argument("--zotero", action="store_true", help="Save harvested papers to Zotero.")
    parser.add_argument("--zotero-collection", default="PaperHarvester", help="Zotero collection name.")
    parser.add_argument("--zotero-library-id", default=None, help="Override Zotero library ID.")
    parser.add_argument("--zotero-api-key", default=None, help="Override Zotero API key.")
    parser.add_argument(
        "--zotero-library-type",
        choices=["user", "group"],
        default=None,
        help="Override Zotero library type.",
    )
    parser.add_argument("--topic", default="", help="Optional topic label included in Markdown artifact.")
    parser.add_argument(
        "--output-prefix",
        default="verified_references",
        help="Prefix for generated JSON/Markdown artifacts.",
    )
    parser.add_argument(
        "--citation-formats",
        default="apa,gbt,ieee",
        help=(
            "Comma-separated citation formats to export. Supported: "
            "apa, gbt, ieee. Use 'none' to disable citation files."
        ),
    )
    return parser.parse_args()


def _select_journals(config: JournalConfigManager, preset: str, journal_ids_raw: str) -> List[Dict]:
    if journal_ids_raw.strip():
        requested_ids = [item.strip() for item in journal_ids_raw.split(",") if item.strip()]
        journals = config.get_journals_by_ids(requested_ids)
        found_ids = {j["id"] for j in journals}
        missing = [jid for jid in requested_ids if jid not in found_ids]
        if missing:
            raise ValueError(f"Unknown journal IDs: {', '.join(missing)}")
        return journals

    try:
        journals = config.get_journals_by_preset(preset)
    except ValueError as exc:
        raise ValueError(
            f"Preset '{preset}' not found. Check config/presets.json or use --journal-ids."
        ) from exc

    if not journals:
        raise ValueError(f"Preset '{preset}' returned no journals.")
    return journals


def _resolve_date_range(args: argparse.Namespace) -> Dict[str, Optional[str]]:
    if args.mode in ("last_n_months", "last_n_years"):
        if args.n <= 0:
            raise ValueError("--n must be > 0 for last_n_months/last_n_years.")
        return build_date_range(args.mode, n=args.n)

    if args.mode == "custom":
        if not args.from_date and not args.until_date:
            raise ValueError("Custom mode requires at least one of --from-date or --until-date.")
        return build_date_range("custom", from_date=args.from_date, until_date=args.until_date)

    return build_date_range(args.mode)


def _dedupe_articles(articles: List[Article]) -> List[Article]:
    seen = set()
    deduped: List[Article] = []
    for article in articles:
        if article.doi:
            key = f"doi:{article.doi.strip().lower()}"
        else:
            key = "meta:{title}|{year}|{journal}".format(
                title=(article.title or "").strip().lower(),
                year=article.year or "",
                journal=(article.journal or "").strip().lower(),
            )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(article)
    return deduped


def _article_to_record(article: Article) -> Dict:
    doi = (article.doi or "").strip()
    doi_url = f"https://doi.org/{doi}" if doi else ""
    authors = article.authors or []
    return {
        "title": article.title or "",
        "authors": authors,
        "journal": article.journal or "",
        "year": article.year,
        "volume": article.volume or "",
        "issue": article.issue or "",
        "pages": article.pages or "",
        "doi": doi,
        "doi_url": doi_url,
        "url": article.url or "",
        "abstract": article.abstract or "",
        "keywords": article.keywords or [],
        "pdf_path": article.pdf_path or "",
    }


def _render_reference_line(record: Dict) -> str:
    authors = ", ".join(record["authors"]) if record["authors"] else "Unknown author"
    year = record["year"] if record["year"] else "n.d."
    journal = record["journal"] or "Unknown journal"
    doi_part = f" DOI: {record['doi_url']}" if record["doi_url"] else ""
    return f"{authors} ({year}). {record['title']}. {journal}.{doi_part}"


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _split_name(name: str) -> Tuple[str, str]:
    normalized = _normalize_space(name)
    if not normalized:
        return "", ""
    if "," in normalized:
        parts = [part.strip() for part in normalized.split(",") if part.strip()]
        family = parts[0]
        given = " ".join(parts[1:]) if len(parts) > 1 else ""
        return family, given
    tokens = normalized.split(" ")
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[-1], " ".join(tokens[:-1])


def _given_name_initials(given_name: str) -> str:
    initials: List[str] = []
    for token in re.split(r"[\s\-]+", given_name):
        token = token.strip(". ")
        if token:
            initials.append(f"{token[0].upper()}.")
    return " ".join(initials)


def _format_author_apa(name: str) -> str:
    family, given = _split_name(name)
    if not family and not given:
        return ""
    initials = _given_name_initials(given)
    return f"{family}, {initials}".strip(", ") if initials else family


def _format_author_ieee(name: str) -> str:
    family, given = _split_name(name)
    if not family and not given:
        return ""
    initials = _given_name_initials(given)
    if initials:
        return f"{initials} {family}".strip()
    return family


def _format_author_list_apa(authors: List[str]) -> str:
    formatted = [item for item in (_format_author_apa(name) for name in authors) if item]
    if not formatted:
        return "Unknown author"
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def _format_author_list_gbt(authors: List[str]) -> str:
    cleaned = [_normalize_space(name) for name in authors if _normalize_space(name)]
    if not cleaned:
        return "Unknown author"
    if len(cleaned) > 3:
        return ", ".join(cleaned[:3]) + ", et al."
    return ", ".join(cleaned)


def _format_author_list_ieee(authors: List[str]) -> str:
    formatted = [item for item in (_format_author_ieee(name) for name in authors) if item]
    if not formatted:
        return "Unknown author"
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


def _format_citation_apa(record: Dict) -> str:
    authors = _format_author_list_apa(record.get("authors", []))
    year = str(record.get("year") or "n.d.")
    title = _normalize_space(record.get("title") or "[No title]")
    journal = _normalize_space(record.get("journal") or "Unknown journal")
    volume = _normalize_space(record.get("volume") or "")
    issue = _normalize_space(record.get("issue") or "")
    pages = _normalize_space(record.get("pages") or "")
    link = _normalize_space(record.get("doi_url") or record.get("url") or "")

    journal_part = journal
    if volume:
        journal_part += f", {volume}"
        if issue:
            journal_part += f"({issue})"
    elif issue:
        journal_part += f", ({issue})"
    if pages:
        journal_part += f", {pages}"
    journal_part += "."

    citation = f"{authors} ({year}). {title}. {journal_part}"
    if link:
        citation += f" {link}"
    return citation


def _format_citation_gbt(record: Dict) -> str:
    authors = _format_author_list_gbt(record.get("authors", []))
    year = str(record.get("year") or "n.d.")
    title = _normalize_space(record.get("title") or "[No title]")
    journal = _normalize_space(record.get("journal") or "Unknown journal")
    volume = _normalize_space(record.get("volume") or "")
    issue = _normalize_space(record.get("issue") or "")
    pages = _normalize_space(record.get("pages") or "")
    doi = _normalize_space(record.get("doi") or "")
    url = _normalize_space(record.get("url") or "")

    journal_part = f"{journal}, {year}"
    if volume:
        journal_part += f", {volume}"
        if issue:
            journal_part += f"({issue})"
    elif issue:
        journal_part += f", ({issue})"
    if pages:
        journal_part += f": {pages}"
    journal_part += "."

    citation = f"{authors}. {title}[J]. {journal_part}"
    if doi:
        citation += f" DOI: {doi}."
    elif url:
        citation += f" URL: {url}."
    return citation


def _format_citation_ieee(record: Dict) -> str:
    authors = _format_author_list_ieee(record.get("authors", []))
    title = _normalize_space(record.get("title") or "[No title]")
    journal = _normalize_space(record.get("journal") or "Unknown journal")
    volume = _normalize_space(record.get("volume") or "")
    issue = _normalize_space(record.get("issue") or "")
    pages = _normalize_space(record.get("pages") or "")
    year = str(record.get("year") or "n.d.")
    doi = _normalize_space(record.get("doi") or "")
    url = _normalize_space(record.get("url") or "")

    parts = [f"{authors}, \"{title},\" {journal}"]
    if volume:
        parts.append(f"vol. {volume}")
    if issue:
        parts.append(f"no. {issue}")
    if pages:
        parts.append(f"pp. {pages}")
    parts.append(year)

    citation = ", ".join(parts) + "."
    if doi:
        citation += f" doi: {doi}."
    elif url:
        citation += f" Available: {url}"
    return citation


def _parse_citation_formats(raw: str) -> List[str]:
    if not raw or raw.strip().lower() in {"none", "off", "no"}:
        return []
    formats: List[str] = []
    for token in raw.split(","):
        cleaned = token.strip().lower()
        if not cleaned:
            continue
        normalized = CITATION_FORMAT_ALIASES.get(cleaned)
        if not normalized or normalized not in SUPPORTED_CITATION_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_CITATION_FORMATS))
            raise ValueError(f"Unsupported citation format '{cleaned}'. Supported: {supported}")
        if normalized not in formats:
            formats.append(normalized)
    return formats


def _write_verified_artifacts(
    articles: List[Article],
    save_path: str,
    output_prefix: str,
    topic: str,
    timestamp: str,
) -> Tuple[str, str]:
    records = [_article_to_record(article) for article in articles]

    json_path = os.path.join(save_path, f"{output_prefix}_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    md_path = os.path.join(save_path, f"{output_prefix}_{timestamp}.md")
    lines: List[str] = []
    lines.append("# Verified References")
    if topic:
        lines.append("")
        lines.append(f"Topic: {topic}")
    lines.append("")
    lines.append(
        "Use only the references below when drafting a proposal/literature review. "
        "If a needed claim is not covered, state that evidence is insufficient."
    )
    lines.append("")
    for idx, record in enumerate(records, 1):
        lines.append(f"{idx}. {_render_reference_line(record)}")
    lines.append("")
    lines.append(f"Total verified references: {len(records)}")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path


def _write_citation_artifacts(
    articles: List[Article],
    save_path: str,
    output_prefix: str,
    timestamp: str,
    formats: List[str],
) -> Dict[str, str]:
    records = [_article_to_record(article) for article in articles]
    formatter_map: Dict[str, Tuple[str, Callable[[Dict], str]]] = {
        "apa": ("apa", _format_citation_apa),
        "gbt": ("gbt7714", _format_citation_gbt),
        "ieee": ("ieee", _format_citation_ieee),
    }
    output_paths: Dict[str, str] = {}

    for fmt in formats:
        alias, formatter = formatter_map[fmt]
        path = os.path.join(save_path, f"{output_prefix}_{alias}_{timestamp}.txt")
        lines: List[str] = []
        for idx, record in enumerate(records, 1):
            prefix = f"[{idx}] " if fmt == "ieee" else f"{idx}. "
            lines.append(prefix + formatter(record))
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        output_paths[fmt] = path

    return output_paths


def _save_to_zotero(
    articles: List[Article],
    settings: UserSettings,
    args: argparse.Namespace,
) -> None:
    library_id = args.zotero_library_id or settings.get("zotero_library_id")
    api_key = args.zotero_api_key or settings.get("zotero_api_key")
    library_type = args.zotero_library_type or settings.get("zotero_library_type", "user")

    if not library_id or not api_key:
        raise ValueError(
            "Zotero credentials missing. Set them in ~/.paper_harvester_settings.json "
            "or provide --zotero-library-id and --zotero-api-key."
        )

    client = ZoteroClient(
        library_id=str(library_id),
        api_key=str(api_key),
        library_type=library_type,
        collection_name=args.zotero_collection,
    )
    stats = client.save_articles(articles)
    print(
        "Zotero sync complete: "
        f"{stats['saved']} saved, {stats['skipped']} skipped, {stats['failed']} failed."
    )


def main() -> None:
    args = _parse_args()
    config = JournalConfigManager()
    settings = UserSettings()

    save_path = args.save_path or settings.get("save_path")
    if not save_path:
        raise ValueError("No save path configured. Use --save-path or set save_path in settings.")
    os.makedirs(save_path, exist_ok=True)

    email = args.unpaywall_email or settings.get("unpaywall_email") or "paper-harvester@example.com"
    journals = _select_journals(config, args.preset, args.journal_ids)
    date_range = _resolve_date_range(args)

    print(f"Selected journals: {len(journals)}")
    for journal in journals:
        print(f"  - {journal['id']}: {journal['name']}")

    scraper = CrossRefScraper(email=email)
    harvested: List[Article] = []

    for journal in journals:
        if args.mode == "latest_issue":
            results = scraper.fetch_latest_issue(journal, max_results=args.max_results)
        else:
            results = scraper.fetch_articles(
                journal,
                max_results=args.max_results,
                from_date=date_range.get("from_date"),
                until_date=date_range.get("until_date"),
            )
        harvested.extend(results)
        print(f"{journal['id']}: fetched {len(results)} article(s)")

    if not harvested:
        raise ValueError("No articles were harvested.")

    deduped = _dedupe_articles(harvested)
    print(f"Total harvested: {len(harvested)} | After dedupe: {len(deduped)}")

    citation_formats = _parse_citation_formats(args.citation_formats)
    if citation_formats:
        print(f"Citation formats: {', '.join(citation_formats)}")
    else:
        print("Citation formats: disabled")

    if args.require_doi:
        with_doi = [article for article in deduped if article.doi]
        removed = len(deduped) - len(with_doi)
        print(f"DOI filter enabled: removed {removed} article(s) without DOI.")
        deduped = with_doi
        if not deduped:
            raise ValueError("No DOI-backed articles remain after filtering.")

    if args.download_pdf:
        creds: Dict = {}
        if settings.get("institutional_login_enabled"):
            creds = {
                "org": settings.get("institutional_org"),
                "username": settings.get("institutional_username"),
                "password": settings.get("institutional_password"),
            }
        downloader = PDFDownloader(
            save_dir=os.path.join(save_path, "pdfs"),
            institutional_credentials=creds,
            unpaywall_email=email,
            use_google_scholar=settings.get("google_scholar_fallback", True),
        )
        deduped = downloader.download(deduped)

    if args.excel:
        exporter = Exporter(save_dir=save_path)
        excel_name = f"papers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        exporter.to_excel(deduped, filename=excel_name)
        exporter.organize_pdfs(deduped)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path, md_path = _write_verified_artifacts(
        articles=deduped,
        save_path=save_path,
        output_prefix=args.output_prefix,
        topic=args.topic,
        timestamp=timestamp,
    )
    print(f"Verified JSON: {json_path}")
    print(f"Verified Markdown: {md_path}")

    citation_paths = _write_citation_artifacts(
        articles=deduped,
        save_path=save_path,
        output_prefix=args.output_prefix,
        timestamp=timestamp,
        formats=citation_formats,
    )
    for fmt, path in citation_paths.items():
        print(f"Citations ({fmt}): {path}")

    if args.zotero:
        _save_to_zotero(deduped, settings, args)

    print("Done.")


if __name__ == "__main__":
    main()
