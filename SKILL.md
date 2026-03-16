---
name: paper-harvester-grounded-zotero
description: Trigger this skill for literature search/review/research-design tasks; harvest DOI-grounded references, verify discipline coverage in config first, and optionally sync to Zotero after explicit user confirmation.
---

# Paper Harvester Grounded Writing + Zotero

## Auto-trigger conditions (must call this skill)

Call this skill whenever the user asks for any of the following:

- literature search / paper search / evidence collection
- literature review / related-work writing
- research proposal / research design / hypothesis development
- Chinese intents such as: “搜索文献”“文献检索”“文献综述”“研究设计”“研究框架”“提出假设”

Use this skill for:

- research proposals
- literature reviews
- related-work sections
- evidence-grounded citation workflows

## Pre-flight checks (required)

1. **Discipline coverage check**
   - Before harvesting, verify the requested discipline can be mapped to presets in:
     - `config/presets.json`
     - (and, if needed) `config/journals.json`
   - If the discipline is **not** covered, stop and ask the user to update config (or provide specific journal IDs), then continue.
   - Do not silently guess an unrelated preset.

2. **Zotero sync decision check**
   - Ask the user whether they want references written to Zotero.
   - If **yes**, request/confirm Zotero parameters:
     - `--zotero-library-id`
     - `--zotero-api-key`
     - `--zotero-library-type` (`user` or `group`)
     - optional `--zotero-collection`
   - If **no**, run harvest without `--zotero`.
   - Never hardcode secrets in prompts or files.

## Mandatory anti-hallucination rules

1. Never invent papers, DOIs, authors, venues, years, or URLs.
2. Harvest first, write later.
3. Prefer DOI-backed records (`--require-doi`).
4. If evidence is missing, explicitly state insufficient evidence.
5. Every citation must map to generated verified artifacts.

## Required workflow

### 1) Harvest verified references

Run from repository root:

```bash
# Without Zotero sync
python grounded_harvest.py \
  --preset marketing_comprehensive \
  --mode last_n_months \
  --n 12 \
  --max-results 120 \
  --require-doi \
  --citation-formats apa,gbt,ieee

# With Zotero sync (only after user confirms Zotero write)
python grounded_harvest.py \
  --preset marketing_comprehensive \
  --mode last_n_months \
  --n 12 \
  --max-results 120 \
  --require-doi \
  --citation-formats apa,gbt,ieee \
  --zotero \
  --zotero-collection "LitReview-Seed"
```

### 2) Cite only generated outputs

- `verified_references_*.json` (source of truth)
- `verified_references_*.md` (human-readable list)
- `verified_references_apa_*.txt`
- `verified_references_gbt7714_*.txt`
- `verified_references_ieee_*.txt`

### 3) Draft with explicit evidence links

- Tie each key claim to verified references.
- Include DOI or URL where available.
- Mark uncertain claims as gaps to verify.

## Zotero credentials

The script reads credentials from `~/.paper_harvester_settings.json` or CLI overrides:

- `--zotero-library-id`
- `--zotero-api-key`
- `--zotero-library-type`

Never hardcode secrets in prompts or files.
