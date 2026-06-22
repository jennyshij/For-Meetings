# AI Recruiting Mapping Tool

Phase 0/1 minimal pipeline for discovering AI/robotics recruiting candidates
from public academic data sources, plus optional Phase 5 Feishu Bitable sync.

This version intentionally does not include a frontend or database. It fetches
OpenAlex paper metadata, applies simple keyword-based classification, exports
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

- conference
- year
- paper_title
- paper_url
- abstract
- authors
- author_name
- author_order
- institution
- matched_org
- org_type
- email
- matched_keywords
- research_direction
- source

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
- Writes the status field `状态` as `未联系` for every new record.

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
