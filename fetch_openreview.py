"""Fetch and normalize author profile enrichment from OpenReview."""

from __future__ import annotations

import argparse
import re
import time
import unicodedata
from typing import Any

import requests

from classifier import classify_research_direction


OPENREVIEW_API_URL = "https://api2.openreview.net"
OPENREVIEW_NOTES_URL = f"{OPENREVIEW_API_URL}/notes"
OPENREVIEW_PROFILES_URL = f"{OPENREVIEW_API_URL}/profiles"
OPENREVIEW_INVITATIONS = {
    ("ICLR", 2026): "ICLR.cc/2026/Conference/-/Submission",
}
REQUEST_TIMEOUT_SECONDS = 10
OPENREVIEW_NOTES_RETRY_DELAYS_SECONDS = [2, 4, 8, 16]
OPENREVIEW_PROFILE_BATCH_SIZE = 10
OPENREVIEW_PROFILE_REQUEST_PAUSE_SECONDS = 2
OPENREVIEW_PROFILE_RATE_LIMIT_SLEEP_SECONDS = 10
OPENREVIEW_PROFILE_MAX_RETRIES = 3
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.+-])")


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
    profiles = fetch_openreview_profiles_batch([author_id], batch_size=1, session=session)
    return profiles.get(author_id)


def _profile_usernames(profile: dict[str, Any]) -> list[str]:
    """Return every username alias that can identify an OpenReview profile."""
    usernames = []
    if profile.get("id"):
        usernames.append(str(profile["id"]))

    content = profile.get("content") or {}
    for name_entry in content.get("names") or []:
        if isinstance(name_entry, dict) and name_entry.get("username"):
            usernames.append(str(name_entry["username"]))

    return list(dict.fromkeys(usernames))


def _add_profile_aliases(results: dict[str, dict[str, Any]], profile: dict[str, Any]) -> None:
    """Map every known OpenReview username alias to the same profile object."""
    for username in _profile_usernames(profile):
        results[username] = profile


def _fetch_single_profile_with_backoff(
    session: requests.Session,
    author_id: str,
) -> dict[str, Any] | None:
    """Fetch one profile with the required slower rate-limit policy."""
    for attempt in range(1, OPENREVIEW_PROFILE_MAX_RETRIES + 1):
        time.sleep(OPENREVIEW_PROFILE_REQUEST_PAUSE_SECONDS)
        try:
            response = session.get(
                OPENREVIEW_PROFILES_URL,
                params={"id": author_id},
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"[WARN] OpenReview single profile request failed for {author_id}: {exc}")
            return None

        if response.status_code == 429:
            print(
                "[WARN] OpenReview single profile rate limited; "
                f"author_id={author_id}, attempt={attempt}/{OPENREVIEW_PROFILE_MAX_RETRIES}"
            )
            if attempt < OPENREVIEW_PROFILE_MAX_RETRIES:
                time.sleep(OPENREVIEW_PROFILE_RATE_LIMIT_SLEEP_SECONDS)
                continue

        if response.status_code != 200:
            print(
                "[WARN] OpenReview single profile skipped; "
                f"author_id={author_id}, status={response.status_code}, body={response.text[:200]}"
            )
            return None

        profiles = response.json().get("profiles") or []
        return profiles[0] if profiles else None

    return None


def _fetch_profiles_individually_for_batch(
    session: requests.Session,
    author_ids: list[str],
    results: dict[str, dict[str, Any]],
) -> None:
    """Fallback for OpenReview deployments that do not support ids=... batches."""
    print(
        "[WARN] OpenReview ids= batch profile endpoint is unavailable; "
        f"falling back to {len(author_ids)} slow single-profile requests"
    )
    for author_id in author_ids:
        profile = _fetch_single_profile_with_backoff(session, author_id)
        if profile:
            _add_profile_aliases(results, profile)


def fetch_openreview_profiles_batch(
    author_ids: list[str],
    batch_size: int = OPENREVIEW_PROFILE_BATCH_SIZE,
    session: requests.Session | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch OpenReview profiles in batches and map all username aliases."""
    unique_author_ids = [author_id for author_id in dict.fromkeys(author_ids) if author_id]
    if not unique_author_ids:
        return {}

    owns_session = session is None
    active_session = session or requests.Session()
    results: dict[str, dict[str, Any]] = {}

    try:
        for batch_start in range(0, len(unique_author_ids), batch_size):
            batch = unique_author_ids[batch_start : batch_start + batch_size]
            ids_str = ",".join(batch)
            time.sleep(OPENREVIEW_PROFILE_REQUEST_PAUSE_SECONDS)

            response = None
            fallback_used = False
            for attempt in range(1, OPENREVIEW_PROFILE_MAX_RETRIES + 1):
                try:
                    response = active_session.get(
                        OPENREVIEW_PROFILES_URL,
                        params={"ids": ids_str},
                        timeout=15,
                    )
                    if response.status_code == 429:
                        print(
                            "[WARN] OpenReview profile batch rate limited; "
                            f"attempt={attempt}/{OPENREVIEW_PROFILE_MAX_RETRIES}, "
                            f"batch_size={len(batch)}"
                        )
                        if attempt < OPENREVIEW_PROFILE_MAX_RETRIES:
                            time.sleep(OPENREVIEW_PROFILE_RATE_LIMIT_SLEEP_SECONDS)
                            continue
                    if response.status_code == 400:
                        _fetch_profiles_individually_for_batch(active_session, batch, results)
                        fallback_used = True
                        response = None
                        break
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    print(f"[WARN] OpenReview profile batch request failed for ids={ids_str}: {exc}")
                    response = None
                    break

            if fallback_used:
                continue

            if response is None or response.status_code != 200:
                print(f"[WARN] OpenReview profile batch skipped after retries for ids={ids_str}")
                continue

            payload = response.json()
            for profile in payload.get("profiles") or []:
                _add_profile_aliases(results, profile)
    finally:
        if owns_session:
            active_session.close()

    return results


def _format_year_range(entry: dict[str, Any]) -> str:
    """Format start/end years from an OpenReview history entry."""
    start = entry.get("start")
    end = entry.get("end")
    if start and end:
        return f"{start}-{end}"
    if start:
        return f"{start}-present"
    if end:
        return f"-{end}"
    return ""


def _institution_type(entry: dict[str, Any]) -> str:
    """Read institution.type from an OpenReview history entry."""
    institution = entry.get("institution")
    if isinstance(institution, dict):
        return _clean_text(institution.get("type")).lower()
    return ""


def _degree_text(entry: dict[str, Any]) -> str:
    """Read degree from common OpenReview history shapes."""
    degree = entry.get("degree")
    if degree:
        return _clean_text(degree)

    position = _clean_text(entry.get("position"))
    position_lower = position.lower()
    degree_terms = ["phd", "ph.d", "doctor", "ms", "m.s", "master", "bs", "b.s", "bachelor"]
    if any(term in position_lower for term in degree_terms):
        return position
    return ""


def _history_institution_parts(entry: dict[str, Any]) -> list[str]:
    """Return department and institution name from a history entry."""
    institution = entry.get("institution") if isinstance(entry.get("institution"), dict) else {}
    return [
        _clean_text(institution.get("department")),
        _clean_text(institution.get("name")),
    ]


def _format_history_entry(entry: dict[str, Any]) -> str:
    """Format one OpenReview history entry."""
    position = _clean_text(entry.get("position") or entry.get("degree"))
    years = _format_year_range(entry)
    parts = [position, *_history_institution_parts(entry), years]
    return ", ".join(part for part in parts if part)


def _is_current_history_entry(entry: dict[str, Any]) -> bool:
    """Return True if a history entry has no end date."""
    return entry.get("end") in [None, "", 0]


def _is_education_history_entry(entry: dict[str, Any]) -> bool:
    """Identify likely education entries in OpenReview history."""
    if entry.get("degree"):
        return True

    position = _clean_text(entry.get("position")).lower()
    institution_type = _institution_type(entry)
    if institution_type in {"education", "university", "college", "school"}:
        return True

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


def _is_career_history_entry(entry: dict[str, Any]) -> bool:
    """Identify likely career/employment entries in OpenReview history."""
    return bool(entry.get("position")) and not _is_education_history_entry(entry)


def _extract_public_email(content: dict[str, Any]) -> str:
    """Extract a non-redacted email from public OpenReview profile fields."""
    candidates = []
    for key in ["emailsConfirmed", "preferredEmail", "emails"]:
        candidates.extend(_as_list(content.get(key)))

    for candidate in candidates:
        text = _clean_text(candidate)
        if not text or "*" in text:
            continue
        match = EMAIL_PATTERN.search(text)
        if match:
            return match.group(0)
    return ""


def _profile_lookup_urls(content: dict[str, Any]) -> str:
    """Return profile links that email enrichment can also inspect."""
    urls = []
    for key in ["gscholar", "dblp"]:
        url = _clean_text(content.get(key))
        if url:
            urls.append(url)
    return "; ".join(dict.fromkeys(urls))


def _history_entry_sort_key(entry: dict[str, Any]) -> tuple[int, int]:
    """Sort history entries with current entries first, then latest start year."""
    end = entry.get("end")
    start = entry.get("start")
    is_current = 1 if end in [None, "", 0] else 0
    try:
        sortable_year = int(start)
    except (TypeError, ValueError):
        sortable_year = 0
    return (is_current, sortable_year)


def _current_history_entry(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the latest current history entry where end is empty."""
    current_entries = [entry for entry in history if _is_current_history_entry(entry)]
    if not current_entries:
        return {}
    return max(current_entries, key=_history_entry_sort_key)


def _latest_history_entry(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the latest OpenReview history entry."""
    if not history:
        return {}
    return max(history, key=_history_entry_sort_key)


def _format_current_institution(entry: dict[str, Any]) -> str:
    """Format the primary institution field from the latest current history entry."""
    parts = [_clean_text(entry.get("position") or entry.get("degree")), *_history_institution_parts(entry)]
    return ", ".join(part for part in parts if part)


def _format_institution_detail(entry: dict[str, Any]) -> str:
    """Format latest history entry as a compact institution detail string."""
    institution = entry.get("institution") if isinstance(entry.get("institution"), dict) else {}
    parts = [
        _clean_text(entry.get("position") or entry.get("degree")),
        _clean_text(institution.get("department")),
        _clean_text(institution.get("name")),
        _clean_text(institution.get("stateProvince")),
        _clean_text(institution.get("country")),
    ]
    return ", ".join(dict.fromkeys(part for part in parts if part))


def _institution_domain(entry: dict[str, Any]) -> str:
    """Read institution.domain from a history entry."""
    institution = entry.get("institution")
    if not isinstance(institution, dict):
        return ""
    return _clean_text(institution.get("domain"))


def _extract_expertise(content: dict[str, Any]) -> str:
    """Flatten OpenReview expertise keywords into a pipe-separated string."""
    expertise_terms: list[str] = []
    for entry in content.get("expertise") or []:
        if isinstance(entry, dict):
            for keyword in _as_list(entry.get("keywords")):
                keyword_text = _clean_text(keyword)
                if keyword_text:
                    expertise_terms.append(keyword_text)
        else:
            entry_text = _clean_text(entry)
            if entry_text:
                expertise_terms.append(entry_text)
    return " | ".join(dict.fromkeys(expertise_terms))


def _is_education_history_text(history_text: str) -> bool:
    """Return True for degree/student history strings."""
    terms = ["Undergrad", "Bachelor", "Master", "PhD", "MS", "BS", "MEng"]
    lowered = history_text.lower()
    return any(term.lower() in lowered for term in terms)


def extract_openreview_profile_fields(profile: dict[str, Any]) -> dict[str, str]:
    """Extract normalized fields needed by the recruiting mapping CSV."""
    content = profile.get("content") or {}
    history = content.get("history") or []
    relations = content.get("relations") or []
    current_entry = _current_history_entry(history)
    latest_entry = _latest_history_entry(history)
    primary_entry = current_entry or latest_entry

    career_history = []
    for entry in sorted(history, key=_history_entry_sort_key, reverse=True):
        career_history.append(_format_history_entry(entry))
    education_history = [entry for entry in career_history if _is_education_history_text(entry)]

    advisor_relations = []
    relation_summaries = []
    for relation in relations:
        relation_type = _clean_text(relation.get("relation"))
        relation_name = _clean_text(relation.get("name") or relation.get("username"))
        relation_type_lower = relation_type.lower()
        if "advisor" in relation_type_lower and "advisee" not in relation_type_lower:
            advisor_relations.append(relation_name)
        elif relation_type or relation_name:
            if relation_name and relation_type:
                relation_summaries.append(f"{relation_name}({relation_type})")
            else:
                relation_summaries.append(relation_name or relation_type)

    return {
        "openreview_institution": _format_current_institution(primary_entry),
        "institution_detail": _format_institution_detail(primary_entry),
        "institution_domain": _institution_domain(primary_entry),
        "education_history": " | ".join(dict.fromkeys(filter(None, education_history))),
        "career_history": " | ".join(dict.fromkeys(filter(None, career_history))),
        "expertise": _extract_expertise(content),
        "advisor": " | ".join(dict.fromkeys(filter(None, advisor_relations))),
        "relations_conflicts": " | ".join(dict.fromkeys(filter(None, relation_summaries))),
        "email": _extract_public_email(content),
        "homepage": _clean_text(content.get("homepage")),
        "linkedin": _clean_text(content.get("linkedin")),
        "github": _clean_text(content.get("github")),
        "gscholar": _clean_text(content.get("gscholar")),
        "dblp": _clean_text(content.get("dblp")),
        "email_lookup_urls": _profile_lookup_urls(content),
    }


def _merge_institution_with_openreview(row: dict[str, Any], profile_fields: dict[str, str]) -> str:
    """Prefer OpenReview current history institution, falling back to note data."""
    openreview_institution = profile_fields.get("openreview_institution", "")
    if openreview_institution:
        return openreview_institution
    return _clean_text(row.get("institution"))


def enrich_rows_with_openreview(
    rows: list[dict[str, Any]],
    request_pause_seconds: float = 0.1,
) -> list[dict[str, Any]]:
    """Enrich paper-author rows with OpenReview profile fields when available."""
    profile_ids_by_author_key: dict[str, list[str]] = {}
    all_profile_ids: list[str] = []
    matched_count = 0

    for row in rows:
        author_key = _clean_text(row.get("openreview_id") or row.get("author_name"))
        if not author_key or author_key in profile_ids_by_author_key:
            continue

        if row.get("openreview_id"):
            profile_ids = [_clean_text(row.get("openreview_id"))]
        else:
            profile_ids = candidate_profile_ids(_clean_text(row.get("author_name")))

        profile_ids_by_author_key[author_key] = profile_ids
        all_profile_ids.extend(profile_ids)

    with requests.Session() as session:
        profile_map = fetch_openreview_profiles_batch(all_profile_ids, session=session)

        for index, row in enumerate(rows, start=1):
            if index == 1 or index % 50 == 0 or index == len(rows):
                print(f"[INFO] OpenReview profile enrichment progress: {index}/{len(rows)} author rows")

            author_key = _clean_text(row.get("openreview_id") or row.get("author_name"))
            if not author_key:
                continue

            profile = None
            for profile_id in profile_ids_by_author_key.get(author_key, []):
                profile = profile_map.get(profile_id)
                if profile:
                    break

            profile_fields = extract_openreview_profile_fields(profile) if profile else {}
            if not profile_fields:
                continue

            matched_count += 1
            row["institution"] = _merge_institution_with_openreview(row, profile_fields)
            for field in [
                "institution_detail",
                "institution_domain",
                "education_history",
                "career_history",
                "expertise",
                "advisor",
                "relations_conflicts",
                "email",
                "homepage",
                "linkedin",
                "github",
                "gscholar",
                "dblp",
                "email_lookup_urls",
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


def _institution_from_author_id(author_id: str) -> str:
    """Fallback institution text when OpenReview authorid is an email address."""
    if "@" not in author_id:
        return ""
    return author_id.rsplit("@", 1)[-1].strip()


def _fetch_openreview_notes_page(
    session: requests.Session,
    invitation: str,
    offset: int,
    limit: int,
) -> tuple[list[dict[str, Any]], int | None, str]:
    """Fetch one OpenReview notes page."""
    params = {
        "invitation": invitation,
        "details": "replyCount",
        "offset": offset,
        "limit": limit,
    }

    for attempt, delay_seconds in enumerate([0] + OPENREVIEW_NOTES_RETRY_DELAYS_SECONDS):
        if delay_seconds:
            print(f"[WARN] OpenReview rate limited at offset={offset}; retrying in {delay_seconds}s")
            time.sleep(delay_seconds)

        response = session.get(
            OPENREVIEW_NOTES_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        print(f"[INFO] OpenReview API request: {response.url}")
        if response.status_code == 429 and attempt < len(OPENREVIEW_NOTES_RETRY_DELAYS_SECONDS):
            continue
        response.raise_for_status()
        break

    payload = response.json()
    return payload.get("notes") or [], payload.get("count"), response.url


def _keyword_variants(keywords: list[str]) -> list[str]:
    """Expand OpenReview direct-fetch keyword variants."""
    variants = list(keywords)
    lowered = {keyword.lower() for keyword in keywords}
    if "vla" in lowered or "vision language action" in lowered or "vision-language-action" in lowered:
        variants.extend(
            [
                "VLA",
                "Vision-Language-Action",
                "Vision Language Action",
                "visuomotor",
            ]
        )
    return list(dict.fromkeys(variants))


def _variant_matches(text: str, variant: str) -> bool:
    """Case-insensitive title/abstract keyword match for OpenReview notes."""
    if not text or not variant:
        return False
    if variant.lower() == "vla":
        return re.search(r"(?<![A-Za-z0-9])VLA(?![A-Za-z0-9])", text, flags=re.I) is not None
    return variant.lower() in text.lower()


def _match_openreview_keywords(title: str, abstract: str, keywords: list[str]) -> list[str]:
    """Match expanded keyword variants against title and abstract."""
    combined_text = f"{title} {abstract}"
    return [variant for variant in _keyword_variants(keywords) if _variant_matches(combined_text, variant)]


def fetch_openreview_papers(
    conference: str,
    year: int,
    keywords: list[str],
    per_query: int = 50,
    accepted_only: bool = True,
    request_pause_seconds: float = 0.6,
    paper_query: str | None = None,
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

    # OpenReview supports up to 1000 notes per request. Always use the maximum
    # for direct conference scans so small --per-query values do not truncate or
    # slow down the full scan.
    page_limit = 1000
    rows: list[dict[str, Any]] = []
    scanned_notes = 0
    accepted_scanned_notes = 0
    matched_notes = 0
    total_count: int | None = None
    print(f"[INFO] OpenReview requested per-query: {per_query}")
    print(f"[INFO] OpenReview effective page limit: {page_limit}")
    print(f"[INFO] OpenReview keyword variants: {', '.join(_keyword_variants(keywords))}")
    if paper_query:
        print(f"[INFO] OpenReview paper title filter: {paper_query}")

    with requests.Session() as session:
        offset = 0
        while True:
            try:
                notes, page_count, _request_url = _fetch_openreview_notes_page(
                    session=session,
                    invitation=invitation,
                    offset=offset,
                    limit=page_limit,
                )
            except requests.RequestException as exc:
                print(f"[WARN] OpenReview notes request failed at offset={offset}: {exc}")
                offset += page_limit
                continue

            if page_count is not None and total_count is None:
                total_count = page_count
                print(f"[INFO] OpenReview total note count: {total_count}")

            if not notes:
                break

            scanned_notes += len(notes)
            for note in notes:
                if accepted_only and not _is_accepted_openreview_note(note):
                    continue
                accepted_scanned_notes += 1

                content = note.get("content") or {}
                title = _clean_text(_content_value(content, "title"))
                abstract = _clean_text(_content_value(content, "abstract"))
                if paper_query and paper_query.lower() not in title.lower():
                    continue

                matched = _match_openreview_keywords(title, abstract, keywords)
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
                            "institution_detail": "",
                            "institution_domain": "",
                            "education_history": "",
                            "career_history": "",
                            "expertise": "",
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
                            "matched_keywords": matched_keywords,
                            "source": "OpenReview",
                        }
                    )
                    continue

                for index, author_name in enumerate(authors):
                    author_id = authorids[index] if index < len(authorids) else ""
                    note_institution = _author_affiliation_for_index(author_affiliations, index)
                    fallback_institution = note_institution or _institution_from_author_id(author_id)
                    rows.append(
                        {
                            "paper_title": title,
                            "year": year,
                            "paper_url": paper_url,
                            "abstract": abstract,
                            "authors": authors_joined,
                            "research_direction": research_direction,
                            "author_name": author_name,
                            "openreview_id": author_id,
                            "institution": fallback_institution,
                            "institution_detail": "",
                            "institution_domain": _institution_from_author_id(author_id),
                            "education_history": "",
                            "career_history": "",
                            "expertise": "",
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
                            "matched_keywords": matched_keywords,
                            "source": "OpenReview",
                        }
                    )

            time.sleep(request_pause_seconds)
            offset += page_limit
            if total_count is not None and offset >= total_count:
                break

    print(
        f"[INFO] OpenReview scanned {scanned_notes} notes, "
        f"accepted_scanned {accepted_scanned_notes} notes, "
        f"matched {matched_notes} papers, "
        f"emitted {len(rows)} author rows"
    )
    print(
        f"[INFO] OpenReview keyword scan summary: scanned={accepted_scanned_notes}, "
        f"matched={matched_notes}"
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
