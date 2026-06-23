# AI Recruiting Mapping Tool

Minimal pipeline for discovering AI/robotics recruiting candidates from public
academic data sources, with optional homepage email enrichment and Phase 5
Feishu Bitable sync.

This version intentionally does not include a frontend or database. It fetches
OpenAlex paper metadata, enriches author profiles from OpenReview when
available, applies simple keyword-based classification, exports
`papers_authors.csv`, and can sync the exported CSV into Feishu only when
`--sync-feishu` is passed.

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

- paper_title
- year
- paper_url
- research_direction
- author_name
- institution
- education_history
- career_history
- advisor
- relations_conflicts
- email
- homepage
- linkedin
- github

Optional email enrichment from author homepages:

```bash
python main.py --conference ICLR --year 2024 --keyword "Reinforcement Learning" --per-query 1 --enrich-email
```

Direct OpenReview fetch for ICLR 2026, useful before OpenAlex indexes the
conference:

```bash
python main.py --conference ICLR --year 2026 --keyword "VLA" --source openreview --per-query 10
```

## Feishu sync

Create a local `.env` file with Feishu self-built app credentials and Bitable
IDs:

```bash
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=your_app_secret
FEISHU_APP_TOKEN=your_bitable_app_token
FEISHU_TABLE_ID=your_table_id
```

Then run with `--sync-feishu`:

```bash
python main.py --conference ICLR --year 2024 --keyword "Reinforcement Learning" --per-query 1 --sync-feishu
```

Sync behavior:

- Reads the exported CSV, defaulting to `papers_authors.csv`.
- Gets `tenant_access_token` from Feishu using `FEISHU_APP_ID` and
  `FEISHU_APP_SECRET`.
- Lists existing Bitable records and skips rows with the same
  `paper_url + author_name`.
- Writes at most 20 records per batch and sleeps 0.5 seconds between batches.
- Logs batch write failures and continues with later batches.
- Writes only the configured Bitable fields. Missing fields in the target
  table are logged as warnings and skipped.

## Module test commands

OpenAlex fetch and CSV export:

```bash
python main.py --conference ICLR --year 2024 --keyword "Reinforcement Learning" --per-query 1 --output /tmp/papers_authors_openalex.csv
```

OpenReview profile extraction:

```bash
python fetch_openreview.py --author-id "~Chelsea_Finn1"
```

OpenReview direct paper fetch:

```bash
python fetch_openreview.py --conference ICLR --year 2026 --keyword "VLA" --per-query 10
```

Homepage email extraction:

```bash
python enrich_email.py --input /tmp/papers_authors_openalex.csv --output /tmp/papers_authors_email.csv
```

Feishu sync with small data:

```bash
python main.py --conference ICLR --year 2024 --keyword "Reinforcement Learning" --per-query 1 --sync-feishu
```

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
