"""Debug raw OpenReview profile API responses for one author."""

from __future__ import annotations

import json

import requests


AUTHOR_ID = "~Jianxiong_Li1"


def print_json_response(label: str, response: requests.Response) -> dict:
    """Print response status and raw JSON payload."""
    print("=" * 100)
    print(label)
    print("Status:", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        print(response.text)
        return {}

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return payload


def print_selected_fields(payload: dict) -> None:
    """Print selected raw profile content fields."""
    profiles = payload.get("profiles") or []
    profile = profiles[0] if profiles else {}
    content = profile.get("content") or {}

    print("=" * 100)
    print("profiles[0][\"content\"][\"history\"]")
    print(json.dumps(content.get("history"), indent=2, ensure_ascii=False))

    print("=" * 100)
    print("profiles[0][\"content\"][\"relations\"]")
    print(json.dumps(content.get("relations"), indent=2, ensure_ascii=False))

    print("=" * 100)
    print("profiles[0][\"content\"][\"expertise\"]")
    print(json.dumps(content.get("expertise"), indent=2, ensure_ascii=False))

    print("=" * 100)
    print("profiles[0][\"content\"][\"title\"]")
    print(json.dumps(content.get("title"), indent=2, ensure_ascii=False))


def main() -> None:
    """Call OpenReview profile API in both requested forms."""
    url = "https://api2.openreview.net/profiles"
    response_with_params = requests.get(url, params={"id": AUTHOR_ID}, timeout=30)
    payload = print_json_response("REQUEST 1: requests.get(url, params={\"id\": \"~Jianxiong_Li1\"})", response_with_params)

    direct_url = "https://api2.openreview.net/profiles?id=~Jianxiong_Li1"
    response_with_query = requests.get(direct_url, timeout=30)
    print_json_response("REQUEST 2: requests.get(\"https://api2.openreview.net/profiles?id=~Jianxiong_Li1\")", response_with_query)

    print_selected_fields(payload)


if __name__ == "__main__":
    main()
