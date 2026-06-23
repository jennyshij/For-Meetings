"""Fetch papers and author metadata from the OpenAlex Works API."""

from __future__ import annotations

import time
from typing import Any

import requests

from classifier import classify_research_direction, match_keywords
from config import (
    CONFERENCE_EVIDENCE_TERMS,
    OPENALEX_MAILTO,
    OPENALEX_PER_QUERY,
    OPENALEX_SOURCE_IDS,
)


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
REQUEST_TIMEOUT_SECONDS = 30


def _restore_abstract(abstract_inverted_index: dict[str, list[int]] | None) -> str:
    """Convert OpenAlex's inverted-index abstract into normal text."""
    if not abstract_inverted_index:
        return ""

    positioned_words: list[tuple[int, str]] = []
    for word, positions in abstract_inverted_index.items():
        for position in positions:
            positioned_words.append((position, word))

    return " ".join(word for _, word in sorted(positioned_words))


def _paper_url(work: dict[str, Any]) -> str:
    """Pick the best public URL available for a paper."""
    primary_location = work.get("primary_location") or {}
    best_oa_location = work.get("best_oa_location") or {}

    for candidate in [
        primary_location.get("landing_page_url"),
        primary_location.get("pdf_url"),
        best_oa_location.get("landing_page_url"),
        best_oa_location.get("pdf_url"),
        work.get("doi"),
        work.get("id"),
    ]:
        if candidate:
            return candidate

    return ""


def _institution_for_author(authorship: dict[str, Any]) -> str:
    """Return a semicolon-separated institution list for one authorship."""
    institutions = authorship.get("institutions") or []
    institution_names = [
        institution.get("display_name", "")
        for institution in institutions
        if institution.get("display_name")
    ]
    return "; ".join(dict.fromkeys(institution_names))


def _conference_metadata_text(work: dict[str, Any]) -> str:
    """Collect venue/source fields that can identify a conference."""
    values: list[str] = []

    for key in ["id", "doi"]:
        if work.get(key):
            values.append(str(work[key]))

    for location_key in ["primary_location", "best_oa_location"]:
        location = work.get(location_key) or {}
        source = location.get("source") or {}
        for field in ["display_name", "landing_page_url", "pdf_url"]:
            if source.get(field):
                values.append(str(source[field]))
            if location.get(field):
                values.append(str(location[field]))

    for location in work.get("locations") or []:
        source = location.get("source") or {}
        for field in ["display_name", "landing_page_url", "pdf_url"]:
            if source.get(field):
                values.append(str(source[field]))
            if location.get(field):
                values.append(str(location[field]))

    return " ".join(values).lower()


def _has_conference_evidence(work: dict[str, Any], conference: str) -> bool:
    """Check whether OpenAlex metadata visibly points to the target venue."""
    evidence_terms = CONFERENCE_EVIDENCE_TERMS.get(conference, [])
    if not evidence_terms:
        return True

    metadata_text = _conference_metadata_text(work)
    return any(term.lower() in metadata_text for term in evidence_terms)


def _query_openalex(
    session: requests.Session,
    conference: str,
    year: int,
    keyword: str,
    per_query: int,
) -> list[dict[str, Any]]:
    """Search OpenAlex for one conference/year/keyword combination."""
    source_ids = OPENALEX_SOURCE_IDS.get(conference, [])
    filters = [
        f"from_publication_date:{year}-01-01",
        f"to_publication_date:{year}-12-31",
    ]
    if source_ids:
        filters.append("locations.source.id:" + "|".join(source_ids))

    params: dict[str, Any] = {
        # OpenAlex search covers title, abstract, and full text where available.
        # When source IDs are configured, they constrain results to the target
        # conference venue. Otherwise, include the conference name in search as
        # a simple Phase 1 fallback.
        "search": keyword if source_ids else f"{conference} {keyword}",
        "filter": ",".join(filters),
        "per-page": per_query,
        "select": ",".join(
            [
                "id",
                "doi",
                "display_name",
                "publication_year",
                "abstract_inverted_index",
                "authorships",
                "primary_location",
                "best_oa_location",
                "locations",
            ]
        ),
    }

    if OPENALEX_MAILTO:
        params["mailto"] = OPENALEX_MAILTO

    response = session.get(OPENALEX_WORKS_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_openalex_papers(
    conferences: list[str],
    years: list[int],
    keywords: list[str],
    per_query: int = OPENALEX_PER_QUERY,
    request_pause_seconds: float = 0.1,
) -> list[dict[str, Any]]:
    """Fetch and normalize OpenAlex results into paper-author CSV rows."""
    rows: list[dict[str, Any]] = []
    seen_papers: dict[str, dict[str, Any]] = {}

    with requests.Session() as session:
        for conference in conferences:
            for year in years:
                for keyword in keywords:
                    try:
                        works = _query_openalex(session, conference, year, keyword, per_query)
                    except requests.RequestException as exc:
                        print(
                            f"[WARN] OpenAlex request failed: conference={conference}, "
                            f"year={year}, keyword={keyword}, error={exc}"
                        )
                        continue

                    source_ids = OPENALEX_SOURCE_IDS.get(conference, [])
                    for work in works:
                        # When we cannot use an OpenAlex source filter, require
                        # visible conference evidence in metadata before
                        # assigning the requested conference label.
                        if not source_ids and not _has_conference_evidence(work, conference):
                            continue

                        paper_id = work.get("id") or work.get("doi") or work.get("display_name")
                        if not paper_id:
                            continue

                        title = work.get("display_name") or ""
                        abstract = _restore_abstract(work.get("abstract_inverted_index"))
                        matched = match_keywords(title, abstract)

                        # OpenAlex often lacks abstracts for conference papers.
                        # If a work was returned for a keyword query but has no
                        # abstract to inspect, keep the query keyword as a
                        # conservative Phase 1 fallback.
                        if not matched and not abstract:
                            matched = [keyword]

                        # Keep only papers that match one of the target
                        # keywords in title/abstract, or via the missing-abstract
                        # fallback above.
                        if not matched:
                            continue

                        if paper_id not in seen_papers:
                            seen_papers[paper_id] = {
                                "conference": conference,
                                "year": work.get("publication_year") or year,
                                "paper_title": title,
                                "paper_url": _paper_url(work),
                                "abstract": abstract,
                                "authors": "",
                                "matched_keywords": set(matched),
                                "research_direction": set(classify_research_direction(matched)),
                                "source": "OpenAlex",
                                "authorships": work.get("authorships") or [],
                            }
                        else:
                            seen_papers[paper_id]["matched_keywords"].update(matched)
                            seen_papers[paper_id]["research_direction"].update(
                                classify_research_direction(matched)
                            )

                    time.sleep(request_pause_seconds)

    for paper in seen_papers.values():
        authorships = paper.pop("authorships", [])
        author_names = [
            (authorship.get("author") or {}).get("display_name", "")
            for authorship in authorships
            if (authorship.get("author") or {}).get("display_name")
        ]
        paper["authors"] = "; ".join(author_names)
        paper["matched_keywords"] = "; ".join(sorted(paper["matched_keywords"]))
        paper["research_direction"] = "; ".join(sorted(paper["research_direction"]))

        if authorships:
            # OpenAlex returns one authorship object per collaborator. Do not
            # slice this list: every co-author becomes a separate CSV row.
            for index, authorship in enumerate(authorships, start=1):
                author = authorship.get("author") or {}
                row = {
                    **paper,
                    "author_name": author.get("display_name", ""),
                    "author_order": index,
                    "openalex_author_id": author.get("id", ""),
                    "institution": _institution_for_author(authorship),
                    "institution_detail": "",
                    "education_history": "",
                    "career_history": "",
                    "advisor": "",
                    "relations_conflicts": "",
                    "email": "",
                    "email_domain": "",
                    "email_source": "",
                    "homepage": "",
                    "linkedin": "",
                    "github": "",
                    "gscholar": "",
                    "dblp": "",
                    "email_lookup_urls": "",
                }
                rows.append(row)
        else:
            rows.append(
                {
                    **paper,
                    "author_name": "",
                    "author_order": "",
                    "openalex_author_id": "",
                    "institution": "",
                    "institution_detail": "",
                    "education_history": "",
                    "career_history": "",
                    "advisor": "",
                    "relations_conflicts": "",
                    "email": "",
                    "email_domain": "",
                    "email_source": "",
                    "homepage": "",
                    "linkedin": "",
                    "github": "",
                    "gscholar": "",
                    "dblp": "",
                    "email_lookup_urls": "",
                }
            )

    return rows
