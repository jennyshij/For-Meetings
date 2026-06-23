"""Enrich author rows with emails found on homepage pages."""

from __future__ import annotations

import argparse
import re
from typing import Any
from urllib.parse import urlparse

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


def _compact_snippet(text: str, max_length: int = 500) -> str:
    """Return a single-line diagnostic snippet."""
    return " ".join((text or "")[:max_length].split())


def _lookup_urls_for_row(row: dict[str, Any]) -> list[str]:
    """Return homepage plus optional profile links to inspect for emails."""
    urls = []
    for key in ["homepage", "email_lookup_urls"]:
        value = str(row.get(key, "") or "").strip()
        if not value:
            continue
        urls.extend(part.strip() for part in value.split(";") if part.strip())
    return list(dict.fromkeys(urls))


def fetch_email_from_url(url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
    """Fetch one URL and extract the first email address with diagnostics."""
    if not url:
        return ""

    label = urlparse(url).netloc or url
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        print(f"[INFO] Email lookup success url={url} status={response.status_code}")
    except requests.Timeout:
        print(f"[WARN] Email lookup timeout url={url}")
        return ""
    except requests.RequestException as exc:
        print(f"[WARN] Email lookup failed url={url}: {exc}")
        return ""

    email = extract_email_from_text(response.text[:1_000_000])
    if email:
        print(f"[INFO] Email found from {label}: {email}")
    else:
        print(f"[INFO] No email found url={url}; first_500_chars={_compact_snippet(response.text)}")
    return email


def fetch_email_from_homepage(homepage: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> str:
    """Backward-compatible wrapper for fetching an email from one homepage."""
    return fetch_email_from_url(homepage, timeout=timeout)


def enrich_rows_with_homepage_emails(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing email fields by scraping author homepages."""
    url_cache: dict[str, str] = {}
    enriched_count = 0
    homepage_author_count = sum(1 for row in rows if str(row.get("homepage", "") or "").strip())
    print(f"[INFO] Email enrichment authors with homepage: {homepage_author_count}")

    for row in rows:
        if row.get("email"):
            continue

        lookup_urls = _lookup_urls_for_row(row)
        if not lookup_urls:
            continue

        for lookup_url in lookup_urls:
            if lookup_url not in url_cache:
                url_cache[lookup_url] = fetch_email_from_url(lookup_url)

            email = url_cache[lookup_url]
            if email:
                row["email"] = email
                enriched_count += 1
                break

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
