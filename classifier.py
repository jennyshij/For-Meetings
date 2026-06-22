"""Keyword matching and lightweight research-direction classification."""

from __future__ import annotations

import re
from typing import Iterable

from config import KEYWORDS, RESEARCH_DIRECTIONS


def _contains_keyword(text: str, keyword: str) -> bool:
    """Return True when a keyword appears as a case-insensitive phrase."""
    if not text:
        return False

    # Use loose word boundaries around phrase-like keywords while still
    # allowing symbols such as RT-1 and RT-2 to match correctly.
    pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def match_keywords(title: str | None, abstract: str | None, keywords: Iterable[str] = KEYWORDS) -> list[str]:
    """Find configured keywords in a paper title and abstract."""
    combined_text = " ".join(value for value in [title or "", abstract or ""] if value)
    return [keyword for keyword in keywords if _contains_keyword(combined_text, keyword)]


def classify_research_direction(matched_keywords: Iterable[str]) -> list[str]:
    """Map matched keywords to broad Phase 1 research directions."""
    matched_set = set(matched_keywords)
    directions: list[str] = []

    for direction, direction_keywords in RESEARCH_DIRECTIONS.items():
        if any(keyword in matched_set for keyword in direction_keywords):
            directions.append(direction)

    return directions
