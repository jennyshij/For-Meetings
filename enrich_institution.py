"""Enrich institution detail and inferred email domains."""

from __future__ import annotations

import html
import re
import time
from typing import Any

import requests


GOOGLE_SCHOLAR_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
GOOGLE_SCHOLAR_TIMEOUT_SECONDS = 8
GOOGLE_SCHOLAR_PAUSE_SECONDS = 2


INSTITUTION_EMAIL_DOMAINS = {
    "MIT": "mit.edu",
    "Massachusetts Institute of Technology": "mit.edu",
    "Stanford": "stanford.edu",
    "Stanford University": "stanford.edu",
    "CMU": "cs.cmu.edu",
    "Carnegie Mellon": "cs.cmu.edu",
    "Carnegie Mellon University": "cs.cmu.edu",
    "清华大学": "tsinghua.edu.cn",
    "Tsinghua": "tsinghua.edu.cn",
    "北京大学": "pku.edu.cn",
    "Peking University": "pku.edu.cn",
    "上海交通大学": "sjtu.edu.cn",
    "SJTU": "sjtu.edu.cn",
    "Shanghai Jiao Tong": "sjtu.edu.cn",
    "浙江大学": "zju.edu.cn",
    "Zhejiang University": "zju.edu.cn",
    "复旦大学": "fudan.edu.cn",
    "Fudan": "fudan.edu.cn",
    "中科院": "ia.ac.cn",
    "CAS": "ia.ac.cn",
    "Chinese Academy": "ia.ac.cn",
    "Chinese Academy of Sciences": "ia.ac.cn",
    "华南理工": "scut.edu.cn",
    "SCUT": "scut.edu.cn",
    "South China University of Technology": "scut.edu.cn",
    "哈工大": "hit.edu.cn",
    "HIT": "hit.edu.cn",
    "Harbin Institute of Technology": "hit.edu.cn",
    "同济": "tongji.edu.cn",
    "Tongji": "tongji.edu.cn",
    "南京大学": "nju.edu.cn",
    "NJU": "nju.edu.cn",
    "Nanjing University": "nju.edu.cn",
    "ETH": "ethz.ch",
    "ETH Zurich": "ethz.ch",
    "UC Berkeley": "berkeley.edu",
    "University of California, Berkeley": "berkeley.edu",
    "Oxford": "ox.ac.uk",
    "University of Oxford": "ox.ac.uk",
    "Cambridge": "cam.ac.uk",
    "University of Cambridge": "cam.ac.uk",
}


def _strip_html(value: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(text).split())


def extract_google_scholar_affiliation(page_html: str) -> str:
    """Extract the affiliation text displayed under the scholar's name."""
    matches = re.findall(r'<div class="gsc_prf_il">(.*?)</div>', page_html or "", flags=re.S)
    for match in matches:
        affiliation = _strip_html(match)
        if affiliation and "@" not in affiliation and "Verified email" not in affiliation:
            return affiliation
    return ""


def fetch_google_scholar_institution_detail(gscholar_url: str) -> str:
    """Fetch a Google Scholar profile and parse its affiliation text."""
    if not gscholar_url:
        return ""

    try:
        response = requests.get(
            gscholar_url,
            headers=GOOGLE_SCHOLAR_HEADERS,
            timeout=GOOGLE_SCHOLAR_TIMEOUT_SECONDS,
        )
        if response.status_code == 403:
            print(f"[WARN] Google Scholar blocked request with 403 url={gscholar_url}")
            return ""
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Google Scholar institution lookup failed url={gscholar_url}: {exc}")
        return ""

    institution_detail = extract_google_scholar_affiliation(response.text)
    if institution_detail:
        print(f"[INFO] Google Scholar institution detail found url={gscholar_url}: {institution_detail}")
    else:
        print(f"[WARN] Google Scholar institution detail not found url={gscholar_url}")
    return institution_detail


def _term_matches(text: str, term: str) -> bool:
    """Fuzzy institution matching, case-insensitive with boundaries for short Latin terms."""
    if not text or not term:
        return False

    lowered_text = text.lower()
    lowered_term = term.lower()
    if re.fullmatch(r"[a-z0-9 .,&-]+", lowered_term):
        pattern = rf"(?<![a-z0-9]){re.escape(lowered_term)}(?![a-z0-9])"
        return re.search(pattern, lowered_text) is not None
    return lowered_term in lowered_text


def infer_email_domain_from_institution(institution_text: str) -> str:
    """Infer an email domain from institution text using a curated mapping."""
    for institution_term, domain in INSTITUTION_EMAIL_DOMAINS.items():
        if _term_matches(institution_text, institution_term):
            return domain
    return ""


def enrich_rows_with_institution_details(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill institution_detail and inferred email domains for author rows."""
    scholar_cache: dict[str, str] = {}
    institution_detail_count = 0
    email_domain_count = 0

    for row in rows:
        gscholar_url = str(row.get("gscholar", "") or "").strip()
        if gscholar_url and gscholar_url not in scholar_cache:
            scholar_cache[gscholar_url] = fetch_google_scholar_institution_detail(gscholar_url)
            time.sleep(GOOGLE_SCHOLAR_PAUSE_SECONDS)

        institution_detail = scholar_cache.get(gscholar_url, "")
        if institution_detail and not row.get("institution_detail"):
            row["institution_detail"] = institution_detail

        if row.get("institution_detail"):
            institution_detail_count += 1

        # Do not infer a domain when a real email is already present.
        if row.get("email"):
            row["email_domain"] = ""
            row["email_source"] = ""
            continue

        institution_text = " ".join(
            str(row.get(field, "") or "")
            for field in ["institution", "institution_detail"]
        )
        email_domain = infer_email_domain_from_institution(institution_text)
        if email_domain:
            row["email_domain"] = email_domain
            row["email_source"] = "inferred_from_institution"
            email_domain_count += 1

    print(f"[INFO] Authors with institution_detail: {institution_detail_count}")
    print(f"[INFO] Authors with email_domain: {email_domain_count}")
    return rows
