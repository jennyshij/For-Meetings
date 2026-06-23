"""Fetch and normalize author profile enrichment from OpenReview."""

from __future__ import annotations

import argparse
import re
import time
import unicodedata
from typing import Any

import requests


OPENREVIEW_API_URL = "https://api2.openreview.net"
REQUEST_TIMEOUT_SECONDS = 10


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
        response = active_session.get(
            f"{OPENREVIEW_API_URL}/profiles",
            params={"id": author_id},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
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
        "openreview_institution": "; ".join(dict.fromkeys(current_institutions)),
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

    if openreview_institution and openreview_title:
        openreview_label = f"{openreview_institution} ({openreview_title})"
    else:
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


def main() -> None:
    """Small command-line helper for testing OpenReview profile extraction."""
    parser = argparse.ArgumentParser(description="Fetch one OpenReview author profile.")
    parser.add_argument("--author-id", help="Exact OpenReview profile id, e.g. ~Chelsea_Finn1.")
    parser.add_argument("--author-name", help="Author name used to build common profile id candidates.")
    args = parser.parse_args()

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
