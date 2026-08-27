"""SQLite cache for the stitch-sheets plugin.

The plugin owns its own SQLite database at ``db_path`` (received in the
``plugin.init`` handshake).  Tables are created on ``_migrate_db``.
The cache stores sheet data snapshots so the plugin can serve reads
without re-fetching from Google Sheets on every call.
"""

# _generated_by: stitch_plugin_tools scaffold v3

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode for concurrent reads."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrate(db_path: str) -> None:
    """Create the cache tables if they do not exist (raw_sql migration)."""
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dataset_cache (
                spreadsheet_id TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                row_number INTEGER NOT NULL,
                cells_json TEXT NOT NULL,
                cached_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (spreadsheet_id, sheet_name, row_number)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_state (
                state TEXT PRIMARY KEY,
                code_verifier TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def cache_sheet(
    db_path: str, spreadsheet_id: str, sheet_name: str, rows: list[dict[str, Any]]
) -> None:
    """Replace the cached rows for a sheet."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "DELETE FROM dataset_cache WHERE spreadsheet_id = ? AND sheet_name = ?",
            (spreadsheet_id, sheet_name),
        )
        for row in rows:
            conn.execute(
                """
                INSERT INTO dataset_cache (spreadsheet_id, sheet_name, row_number, cells_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    spreadsheet_id,
                    sheet_name,
                    row.get("rowNumber", 0),
                    json.dumps(row.get("cells", []), ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def load_cached_sheet(
    db_path: str, spreadsheet_id: str, sheet_name: str
) -> list[dict[str, Any]]:
    """Return cached rows for a sheet (empty when no cache)."""
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT row_number, cells_json FROM dataset_cache
            WHERE spreadsheet_id = ? AND sheet_name = ?
            ORDER BY row_number
            """,
            (spreadsheet_id, sheet_name),
        ).fetchall()
        return [
            {
                "rowNumber": r["row_number"],
                "cells": json.loads(r["cells_json"]),
            }
            for r in rows
        ]
    finally:
        conn.close()
