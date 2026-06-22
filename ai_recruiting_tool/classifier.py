"""
classifier.py
-------------
Keyword-based research direction classifier.

For each paper we scan its title and abstract (case-insensitive) for every
keyword defined in config.KEYWORDS.  All matched keywords are collected and
their corresponding direction labels are deduplicated into a single string.

This is intentionally simple (no ML) so it runs instantly and is easy to
audit / extend.
"""

import re
import logging
from config import KEYWORDS

logger = logging.getLogger(__name__)

# Pre-compile one regex per keyword for speed (avoid recompiling in the loop).
# Use word-boundary anchors so "VLA" doesn't match "BVLA" etc.
_KW_PATTERNS: list[tuple[str, str, re.Pattern]] = []
for _kw, _direction in KEYWORDS.items():
    # Escape special regex chars in the keyword, then wrap in word boundaries.
    # We use (?<!\w) / (?!\w) instead of \b so accented chars don't break things.
    pattern = r"(?<!\w)" + re.escape(_kw) + r"(?!\w)"
    _KW_PATTERNS.append((_kw, _direction, re.compile(pattern, re.IGNORECASE)))


def classify_paper(paper: dict) -> dict:
    """
    Classify a single paper dict in-place.

    Adds / updates two fields:
        matched_keywords  – comma-separated list of all matched keywords
        research_direction – comma-separated list of matched direction labels

    Returns the (mutated) paper dict for convenience.
    """
    text_to_search = " ".join([
        paper.get("paper_title") or "",
        paper.get("abstract") or "",
    ])

    already_matched = set(
        kw.strip()
        for kw in (paper.get("matched_keywords") or "").split(",")
        if kw.strip()
    )
    matched_directions: set[str] = set()

    for kw, direction, pat in _KW_PATTERNS:
        if pat.search(text_to_search):
            already_matched.add(kw)
            matched_directions.add(direction)

    paper["matched_keywords"]   = ", ".join(sorted(already_matched))
    paper["research_direction"] = ", ".join(sorted(matched_directions))
    return paper


def classify_all(papers: list[dict]) -> list[dict]:
    """
    Classify every paper in the list.
    Papers that match no keyword at all are kept but will have empty
    matched_keywords / research_direction (shouldn't happen in practice since
    they were fetched via keyword search, but better to be safe).
    """
    for paper in papers:
        classify_paper(paper)

    classified = sum(1 for p in papers if p.get("matched_keywords"))
    logger.info("Classification done: %d / %d papers have keyword matches",
                classified, len(papers))
    return papers
