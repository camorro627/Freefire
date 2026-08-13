# -*- coding: utf-8 -*-
"""
registrar.py — إنشاء واستقبال الحسابات الحقيقية
===============================================
ما الذي تغيّر عن النسخة الوهمية؟
* register_account: لم تعد تولّد بيانات عشوائية. تطلب حساب ضيف حقيقي
  من خدمة المزرعة (FF_FARM_ENDPOINT) — مثل freefire-jwt-generator-api
  أو أي واجهة تعيد {"uid": ..., "access_token": ...}.
* RegListener: خادم HTTP يستقبل حسابات الضيوف الحقيقية القادمة من
  frida_guest.js على المحاكي (POST /ingest) ويخزّنها في freefire.db.
* قيود واقعية مدمجة:
  - حساب الضيف = لايك واحد فقط لكل هدف (قيد Garena).
  - Garena يراقب الأنماط الجماعية (نفس الجهاز/البروكسي) —
    وزّع المزرعة على محاكيات وبروكسيات مختلفة.
"""
import asyncio
import random
import secrets
import sqlite3
import string
import threading
import time
from dataclasses import dataclass

import aiohttp
from aiohttp import web

import config
import db


# ---------- توليد معرّف المهمة (وليس بيانات الحساب!) ----------
def generate_player_id(digits=None):
    """معرّف مؤقت لسطر الطابور فقط — الحساب الحقيقي يأتي من المزرعة."""
    digits = digits or config.CRED_ID_DIGITS
    first = random.choice(string.digits[1:])
    return first + "".join(random.choices(string.digits, k=digits - 1))


def generate_access_token(nbytes=None):
    return secrets.token_hex(nbytes or config.CRED_TOKEN_BYTES)


def generate_credentials():
    return {"player_id": generate_player_id(), "access_token": generate_access_token()}


# ---------- استثناءات التصنيف ----------
class RegBlocked(Exception):
    """403 / حظر نهائي — لا إعادة محاولة."""


class RegRateLimited(Exception):
    """429 / ضغط — انتظر ثم أعد المحاولة."""


class RegNetworkError(Exception):
    """خطأ شبكة/بروكسي/5xx — قابل لإعادة المحاولة."""


# ---------- طلب حساب حقيقي من المزرعة ----------
async def register_account(session, player_id, region=None, proxy=None, ua=None):
    """يطلب حساب ضيف حقيقياً من مزرعة الحسابات.

    FF_FARM_ENDPOINT: عنوان خدمة المزرعة التي تُنشئ الحسابات داخل اللعبة
    (أو خادم freefire-jwt-generator-api) وتُرجع
    {"uid": ..., "access_token": ...}.
    عند عدم ضبطه تُرفع RegNetworkError وتُحال المهمة للمستمع.
    """
    if not config.FF_FARM_ENDPOINT:
        raise RegNetworkError(
            "FF_FARM_ENDPOINT غير مضبوط — استخدم reg_listen لاستقبال "
            "الحسابات من frida_guest.js على المحاكي"
        )
    timeout = aiohttp.ClientTimeout(total=config.REG_TIMEOUT)
    async with session.post(
        config.FF_FARM_ENDPOINT,
        json={"uid": str(player_id), "region": region or config.DEFAULT_REGION},
        headers={"User-Agent": ua or config.USER_AGENT},
        proxy=f"http://{proxy}" if proxy else None,
        timeout=timeout,
    ) as resp:
        if resp.status == 429:
            raise RegRateLimited("HTTP 429")
        if resp.status in (401, 403):
            raise RegBlocked(f"HTTP {resp.status}")
        if resp.status >= 500:
            raise RegNetworkError(f"HTTP {resp.status}")
        data = await resp.json(content_type=None)
        uid = data.get("uid") or data.get("player_id")
        token = data.get("access_token") or data.get("jwt")
        if not uid or not token:
            raise RegNetworkError("استجابة مزرعة ناقصة (uid/access_token)")
        return {"player_id": str(uid), "access_token": str(token)}


# ---------- قاعدة بيانات طابور التسجيل ----------
def _connect():
    return sqlite3.connect(config.DB_PATH, timeout=15)


def init_schema():
    with _connect() as con:
        con.execute(f"""
            CREATE TABLE IF NOT EXISTS {config.REG_QUEUE_TABLE} (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id    TEXT NOT NULL,
                access_token TEXT,
                status       TEXT NOT NULL DEFAULT 'pending',
                attempts     INTEGER NOT NULL DEFAULT 0,
                proxy        TEXT,
                error        TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at  TEXT
            )
        """)


def enqueue(count):
    ids = []
    with _connect() as con:
        for _ in range(max(1, int(count))):
            cur = con.execute(
                f"INSERT INTO {config.REG_QUEUE_TABLE} (player_id) VALUES (?)",
                (generate_player_id(),),
            )
            ids.append(cur.lastrowid)
    return ids


def _get_job(job_id):
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            f"SELECT * FROM {config.REG_QUEUE_TABLE} WHERE id=?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def _mark(job_id, status, token=None, attempts=None, proxy=None, error=None):
    with _connect() as con:
        sets, vals = ["status=?"], [status]
        if token is not None:
            sets.append("access_token=?")
            vals.append(token)
        if attempts is not None:
            sets.append("attempts=?")
            vals.append(attempts)
        if proxy is not None:
            sets.append("proxy=?")
            vals.append(proxy)
        if error is not None:
            sets.append("error=?")
            vals.append(error)
        if status in ("done", "failed"):
            sets.append("finished_at=datetime('now')")
        vals.append(job_id)
        con.execute(
            f"UPDATE {config.REG_QUEUE_TABLE} SET {', '.join(sets)} WHERE id=?",
            vals)


def _mark_by_player(player_id, status, token=None, error=None):
    """يُحدّث المهمة المعلقة المطابقة لـ player_id (يستخدمه المستمع)."""
    with _connect() as con:
        sets, vals = ["status=?"], [status]
        if token is not None:
            sets.append("access_token=?")
            vals.append(token)
        if error is not None:
            sets.append("error=?")
            vals.append(error)
        if status in ("done", "failed"):
            sets.append("finished_at=datetime('now')")
        vals.append(player_id)
        con.execute(
            f"UPDATE {config.REG_QUEUE_TABLE} SET {', '.join(sets)} WHERE player_id=?",
            vals)


def store_account(player_id, access_token):
    """يحفظ الحساب في accounts — يتجاهل التكرار بهدوء."""
    try:
        return db.add_account(player_id, access_token)
    except Exception as e:
        print(f"[registrar] تعذّر حفظ {player_id}: {e}")
        return False


def reg_queue_summary():
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT status, COUNT(*) n FROM {config.REG_QUEUE_TABLE} GROUP BY status"
        ).fetchall()
    return [dict(r) for r in rows]


def failed_jobs():
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"SELECT * FROM {config.REG_QUEUE_TABLE} WHERE status='failed' ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- المستمع: استقبال حسابات الضيوف من المحاكي ----------
async def _ingest_handler(request):
    """POST /ingest — يصل من frida_guest.js: {player_id, access_token, region}."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)
    pid = str(data.get("player_id") or data.get("uid") or "").strip()
    tok = str(data.get("access_token") or data.get("jwt") or "").strip()
    region = str(data.get("region") or config.DEFAULT_REGION).strip()
    if not pid.isdigit() or not (5 <= len(pid) <= 15) or not tok:
        return web.json_response({"ok": False, "error": "invalid fields"}, status=400)
    stored = store_account(pid, tok)
    _mark_by_player(pid, "done", token=tok)
    print(f"[listener] حساب ضيف جديد: {pid} ({region}) — مخزّن: {stored}")
    return web.json_response({"ok": True, "player_id": pid, "stored": stored})


async def _health_handler(request):
    return web.json_response({"ok": True, "name": "ff-control-ingest"})


def start_listener(port=None):
    """يشغّل المستمع في خيط خلفي (لا يجمّد CLI)."""
    port = port or config.REG_LISTEN_PORT
    app = web.Application()
    app.router.add_post(config.REG_INGEST_PATH, _ingest_handler)
    app.router.add_get("/health", _health_handler)

    def _runner():
        web.run_app(app, host=config.REG_LISTEN_HOST, port=port, print=None)

    t = threading.Thread(target=_runner, daemon=True, name="reg-listener")
    t.start()
    return t


# ---------- مدير التسجيل ----------
@dataclass
class RegResult:
    player_id: str
    ok: bool
    token: str = ""
    error: str = ""
    attempts: int = 0
    proxy: str = ""
    duration: float = 0.0


class RegistrationManager:
    """ينفّذ مهام reg_queue بالتوازي مع حد REG_CONCURRENCY."""

    def __init__(self, proxy_manager=None, on_event=None):
        self.pm = proxy_manager
        self.on_event = on_event or (lambda m: None)
        self.results = []
        self._sem = asyncio.Semaphore(config.REG_CONCURRENCY)

    def _next_proxy(self, key):
        if not self.pm:
            return None
        try:
            return self.pm.get_for(key)
        except Exception:
            return None

    def _report_failure(self, proxy):
        if self.pm and proxy:
            try:
                self.pm.report_failure(proxy)
            except Exception:
                pass

    @staticmethod
    def _backoff(attempt):
        base = min(2 ** (attempt - 1), 8)
        return base + random.uniform(config.REG_DELAY_MIN, config.REG_DELAY_MAX)

    async def _work(self, job_id):
        async with self._sem:
            job = _get_job(job_id)
            if not job:
                return
            player_id = job["player_id"]
            proxy = self._next_proxy(player_id)
            started = time.monotonic()
            self.on_event(f"[+] طلب حساب {player_id} عبر {proxy or 'مباشر'}")

            for attempt in range(1, config.REG_MAX_RETRIES + 1):
                try:
                    async with aiohttp.ClientSession() as session:
                        creds = await register_account(
                            session, player_id, region=config.DEFAULT_REGION,
                            proxy=proxy, ua=config.USER_AGENT,
                        )
                    _mark(job_id, "done", token=creds["access_token"],
                          attempts=attempt, proxy=proxy)
                    store_account(creds["player_id"], creds["access_token"])
                    self.results.append(RegResult(
                        creds["player_id"], True, token=creds["access_token"],
                        attempts=attempt, proxy=proxy or "",
                        duration=time.monotonic() - started,
                    ))
                    self.on_event(f"[OK] {creds['player_id']} جاهز (محاولة {attempt})")
                    return

                except RegBlocked as e:
                    _mark(job_id, "failed", attempts=attempt, proxy=proxy, error=str(e))
                    self.results.append(RegResult(
                        player_id, False, error=str(e), attempts=attempt,
                        proxy=proxy or "",
                    ))
                    self.on_event(f"[X] {player_id} محظور: {e}")
                    return

                except RegRateLimited as e:
                    self.on_event(f"[429] {player_id} تراجع (محاولة {attempt})")
                    if attempt < config.REG_MAX_RETRIES:
                        await asyncio.sleep(self._backoff(attempt))

                except Exception as e:
                    self._report_failure(proxy)
                    self.on_event(f"[~] {player_id} فشل ({e}) — إعادة (محاولة {attempt})")
                    if attempt < config.REG_MAX_RETRIES:
                        await asyncio.sleep(self._backoff(attempt))

            _mark(job_id, "failed", attempts=config.REG_MAX_RETRIES, proxy=proxy,
                  error="max retries exceeded")
            self.results.append(RegResult(
                player_id, False, error="max retries",
                attempts=config.REG_MAX_RETRIES, proxy=proxy or "",
            ))

    async def run(self, job_ids):
        self.results = []
        await asyncio.gather(*(self._work(i) for i in job_ids), return_exceptions=True)
        return self.results


# ---------- مشغّل الخلفية (لا يجمّد CLI) ----------
def _requeue_failed():
    ids = [j["id"] for j in failed_jobs()]
    with _connect() as con:
        for i in ids:
            con.execute(
                f"UPDATE {config.REG_QUEUE_TABLE} SET status='pending', "
                "error=NULL, attempts=0 WHERE id=?",
                (i,),
            )
    return ids


def start_registration(count=5, proxy_manager=None, retry_failed=False):
    """يشغّل دورة طلب الحسابات من المزرعة في خيط خلفي."""
    init_schema()
    job_ids = _requeue_failed() if retry_failed else enqueue(count)

    def _runner():
        async def _main():
            mgr = RegistrationManager(proxy_manager=proxy_manager, on_event=print)
            results = await mgr.run(job_ids)
            ok = sum(1 for r in results if r.ok)
            print(f"\n[registrar] انتهت الدورة: {ok}/{len(results)} نجحت.")

        try:
            asyncio.run(_main())
        except Exception as e:
            print(f"[registrar] خطأ عام في الدورة: {e}")

    t = threading.Thread(target=_runner, daemon=True, name="registrar")
    t.start()
    return t
