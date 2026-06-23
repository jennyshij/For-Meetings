"""Print raw OpenReview note/profile data for the X-VLA paper."""

from __future__ import annotations

import json

import requests


OPENREVIEW_API_URL = "https://api2.openreview.net"
PAPER_TITLE = (
    "X-VLA: Soft-Prompted Transformer as Scalable "
    "Cross-Embodiment Vision-Language-Action Model"
)
NOTE_ID = "kt51kZH4aG"


def content_value(content: dict, key: str, default=None):
    """Read an OpenReview content field without transforming the raw value."""
    value = content.get(key, default)
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def get_note() -> dict:
    """Fetch the target paper note by id."""
    response = requests.get(
        f"{OPENREVIEW_API_URL}/notes",
        params={"id": NOTE_ID},
        timeout=30,
    )
    response.raise_for_status()
    notes = response.json().get("notes") or []
    if not notes:
        raise RuntimeError(f"OpenReview note not found: {NOTE_ID}")
    return notes[0]


def get_profile(author_id: str) -> dict:
    """Fetch an OpenReview profile by author id."""
    response = requests.get(
        f"{OPENREVIEW_API_URL}/profiles",
        params={"id": author_id},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    profiles = payload.get("profiles") or []
    return profiles[0] if profiles else payload


def main() -> None:
    """Print raw note/profile diagnostics for every author."""
    note = get_note()
    content = note.get("content") or {}
    title = content_value(content, "title")
    authors = content_value(content, "authors", []) or []
    authorids = content_value(content, "authorids", []) or []
    author_affiliations = content_value(content, "author_affiliations", [])

    print("PAPER_TITLE_FROM_NOTE:")
    print(title)
    print()
    print("NOTE_ID:")
    print(note.get("id"))
    print()
    print("NOTE_AUTHORIDS_RAW:")
    print(json.dumps(authorids, indent=2, ensure_ascii=False))
    print()
    print("NOTE_AUTHOR_AFFILIATIONS_RAW:")
    print(json.dumps(author_affiliations, indent=2, ensure_ascii=False))
    print()

    for index, author_name in enumerate(authors):
        author_id = authorids[index] if index < len(authorids) else ""
        print("=" * 100)
        print(f"AUTHOR_INDEX: {index + 1}")
        print(f"AUTHOR_NAME: {author_name}")
        print("AUTHORID_FROM_NOTE:")
        print(json.dumps(author_id, indent=2, ensure_ascii=False))
        print("AUTHOR_AFFILIATION_FROM_NOTE:")
        affiliation = author_affiliations[index] if isinstance(author_affiliations, list) and index < len(author_affiliations) else None
        print(json.dumps(affiliation, indent=2, ensure_ascii=False))
        print()

        if not author_id:
            print("PROFILE_RAW_JSON:")
            print("{}")
            continue

        profile = get_profile(author_id)
        print("PROFILE_RAW_JSON:")
        print(json.dumps(profile, indent=2, ensure_ascii=False))
        print()

        profile_content = profile.get("content", {}) if isinstance(profile, dict) else {}
        print("PROFILE_FIELD_content.title_RAW:")
        print(json.dumps(profile_content.get("title"), indent=2, ensure_ascii=False))
        print("PROFILE_FIELD_content.position_RAW:")
        print(json.dumps(profile_content.get("position"), indent=2, ensure_ascii=False))
        print("PROFILE_FIELD_content.history_RAW:")
        print(json.dumps(profile_content.get("history"), indent=2, ensure_ascii=False))
        print("PROFILE_FIELD_content.relations_RAW:")
        print(json.dumps(profile_content.get("relations"), indent=2, ensure_ascii=False))
        print("PROFILE_FIELD_content.expertise_RAW:")
        print(json.dumps(profile_content.get("expertise"), indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
