"""CSV export helpers for the recruiting mapping pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


CSV_COLUMNS = [
    "paper_title",
    "year",
    "paper_url",
    "research_direction",
    "author_name",
    "institution",
    "education_history",
    "career_history",
    "advisor",
    "relations_conflicts",
    "email",
    "homepage",
    "linkedin",
    "github",
]


def export_papers_authors_csv(rows: list[dict[str, Any]], output_path: str) -> Path:
    """Write normalized paper-author rows to the requested CSV file."""
    path = Path(output_path)
    dataframe = pd.DataFrame(rows, columns=CSV_COLUMNS)

    # Pandas will leave missing fields as NaN by default; replace them so empty
    # OpenAlex fields become blank CSV cells as requested.
    dataframe = dataframe.fillna("")
    dataframe.to_csv(path, index=False, encoding="utf-8")
    return path
