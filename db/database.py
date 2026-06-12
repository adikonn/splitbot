"""Подключение к SQLite (aiosqlite) и схема базы данных."""
from __future__ import annotations

from typing import Any, Iterable

import aiosqlite

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL UNIQUE,
    username    TEXT,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member'      -- member | admin
                CHECK (role IN ('member', 'admin')),
    status      TEXT NOT NULL DEFAULT 'pending'     -- pending | active | removed
                CHECK (status IN ('pending', 'active', 'removed')),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS periods (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    year          INTEGER NOT NULL,
    month         INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    status        TEXT NOT NULL DEFAULT 'open'       -- open | confirming | closed
                  CHECK (status IN ('open', 'confirming', 'closed')),
    opened_at     TEXT NOT NULL,
    confirming_at TEXT,
    closed_at     TEXT,
    UNIQUE (year, month)
);

CREATE TABLE IF NOT EXISTS expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id   INTEGER NOT NULL REFERENCES periods (id),
    payer_id    INTEGER NOT NULL REFERENCES users (id),
    type        TEXT NOT NULL CHECK (type IN ('common', 'daily')),
    date        TEXT NOT NULL,                      -- ISO YYYY-MM-DD
    amount      INTEGER NOT NULL CHECK (amount > 0),-- копейки
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT,
    edited_by   INTEGER REFERENCES users (id),
    deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_expenses_period ON expenses (period_id, deleted);

CREATE TABLE IF NOT EXISTS absences (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES periods (id),
    user_id   INTEGER NOT NULL REFERENCES users (id),
    date      TEXT NOT NULL,                        -- ISO YYYY-MM-DD
    UNIQUE (period_id, user_id, date)
);

CREATE TABLE IF NOT EXISTS confirmations (
    period_id    INTEGER NOT NULL REFERENCES periods (id),
    user_id      INTEGER NOT NULL REFERENCES users (id),
    confirmed_at TEXT NOT NULL,
    PRIMARY KEY (period_id, user_id)
);

CREATE TABLE IF NOT EXISTS settlements (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id INTEGER NOT NULL REFERENCES periods (id),
    from_user INTEGER NOT NULL REFERENCES users (id),
    to_user   INTEGER NOT NULL REFERENCES users (id),
    amount    INTEGER NOT NULL CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS scheduler_log (
    job_key     TEXT PRIMARY KEY,
    executed_at TEXT NOT NULL
);
"""


class Database:
    """Тонкая обёртка над aiosqlite: один коннект на процесс."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchall()
