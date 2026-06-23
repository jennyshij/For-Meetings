"""Enrich author rows with emails found on homepage pages."""

from __future__ import annotations

import argparse
import re
from typing import Any

import pandas as pd
import requests


REQUEST_TIMEOUT_SECONDS = 5
EMAIL_PATTERN = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.+-])")
USER_AGENT = "AI-Recruiting-Mapping-Tool/0.1"


def extract_email_from_text(text: str) -> str:
    """Return the first plausible non-redacted email found in text."""
    for match in EMAIL_PATTERN.findall(text or ""):
        email = match.strip().strip(".,;:()[]{}<>")
        if not email or "*" in email:
            continue
        if email.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
            continue
        return email
    return ""


def fetch_email_from_homepage(homepage: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
    """Fetch one homepage and extract the first email address with regex."""
    if not homepage:
        return ""

    try:
        response = requests.get(
            homepage,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Email enrichment skipped homepage={homepage}: {exc}")
        return ""

    return extract_email_from_text(response.text[:1_000_000])


def enrich_rows_with_homepage_emails(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing email fields by scraping author homepages."""
    homepage_cache: dict[str, str] = {}
    enriched_count = 0

    for row in rows:
        if row.get("email"):
            continue

        homepage = str(row.get("homepage", "") or "").strip()
        if not homepage:
            continue

        if homepage not in homepage_cache:
            homepage_cache[homepage] = fetch_email_from_homepage(homepage)

        email = homepage_cache[homepage]
        if email:
            row["email"] = email
            enriched_count += 1

    print(f"[INFO] Email enrichment filled {enriched_count} author rows")
    return rows


def main() -> None:
    """Small command-line helper for testing email enrichment on a CSV file."""
    parser = argparse.ArgumentParser(description="Extract emails from homepage URLs in a CSV.")
    parser.add_argument("--input", required=True, help="Input CSV path.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    args = parser.parse_args()

    dataframe = pd.read_csv(args.input, dtype=str, keep_default_na=False).fillna("")
    rows = enrich_rows_with_homepage_emails(dataframe.to_dict(orient="records"))
    pd.DataFrame(rows).fillna("").to_csv(args.output, index=False, encoding="utf-8")
    print(f"Exported email-enriched rows to {args.output}")


if __name__ == "__main__":
    main()
