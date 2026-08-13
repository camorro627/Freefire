# ============================================================
# db.py — طبقة sqlite3 لحساباتك المسجلة
# ============================================================
import sqlite3
import threading

_conn = None
_lock = threading.Lock()


def _connect(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            player_id    TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'active',
            proxy        TEXT,
            last_checked TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    return conn


def init_db(path="freefire.db"):
    """تهيئة الاتصال (تُستدعى مرة واحدة عند الإقلاع)."""
    global _conn
    with _lock:
        _conn = _connect(path)


def _c():
    global _conn
    if _conn is None:
        init_db()
    return _conn


def add_account(player_id, access_token, proxy=None):
    """إدراج حساب جديد أو تحديث التوكن لحساب موجود."""
    with _lock:
        cur = _c().execute(
            """INSERT INTO accounts (player_id, access_token, proxy)
               VALUES (?, ?, ?)
               ON CONFLICT(player_id) DO UPDATE SET
                   access_token = excluded.access_token,
                   proxy = COALESCE(excluded.proxy, accounts.proxy)""",
            (player_id, access_token, proxy),
        )
        _c().commit()
        return cur.rowcount


def remove_account(player_id):
    with _lock:
        cur = _c().execute("DELETE FROM accounts WHERE player_id = ?", (player_id,))
        _c().commit()
        return cur.rowcount > 0


def get_account(player_id):
    with _lock:
        row = _c().execute(
            "SELECT * FROM accounts WHERE player_id = ?", (player_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_accounts(status=None):
    """جلب كل الحسابات (أو حسب الحالة) كقائمة قواميس."""
    with _lock:
        if status:
            rows = _c().execute(
                "SELECT * FROM accounts WHERE status = ?", (status,)
            ).fetchall()
        else:
            rows = _c().execute("SELECT * FROM accounts").fetchall()
        return [dict(r) for r in rows]


def set_status(player_id, status):
    with _lock:
        _c().execute(
            "UPDATE accounts SET status = ? WHERE player_id = ?",
            (status, player_id),
        )
        _c().commit()


def touch(player_id):
    """تحديث وقت آخر فحص ناجح."""
    with _lock:
        _c().execute(
            "UPDATE accounts SET last_checked = datetime('now') WHERE player_id = ?",
            (player_id,),
        )
        _c().commit()
