# ============================================================
# db.py — إضافات camorro: استيراد/تصدير جماعي + ترقيم صفحات
# ============================================================
def import_accounts_from_csv(path):
    """استيراد جماعي: player_id,access_token[,status] — سطر لكل حساب.
    الموجود مسبقاً يُحدَّث توكنه وحالته (UPSERT)."""
    import csv
    added = 0
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader, None)  # تخطي الترويسة
        with _lock:
            for row in reader:
                if len(row) < 2:
                    continue
                pid, tok = row[0].strip(), row[1].strip()
                if not pid or not tok:
                    continue
                status = row[2].strip() if len(row) > 2 and row[2].strip() else "active"
                _c().execute(
                    """INSERT INTO accounts (player_id, access_token, status)
                       VALUES (?, ?, ?)
                       ON CONFLICT(player_id) DO UPDATE SET
                           access_token = excluded.access_token,
                           status = excluded.status""",
                    (pid, tok, status),
                )
                added += 1
            _c().commit()
    return added


def export_accounts_to_csv(path):
    """نسخة احتياطية كاملة (player_id, access_token, status)."""
    import csv
    with _lock:
        rows = _c().execute(
            "SELECT player_id, access_token, status FROM accounts"
        ).fetchall()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["player_id", "access_token", "status"])
        writer.writerows(rows)
    return len(rows)


def count_accounts(status=None):
    with _lock:
        if status:
            row = _c().execute(
                "SELECT COUNT(*) FROM accounts WHERE status = ?", (status,)
            ).fetchone()
        else:
            row = _c().execute("SELECT COUNT(*) FROM accounts").fetchone()
        return row[0]


def get_accounts_page(page=1, size=20):
    with _lock:
        rows = _c().execute(
            "SELECT * FROM accounts ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (size, (page - 1) * size),
        ).fetchall()
        return [dict(r) for r in rows]
