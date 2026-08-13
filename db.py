# -*- coding: utf-8 -*-
"""
db.py — طبقة قاعدة البيانات (sqlite3)
=====================================
* جدول accounts: player_id, access_token, status, last_check ...
* استيراد/تصدير CSV + ترقيم صفحات
"""
import csv
import os
import sqlite3
import threading

import config

_lock = threading.RLock()


def _connect():
    return sqlite3.connect(config.DB_PATH, timeout=15)


def init_db():
    with _lock, _connect() as con:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {config.ACCOUNTS_TABLE} (
                player_id    TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'active',
                proxy        TEXT,
                last_check   TEXT,
                last_result  TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_status ON accounts(status)")


# ---------- عمليات فردية ----------
def add_account(player_id, access_token):
    with _lock, _connect() as con:
        cur = con.execute(
            f"INSERT OR IGNORE INTO {config.ACCOUNTS_TABLE} (player_id, access_token) VALUES (?, ?)",
            (player_id, access_token),
        )
        return cur.rowcount > 0


def remove_account(player_id):
    with _lock, _connect() as con:
        cur = con.execute(f"DELETE FROM {config.ACCOUNTS_TABLE} WHERE player_id=?", (player_id,))
        return cur.rowcount > 0


def get_account(player_id):
    with _lock, _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            f"SELECT * FROM {config.ACCOUNTS_TABLE} WHERE player_id=?", (player_id,)
        ).fetchone()
    return dict(row) if row else None


def update_account(player_id, **fields):
    """تحديث حقول محددة بأمان (status, proxy, last_check, last_result ...)."""
    allowed = {"status", "proxy", "last_check", "last_result", "access_token"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(player_id)
    with _lock, _connect() as con:
        con.execute(
            f"UPDATE {config.ACCOUNTS_TABLE} SET {', '.join(sets)} WHERE player_id=?",
            vals,
        )


# ---------- استيراد / تصدير CSV ----------
def import_csv(path):
    imported = 0
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pid = (row.get("player_id") or "").strip()
            tok = (row.get("access_token") or "").strip()
            if not pid or not tok:
                continue
            if add_account(pid, tok):
                imported += 1
    return imported


def export_csv(path=None):
    path = path or os.path.join(config.BASE_DIR, "accounts_backup.csv")
    with _lock, _connect() as con:
        rows = con.execute(
            f"SELECT player_id, access_token, status FROM {config.ACCOUNTS_TABLE}"
        ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["player_id", "access_token", "status"])
        writer.writerows(rows)
    return path, len(rows)


# ---------- عرض / إحصاء ----------
def list_accounts(page=1, per_page=20):
    page = max(1, page)
    offset = (page - 1) * per_page
    with _lock, _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM {config.ACCOUNTS_TABLE} ORDER BY rowid LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()
        total = con.execute(
            f"SELECT COUNT(*) FROM {config.ACCOUNTS_TABLE}"
        ).fetchone()[0]
    return [dict(r) for r in rows], total


def count_by_status():
    with _lock, _connect() as con:
        rows = con.execute(
            f"SELECT status, COUNT(*) n FROM {config.ACCOUNTS_TABLE} GROUP BY status"
        ).fetchall()
    return {s: n for s, n in rows}


def all_active():
    with _lock, _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT player_id, access_token FROM {config.ACCOUNTS_TABLE} WHERE status='active'"
        ).fetchall()
    return [dict(r) for r in rows]
