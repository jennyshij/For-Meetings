"""Sync paper-author CSV rows into a Feishu Bitable table.

Phase 5 keeps the integration small and explicit:
- credentials are loaded from .env or the process environment;
- existing Feishu rows are listed once and de-duplicated by paper_url + author_name;
- new rows are written with batch_create in chunks of 20.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests


FEISHU_AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_RECORDS_URL = (
    "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
)
FEISHU_BATCH_CREATE_URL = FEISHU_RECORDS_URL + "/batch_create"
REQUEST_TIMEOUT_SECONDS = 30
BATCH_SIZE = 20
DEFAULT_STATUS_FIELD = "状态"
DEFAULT_STATUS_VALUE = "未联系"


FIELD_MAPPING = {
    "paper_title": "paper_title",
    "conference": "conference",
    "year": "year",
    "research_direction": "research_direction",
    "author_name": "author_name",
    "author_order": "author_order",
    "institution": "institution",
    "matched_org": "matched_org",
    "org_type": "org_type",
    "email": "email",
    "paper_url": "paper_url",
    "matched_keywords": "matched_keywords",
    "source": "source",
}


def load_env(env_path: str = ".env") -> None:
    """Load simple KEY=VALUE pairs from .env without adding a dependency."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _required_env(name: str) -> str:
    """Return a required environment value or raise a clear error."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def load_feishu_settings(env_path: str = ".env") -> dict[str, str]:
    """Load Feishu app/table settings from .env and environment variables."""
    load_env(env_path)
    return {
        "app_id": _required_env("FEISHU_APP_ID"),
        "app_secret": _required_env("FEISHU_APP_SECRET"),
        "app_token": _required_env("FEISHU_APP_TOKEN"),
        "table_id": _required_env("FEISHU_TABLE_ID"),
    }


def get_tenant_access_token(session: requests.Session, app_id: str, app_secret: str) -> str:
    """Authenticate with Feishu and return tenant_access_token."""
    response = session.post(
        FEISHU_AUTH_URL,
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {payload}")

    token = payload.get("tenant_access_token", "")
    if not token:
        raise RuntimeError("Feishu auth response did not include tenant_access_token")

    return token


def _headers(token: str) -> dict[str, str]:
    """Build Feishu API headers with bearer token authentication."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _stringify_feishu_value(value: Any) -> str:
    """Normalize Feishu field values into strings for de-duplication."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value).strip()
    if isinstance(value, list):
        return " ".join(_stringify_feishu_value(item) for item in value).strip()
    if isinstance(value, dict):
        # Text fields can be returned as rich-text objects. Prefer common text
        # keys, then fall back to joining all nested values.
        for key in ["text", "name", "value"]:
            if key in value:
                return _stringify_feishu_value(value[key])
        return " ".join(_stringify_feishu_value(item) for item in value.values()).strip()
    return str(value).strip()


def _dedupe_key(row: dict[str, Any]) -> tuple[str, str]:
    """Build the paper_url + author_name key requested for duplicate checks."""
    return (
        str(row.get("paper_url", "") or "").strip(),
        str(row.get("author_name", "") or "").strip(),
    )


def fetch_existing_keys(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
) -> set[tuple[str, str]]:
    """Read existing Feishu records and collect paper_url + author_name keys."""
    url = FEISHU_RECORDS_URL.format(app_token=app_token, table_id=table_id)
    existing_keys: set[tuple[str, str]] = set()
    page_token = ""

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        response = session.get(
            url,
            headers=_headers(token),
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != 0:
            raise RuntimeError(f"Feishu list records failed: {payload}")

        data = payload.get("data") or {}
        for item in data.get("items") or []:
            fields = item.get("fields") or {}
            key = (
                _stringify_feishu_value(fields.get("paper_url")),
                _stringify_feishu_value(fields.get("author_name")),
            )
            if any(key):
                existing_keys.add(key)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break

    return existing_keys


def read_csv_records(csv_path: str) -> list[dict[str, Any]]:
    """Read paper-author rows from CSV and de-duplicate within the file."""
    dataframe = pd.read_csv(csv_path, dtype=str, keep_default_na=False).fillna("")
    records: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for row in dataframe.to_dict(orient="records"):
        key = _dedupe_key(row)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        records.append(row)

    return records


def _coerce_bitable_value(csv_column: str, value: Any) -> str:
    """Convert CSV values into Feishu-friendly text values.

    The target Bitable currently exposes fields such as author_order as
    Multiline/Text, so keep values as strings instead of inferring numbers.
    """
    if value is None:
        return ""

    return str(value).strip()


def build_feishu_record(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map one CSV row into Feishu batch_create record format."""
    fields: dict[str, Any] = {}

    for csv_column, feishu_field in FIELD_MAPPING.items():
        fields[feishu_field] = _coerce_bitable_value(csv_column, row.get(csv_column, ""))

    fields[DEFAULT_STATUS_FIELD] = DEFAULT_STATUS_VALUE
    return {"fields": fields}


def _chunked(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    """Split records into fixed-size chunks for Feishu batch_create."""
    return [records[index : index + size] for index in range(0, len(records), size)]


def batch_create_records(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> int:
    """Write records to Feishu in batches; log failures and continue."""
    url = FEISHU_BATCH_CREATE_URL.format(app_token=app_token, table_id=table_id)
    success_count = 0

    for batch_index, batch in enumerate(_chunked(records, BATCH_SIZE), start=1):
        try:
            response = session.post(
                url,
                headers=_headers(token),
                json={"records": batch},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                print(f"[ERROR] Feishu batch {batch_index} failed: {payload}")
            else:
                success_count += len(batch)
                print(f"[INFO] Feishu batch {batch_index} wrote {len(batch)} records")
        except requests.RequestException as exc:
            print(f"[ERROR] Feishu batch {batch_index} request failed: {exc}")

        time.sleep(0.5)

    return success_count


def sync_csv_to_feishu(csv_path: str, env_path: str = ".env") -> int:
    """Sync new CSV rows into Feishu Bitable and return written row count."""
    settings = load_feishu_settings(env_path)
    csv_records = read_csv_records(csv_path)

    with requests.Session() as session:
        token = get_tenant_access_token(
            session=session,
            app_id=settings["app_id"],
            app_secret=settings["app_secret"],
        )
        existing_keys = fetch_existing_keys(
            session=session,
            token=token,
            app_token=settings["app_token"],
            table_id=settings["table_id"],
        )

        records_to_create = []
        skipped_count = 0
        for row in csv_records:
            if _dedupe_key(row) in existing_keys:
                skipped_count += 1
                continue
            records_to_create.append(build_feishu_record(row))

        print(
            f"[INFO] Feishu sync loaded {len(csv_records)} CSV rows, "
            f"skipped {skipped_count} existing rows, writing {len(records_to_create)} new rows"
        )

        if not records_to_create:
            return 0

        return batch_create_records(
            session=session,
            token=token,
            app_token=settings["app_token"],
            table_id=settings["table_id"],
            records=records_to_create,
        )
