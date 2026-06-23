"""Debug batched OpenReview profile parsing for the X-VLA paper."""

from __future__ import annotations

import requests

from fetch_openreview import (
    extract_openreview_profile_fields,
    fetch_openreview_profiles_batch,
)


OPENREVIEW_API_URL = "https://api2.openreview.net"
NOTE_ID = "kt51kZH4aG"


def _content_value(content: dict, key: str, default=None):
    """Read OpenReview content fields that are often wrapped as {value: ...}."""
    value = content.get(key, default)
    if isinstance(value, dict) and "value" in value:
        return value.get("value", default)
    return value


def get_x_vla_authors() -> tuple[list[str], list[str]]:
    """Fetch X-VLA note author names and OpenReview IDs."""
    response = requests.get(
        f"{OPENREVIEW_API_URL}/notes",
        params={"id": NOTE_ID},
        timeout=30,
    )
    response.raise_for_status()
    notes = response.json().get("notes") or []
    if not notes:
        raise RuntimeError(f"Note not found: {NOTE_ID}")

    content = notes[0].get("content") or {}
    authors = _content_value(content, "authors", []) or []
    authorids = _content_value(content, "authorids", []) or []
    return authors, authorids


def main() -> None:
    """Batch fetch X-VLA profiles and print parsed fields."""
    authors, authorids = get_x_vla_authors()
    print(f"X-VLA author count: {len(authors)}")
    print(f"X-VLA authorids: {', '.join(authorids)}")

    profile_map = fetch_openreview_profiles_batch(authorids, batch_size=10)
    print(f"Profiles returned/mapped aliases: {len(profile_map)}")
    print()

    for index, author_name in enumerate(authors):
        author_id = authorids[index] if index < len(authorids) else ""
        profile = profile_map.get(author_id)
        fields = extract_openreview_profile_fields(profile) if profile else {}
        print("=" * 100)
        print(f"author_name: {author_name}")
        print(f"authorid: {author_id}")
        print(f"profile_found: {bool(profile)}")
        print(f"institution: {fields.get('openreview_institution', '')}")
        print(f"career_history: {fields.get('career_history', '')}")
        print(f"advisor: {fields.get('advisor', '')}")


if __name__ == "__main__":
    main()
