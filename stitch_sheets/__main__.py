"""RPC entry point for the stitch-sheets service plugin.

Spawned by ``ServicePluginHost`` as ``python -m stitch_sheets``.
Implements the JSON-RPC 2.0 line protocol via ``RpcPluginServer``
(imported from ``autoreg.plugin.rpc`` when available, otherwise from
the vendored ``_vendor/rpc_server.py`` copy), plus reverse
RPC (``call_host``) for OAuth operations.

Protocol methods handled by ``RpcPluginServer``:
  - ``plugin.init``    → stores handshake params (db_path, data_dir).
  - ``plugin.call``    → dispatches to command handlers.
  - ``plugin.ping``    → returns ``"pong"``.
  - ``plugin.shutdown`` → returns ``None`` and exits.

Commands mirror ``google_sheets_*`` built-in commands with the
``google_sheets_`` prefix stripped:
  test_connection, fetch_dataset, init_schema,
  upsert_link, delete_link,
  upsert_account_link, delete_account_link,
  upsert_profile_link, delete_profile_link,
  upsert_auth_method, delete_auth_method,
  upsert_account_auth_link, delete_account_auth_link,
  start_oauth, exchange_oauth_code

The ``start_oauth`` and ``exchange_oauth_code`` handlers use
``server.call_host`` to invoke the host's ``engine.oauth.*`` reverse-RPC
methods (PKCE flow start + code exchange).
"""

# _generated_by: stitch_plugin_tools scaffold v3

from __future__ import annotations

import asyncio
from typing import Any

from . import service, storage

try:
    from autoreg.plugin.rpc import RpcPluginServer
except ImportError:
    from ._vendor.rpc_server import RpcPluginServer


# ── State received in plugin.init handshake ───────────────────────────────


class _Ctx:
    """Mutable container for plugin.init handshake state."""

    db_path: str = ""
    data_dir: str = ""


ctx = _Ctx()


def _handle_init(params: dict[str, Any]) -> dict[str, Any]:
    """Store handshake params and return them as the init result."""
    ctx.db_path = str(params.get("db_path", ""))
    ctx.data_dir = str(params.get("data_dir", ""))
    return {
        "plugin_id": params.get("plugin_id", ""),
        "db_path": ctx.db_path,
        "data_dir": ctx.data_dir,
        # Capability negotiation: this plugin uses server.call_host for
        # engine.oauth.* reverse-RPC, so it declares the reverse_rpc
        # capability to the host.
        "capabilities": ["reverse_rpc"],
    }


def _handle_migrate_db(params: dict[str, Any]) -> dict[str, Any]:
    if ctx.db_path:
        storage.migrate(ctx.db_path)
    return {
        "from_version": params.get("from_version", 0),
        "to_version": params.get("to_version", 1),
    }


def _resolve_sa_json(provided: str) -> str:
    """Resolve the service account JSON from params (no settings fallback)."""
    trimmed = (provided or "").strip()
    if trimmed and trimmed != "********":
        return trimmed
    return ""


def _handle_test_connection(params: dict[str, Any]) -> dict[str, Any]:
    spreadsheet_id = str(params.get("spreadsheetId", ""))
    sa_json = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.test_connection(spreadsheet_id, sa_json))


def _handle_fetch_dataset(params: dict[str, Any]) -> dict[str, Any]:
    spreadsheet_id = str(params.get("spreadsheetId", ""))
    sa_json = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    dataset = asyncio.run(service.fetch_dataset(spreadsheet_id, sa_json))
    # Cache identities and links for the declarative UI tables.
    if ctx.db_path:
        storage.cache_sheet(ctx.db_path, spreadsheet_id, "IDENTITIES", dataset.get("identities", []))
        storage.cache_sheet(ctx.db_path, spreadsheet_id, "LINKS", dataset.get("links", []))
    return dataset


def _handle_init_schema(params: dict[str, Any]) -> dict[str, Any]:
    spreadsheet_id = str(params.get("spreadsheetId", ""))
    sa_json = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.init_schema(spreadsheet_id, sa_json))


def _handle_upsert_link(params: dict[str, Any]) -> list[dict]:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.upsert_link(sid, sa, params.get("link", [])))


def _handle_delete_link(params: dict[str, Any]) -> bool:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.soft_delete_link(sid, sa, str(params.get("linkId", ""))))


def _handle_upsert_account_link(params: dict[str, Any]) -> list[dict]:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.upsert_account_link(sid, sa, params.get("link", [])))


def _handle_delete_account_link(params: dict[str, Any]) -> bool:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.soft_delete_account_link(sid, sa, str(params.get("accountLinkId", ""))))


def _handle_upsert_profile_link(params: dict[str, Any]) -> list[dict]:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.upsert_profile_link(sid, sa, params.get("link", [])))


def _handle_delete_profile_link(params: dict[str, Any]) -> bool:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.soft_delete_profile_link(sid, sa, str(params.get("profileLinkId", ""))))


def _handle_upsert_auth_method(params: dict[str, Any]) -> list[dict]:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.upsert_auth_method(sid, sa, params.get("method", [])))


def _handle_delete_auth_method(params: dict[str, Any]) -> bool:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.soft_delete_auth_method(sid, sa, str(params.get("authMethodId", ""))))


def _handle_upsert_account_auth_link(params: dict[str, Any]) -> list[dict]:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.upsert_account_auth_link(sid, sa, params.get("link", [])))


def _handle_delete_account_auth_link(params: dict[str, Any]) -> bool:
    sid = str(params.get("spreadsheetId", ""))
    sa = _resolve_sa_json(str(params.get("serviceAccountJson", "")))
    return asyncio.run(service.soft_delete_account_auth_link(sid, sa, str(params.get("accountAuthLinkId", ""))))


# ── Server entry point ────────────────────────────────────────────────────


def main() -> None:
    """Register handlers and serve the JSON-RPC loop.

    The ``start_oauth`` and ``exchange_oauth_code`` handlers are closures
    over ``server`` so they can invoke ``server.call_host`` for reverse
    RPC to the host's ``engine.oauth.*`` methods.
    """
    server = RpcPluginServer()
    server.set_init_handler(_handle_init)
    server.register("_migrate_db", _handle_migrate_db)
    server.register("test_connection", _handle_test_connection)
    server.register("fetch_dataset", _handle_fetch_dataset)
    server.register("init_schema", _handle_init_schema)
    server.register("upsert_link", _handle_upsert_link)
    server.register("delete_link", _handle_delete_link)
    server.register("upsert_account_link", _handle_upsert_account_link)
    server.register("delete_account_link", _handle_delete_account_link)
    server.register("upsert_profile_link", _handle_upsert_profile_link)
    server.register("delete_profile_link", _handle_delete_profile_link)
    server.register("upsert_auth_method", _handle_upsert_auth_method)
    server.register("delete_auth_method", _handle_delete_auth_method)
    server.register("upsert_account_auth_link", _handle_upsert_account_auth_link)
    server.register("delete_account_auth_link", _handle_delete_account_auth_link)

    def _handle_start_oauth(params: dict[str, Any]) -> dict[str, Any]:
        """Start a PKCE flow via the host's engine.oauth.start_pkce_flow."""
        return server.call_host("engine.oauth.start_pkce_flow", {
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": str(params.get("clientId", "")),
            "scope": "https://www.googleapis.com/auth/spreadsheets",
            "redirect_uri": "http://localhost:25584/api/oauth/callback",
        })

    def _handle_exchange_oauth_code(params: dict[str, Any]) -> dict[str, Any]:
        """Exchange an OAuth code for tokens via the host's engine.oauth.exchange_code."""
        return server.call_host("engine.oauth.exchange_code", {
            "code": str(params.get("code", "")),
            "code_verifier": str(params.get("code_verifier", "")),
            "token_url": "https://oauth2.googleapis.com/token",
            "client_id": str(params.get("clientId", "")),
            "redirect_uri": "http://localhost:25584/api/oauth/callback",
        })

    server.register("start_oauth", _handle_start_oauth)
    server.register("exchange_oauth_code", _handle_exchange_oauth_code)
    server.serve()


if __name__ == "__main__":
    main()
