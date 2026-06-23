"""Backfill missing Feishu author fields from OpenReview profiles.

This script is intentionally separate from main.py so it can be resumed safely
with enriched_record_ids.txt while updating only empty fields in existing rows.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from fetch_openreview import (
    candidate_profile_ids,
    extract_openreview_profile_fields,
)
from sync_feishu import (
    FEISHU_RECORD_URL,
    FEISHU_RECORDS_URL,
    _headers,
    get_tenant_access_token,
    load_feishu_settings,
)


CHECKPOINT_PATH = Path("enriched_record_ids.txt")
OPENREVIEW_SEARCH_URL = "https://api2.openreview.net/profiles/search"
OPENREVIEW_PROFILE_URL = "https://api2.openreview.net/profiles"
OPENREVIEW_NOTES_URL = "https://api2.openreview.net/notes"
OPENREVIEW_SLEEP_SECONDS = 4
OPENREVIEW_RATE_LIMIT_SLEEP_SECONDS = 10
OPENREVIEW_MAX_RETRIES = 3
FEISHU_SLEEP_SECONDS = 0.5
FEISHU_PAGE_SIZE = 100
OPENREVIEW_SEARCH_DISABLED = False

BACKFILL_FIELDS = [
    "institution",
    "career_history",
    "education_history",
    "advisor",
    "expertise",
    "email_domain",
]


def _stringify(value: Any) -> str:
    """Normalize Feishu rich values to plain strings."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(_stringify(item) for item in value).strip()
    if isinstance(value, dict):
        for key in ["text", "name", "value"]:
            if key in value:
                return _stringify(value[key])
        return " ".join(_stringify(item) for item in value.values()).strip()
    return str(value).strip()


def load_checkpoint() -> set[str]:
    """Load processed Feishu record IDs."""
    if not CHECKPOINT_PATH.exists():
        return set()
    return {
        line.strip()
        for line in CHECKPOINT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def mark_processed(record_id: str) -> None:
    """Append one processed Feishu record ID to the checkpoint file."""
    with CHECKPOINT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(record_id + "\n")


def fetch_all_feishu_records(session: requests.Session, token: str, app_token: str, table_id: str) -> list[dict[str, Any]]:
    """Fetch all Feishu records with page_size=100."""
    url = FEISHU_RECORDS_URL.format(app_token=app_token, table_id=table_id)
    records: list[dict[str, Any]] = []
    page_token = ""

    while True:
        params = {"page_size": FEISHU_PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token

        response = session.get(url, headers=_headers(token), params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu list records failed: {payload}")

        data = payload.get("data") or {}
        records.extend(data.get("items") or [])

        print(f"[INFO] Feishu fetched records so far: {len(records)}")
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break

    return records


def needs_backfill(record: dict[str, Any]) -> bool:
    """Return True when institution or career_history is empty."""
    fields = record.get("fields") or {}
    return not _stringify(fields.get("institution")) or not _stringify(fields.get("career_history"))


def _name_score(author_name: str, profile: dict[str, Any]) -> int:
    """Score a profile by exact or fuzzy full-name match."""
    target = " ".join(author_name.lower().split())
    if not target:
        return 0

    content = profile.get("content") or {}
    score = 0
    for name_entry in content.get("names") or []:
        if not isinstance(name_entry, dict):
            continue
        fullname = " ".join(str(name_entry.get("fullname", "")).lower().split())
        if fullname == target:
            score = max(score, 100)
        elif target in fullname or fullname in target:
            score = max(score, 50)
    return score


def _normalize_name(name: str) -> str:
    """Normalize names for note author matching."""
    return " ".join(str(name or "").lower().replace("-", " ").split())


def _content_value(content: dict[str, Any], key: str, default: Any = "") -> Any:
    """Read OpenReview note content fields wrapped as {value: ...}."""
    value = content.get(key, default)
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def _note_id_from_paper_url(paper_url: str) -> str:
    """Extract OpenReview forum id from paper_url."""
    if "openreview.net/forum?id=" not in paper_url:
        return ""
    return paper_url.split("openreview.net/forum?id=", 1)[-1].split("&", 1)[0].strip()


def fetch_note_authorids(
    session: requests.Session,
    note_id: str,
    note_cache: dict[str, dict[str, str]],
) -> dict[str, str]:
    """Fetch one OpenReview note and map normalized author names to authorids."""
    if not note_id:
        return {}
    if note_id in note_cache:
        return note_cache[note_id]

    for attempt in range(1, OPENREVIEW_MAX_RETRIES + 1):
        time.sleep(OPENREVIEW_SLEEP_SECONDS)
        try:
            response = session.get(
                OPENREVIEW_NOTES_URL,
                params={"id": note_id},
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"[WARN] OpenReview note request failed for {note_id}: {exc}")
            note_cache[note_id] = {}
            return {}

        if response.status_code == 429:
            print(
                f"[WARN] OpenReview note request rate limited for {note_id}; "
                f"attempt={attempt}/{OPENREVIEW_MAX_RETRIES}"
            )
            if attempt < OPENREVIEW_MAX_RETRIES:
                time.sleep(OPENREVIEW_RATE_LIMIT_SLEEP_SECONDS)
                continue

        if response.status_code != 200:
            print(
                f"[WARN] OpenReview note request unavailable for {note_id}: "
                f"status={response.status_code}, body={response.text[:200]}"
            )
            note_cache[note_id] = {}
            return {}

        notes = response.json().get("notes") or []
        if not notes:
            note_cache[note_id] = {}
            return {}

        content = notes[0].get("content") or {}
        authors = _content_value(content, "authors", []) or []
        authorids = _content_value(content, "authorids", []) or []
        mapping = {}
        for index, author_name in enumerate(authors):
            if index < len(authorids):
                mapping[_normalize_name(author_name)] = str(authorids[index])
        note_cache[note_id] = mapping
        return mapping

    note_cache[note_id] = {}
    return {}


def search_openreview_profile(session: requests.Session, author_name: str) -> dict[str, Any] | None:
    """Search OpenReview profile by author name, falling back to generated IDs."""
    global OPENREVIEW_SEARCH_DISABLED

    if not OPENREVIEW_SEARCH_DISABLED:
        for attempt in range(1, OPENREVIEW_MAX_RETRIES + 1):
            time.sleep(OPENREVIEW_SLEEP_SECONDS)
            try:
                response = session.get(
                    OPENREVIEW_SEARCH_URL,
                    params={"term": author_name, "limit": 3},
                    timeout=15,
                )
            except requests.RequestException as exc:
                print(f"[WARN] OpenReview profile search failed for {author_name}: {exc}")
                break

            if response.status_code == 429:
                print(
                    f"[WARN] OpenReview profile search rate limited for {author_name}; "
                    f"attempt={attempt}/{OPENREVIEW_MAX_RETRIES}"
                )
                if attempt < OPENREVIEW_MAX_RETRIES:
                    time.sleep(OPENREVIEW_RATE_LIMIT_SLEEP_SECONDS)
                    continue

            if response.status_code == 200:
                profiles = response.json().get("profiles") or []
                if profiles:
                    best_profile = max(profiles, key=lambda profile: _name_score(author_name, profile))
                    if _name_score(author_name, best_profile) > 0:
                        return best_profile
                break

            if response.status_code == 403:
                OPENREVIEW_SEARCH_DISABLED = True
                print("[WARN] OpenReview profile search is forbidden for guest; disabling search fallback")
            else:
                print(
                    f"[WARN] OpenReview profile search unavailable for {author_name}: "
                    f"status={response.status_code}, body={response.text[:200]}"
                )
            break

    for profile_id in candidate_profile_ids(author_name):
        profile = fetch_profile_by_id(session, profile_id)
        if profile and _name_score(author_name, profile) > 0:
            return profile

    return None


def fetch_profile_by_id(session: requests.Session, profile_id: str) -> dict[str, Any] | None:
    """Fetch one OpenReview profile with the requested pacing/backoff."""
    for attempt in range(1, OPENREVIEW_MAX_RETRIES + 1):
        time.sleep(OPENREVIEW_SLEEP_SECONDS)
        try:
            response = session.get(
                OPENREVIEW_PROFILE_URL,
                params={"id": profile_id},
                timeout=15,
            )
        except requests.RequestException as exc:
            print(f"[WARN] OpenReview profile request failed for {profile_id}: {exc}")
            return None

        if response.status_code == 429:
            print(
                f"[WARN] OpenReview profile request rate limited for {profile_id}; "
                f"attempt={attempt}/{OPENREVIEW_MAX_RETRIES}"
            )
            if attempt < OPENREVIEW_MAX_RETRIES:
                time.sleep(OPENREVIEW_RATE_LIMIT_SLEEP_SECONDS)
                continue

        if response.status_code == 200:
            profiles = response.json().get("profiles") or []
            if profiles:
                return profiles[0]
            return None

        print(
            f"[WARN] OpenReview profile request unavailable for {profile_id}: "
            f"status={response.status_code}, body={response.text[:200]}"
        )
        return None
    return None


def profile_for_record(session: requests.Session, record: dict[str, Any]) -> dict[str, Any] | None:
    """Find the best OpenReview profile for one Feishu record."""
    if not hasattr(profile_for_record, "_note_cache"):
        profile_for_record._note_cache = {}  # type: ignore[attr-defined]

    fields = record.get("fields") or {}
    author_id = (
        _stringify(fields.get("openreview_id"))
        or _stringify(fields.get("authorid"))
        or _stringify(fields.get("author_id"))
    )
    if not author_id:
        paper_url = _stringify(fields.get("paper_url"))
        note_id = _note_id_from_paper_url(paper_url)
        note_authorids = fetch_note_authorids(
            session,
            note_id,
            profile_for_record._note_cache,  # type: ignore[attr-defined]
        )
        author_id = note_authorids.get(_normalize_name(_stringify(fields.get("author_name"))), "")

    if author_id:
        profile = fetch_profile_by_id(session, author_id)
        return profile

    author_name = _stringify(fields.get("author_name"))
    if not author_name:
        return None
    return search_openreview_profile(session, author_name)


def build_patch_fields(record: dict[str, Any], profile_fields: dict[str, str]) -> dict[str, Any]:
    """Build PATCH fields, updating only currently empty values."""
    current_fields = record.get("fields") or {}
    patch_fields: dict[str, Any] = {}

    for field_name in BACKFILL_FIELDS:
        if _stringify(current_fields.get(field_name)):
            continue
        value = profile_fields.get(field_name, "")
        if field_name == "email_domain" and value and not value.startswith("@"):
            value = "@" + value
        if value:
            patch_fields[field_name] = value

    return patch_fields


def update_feishu_record(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict[str, Any],
) -> bool:
    """Update one Feishu record with only the requested fields.

    The Feishu deployment used here returns 404 for PATCH /records/{record_id},
    while PUT /records/{record_id} is supported and updates provided fields.
    """
    url = FEISHU_RECORD_URL.format(app_token=app_token, table_id=table_id, record_id=record_id)
    response = session.put(
        url,
        headers=_headers(token),
        json={"fields": fields},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        print(f"[ERROR] Feishu update failed record_id={record_id}: {json.dumps(payload, ensure_ascii=False)}")
        return False
    return True


def main() -> None:
    """Backfill existing Feishu records from OpenReview profiles."""
    settings = load_feishu_settings()
    checkpoint = load_checkpoint()

    processed_count = 0
    updated_records_count = 0
    institution_filled_count = 0
    career_filled_count = 0
    still_empty_count = 0

    with requests.Session() as session:
        token = get_tenant_access_token(session, settings["app_id"], settings["app_secret"])
        records = fetch_all_feishu_records(session, token, settings["app_token"], settings["table_id"])

        total_records = len(records)
        candidates = [
            record
            for record in records
            if needs_backfill(record) and (record.get("record_id") or record.get("id")) not in checkpoint
        ]
        print(f"[INFO] Feishu total records: {total_records}")
        print(f"[INFO] Records needing backfill after checkpoint: {len(candidates)}")

        for record in candidates:
            record_id = str(record.get("record_id") or record.get("id") or "")
            if not record_id:
                continue

            processed_count += 1
            profile = profile_for_record(session, record)
            profile_fields = extract_openreview_profile_fields(profile) if profile else {}
            patch_fields = build_patch_fields(record, profile_fields)
            processed_successfully = False

            if patch_fields:
                try:
                    if update_feishu_record(
                        session,
                        token,
                        settings["app_token"],
                        settings["table_id"],
                        record_id,
                        patch_fields,
                    ):
                        updated_records_count += 1
                        if "institution" in patch_fields:
                            institution_filled_count += 1
                        if "career_history" in patch_fields:
                            career_filled_count += 1
                        processed_successfully = True
                except requests.RequestException as exc:
                    print(f"[ERROR] Feishu update request failed record_id={record_id}: {exc}")
                time.sleep(FEISHU_SLEEP_SECONDS)
            else:
                processed_successfully = bool(profile)

            current_fields = record.get("fields") or {}
            final_institution = _stringify(current_fields.get("institution")) or patch_fields.get("institution", "")
            final_career = _stringify(current_fields.get("career_history")) or patch_fields.get("career_history", "")
            if not final_institution or not final_career:
                still_empty_count += 1

            if processed_successfully:
                mark_processed(record_id)

            if processed_count % 10 == 0:
                print(f"已处理 {processed_count}/{total_records}，成功补全 {updated_records_count} 条")

    print("========== Backfill Summary ==========")
    print(f"总处理条数: {processed_count}")
    print(f"成功补全 institution 的数量: {institution_filled_count}")
    print(f"成功补全 career_history 的数量: {career_filled_count}")
    print(f"仍然为空的数量: {still_empty_count}")


if __name__ == "__main__":
    main()
