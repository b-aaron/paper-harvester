---
name: paper-harvester-grounded-zotero
description: Grounded literature harvesting workflow for proposal/literature-review writing, with verified references, citation exports, and optional Zotero sync.
---

# Paper Harvester Grounded Writing + Zotero

Use this skill for:

- research proposals
- literature reviews
- related-work sections
- evidence-grounded citation workflows

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
