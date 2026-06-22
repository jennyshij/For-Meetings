"""
main.py
-------
Entry point for the AI Recruiting Mapping Tool — Phase 1.

Pipeline
~~~~~~~~
1. fetch_all_papers()  → raw paper dicts from Semantic Scholar + OpenAlex
2. classify_all()      → add matched_keywords + research_direction
3. export_csv()        → write output/papers_authors.csv

Data sources
~~~~~~~~~~~~
- Semantic Scholar (primary)  — reliable venue/conference data, free API
- OpenAlex          (fallback) — broader coverage, author + institution data

Usage
~~~~~
    cd ai_recruiting_tool
    python3 main.py

Optional flags
~~~~~~~~~~~~~~
    --quick       2 keywords × 3 conferences × 1 year; fast smoke-test.
    --source s2   Use only Semantic Scholar  (default: both)
    --source oa   Use only OpenAlex
    --source both Use both sources (default)
    --output DIR  Override output directory (default: output/)
"""

import argparse
import logging
import sys
import os

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("recruiting_tool.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

import config                                       # noqa: E402
from fetch_semantic_scholar import fetch_all_papers as s2_fetch   # noqa: E402
from fetch_openalex import fetch_all_papers as oa_fetch           # noqa: E402
from classifier import classify_all                               # noqa: E402
from export_csv import export_csv                                 # noqa: E402


def apply_quick_mode() -> None:
    """Restrict config to a small subset for a fast smoke-test."""
    quick_kws = dict(list(config.KEYWORDS.items())[:2])
    config.KEYWORDS.clear()
    config.KEYWORDS.update(quick_kws)

    quick_confs = dict(list(config.CONFERENCES.items())[:3])
    config.CONFERENCES.clear()
    config.CONFERENCES.update(quick_confs)

    config.TARGET_YEARS[:] = [config.TARGET_YEARS[-1]]
    config.OPENALEX_MAX_PAGES = 1
    config.OPENALEX_PAGE_SIZE = 25

    logger.info(
        "Quick mode: keywords=%s  confs=%s  years=%s",
        list(config.KEYWORDS.keys()),
        list(config.CONFERENCES.keys()),
        config.TARGET_YEARS,
    )


def merge_papers(lists: list[list[dict]]) -> list[dict]:
    """
    Merge multiple paper lists, deduplicating by (year, normalised_title).
    When duplicates exist, prefer the record with a non-empty conference.
    Matched keywords are merged across duplicates.
    """
    paper_map: dict[tuple, dict] = {}
    for papers in lists:
        for paper in papers:
            key = (paper["year"], paper["paper_title"].lower().strip())
            if key not in paper_map:
                paper_map[key] = paper
            else:
                existing = paper_map[key]
                # Prefer the record that has a conference assigned
                if not existing.get("conference") and paper.get("conference"):
                    paper_map[key] = paper
                # Always merge matched keywords
                kws = set(existing.get("matched_keywords", "").split(", "))
                kws.update(paper.get("matched_keywords", "").split(", "))
                kws.discard("")
                paper_map[key]["matched_keywords"] = ", ".join(sorted(kws))
    return list(paper_map.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Recruiting Mapping Tool — fetch papers from top AI/Robotics conferences"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick smoke-test mode (small data subset)",
    )
    parser.add_argument(
        "--source",
        choices=["s2", "oa", "both"],
        default="oa",
        help=(
            "Data source: oa=OpenAlex (default, fast, no rate-limit), "
            "s2=SemanticScholar (better venue data, requires patience), "
            "both=merge all sources"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Override output directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.quick:
        apply_quick_mode()
    if args.output:
        config.OUTPUT_DIR = args.output

    logger.info("=" * 60)
    logger.info("AI Recruiting Mapping Tool  —  Phase 1 Start")
    logger.info("Conferences : %s", list(config.CONFERENCES.keys()))
    logger.info("Years       : %s", config.TARGET_YEARS)
    logger.info("Keywords    : %d defined", len(config.KEYWORDS))
    logger.info("Source      : %s", args.source)
    logger.info("=" * 60)

    all_paper_lists: list[list[dict]] = []

    # ── Step 1a: Semantic Scholar fetch ───────────────────────────────────────
    if args.source in ("s2", "both"):
        logger.info("Step 1a — Fetching from Semantic Scholar …")
        s2_papers = s2_fetch()
        logger.info("Step 1a done  →  %d S2 papers", len(s2_papers))
        all_paper_lists.append(s2_papers)

    # ── Step 1b: OpenAlex fetch ───────────────────────────────────────────────
    if args.source in ("oa", "both"):
        logger.info("Step 1b — Fetching from OpenAlex …")
        oa_papers = oa_fetch()
        logger.info("Step 1b done  →  %d OA papers", len(oa_papers))
        all_paper_lists.append(oa_papers)

    # ── Merge ─────────────────────────────────────────────────────────────────
    papers = merge_papers(all_paper_lists)
    logger.info("After merge: %d unique papers", len(papers))

    if not papers:
        logger.warning("No papers found. Check your config or network connection.")
        sys.exit(0)

    # ── Step 2: Classify ──────────────────────────────────────────────────────
    logger.info("Step 2/3 — Classifying papers by keyword …")
    papers = classify_all(papers)

    from collections import Counter
    direction_counts: Counter = Counter()
    for p in papers:
        for d in (p.get("research_direction") or "").split(", "):
            if d:
                direction_counts[d] += 1
    logger.info("Research direction breakdown:")
    for direction, count in direction_counts.most_common():
        logger.info("  %-35s %d", direction, count)

    # Conference breakdown
    conf_counts: Counter = Counter(
        p.get("conference") or "(unknown)" for p in papers
    )
    logger.info("Conference breakdown:")
    for conf, count in conf_counts.most_common():
        logger.info("  %-10s %d", conf, count)

    # ── Step 3: Export ────────────────────────────────────────────────────────
    logger.info("Step 3/3 — Exporting CSV …")
    output_path = export_csv(papers)
    logger.info("Step 3 done  →  %s", output_path)

    logger.info("=" * 60)
    logger.info("All done!  Output: %s", os.path.abspath(output_path))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
