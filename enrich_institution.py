"""Enrich inferred email domains from OpenReview institution metadata."""

from __future__ import annotations

import re
from typing import Any


INSTITUTION_EMAIL_DOMAINS = {
    "South China University of Technology": "mail.scut.edu.cn",
    "华南理工大学": "mail.scut.edu.cn",
    "华南理工": "mail.scut.edu.cn",
    "SCUT": "mail.scut.edu.cn",
    "Tsinghua University": "mail.tsinghua.edu.cn",
    "清华大学": "mail.tsinghua.edu.cn",
    "Tsinghua": "mail.tsinghua.edu.cn",
    "清华": "mail.tsinghua.edu.cn",
    "THU": "mail.tsinghua.edu.cn",
    "Peking University": "pku.edu.cn",
    "北京大学": "pku.edu.cn",
    "PKU": "pku.edu.cn",
    "Shanghai Jiao Tong University": "sjtu.edu.cn",
    "Shanghai Jiao Tong": "sjtu.edu.cn",
    "上海交通大学": "sjtu.edu.cn",
    "SJTU": "sjtu.edu.cn",
    "Zhejiang University": "zju.edu.cn",
    "浙江大学": "zju.edu.cn",
    "ZJU": "zju.edu.cn",
    "复旦大学": "fudan.edu.cn",
    "复旦": "fudan.edu.cn",
    "Fudan": "fudan.edu.cn",
    "Harbin Institute of Technology": "hit.edu.cn",
    "哈工大": "hit.edu.cn",
    "HIT": "hit.edu.cn",
    "University of Science and Technology of China": "ustc.edu.cn",
    "中科大": "ustc.edu.cn",
    "USTC": "ustc.edu.cn",
    "Nanjing University": "nju.edu.cn",
    "南京大学": "nju.edu.cn",
    "NJU": "nju.edu.cn",
    "Tongji University": "tongji.edu.cn",
    "同济大学": "tongji.edu.cn",
    "Tongji": "tongji.edu.cn",
    "同济": "tongji.edu.cn",
    "Wuhan University": "whu.edu.cn",
    "武汉大学": "whu.edu.cn",
    "Sun Yat-sen University": "mail.sysu.edu.cn",
    "Sun Yat-sen": "mail.sysu.edu.cn",
    "中山大学": "mail.sysu.edu.cn",
    "SYSU": "mail.sysu.edu.cn",
    "Institute of Automation": "ia.ac.cn",
    "自动化研究所": "ia.ac.cn",
    "CASIA": "ia.ac.cn",
    "Chinese Academy of Sciences": "ia.ac.cn",
    "Chinese Academy": "ia.ac.cn",
    "中科院": "ia.ac.cn",
    "CAS": "ia.ac.cn",
    "Shenyang Institute of Automation": "sia.cn",
    "沈阳自动化研究所": "sia.cn",
    "沈阳自动化": "sia.cn",
    "SIA": "sia.cn",
    "Massachusetts Institute of Technology": "mit.edu",
    "MIT": "mit.edu",
    "Stanford University": "stanford.edu",
    "Stanford": "stanford.edu",
    "Carnegie Mellon University": "cs.cmu.edu",
    "Carnegie Mellon": "cs.cmu.edu",
    "CMU": "cs.cmu.edu",
    "University of California, Berkeley": "berkeley.edu",
    "UC Berkeley": "berkeley.edu",
    "Berkeley": "berkeley.edu",
    "ETH Zurich": "ethz.ch",
    "ETH": "ethz.ch",
    "University of Oxford": "ox.ac.uk",
    "Oxford": "ox.ac.uk",
    "University of Cambridge": "cam.ac.uk",
    "Cambridge": "cam.ac.uk",
    "Google DeepMind": "google.com",
    "DeepMind": "google.com",
    "Google": "google.com",
    "Meta AI": "meta.com",
    "FAIR": "meta.com",
    "Meta": "meta.com",
    "Microsoft Research": "microsoft.com",
    "Microsoft": "microsoft.com",
    "MSR": "microsoft.com",
    "Apple": "apple.com",
    "Amazon": "amazon.com",
    "Figure AI": "figure.ai",
    "Figure": "figure.ai",
    "Physical Intelligence": "physicalintelligence.ai",
    "PI": "physicalintelligence.ai",
}


def _term_matches(text: str, term: str) -> bool:
    """Case-insensitive fuzzy institution matching."""
    if not text or not term:
        return False

    lowered_text = text.lower()
    lowered_term = term.lower()
    # Two-letter aliases such as PI are too broad as raw substrings; keep token
    # boundaries for them while using substring matching for normal aliases.
    if re.fullmatch(r"[a-z]{2}", lowered_term):
        return re.search(rf"(?<![a-z0-9]){re.escape(lowered_term)}(?![a-z0-9])", lowered_text) is not None
    return lowered_term in lowered_text


def infer_email_domain_from_institution(institution_text: str) -> str:
    """Infer an email domain from institution text using the most specific alias."""
    matches = [
        (institution_term, domain)
        for institution_term, domain in INSTITUTION_EMAIL_DOMAINS.items()
        if _term_matches(institution_text, institution_term)
    ]
    if matches:
        _, domain = max(matches, key=lambda item: len(item[0]))
        return f"@{domain}" if not domain.startswith("@") else domain
    return ""


def _format_email_domain(domain: str) -> str:
    """Normalize a raw institution domain into the email_domain display format."""
    domain = str(domain or "").strip().lstrip("@")
    return f"@{domain}" if domain else ""


def enrich_rows_with_institution_details(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill inferred email domains for author rows."""
    institution_detail_count = 0
    email_domain_count = 0
    unmatched_rows: list[dict[str, str]] = []

    for row in rows:
        if row.get("institution_detail"):
            institution_detail_count += 1

        institution_domain = _format_email_domain(row.get("institution_domain", ""))
        if institution_domain:
            row["email_domain"] = institution_domain
            row["email_source"] = "openreview_institution_domain"
            email_domain_count += 1
            continue

        institution_text = " ".join(
            str(row.get(field, "") or "")
            for field in ["institution", "institution_detail", "education_history", "career_history"]
        )
        email_domain = infer_email_domain_from_institution(institution_text)
        if email_domain:
            row["email_domain"] = email_domain
            row["email_source"] = "inferred_from_institution"
            email_domain_count += 1
        else:
            unmatched_rows.append(
                {
                    "author_name": str(row.get("author_name", "") or ""),
                    "institution": str(row.get("institution", "") or ""),
                    "institution_detail": str(row.get("institution_detail", "") or ""),
                }
            )

    total_authors = len(rows)
    match_ratio = (email_domain_count / total_authors * 100) if total_authors else 0
    print(f"[INFO] Authors with institution_detail: {institution_detail_count}")
    print(f"[INFO] Total authors: {total_authors}")
    print(
        f"[INFO] Email domain matched authors: {email_domain_count}/{total_authors} "
        f"({match_ratio:.1f}%)"
    )
    if unmatched_rows:
        print("[INFO] Email domain unmatched authors without real email:")
        for unmatched in unmatched_rows:
            print(
                "[INFO] - "
                f"author={unmatched['author_name']} | "
                f"institution={unmatched['institution']} | "
                f"institution_detail={unmatched['institution_detail']}"
            )
    return rows
