"""Optional homepage + Claude enrichment for rows missing institutions."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
REQUEST_TIMEOUT_SECONDS = 30
HOMEPAGE_TIMEOUT_SECONDS = 8
MAX_PAGE_TEXT_CHARS = 12000


def _strip_html(html_text: str) -> str:
    """Convert rough HTML into compact text for LLM extraction."""
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html_text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return " ".join(text.split())


def _anthropic_api_key() -> str:
    """Read Claude API key from common environment variable names."""
    return os.getenv("ANTHROPIC_API_KEY", "").strip() or os.getenv("CLAUDE_API_KEY", "").strip()


def _fetch_homepage_text(homepage: str) -> str:
    """Fetch homepage text for optional LLM extraction."""
    if not homepage:
        return ""
    try:
        response = requests.get(homepage, timeout=HOMEPAGE_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Homepage enrichment fetch failed url={homepage}: {exc}")
        return ""
    return _strip_html(response.text)[:MAX_PAGE_TEXT_CHARS]


def _extract_json(text: str) -> dict[str, str]:
    """Extract a JSON object from a Claude response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return {
        "institution": str(payload.get("institution", "") or "").strip(),
        "career_history": str(payload.get("career_history", "") or "").strip(),
        "education_history": str(payload.get("education_history", "") or "").strip(),
    }


def _call_claude_for_homepage(page_text: str) -> dict[str, str]:
    """Use Claude API to extract structured profile details from homepage text."""
    api_key = _anthropic_api_key()
    if not api_key:
        print("[WARN] Homepage enrichment skipped: ANTHROPIC_API_KEY/CLAUDE_API_KEY is not set")
        return {}

    prompt = f"""
从以下个人主页内容提取此人的信息，
用JSON格式返回：
{{
  "institution": "当前职位和所在机构，例如：PhD student, AIR, Tsinghua University",
  "career_history": "工作和实习经历，用|分隔，例如：Intern, PI, 2024|RA, MIT, 2023",
  "education_history": "教育经历，用|分隔"
}}
如果找不到某项信息，对应字段返回空字符串。

页面内容：
{page_text}
"""

    try:
        response = requests.post(
            ANTHROPIC_MESSAGES_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Claude homepage enrichment failed: {exc}")
        return {}

    payload = response.json()
    content_blocks = payload.get("content") or []
    response_text = "\n".join(block.get("text", "") for block in content_blocks if block.get("type") == "text")
    return _extract_json(response_text)


def enrich_rows_with_homepage_claude(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing institution fields from homepage text via Claude API."""
    enriched_count = 0
    missing_rows = [row for row in rows if not row.get("institution") and row.get("homepage")]
    if not missing_rows:
        print("[INFO] Homepage Claude enrichment: 0 candidate rows")
        return rows
    if not _anthropic_api_key():
        print(
            "[WARN] Homepage Claude enrichment skipped: "
            "ANTHROPIC_API_KEY/CLAUDE_API_KEY is not set"
        )
        return rows

    print(f"[INFO] Homepage Claude enrichment candidate rows: {len(missing_rows)}")
    for row in missing_rows:
        page_text = _fetch_homepage_text(str(row.get("homepage", "")))
        if not page_text:
            continue
        extracted = _call_claude_for_homepage(page_text)
        if not extracted:
            continue

        if extracted.get("institution") and not row.get("institution"):
            row["institution"] = extracted["institution"]
        if extracted.get("career_history") and not row.get("career_history"):
            row["career_history"] = extracted["career_history"]
        if extracted.get("education_history") and not row.get("education_history"):
            row["education_history"] = extracted["education_history"]
        enriched_count += 1

    print(f"[INFO] Homepage Claude enrichment filled {enriched_count} rows")
    return rows
