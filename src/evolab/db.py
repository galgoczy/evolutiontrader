"""SQLite állapot-adatbázis (data/lab.db) létrehozása és kapcsolat."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from evolab import __version__
from evolab.config import Config


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(cfg: Config) -> Path:
    """Létrehozza (vagy frissíti) az adatbázist a db/schema.sql alapján. Idempotens."""
    schema = (cfg.root / "db" / "schema.sql").read_text(encoding="utf-8")
    with connect(cfg.db_path) as conn:
        conn.executescript(schema)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_created_by', ?) "
            "ON CONFLICT(key) DO NOTHING",
            (__version__,),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('judge_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(cfg.judge_version),),
        )
    return cfg.db_path


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [r["name"] for r in rows]
