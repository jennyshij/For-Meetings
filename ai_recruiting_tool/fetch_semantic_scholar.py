"""
fetch_semantic_scholar.py
--------------------------
Fetches papers and author metadata from the Semantic Scholar public API.

Semantic Scholar is used as a *conference-aware* source: its `venue`
field reliably names the conference for recent (2023–2025) papers.
We search per (keyword, conference_name, year) and post-filter by venue.

No API key is required for the public tier, but rate limits apply
(~1 request / second without a key).  We respect this with REQUEST_DELAY.

Reference: https://api.semanticscholar.org/graph/v1
"""

import time
import logging
from typing import Any

import requests

from config import (
    CONFERENCES,
    TARGET_YEARS,
    KEYWORDS,
    REQUEST_DELAY,
)

logger = logging.getLogger(__name__)

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"

# Fields to request from Semantic Scholar for each paper
S2_PAPER_FIELDS = (
    "paperId,title,year,venue,externalIds,"
    "abstract,authors,authors.name,authors.affiliations"
)

# Max results per page (Semantic Scholar allows up to 100)
S2_PAGE_SIZE = 100

# Max pages per (keyword, conference, year) query
S2_MAX_PAGES = 3

# Seconds to wait between requests.
# Without a key the free tier is ~1 req/s; with a key it's much higher.
# We use a conservative 3s to avoid 429 errors in batch mode.
S2_DELAY = 3.0

# Exponential backoff caps for 429 responses (seconds)
S2_RETRY_DELAYS = [30, 60, 120]

# Venue substrings used to match Semantic Scholar venue strings (lowercase)
_VENUE_HINTS: dict[str, list[str]] = {
    "CoRL":    ["robot learning", "corl"],
    "RSS":     ["robotics: science", "robotics science and systems", "rss"],
    "ICRA":    ["robotics and automation", "icra"],
    "IROS":    ["intelligent robots and systems", "iros"],
    "NeurIPS": ["neural information processing", "neurips", "nips"],
    "ICML":    ["machine learning", "icml"],
    "ICLR":    ["learning representations", "iclr"],
    "CVPR":    ["computer vision and pattern recognition", "cvpr"],
    "ICCV":    ["international conference on computer vision", "iccv"],
    "ECCV":    ["european conference on computer vision", "eccv"],
}


def _build_session() -> requests.Session:
    from config import S2_API_KEY
    session = requests.Session()
    session.headers.update({
        "User-Agent": "AIRecruitingTool/1.0",
        "Accept":     "application/json",
    })
    if S2_API_KEY:
        session.headers["x-api-key"] = S2_API_KEY
    return session


def _detect_conference_from_venue(venue: str) -> str:
    """
    Map a Semantic Scholar `venue` string to our conference short-code.
    Returns empty string if no match is found.
    """
    venue_lc = venue.lower()
    for conf_code, hints in _VENUE_HINTS.items():
        for hint in hints:
            if hint in venue_lc:
                return conf_code
    return ""


def _extract_authors(raw_authors: list[dict]) -> list[dict]:
    """Parse Semantic Scholar authors list into flat author dicts."""
    out = []
    for idx, a in enumerate(raw_authors):
        name = a.get("name") or ""
        affiliations = a.get("affiliations") or []
        institution_str = "; ".join(aff for aff in affiliations if aff)
        order = "first" if idx == 0 else ("last" if idx == len(raw_authors) - 1 else "middle")
        out.append({
            "author_name":  name,
            "author_order": order,
            "institution":  institution_str,
        })
    return out


def _parse_paper(paper: dict, target_conf: str, year: int, keyword: str) -> dict | None:
    """Convert a Semantic Scholar paper JSON into a structured paper dict."""
    title = (paper.get("title") or "").strip()
    if not title:
        return None

    # Get the best URL: prefer DOI, fall back to S2 paper page
    ext_ids = paper.get("externalIds") or {}
    doi = ext_ids.get("DOI") or ""
    paper_url = (
        f"https://doi.org/{doi}" if doi
        else f"https://www.semanticscholar.org/paper/{paper.get('paperId','')}"
    )

    venue = paper.get("venue") or ""
    detected_conf = _detect_conference_from_venue(venue)

    # Only keep paper if it belongs to the conference we're targeting
    if target_conf and detected_conf and detected_conf != target_conf:
        return None
    if target_conf and not detected_conf:
        # Venue data is missing or doesn't match — skip to avoid noise
        return None

    authors = _extract_authors(paper.get("authors") or [])

    return {
        "conference":       detected_conf or target_conf,
        "year":             year,
        "paper_title":      title,
        "paper_url":        paper_url,
        "abstract":         paper.get("abstract") or "",
        "authors":          ", ".join(a["author_name"] for a in authors),
        "_authors_detail":  authors,
        "matched_keywords": keyword,
        "source":           "SemanticScholar",
    }


def fetch_s2_papers_for_combo(
    session: requests.Session,
    keyword: str,
    conf_code: str,
    year: int,
) -> list[dict]:
    """
    Query Semantic Scholar for papers matching keyword, filtered to a specific
    conference and year.  Returns list of parsed paper dicts.
    """
    papers: list[dict] = []
    seen_ids: set[str] = set()
    offset = 0

    for page in range(S2_MAX_PAGES):
        params: dict[str, Any] = {
            "query":  keyword,
            "fields": S2_PAPER_FIELDS,
            "limit":  S2_PAGE_SIZE,
            "offset": offset,
            "year":   str(year),
        }

        data = None
        for attempt, backoff in enumerate([0] + S2_RETRY_DELAYS):
            if backoff:
                logger.warning("S2 rate limited — sleeping %ds (attempt %d) …", backoff, attempt)
                time.sleep(backoff)
            try:
                resp = session.get(
                    f"{S2_BASE_URL}/paper/search",
                    params=params,
                    timeout=30,
                )
                if resp.status_code == 429:
                    continue  # retry with next backoff
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.RequestException as exc:
                logger.warning(
                    "S2 request failed (kw=%s conf=%s year=%d page=%d): %s",
                    keyword, conf_code, year, page, exc,
                )
                break

        if data is None:
            logger.warning("S2 skipping combo after repeated failures")
            break

        results: list[dict] = data.get("data") or []
        if not results:
            break

        for paper in results:
            pid = paper.get("paperId") or ""
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            parsed = _parse_paper(paper, conf_code, year, keyword)
            if parsed:
                papers.append(parsed)

        total = data.get("total") or 0
        offset += S2_PAGE_SIZE
        if offset >= total:
            break

        time.sleep(S2_DELAY)

    return papers


def fetch_all_papers() -> list[dict]:
    """
    Iterate over (keyword, conference, year) and return deduplicated papers.
    Deduplication key: (conference, year, normalised_title).

    NOTE: Without a Semantic Scholar API key, the free tier allows only
    ~1 request/second and may return 429 errors for large batch jobs.
    Get a free key at https://www.semanticscholar.org/product/api and set
    S2_API_KEY in config.py (or via S2_API_KEY environment variable) to
    dramatically improve throughput.
    """
    from config import S2_API_KEY
    if not S2_API_KEY:
        logger.warning(
            "No S2_API_KEY configured — Semantic Scholar requests will be "
            "heavily rate-limited. Set S2_API_KEY in config.py for better results. "
            "Get a free key at https://www.semanticscholar.org/product/api"
        )

    session = _build_session()
    paper_map: dict[tuple, dict] = {}

    total_combos = len(KEYWORDS) * len(CONFERENCES) * len(TARGET_YEARS)
    combo_idx = 0

    for keyword in KEYWORDS:
        for conf_code in CONFERENCES:
            for year in TARGET_YEARS:
                combo_idx += 1
                logger.info(
                    "[%d/%d] S2  keyword='%s'  conf=%s  year=%d",
                    combo_idx, total_combos, keyword, conf_code, year,
                )

                papers = fetch_s2_papers_for_combo(session, keyword, conf_code, year)

                for paper in papers:
                    key = (
                        paper["conference"],
                        paper["year"],
                        paper["paper_title"].lower().strip(),
                    )
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

                time.sleep(S2_DELAY)

    logger.info("SemanticScholar: %d unique papers collected", len(paper_map))
    return list(paper_map.values())
