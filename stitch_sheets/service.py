"""Google Sheets API service — self-contained, no stitch_backend imports.

Implements the subset of :class:`GoogleSheetsService` needed by the
stitch-sheets plugin: connection test, schema init, dataset fetch, and
row CRUD.  Auth is via service-account JWT (self-contained) or OAuth
tokens obtained from the host via reverse RPC.
"""

# _generated_by: stitch_plugin_tools scaffold v3

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from typing import Any, cast

import httpx

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

SCHEMA_SHEETS: dict[str, list[str]] = {
    "INDEX": ["key", "value", "updated_at"],
    "ENUMS": ["name", "values", "description"],
    "IDENTITIES": [
        "identity_id", "display_name", "email", "status", "tags",
        "created_at", "updated_at",
    ],
    "LINKS": [
        "link_id", "identity_id", "provider", "account_id", "role",
        "status", "is_primary", "metadata", "created_at", "updated_at",
    ],
    "SVC_ACCOUNT_LINKS": [
        "account_link_id", "account_id", "provider", "email", "status",
        "token_type", "metadata", "created_at", "updated_at",
    ],
    "SVC_PROFILE_LINKS": [
        "profile_link_id", "account_id", "profile_name", "fingerprint_id",
        "status", "metadata", "created_at", "updated_at",
    ],
    "SVC_AUTH_METHODS": [
        "auth_method_id", "provider", "method_type", "client_id",
        "status", "metadata", "created_at", "updated_at",
    ],
    "SVC_ACCOUNT_AUTH_LINKS": [
        "account_auth_link_id", "account_id", "auth_method_id",
        "status", "metadata", "created_at", "updated_at",
    ],
}

SVC_FIELD_MAP: dict[str, str] = {
    "SVC_ACCOUNT_LINKS": "accountLinks",
    "SVC_PROFILE_LINKS": "profileLinks",
    "SVC_AUTH_METHODS": "authMethods",
    "SVC_ACCOUNT_AUTH_LINKS": "accountAuthLinks",
}

_token_cache: dict[str, tuple[str, float]] = {}
_TOKEN_TTL = 3300.0


def _fetch_sa_token(sa_json: str) -> str:
    """Fetch an OAuth2 access token from a service account JSON."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account as sa

        creds = sa.Credentials.from_service_account_info(
            json.loads(sa_json),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        creds.refresh(Request())
        return cast("str", creds.token)
    except ImportError:
        pass

    sa_info = json.loads(sa_json)
    now = int(time.time())
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": sa_info["client_email"],
        "scope": "https://www.googleapis.com/auth/spreadsheets",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }).encode()).rstrip(b"=")
    signing_input = header + b"." + payload

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    private_key = serialization.load_pem_private_key(
        sa_info["private_key"].encode(), password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    jwt_token = (signing_input + b"." + sig_b64).decode()

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt_token,
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    return cast("str", resp.json()["access_token"])


def _get_sa_token(sa_json: str) -> str:
    """Get a cached SA token (or fetch a new one)."""
    cache_key = hashlib.sha256(sa_json.encode()).hexdigest()
    cached = _token_cache.get(cache_key)
    if cached and cached[1] > time.time():
        return cached[0]
    token = _fetch_sa_token(sa_json)
    _token_cache[cache_key] = (token, time.time() + _TOKEN_TTL)
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _normalize_row(row_number: int, headers: list[str], raw_row: list[str]) -> dict:
    cells = []
    for i, header in enumerate(headers):
        value = raw_row[i] if i < len(raw_row) else ""
        cells.append({"key": header, "value": "" if value is None else str(value)})
    return {"rowNumber": row_number, "cells": cells}


def _get_cell_value(normalized_row: dict, key: str) -> str:
    for cell in normalized_row.get("cells", []):
        if cell["key"] == key:
            return cast("str", cell["value"])
    return ""


def _flatten_row(normalized_row: dict) -> dict[str, Any]:
    """Flatten a ``{rowNumber, cells: [{key, value}]}`` row into a flat dict.

    The declarative UI tables resolve ``row[column.key]`` directly, so they
    need flat rows keyed by the sheet headers (plus ``rowNumber``). The
    cell-shaped originals are kept alongside for the identity graph, which
    parses ``row.cells`` (see ``useGoogleSheetsDataset``).
    """
    flat: dict[str, Any] = {"rowNumber": normalized_row.get("rowNumber", 0)}
    for cell in normalized_row.get("cells", []):
        flat[cell["key"]] = cell["value"]
    return flat


async def test_connection(
    spreadsheet_id: str, sa_json: str, oauth_token: str | None = None
) -> dict[str, Any]:
    """Test a Google Sheets connection and return connection status.

    The return shape ``{ok, spreadsheetId, title, sheets, warnings}``
    mirrors the built-in ``GoogleSheetsConnectionStatus.to_dict()`` (in
    ``stitch_backend.domains.google_sheets.service``) because this
    command dual-routes: when the plugin is healthy the dispatcher routes
    ``test_google_sheets_connection`` here (see ``sheets_dual.py``);
    when the plugin is down it falls through to the built-in handler
    which returns the same shape.  The frontend consumer
    (``GoogleSheetsConnectionStatus`` type) depends on this contract, so
    the ``{ok, warnings}`` keys must NOT be changed to ``{success, error}``.
    """
    token = oauth_token or _get_sa_token(sa_json)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{SHEETS_API_BASE}/{spreadsheet_id}",
                params={"includeGridData": "false"},
                headers=_headers(token),
            )
            resp.raise_for_status()
            data = resp.json()
            sheets = [
                {"title": s["properties"]["title"], "sheetId": s["properties"]["sheetId"]}
                for s in data.get("sheets", [])
            ]
            return {
                "ok": True,
                "spreadsheetId": spreadsheet_id,
                "title": data.get("properties", {}).get("title"),
                "sheets": sheets,
                "warnings": [],
            }
    except Exception as exc:
        return {
            "ok": False,
            "spreadsheetId": spreadsheet_id,
            "title": None,
            "sheets": [],
            "warnings": [str(exc)[:300]],
        }


async def init_schema(
    spreadsheet_id: str, sa_json: str, oauth_token: str | None = None
) -> dict[str, Any]:
    token = oauth_token or _get_sa_token(sa_json)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{SHEETS_API_BASE}/{spreadsheet_id}",
            params={"includeGridData": "false"},
            headers=_headers(token),
        )
        resp.raise_for_status()
        existing = {s["properties"]["title"] for s in resp.json().get("sheets", [])}

        requests: list[dict] = []
        for sheet_name in SCHEMA_SHEETS:
            if sheet_name not in existing:
                requests.append({"addSheet": {"properties": {"title": sheet_name}}})
        if requests:
            await client.post(
                f"{SHEETS_API_BASE}/{spreadsheet_id}:batchUpdate",
                json={"requests": requests},
                headers=_headers(token),
            )
        for sheet_name, headers in SCHEMA_SHEETS.items():
            range_str = f"{sheet_name}!A1:{chr(64 + len(headers))}1"
            await client.put(
                f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_str}",
                params={"valueInputOption": "RAW"},
                json={"values": [headers]},
                headers=_headers(token),
            )
    return await test_connection(spreadsheet_id, sa_json, oauth_token)


async def _fetch_sheet(
    client: httpx.AsyncClient, token: str, spreadsheet_id: str, sheet_name: str
) -> list[dict]:
    resp = await client.get(
        f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{sheet_name}",
        headers=_headers(token),
    )
    if resp.status_code != 200:
        return []
    values = resp.json().get("values", [])
    if len(values) < 2:
        return []
    headers = values[0]
    return [
        _normalize_row(i + 2, headers, row) for i, row in enumerate(values[1:])
    ]


async def fetch_dataset(
    spreadsheet_id: str, sa_json: str, oauth_token: str | None = None
) -> dict[str, Any]:
    token = oauth_token or _get_sa_token(sa_json)
    dataset: dict[str, Any] = {
        "spreadsheetId": spreadsheet_id, "title": None,
        "identities": [], "links": [], "accountLinks": [],
        "profileLinks": [], "authMethods": [], "accountAuthLinks": [],
        "services": [], "invalidRows": [], "schemaIssues": [],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{SHEETS_API_BASE}/{spreadsheet_id}",
                params={"includeGridData": "false"},
                headers=_headers(token),
            )
            resp.raise_for_status()
            data = resp.json()
            dataset["title"] = data.get("properties", {}).get("title")
            sheet_map = {
                s["properties"]["title"]: s["properties"].get("sheetId", 0)
                for s in data.get("sheets", [])
            }
            sheet_names = list(sheet_map.keys())
        except Exception:
            return dataset

        if "IDENTITIES" in sheet_names:
            dataset["identities"] = await _fetch_sheet(client, token, spreadsheet_id, "IDENTITIES")
        if "LINKS" in sheet_names:
            dataset["links"] = await _fetch_sheet(client, token, spreadsheet_id, "LINKS")
        for name in sheet_names:
            if not name.startswith("SVC_"):
                continue
            rows = await _fetch_sheet(client, token, spreadsheet_id, name)
            dataset["services"].append({
                "sheetName": name, "sheetId": sheet_map.get(name, 0), "rows": rows,
            })
            field = SVC_FIELD_MAP.get(name)
            if field == "accountLinks":
                dataset["accountLinks"] = rows
            elif field == "profileLinks":
                dataset["profileLinks"] = rows
            elif field == "authMethods":
                dataset["authMethods"] = rows
            elif field == "accountAuthLinks":
                dataset["accountAuthLinks"] = rows
        for required in ("IDENTITIES", "LINKS"):
            if required not in sheet_names:
                dataset["schemaIssues"].append({
                    "level": "warning", "sheetName": required,
                    "message": f"Required sheet '{required}' is missing",
                })
    # Flat variants for the declarative UI tables (row[column.key] lookups).
    # The cell-shaped originals stay for the identity graph.
    dataset["identitiesFlat"] = [_flatten_row(r) for r in dataset["identities"]]
    dataset["linksFlat"] = [_flatten_row(r) for r in dataset["links"]]
    return dataset


async def _upsert_row(
    token: str, spreadsheet_id: str, sheet_name: str,
    row: list[dict], id_column: str,
) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        row_dict = {kv["key"]: kv["value"] for kv in row}
        row_id = row_dict.get(id_column, "")
        if not row_id:
            row_id = str(uuid.uuid4())
            row_dict[id_column] = row_id
        existing = await _fetch_sheet(client, token, spreadsheet_id, sheet_name)
        headers = SCHEMA_SHEETS.get(sheet_name, list(row_dict.keys()))
        row_index = -1
        for i, existing_row in enumerate(existing):
            if _get_cell_value(existing_row, id_column) == row_id:
                row_index = i
                break
        values_row = [str(row_dict.get(h, "")) for h in headers]
        if row_index >= 0:
            range_str = f"{sheet_name}!A{row_index + 2}:{chr(64 + len(headers))}{row_index + 2}"
        else:
            range_str = f"{sheet_name}!A:{chr(64 + len(headers))}"
        if row_index < 0:
            await client.post(
                f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_str}:append",
                params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                json={"values": [values_row]}, headers=_headers(token),
            )
        else:
            await client.put(
                f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_str}",
                params={"valueInputOption": "RAW"},
                json={"values": [values_row]}, headers=_headers(token),
            )
        return [{"key": k, "value": row_dict.get(k, "")} for k in headers]


async def _soft_delete_row(
    token: str, spreadsheet_id: str, sheet_name: str,
    row_id: str, id_column: str,
) -> bool:
    async with httpx.AsyncClient(timeout=30.0) as client:
        existing = await _fetch_sheet(client, token, spreadsheet_id, sheet_name)
        headers = SCHEMA_SHEETS.get(sheet_name, [])
        for i, row in enumerate(existing):
            if _get_cell_value(row, id_column) == row_id:
                values_row = [str(_get_cell_value(row, h)) for h in headers]
                status_idx = headers.index("status") if "status" in headers else -1
                is_primary_idx = headers.index("is_primary") if "is_primary" in headers else -1
                if status_idx >= 0:
                    values_row[status_idx] = "deleted"
                if is_primary_idx >= 0:
                    values_row[is_primary_idx] = "FALSE"
                range_str = f"{sheet_name}!A{i + 2}:{chr(64 + len(headers))}{i + 2}"
                await client.put(
                    f"{SHEETS_API_BASE}/{spreadsheet_id}/values/{range_str}",
                    params={"valueInputOption": "RAW"},
                    json={"values": [values_row]}, headers=_headers(token),
                )
                return True
    return False


# ── Public CRUD wrappers ──────────────────────────────────────────────────────


async def upsert_link(spreadsheet_id: str, sa_json: str, link: list[dict],
                      oauth_token: str | None = None) -> list[dict]:
    token = oauth_token or _get_sa_token(sa_json)
    return await _upsert_row(token, spreadsheet_id, "LINKS", link, "link_id")


async def soft_delete_link(spreadsheet_id: str, sa_json: str, link_id: str,
                           oauth_token: str | None = None) -> bool:
    token = oauth_token or _get_sa_token(sa_json)
    return await _soft_delete_row(token, spreadsheet_id, "LINKS", link_id, "link_id")


async def upsert_account_link(spreadsheet_id: str, sa_json: str, link: list[dict],
                              oauth_token: str | None = None) -> list[dict]:
    token = oauth_token or _get_sa_token(sa_json)
    return await _upsert_row(token, spreadsheet_id, "SVC_ACCOUNT_LINKS", link, "account_link_id")


async def soft_delete_account_link(spreadsheet_id: str, sa_json: str, link_id: str,
                                   oauth_token: str | None = None) -> bool:
    token = oauth_token or _get_sa_token(sa_json)
    return await _soft_delete_row(token, spreadsheet_id, "SVC_ACCOUNT_LINKS", link_id, "account_link_id")


async def upsert_profile_link(spreadsheet_id: str, sa_json: str, link: list[dict],
                              oauth_token: str | None = None) -> list[dict]:
    token = oauth_token or _get_sa_token(sa_json)
    return await _upsert_row(token, spreadsheet_id, "SVC_PROFILE_LINKS", link, "profile_link_id")


async def soft_delete_profile_link(spreadsheet_id: str, sa_json: str, link_id: str,
                                   oauth_token: str | None = None) -> bool:
    token = oauth_token or _get_sa_token(sa_json)
    return await _soft_delete_row(token, spreadsheet_id, "SVC_PROFILE_LINKS", link_id, "profile_link_id")


async def upsert_auth_method(spreadsheet_id: str, sa_json: str, method: list[dict],
                             oauth_token: str | None = None) -> list[dict]:
    token = oauth_token or _get_sa_token(sa_json)
    return await _upsert_row(token, spreadsheet_id, "SVC_AUTH_METHODS", method, "auth_method_id")


async def soft_delete_auth_method(spreadsheet_id: str, sa_json: str, method_id: str,
                                  oauth_token: str | None = None) -> bool:
    token = oauth_token or _get_sa_token(sa_json)
    return await _soft_delete_row(token, spreadsheet_id, "SVC_AUTH_METHODS", method_id, "auth_method_id")


async def upsert_account_auth_link(spreadsheet_id: str, sa_json: str, link: list[dict],
                                   oauth_token: str | None = None) -> list[dict]:
    token = oauth_token or _get_sa_token(sa_json)
    return await _upsert_row(token, spreadsheet_id, "SVC_ACCOUNT_AUTH_LINKS", link, "account_auth_link_id")


async def soft_delete_account_auth_link(spreadsheet_id: str, sa_json: str, link_id: str,
                                        oauth_token: str | None = None) -> bool:
    token = oauth_token or _get_sa_token(sa_json)
    return await _soft_delete_row(token, spreadsheet_id, "SVC_ACCOUNT_AUTH_LINKS", link_id, "account_auth_link_id")
