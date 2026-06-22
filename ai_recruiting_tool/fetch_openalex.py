"""
fetch_openalex.py
-----------------
Fetches papers and author metadata from the OpenAlex public API.

Strategy
~~~~~~~~
OpenAlex is queried by keyword + publication_year only.  We do NOT
filter by venue inside the API because OpenAlex does not have reliable
venue data for recent conference proceedings (2023-2025); most papers
appear under "arXiv" or have an empty source.

Conference assignment is done in post-processing by checking whatever
venue/source name OpenAlex returns against our known conference list.

Reference: https://docs.openalex.org/api-entities/works
"""

import time
import logging
from typing import Any

import requests

from config import (
    CONFERENCES,
    TARGET_YEARS,
    KEYWORDS,
    OPENALEX_BASE_URL,
    OPENALEX_EMAIL,
    OPENALEX_PAGE_SIZE,
    OPENALEX_MAX_PAGES,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)

# Conference short-code → list of substrings to match against venue names (lowercase)
_CONF_VENUE_HINTS: dict[str, list[str]] = {
    "CoRL":    ["robot learning", "corl"],
    "RSS":     ["robotics: science", "rss"],
    "ICRA":    ["robotics and automation", "icra"],
    "IROS":    ["intelligent robots and systems", "iros"],
    "NeurIPS": ["neural information processing", "neurips", "nips"],
    "ICML":    ["international conference on machine learning", "icml"],
    "ICLR":    ["learning representations", "iclr"],
    "CVPR":    ["computer vision and pattern recognition", "cvpr"],
    "ICCV":    ["international conference on computer vision", "iccv"],
    "ECCV":    ["european conference on computer vision", "eccv"],
}


def _detect_conference(locations: list[dict]) -> str:
    """
    Scan all location source names for a known conference venue substring.
    Returns the conference short-code, or empty string if none matched.
    """
    venue_texts: list[str] = []
    for loc in locations:
        src = loc.get("source") or {}
        name = (src.get("display_name") or "").lower()
        if name:
            venue_texts.append(name)

    for conf_code, hints in _CONF_VENUE_HINTS.items():
        for venue_text in venue_texts:
            for hint in hints:
                if hint in venue_text:
                    return conf_code
    return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_session() -> requests.Session:
    """Return a requests Session with a descriptive User-Agent."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": f"AIRecruitingTool/1.0 (mailto:{OPENALEX_EMAIL})",
        "Accept": "application/json",
    })
    return session


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """
    OpenAlex stores abstracts as an inverted index  {word: [pos, pos, ...]}.
    Reconstruct the original sentence by sorting positions.
    Returns empty string if index is None or empty.
    """
    if not inverted_index:
        return ""
    pos_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[p] for p in sorted(pos_word))


def _extract_authors(authorships: list[dict]) -> list[dict]:
    """
    Parse the `authorships` list from an OpenAlex Work into a flat list of
    author dicts ready for the CSV rows.
    """
    authors_out = []
    for authorship in authorships:
        author_info = authorship.get("author") or {}
        name = author_info.get("display_name") or ""
        order = authorship.get("author_position") or ""
        institutions = [
            inst.get("display_name") or ""
            for inst in (authorship.get("institutions") or [])
            if inst.get("display_name")
        ]
        institution_str = "; ".join(institutions)
        authors_out.append({
            "author_name":  name,
            "author_order": order,
            "institution":  institution_str,
        })
    return authors_out


def _parse_work(work: dict, year: int, keyword: str) -> dict | None:
    """
    Convert a single OpenAlex Work JSON object into a structured paper dict.
    Conference code is detected from venue data (may be empty).
    """
    title = (work.get("title") or "").strip()
    if not title:
        return None

    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    doi = work.get("doi") or ""
    paper_url = doi if doi.startswith("http") else work.get("id") or ""

    locations = work.get("locations") or []
    conference_code = _detect_conference(locations)

    authors = _extract_authors(work.get("authorships") or [])

    return {
        "conference":       conference_code,
        "year":             year,
        "paper_title":      title,
        "paper_url":        paper_url,
        "abstract":         abstract,
        "authors":          ", ".join(a["author_name"] for a in authors),
        "_authors_detail":  authors,
        "matched_keywords": keyword,
        "source":           "OpenAlex",
    }


# ── Core fetcher ──────────────────────────────────────────────────────────────

def fetch_papers_for_keyword(
    session: requests.Session,
    keyword: str,
    year: int,
) -> list[dict]:
    """
    Search OpenAlex for works matching `keyword` published in `year`.
    No venue filter is applied (venue matching is done post-fetch).
    Returns a list of parsed paper dicts.
    """
    papers: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, OPENALEX_MAX_PAGES + 1):
        params: dict[str, Any] = {
            "filter":  f"title_and_abstract.search:{keyword},publication_year:{year}",
            "per-page": OPENALEX_PAGE_SIZE,
            "page":     page,
            "select":   (
                "id,doi,title,publication_year,"
                "locations,authorships,"
                "abstract_inverted_index"
            ),
            "mailto":   OPENALEX_EMAIL,
        }

        try:
            resp = session.get(
                f"{OPENALEX_BASE_URL}/works",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning(
                "OpenAlex request failed (kw=%s year=%d page=%d): %s",
                keyword, year, page, exc,
            )
            break

        results: list[dict] = data.get("results") or []
        if not results:
            break

        for work in results:
            work_id = work.get("id") or ""
            if work_id in seen_ids:
                continue
            seen_ids.add(work_id)
            parsed = _parse_work(work, year, keyword)
            if parsed:
                papers.append(parsed)

        meta = data.get("meta") or {}
        total = meta.get("count") or 0
        fetched_so_far = page * OPENALEX_PAGE_SIZE
        if fetched_so_far >= total:
            break

        time.sleep(REQUEST_DELAY)

    return papers


def fetch_all_papers() -> list[dict]:
    """
    Iterate over all (keyword, year) combinations and collect deduplicated
    paper records from OpenAlex.

    Deduplication key: (year, normalised_title).
    When the same paper is matched by multiple keywords the matched_keywords
    field is updated to a comma-joined string.
    """
    session = _build_session()

    paper_map: dict[tuple, dict] = {}
    total_combos = len(KEYWORDS) * len(TARGET_YEARS)
    combo_idx = 0

    for keyword in KEYWORDS:
        for year in TARGET_YEARS:
            combo_idx += 1
            logger.info(
                "[%d/%d] OpenAlex  keyword='%s'  year=%d",
                combo_idx, total_combos, keyword, year,
            )

            papers = fetch_papers_for_keyword(session, keyword, year)

            for paper in papers:
                key = (paper["year"], paper["paper_title"].lower().strip())
                if key in paper_map:
                    existing_kws = set(
                        paper_map[key]["matched_keywords"].split(", ")
                    )
                    existing_kws.add(keyword)
                    paper_map[key]["matched_keywords"] = ", ".join(
                        sorted(existing_kws)
                    )
                else:
                    paper_map[key] = paper

            time.sleep(REQUEST_DELAY)

    logger.info("OpenAlex: %d unique papers collected", len(paper_map))
    return list(paper_map.values())
