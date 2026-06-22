# AI Recruiting Mapping Tool

Phase 0/1 minimal pipeline for discovering AI/robotics recruiting candidates
from public academic data sources.

This version intentionally does not include Feishu sync, a frontend, or a
database. It fetches OpenAlex paper metadata, applies simple keyword-based
classification, and exports `papers_authors.csv`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ is recommended.

## Run

Run the full configured pipeline:

```bash
python main.py
```

For a small smoke test:

```bash
python main.py --conference CoRL --year 2024 --keyword "Robot Learning" --per-query 3
```

The output CSV contains:

- conference
- year
- paper_title
- paper_url
- abstract
- authors
- author_name
- author_order
- institution
- matched_keywords
- research_direction
- source

## Configuration

Edit `config.py` to change conferences, years, keywords, research-direction
buckets, or the default output path.

Optional environment variables:

- `OPENALEX_MAILTO`: email address for OpenAlex polite pool requests.
- `OPENALEX_PER_QUERY`: default number of OpenAlex works per query.
- `OUTPUT_CSV`: default output file path.

## Phase 1 data-source note

OpenAlex conference metadata is useful but incomplete, especially for some
robotics conference proceedings and year-specific IEEE/CVF venues. This
minimal version prefers known OpenAlex source IDs when available and otherwise
requires visible conference evidence in paper metadata before assigning a
conference label. Later phases can add OpenReview, arXiv, Semantic Scholar, and
conference accepted-paper page parsers to improve coverage.
