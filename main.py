"""Run the Phase 1 AI recruiting mapping pipeline."""

from __future__ import annotations

import argparse

from config import CONFERENCES, KEYWORDS, OPENALEX_PER_QUERY, OUTPUT_CSV, YEARS
from enrich_email import enrich_rows_with_homepage_emails
from enrich_institution import enrich_rows_with_institution_details
from export_csv import export_papers_authors_csv
from fetch_openalex import fetch_openalex_papers
from fetch_openreview import enrich_rows_with_openreview, fetch_openreview_papers
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
        "--source",
        choices=["openalex", "openreview"],
        default="openalex",
        help="Paper metadata source. Use openreview for direct ICLR 2026 fetching.",
    )
    parser.add_argument(
        "--sync-feishu",
        action="store_true",
        help="Sync the exported CSV rows to Feishu Bitable after CSV export.",
    )
    parser.add_argument(
        "--enrich-email",
        action="store_true",
        help="Fetch author homepages and extract emails before CSV export.",
    )
    parser.add_argument(
        "--force-update",
        action="store_true",
        help="When syncing Feishu, update existing rows instead of skipping them.",
    )
    return parser.parse_args()


def main() -> None:
    """Execute the full minimal pipeline: fetch, classify, and export."""
    args = parse_args()

    conferences = args.conference or CONFERENCES
    years = args.year or YEARS
    keywords = args.keyword or KEYWORDS

    if args.source == "openreview":
        if len(conferences) != 1 or len(years) != 1:
            print("[WARN] OpenReview direct fetch expects one conference and one year; using first values")
        conference = conferences[0]
        year = years[0]
        print(
            f"Fetching OpenReview papers for {conference} {year} "
            f"and {len(keywords)} keywords..."
        )
        rows = fetch_openreview_papers(
            conference=conference,
            year=year,
            keywords=keywords,
            per_query=args.per_query,
        )
    else:
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
        rows = enrich_rows_with_openreview(rows)
    if args.enrich_email:
        rows = enrich_rows_with_homepage_emails(rows)
    rows = enrich_rows_with_institution_details(rows)

    output_path = export_papers_authors_csv(rows, args.output)
    print(f"Exported {len(rows)} paper-author rows to {output_path}")

    if args.sync_feishu:
        try:
            sync_result = sync_csv_to_feishu(str(output_path), force_update=args.force_update)
            print(
                "Feishu sync completed, "
                f"created {sync_result['created']} rows, "
                f"updated {sync_result['updated']} rows, "
                f"skipped {sync_result['skipped']} rows"
            )
        except Exception as exc:
            print(f"[ERROR] Feishu sync failed: {exc}")


if __name__ == "__main__":
    main()
