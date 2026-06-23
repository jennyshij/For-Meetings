"""Fetch and normalize author profile enrichment from OpenReview."""

from __future__ import annotations

import argparse
import re
import time
import unicodedata
from typing import Any

import requests

from classifier import classify_research_direction, match_keywords
from config import OPENREVIEW_MAX_PAGES


OPENREVIEW_API_URL = "https://api2.openreview.net"
OPENREVIEW_NOTES_URL = f"{OPENREVIEW_API_URL}/notes"
OPENREVIEW_PROFILES_URL = f"{OPENREVIEW_API_URL}/profiles"
OPENREVIEW_INVITATIONS = {
    ("ICLR", 2026): "ICLR.cc/2026/Conference/-/Submission",
}
REQUEST_TIMEOUT_SECONDS = 10
OPENREVIEW_RETRY_DELAYS_SECONDS = [2, 4, 8, 16]


def _clean_text(value: Any) -> str:
    """Normalize scalar/list/dict values into compact text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return "; ".join(_clean_text(item) for item in value if _clean_text(item))
    if isinstance(value, dict):
        for key in ["name", "fullname", "text", "value", "url"]:
            if value.get(key):
                return _clean_text(value[key])
        return "; ".join(_clean_text(item) for item in value.values() if _clean_text(item))
    return str(value).strip()


def _content_value(content: dict[str, Any], key: str, default: Any = "") -> Any:
    """Read OpenReview content fields that are usually wrapped in {value: ...}."""
    value = content.get(key, default)
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def _as_list(value: Any) -> list[Any]:
    """Normalize OpenReview scalar/list content values into a list."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def candidate_profile_ids(author_name: str, max_suffix: int = 3) -> list[str]:
    """Build common OpenReview profile-id candidates from an author name."""
    if not author_name:
        return []
    if author_name.startswith("~"):
        return [author_name]

    ascii_name = unicodedata.normalize("NFKD", author_name).encode("ascii", "ignore").decode()
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", ascii_name.strip()) if part]
    if len(parts) < 2:
        return []

    first = parts[0]
    last = parts[-1]
    full = "_".join(parts)
    base_names = [f"{first}_{last}"]
    if full not in base_names[0]:
        base_names.append(full)

    candidates: list[str] = []
    for base_name in base_names:
        for suffix in range(1, max_suffix + 1):
            candidates.append(f"~{base_name}{suffix}")
    return candidates


def fetch_openreview_profile(
    author_id: str,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    """Fetch one OpenReview profile by exact profile id."""
    owns_session = session is None
    active_session = session or requests.Session()
    try:
        for attempt, delay_seconds in enumerate([0] + OPENREVIEW_RETRY_DELAYS_SECONDS):
            if delay_seconds:
                time.sleep(delay_seconds)
            response = active_session.get(
                OPENREVIEW_PROFILES_URL,
                params={"id": author_id},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if response.status_code == 429 and attempt < len(OPENREVIEW_RETRY_DELAYS_SECONDS):
                continue
            response.raise_for_status()
            break
        payload = response.json()
    except requests.RequestException as exc:
        print(f"[WARN] OpenReview profile request failed for {author_id}: {exc}")
        return None
    finally:
        if owns_session:
            active_session.close()

    profiles = payload.get("profiles") or []
    return profiles[0] if profiles else None


def _format_year_range(entry: dict[str, Any]) -> str:
    """Format start/end years from an OpenReview history entry."""
    start = entry.get("start")
    end = entry.get("end")
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"{start}-"
    if end:
        return f"-{end}"
    return ""


def _format_history_entry(entry: dict[str, Any]) -> str:
    """Format one OpenReview history entry."""
    position = _clean_text(entry.get("position"))
    institution = _clean_text(entry.get("institution"))
    years = _format_year_range(entry)
    parts = [part for part in [position, institution, years] if part]
    return ", ".join(parts)


def _is_current_history_entry(entry: dict[str, Any]) -> bool:
    """Return True if a history entry has no end date."""
    return entry.get("end") in [None, "", 0]


def _is_education_history_entry(entry: dict[str, Any]) -> bool:
    """Identify likely education entries in OpenReview history."""
    position = _clean_text(entry.get("position")).lower()
    education_terms = [
        "student",
        "phd",
        "ph.d",
        "doctor",
        "master",
        "bachelor",
        "undergraduate",
        "graduate",
    ]
    return any(term in position for term in education_terms)


def extract_openreview_profile_fields(profile: dict[str, Any]) -> dict[str, str]:
    """Extract normalized fields needed by the recruiting mapping CSV."""
    content = profile.get("content") or {}
    history = content.get("history") or []
    relations = content.get("relations") or []

    current_entries = [entry for entry in history if _is_current_history_entry(entry)]
    current_titles = [
        _clean_text(entry.get("position")) for entry in current_entries if _clean_text(entry.get("position"))
    ]
    current_institutions = [
        _clean_text(entry.get("institution"))
        for entry in current_entries
        if _clean_text(entry.get("institution"))
    ]
    current_affiliations = []
    for entry in current_entries:
        title = _clean_text(entry.get("position"))
        institution = _clean_text(entry.get("institution"))
        if institution and title:
            current_affiliations.append(f"{institution} ({title})")
        elif institution or title:
            current_affiliations.append(institution or title)

    education_history = [
        _format_history_entry(entry) for entry in history if _is_education_history_entry(entry)
    ]

    advisor_relations = []
    relation_summaries = []
    for relation in relations:
        relation_type = _clean_text(relation.get("relation"))
        relation_name = _clean_text(relation.get("name") or relation.get("username"))
        if relation_type or relation_name:
            relation_summaries.append(": ".join(part for part in [relation_type, relation_name] if part))
        relation_type_lower = relation_type.lower()
        if "advisor" in relation_type_lower and "advisee" not in relation_type_lower:
            advisor_relations.append(relation_name)

    return {
        "openreview_title": "; ".join(dict.fromkeys(current_titles)),
        "openreview_institution": "; ".join(dict.fromkeys(current_affiliations or current_institutions)),
        "education_history": "; ".join(dict.fromkeys(filter(None, education_history))),
        "advisor": "; ".join(dict.fromkeys(filter(None, advisor_relations))),
        "relations_conflicts": "; ".join(dict.fromkeys(filter(None, relation_summaries))),
        "homepage": _clean_text(content.get("homepage")),
        "linkedin": _clean_text(content.get("linkedin")),
        "github": _clean_text(content.get("github")),
    }


def _merge_institution_with_openreview(row: dict[str, Any], profile_fields: dict[str, str]) -> str:
    """Append OpenReview current title/institution to the CSV institution field."""
    existing_institution = _clean_text(row.get("institution"))
    openreview_institution = profile_fields.get("openreview_institution", "")
    openreview_title = profile_fields.get("openreview_title", "")

    openreview_label = openreview_institution or openreview_title

    parts = [part for part in [existing_institution, openreview_label] if part]
    return "; ".join(dict.fromkeys(parts))


def enrich_rows_with_openreview(
    rows: list[dict[str, Any]],
    request_pause_seconds: float = 0.1,
) -> list[dict[str, Any]]:
    """Enrich paper-author rows with OpenReview profile fields when available."""
    cache: dict[str, dict[str, str]] = {}
    matched_count = 0

    with requests.Session() as session:
        for row in rows:
            author_key = _clean_text(row.get("openreview_id") or row.get("author_name"))
            if not author_key:
                continue

            if author_key not in cache:
                profile = None
                profile_ids = []
                if row.get("openreview_id"):
                    profile_ids = [_clean_text(row.get("openreview_id"))]
                else:
                    profile_ids = candidate_profile_ids(_clean_text(row.get("author_name")))

                for profile_id in profile_ids:
                    profile = fetch_openreview_profile(profile_id, session=session)
                    if profile:
                        break
                    time.sleep(request_pause_seconds)

                cache[author_key] = extract_openreview_profile_fields(profile) if profile else {}

            profile_fields = cache[author_key]
            if not profile_fields:
                continue

            matched_count += 1
            row["institution"] = _merge_institution_with_openreview(row, profile_fields)
            for field in [
                "education_history",
                "advisor",
                "relations_conflicts",
                "homepage",
                "linkedin",
                "github",
            ]:
                if profile_fields.get(field) and not row.get(field):
                    row[field] = profile_fields[field]

    print(f"[INFO] OpenReview enriched {matched_count} author rows")
    return rows


def _is_accepted_openreview_note(note: dict[str, Any]) -> bool:
    """Treat non-rejected and non-withdrawn ICLR 2026 notes as accepted/public."""
    content = note.get("content") or {}
    venueid = _clean_text(_content_value(content, "venueid")).lower()
    venue = _clean_text(_content_value(content, "venue")).lower()
    status_text = f"{venueid} {venue}"
    rejected_terms = ["rejected", "withdrawn", "desk_rejected"]
    return not any(term in status_text for term in rejected_terms)


def _author_affiliation_for_index(author_affiliations: list[Any], index: int) -> str:
    """Read the affiliation matching one author index when available."""
    if index >= len(author_affiliations):
        return ""
    return _clean_text(author_affiliations[index])


def _fetch_openreview_notes_page(
    session: requests.Session,
    invitation: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch one OpenReview notes page."""
    params = {
        "invitation": invitation,
        "details": "replyCount",
        "offset": offset,
        "limit": limit,
    }

    for attempt, delay_seconds in enumerate([0] + OPENREVIEW_RETRY_DELAYS_SECONDS):
        if delay_seconds:
            print(f"[WARN] OpenReview rate limited at offset={offset}; retrying in {delay_seconds}s")
            time.sleep(delay_seconds)

        response = session.get(
            OPENREVIEW_NOTES_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 429 and attempt < len(OPENREVIEW_RETRY_DELAYS_SECONDS):
            continue
        response.raise_for_status()
        break

    return response.json().get("notes") or []


def fetch_openreview_papers(
    conference: str,
    year: int,
    keywords: list[str],
    per_query: int = 50,
    max_pages: int = OPENREVIEW_MAX_PAGES,
    accepted_only: bool = True,
    request_pause_seconds: float = 0.6,
) -> list[dict[str, Any]]:
    """Fetch paper-author rows directly from OpenReview notes.

    This is primarily used for ICLR 2026, where OpenAlex may not have indexed
    the accepted papers yet. It fetches notes first, filters title/abstract by
    keyword, then emits one row per listed co-author.
    """
    invitation = OPENREVIEW_INVITATIONS.get((conference, year))
    if not invitation:
        print(f"[WARN] OpenReview direct fetch is not configured for {conference} {year}")
        return []

    # The requested endpoint uses limit=50. Keep at least that page size even
    # when --per-query is smaller, so the smoke test can reach relevant papers.
    page_limit = max(per_query, 50)
    rows: list[dict[str, Any]] = []
    scanned_notes = 0
    matched_notes = 0

    with requests.Session() as session:
        for page_index in range(max_pages):
            offset = page_index * page_limit
            try:
                notes = _fetch_openreview_notes_page(
                    session=session,
                    invitation=invitation,
                    offset=offset,
                    limit=page_limit,
                )
            except requests.RequestException as exc:
                print(f"[WARN] OpenReview notes request failed at offset={offset}: {exc}")
                continue

            if not notes:
                break

            scanned_notes += len(notes)
            for note in notes:
                if accepted_only and not _is_accepted_openreview_note(note):
                    continue

                content = note.get("content") or {}
                title = _clean_text(_content_value(content, "title"))
                abstract = _clean_text(_content_value(content, "abstract"))
                matched = match_keywords(title, abstract, keywords)
                if not matched:
                    continue

                matched_notes += 1
                paper_url = f"https://openreview.net/forum?id={note.get('forum') or note.get('id')}"
                authors = [_clean_text(author) for author in _as_list(_content_value(content, "authors"))]
                authorids = [
                    _clean_text(author_id) for author_id in _as_list(_content_value(content, "authorids"))
                ]
                author_affiliations = _as_list(_content_value(content, "author_affiliations"))
                authors_joined = "; ".join(author for author in authors if author)
                research_direction = "; ".join(classify_research_direction(matched))
                matched_keywords = "; ".join(matched)

                if not authors:
                    rows.append(
                        {
                            "paper_title": title,
                            "year": year,
                            "paper_url": paper_url,
                            "abstract": abstract,
                            "authors": authors_joined,
                            "research_direction": research_direction,
                            "author_name": "",
                            "openreview_id": "",
                            "institution": "",
                            "education_history": "",
                            "advisor": "",
                            "relations_conflicts": "",
                            "email": "",
                            "homepage": "",
                            "linkedin": "",
                            "github": "",
                            "matched_keywords": matched_keywords,
                            "source": "OpenReview",
                        }
                    )
                    continue

                for index, author_name in enumerate(authors):
                    rows.append(
                        {
                            "paper_title": title,
                            "year": year,
                            "paper_url": paper_url,
                            "abstract": abstract,
                            "authors": authors_joined,
                            "research_direction": research_direction,
                            "author_name": author_name,
                            "openreview_id": authorids[index] if index < len(authorids) else "",
                            "institution": _author_affiliation_for_index(author_affiliations, index),
                            "education_history": "",
                            "advisor": "",
                            "relations_conflicts": "",
                            "email": "",
                            "homepage": "",
                            "linkedin": "",
                            "github": "",
                            "matched_keywords": matched_keywords,
                            "source": "OpenReview",
                        }
                    )

            time.sleep(request_pause_seconds)

    print(
        f"[INFO] OpenReview scanned {scanned_notes} notes, matched {matched_notes} papers, "
        f"emitted {len(rows)} author rows"
    )
    return enrich_rows_with_openreview(rows)


def main() -> None:
    """Small command-line helper for testing OpenReview profile extraction."""
    parser = argparse.ArgumentParser(description="Fetch OpenReview profiles or ICLR 2026 papers.")
    parser.add_argument("--author-id", help="Exact OpenReview profile id, e.g. ~Chelsea_Finn1.")
    parser.add_argument("--author-name", help="Author name used to build common profile id candidates.")
    parser.add_argument("--conference", choices=["ICLR"], help="Conference for direct paper fetching.")
    parser.add_argument("--year", type=int, help="Year for direct paper fetching.")
    parser.add_argument("--keyword", action="append", help="Keyword for direct paper filtering.")
    parser.add_argument("--per-query", type=int, default=50, help="OpenReview notes page size.")
    args = parser.parse_args()

    if args.conference and args.year:
        rows = fetch_openreview_papers(
            conference=args.conference,
            year=args.year,
            keywords=args.keyword or ["VLA", "Vision Language Action"],
            per_query=args.per_query,
        )
        print(f"Fetched {len(rows)} OpenReview author rows")
        return

    profile_ids = [args.author_id] if args.author_id else candidate_profile_ids(args.author_name or "")
    with requests.Session() as session:
        for profile_id in profile_ids:
            profile = fetch_openreview_profile(profile_id, session=session)
            if profile:
                print(extract_openreview_profile_fields(profile))
                return
    print("[WARN] No OpenReview profile found")


if __name__ == "__main__":
    main()
