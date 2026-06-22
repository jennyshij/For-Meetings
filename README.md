# AI Recruiting Mapping Tool

Discover algorithm candidates from top AI / Robotics conferences by mining
public academic databases.

## Project Structure

```
ai_recruiting_tool/
├── config.py           # Conferences, years, keywords, API settings
├── fetch_openalex.py   # Fetch papers & authors from OpenAlex API
├── classifier.py       # Keyword-based research direction classifier
├── export_csv.py       # Export results to papers_authors.csv
├── main.py             # Pipeline entry point
├── requirements.txt
└── output/
    └── papers_authors.csv   ← generated after a run
```

## Quick Start

```bash
cd ai_recruiting_tool
pip install -r requirements.txt

# Full run (all 10 conferences × 3 years × 20 keywords — takes ~30 min)
python main.py

# Quick smoke-test (2 keywords × 3 conferences × 1 year — takes ~1 min)
python main.py --quick
```

## Output

`output/papers_authors.csv` — one row per (paper, author):

| column | description |
|---|---|
| conference | short code, e.g. ICRA |
| year | publication year |
| paper_title | full paper title |
| paper_url | DOI or OpenAlex URL |
| abstract | reconstructed abstract text |
| authors | all authors (comma-separated) |
| author_name | this row's author |
| author_order | first / middle / last |
| institution | author's institution(s) |
| matched_keywords | keywords found in title/abstract |
| research_direction | direction labels derived from keywords |
| source | data source (OpenAlex) |

## Data Sources (Phase 1)

- **OpenAlex** (primary) — free, no API key required, full structured metadata

## Phases

| Phase | Status | Description |
|---|---|---|
| 0 | ✅ Done | Project structure |
| 1 | ✅ Done | OpenAlex paper/author scraping + CSV export |
| 2 | Planned | Semantic Scholar + arXiv fallback, OpenReview integration |
| 3 | Planned | Author deduplication, h-index enrichment |
