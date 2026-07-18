from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS dishes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    for_comida       INTEGER NOT NULL DEFAULT 0,
    for_cena         INTEGER NOT NULL DEFAULT 0,
    fresco           INTEGER NOT NULL DEFAULT 0,
    tupper           INTEGER NOT NULL DEFAULT 0,
    rapido           INTEGER NOT NULL DEFAULT 0,
    rendimiento      INTEGER NOT NULL DEFAULT 1,
    ingredients_json TEXT NOT NULL,
    steps_json       TEXT NOT NULL DEFAULT '[]',
    metodo           TEXT,
    source_url       TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (for_comida = 1 OR for_cena = 1)
);

CREATE TABLE IF NOT EXISTS weekly_plans (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start_date  TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL DEFAULT 'in_progress',
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_slots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    weekly_plan_id   INTEGER NOT NULL REFERENCES weekly_plans(id),
    slot_date        TEXT NOT NULL,
    meal_type        TEXT NOT NULL CHECK (meal_type IN ('comida','cena')),
    shift_type       TEXT,
    dish_id          INTEGER REFERENCES dishes(id),
    batch_group_id   INTEGER,
    from_leftover    INTEGER NOT NULL DEFAULT 0,
    resolved_at      TEXT,
    UNIQUE (weekly_plan_id, slot_date, meal_type)
);
CREATE INDEX IF NOT EXISTS idx_plan_slots_plan ON plan_slots(weekly_plan_id);

CREATE TABLE IF NOT EXISTS shift_cache (
    slot_date        TEXT PRIMARY KEY,
    shift_type       TEXT NOT NULL,
    fetched_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batch_leftovers (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    dish_id               INTEGER NOT NULL REFERENCES dishes(id),
    meal_type             TEXT NOT NULL CHECK (meal_type IN ('comida','cena')),
    remaining_days        INTEGER NOT NULL,
    source_weekly_plan_id INTEGER NOT NULL REFERENCES weekly_plans(id),
    consumed              INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


_connection: sqlite3.Connection | None = None


def get_connection() -> sqlite3.Connection:
    """Conexión sqlite3 única compartida por todos los handlers (bot de un solo usuario,
    sin actualizaciones concurrentes, así que no hace falta pool ni locking extra)."""
    global _connection
    if _connection is None:
        from .config import config

        _connection = connect(config.db_path)
    return _connection


@contextmanager
def cursor(conn: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
