"""
export_csv.py
-------------
Converts the list of paper dicts into the final papers_authors.csv.

Each paper is expanded so that every (paper, author) pair becomes its own row.
If a paper has no authors an empty author row is still written so the paper
is not silently dropped from the output.

Output columns (in order):
    conference, year, paper_title, paper_url, abstract,
    authors, author_name, author_order, institution,
    matched_keywords, research_direction, source
"""

import os
import logging
import pandas as pd

from config import OUTPUT_DIR, OUTPUT_CSV

logger = logging.getLogger(__name__)

# Final column order for the CSV
COLUMNS = [
    "conference",
    "year",
    "paper_title",
    "paper_url",
    "abstract",
    "authors",
    "author_name",
    "author_order",
    "institution",
    "matched_keywords",
    "research_direction",
    "source",
]


def papers_to_rows(papers: list[dict]) -> list[dict]:
    """
    Expand a list of paper dicts into flat row dicts, one per (paper, author).
    The `_authors_detail` internal field is consumed and removed.
    """
    rows: list[dict] = []
    for paper in papers:
        authors_detail: list[dict] = paper.pop("_authors_detail", [])

        # Base row shared by all authors of this paper
        base = {col: paper.get(col, "") for col in COLUMNS}

        if not authors_detail:
            # No author information available — write one row with blanks
            base["author_name"]  = ""
            base["author_order"] = ""
            base["institution"]  = ""
            rows.append(base)
        else:
            for author in authors_detail:
                row = dict(base)
                row["author_name"]  = author.get("author_name", "")
                row["author_order"] = author.get("author_order", "")
                row["institution"]  = author.get("institution", "")
                rows.append(row)

    return rows


def export_csv(papers: list[dict]) -> str:
    """
    Write papers_authors.csv to OUTPUT_DIR.
    Returns the full path to the written file.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, OUTPUT_CSV)

    rows = papers_to_rows(papers)

    if not rows:
        logger.warning("No rows to export — writing empty CSV with headers only.")
        df = pd.DataFrame(columns=COLUMNS)
    else:
        df = pd.DataFrame(rows, columns=COLUMNS)

    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    logger.info(
        "Exported %d rows (%d unique papers) → %s",
        len(df), df["paper_title"].nunique(), output_path,
    )
    return output_path
