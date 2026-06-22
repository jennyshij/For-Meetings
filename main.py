"""Run the Phase 1 AI recruiting mapping pipeline."""

from __future__ import annotations

import argparse

from config import CONFERENCES, KEYWORDS, OPENALEX_PER_QUERY, OUTPUT_CSV, YEARS
from export_csv import export_papers_authors_csv
from fetch_openalex import fetch_openalex_papers
from sync_feishu import sync_csv_to_feishu


def parse_args() -> argparse.Namespace:
    """Parse small runtime overrides for local testing and iteration."""
    parser = argparse.ArgumentParser(
        description="Fetch AI/robotics conference papers from OpenAlex and export paper-author CSV."
    )
    parser.add_argument("--output", default=OUTPUT_CSV, help="CSV output path.")
    parser.add_argument(
        "--per-query",
        type=int,
        default=OPENALEX_PER_QUERY,
        help="Maximum OpenAlex works to fetch per conference/year/keyword query.",
    )
    parser.add_argument(
        "--conference",
        action="append",
        choices=CONFERENCES,
        help="Limit to one or more configured conferences. Can be passed multiple times.",
    )
    parser.add_argument(
        "--year",
        action="append",
        type=int,
        choices=YEARS,
        help="Limit to one or more configured years. Can be passed multiple times.",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        choices=KEYWORDS,
        help="Limit to one or more configured keywords. Can be passed multiple times.",
    )
    parser.add_argument(
        "--sync-feishu",
        action="store_true",
        help="Sync the exported CSV rows to Feishu Bitable after CSV export.",
    )
    return parser.parse_args()


def main() -> None:
    """Execute the full minimal pipeline: fetch, classify, and export."""
    args = parse_args()

    conferences = args.conference or CONFERENCES
    years = args.year or YEARS
    keywords = args.keyword or KEYWORDS

    print(
        f"Fetching OpenAlex papers for {len(conferences)} conferences, "
        f"{len(years)} years, and {len(keywords)} keywords..."
    )
    rows = fetch_openalex_papers(
        conferences=conferences,
        years=years,
        keywords=keywords,
        per_query=args.per_query,
    )

    output_path = export_papers_authors_csv(rows, args.output)
    print(f"Exported {len(rows)} paper-author rows to {output_path}")

    if args.sync_feishu:
        try:
            written_count = sync_csv_to_feishu(str(output_path))
            print(f"Feishu sync completed, wrote {written_count} new rows")
        except Exception as exc:
            print(f"[ERROR] Feishu sync failed: {exc}")


if __name__ == "__main__":
    main()
