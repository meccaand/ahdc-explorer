"""Read-only access to the AHDC database (SQLite standing in for AHDC's PostgreSQL)."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "ahdc.db"
DICTIONARY_PATH = ROOT / "data" / "data_dictionary.yaml"

MAX_ROWS = 1000          # hard cap on rows fetched by any query
QUERY_TIMEOUT_S = 5.0    # abort queries that run longer than this


@lru_cache(maxsize=1)
def dictionary() -> dict[str, Any]:
    return yaml.safe_load(DICTIONARY_PATH.read_text(encoding="utf-8"))


def allowed_tables() -> set[str]:
    return set(dictionary()["tables"])


def connect() -> sqlite3.Connection:
    """Open the database read-only. Writes fail at the SQLite level as well as in the SQL guard."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"{DB_PATH} not found. Run: uv run python data/generate.py")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    return con


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    duration_ms: int


def run_query(sql: str, params: tuple = (), max_rows: int = MAX_ROWS) -> QueryResult:
    con = connect()
    deadline = time.monotonic() + QUERY_TIMEOUT_S

    def abort_if_slow() -> int:
        return 1 if time.monotonic() > deadline else 0

    con.set_progress_handler(abort_if_slow, 10_000)
    t0 = time.monotonic()
    try:
        cur = con.execute(sql, params)
        rows = cur.fetchmany(max_rows + 1)
        columns = [d[0] for d in cur.description or []]
    finally:
        con.close()
    truncated = len(rows) > max_rows
    return QueryResult(columns, rows[:max_rows], truncated, round((time.monotonic() - t0) * 1000))
