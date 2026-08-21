"""Telegram subscriber registration and broadcast helpers for the secondary bot."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from app.config import Config
from app.models import get_db


def init_subscribers() -> None:
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_subscribers (
            chat_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Preserve the existing configured recipient during migration.
    if Config.TELEGRAM_USER_ID_2:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("""
            INSERT INTO telegram_subscribers
              (chat_id, is_active, created_at, updated_at)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET is_active = 1, updated_at = excluded.updated_at
        """, (str(Config.TELEGRAM_USER_ID_2), now, now))
    conn.commit()
    conn.close()


def register_subscriber(chat_id: str, user: dict | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    user = user or {}
    conn = get_db()
    conn.execute("""
        INSERT INTO telegram_subscribers
          (chat_id, username, first_name, last_name, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
          username = excluded.username,
          first_name = excluded.first_name,
          last_name = excluded.last_name,
          is_active = 1,
          updated_at = excluded.updated_at
    """, (str(chat_id), user.get('username'), user.get('first_name'),
          user.get('last_name'), now, now))
    conn.commit()
    conn.close()


def unregister_subscriber(chat_id: str) -> None:
    conn = get_db()
    conn.execute("UPDATE telegram_subscribers SET is_active = 0, updated_at = ? WHERE chat_id = ?",
                 (datetime.now(timezone.utc).isoformat(), str(chat_id)))
    conn.commit()
    conn.close()


def get_subscriber_chat_ids() -> list[str]:
    conn = get_db()
    rows = conn.execute("SELECT chat_id FROM telegram_subscribers WHERE is_active = 1 ORDER BY chat_id").fetchall()
    conn.close()
    return [str(row[0]) for row in rows]


init_subscribers()
