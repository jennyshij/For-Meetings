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
FEISHU_RECORD_URL = FEISHU_RECORDS_URL + "/{record_id}"
FEISHU_FIELDS_URL = (
    "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
)
REQUEST_TIMEOUT_SECONDS = 30
BATCH_SIZE = 20


FIELD_MAPPING = {
    "paper_title": "paper_title",
    "year": "year",
    "paper_url": "paper_url",
    "research_direction": "research_direction",
    "author_name": "author_name",
    "institution": "institution",
    "institution_detail": "institution_detail",
    "education_history": "education_history",
    "career_history": "career_history",
    "advisor": "advisor",
    "relations_conflicts": "relations_conflicts",
    "email": "email",
    "email_domain": "email_domain",
    "homepage": "homepage",
    "linkedin": "linkedin",
    "github": "github",
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


def fetch_existing_records(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
) -> dict[tuple[str, str], str]:
    """Read existing Feishu records and map paper_url + author_name to record_id."""
    url = FEISHU_RECORDS_URL.format(app_token=app_token, table_id=table_id)
    existing_records: dict[tuple[str, str], str] = {}
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
            record_id = item.get("record_id") or item.get("id") or ""
            if any(key) and record_id:
                existing_records[key] = str(record_id)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break

    return existing_records


def fetch_table_field_names(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
) -> set[str]:
    """Read Feishu table fields so missing optional columns can be skipped."""
    url = FEISHU_FIELDS_URL.format(app_token=app_token, table_id=table_id)
    field_names: set[str] = set()
    page_token = ""

    while True:
        params = {"page_size": 100}
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
            raise RuntimeError(f"Feishu list fields failed: {payload}")

        data = payload.get("data") or {}
        for item in data.get("items") or []:
            field_name = item.get("field_name") or item.get("name")
            if field_name:
                field_names.add(str(field_name))

        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break

    return field_names


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


def _coerce_bitable_value(csv_column: str, value: Any) -> Any:
    """Convert CSV values into Feishu-friendly field values."""
    if value is None:
        return ""

    text = str(value).strip()
    if csv_column == "year":
        return int(text) if text.isdigit() else ""
    return text


def build_feishu_record(
    row: dict[str, Any],
    allowed_field_names: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map one CSV row into Feishu batch_create record format."""
    fields: dict[str, Any] = {}

    for csv_column, feishu_field in FIELD_MAPPING.items():
        if allowed_field_names is not None and feishu_field not in allowed_field_names:
            continue
        fields[feishu_field] = _coerce_bitable_value(csv_column, row.get(csv_column, ""))

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


def update_existing_records(
    session: requests.Session,
    token: str,
    app_token: str,
    table_id: str,
    records: list[tuple[str, dict[str, dict[str, Any]]]],
) -> int:
    """Update existing Feishu records one by one; log failures and continue."""
    success_count = 0

    for index, (record_id, record) in enumerate(records, start=1):
        url = FEISHU_RECORD_URL.format(
            app_token=app_token,
            table_id=table_id,
            record_id=record_id,
        )
        try:
            response = session.put(
                url,
                headers=_headers(token),
                json=record,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                print(f"[ERROR] Feishu update {index} failed record_id={record_id}: {payload}")
            else:
                success_count += 1
                print(f"[INFO] Feishu update {index} updated record_id={record_id}")
        except requests.RequestException as exc:
            print(f"[ERROR] Feishu update {index} request failed record_id={record_id}: {exc}")

        time.sleep(0.2)

    return success_count


def sync_csv_to_feishu(
    csv_path: str,
    env_path: str = ".env",
    force_update: bool = False,
) -> dict[str, int]:
    """Sync CSV rows into Feishu Bitable and return create/update counts."""
    settings = load_feishu_settings(env_path)
    csv_records = read_csv_records(csv_path)

    with requests.Session() as session:
        token = get_tenant_access_token(
            session=session,
            app_id=settings["app_id"],
            app_secret=settings["app_secret"],
        )
        existing_records = fetch_existing_records(
            session=session,
            token=token,
            app_token=settings["app_token"],
            table_id=settings["table_id"],
        )
        field_names = fetch_table_field_names(
            session=session,
            token=token,
            app_token=settings["app_token"],
            table_id=settings["table_id"],
        )

        requested_field_names = set(FIELD_MAPPING.values())
        missing_field_names = sorted(requested_field_names - field_names)
        if missing_field_names:
            print(
                "[WARN] Feishu table is missing these fields; they will be skipped: "
                + ", ".join(missing_field_names)
            )

        records_to_create = []
        records_to_update = []
        skipped_count = 0
        for row in csv_records:
            key = _dedupe_key(row)
            record = build_feishu_record(row, allowed_field_names=field_names)
            existing_record_id = existing_records.get(key)
            if existing_record_id:
                if force_update:
                    records_to_update.append((existing_record_id, record))
                else:
                    skipped_count += 1
                continue
            records_to_create.append(record)

        print(
            f"[INFO] Feishu sync loaded {len(csv_records)} CSV rows, "
            f"skipped {skipped_count} existing rows, "
            f"creating {len(records_to_create)} new rows, "
            f"updating {len(records_to_update)} existing rows"
        )

        created_count = 0
        updated_count = 0
        if records_to_create:
            created_count = batch_create_records(
                session=session,
                token=token,
                app_token=settings["app_token"],
                table_id=settings["table_id"],
                records=records_to_create,
            )
        if records_to_update:
            updated_count = update_existing_records(
                session=session,
                token=token,
                app_token=settings["app_token"],
                table_id=settings["table_id"],
                records=records_to_update,
            )

        return {
            "created": created_count,
            "updated": updated_count,
            "skipped": skipped_count,
        }
