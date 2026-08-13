# -*- coding: utf-8 -*-
"""
registrar.py — التسجيل الذاتي للحسابات (Auto-Register)
======================================================
ميزة جديدة: الأداة تنشئ N حساباً بنفسها وتخزن بياناتها في freefire.db
ليتحكم بها السيد عبر master_cli كأي حساب مستورد.

البنية:
  * generate_credentials()   : توليد player_id + access_token
  * register_account()       : المفصل القابل للاستبدال (Mock افتراضياً)
  * RegistrationManager      : تنفيذ متوازٍ + تراجع أسي + بروكسي لكل حساب
  * جدول reg_queue           : تتبع المهام (pending -> done/failed)

النطاق: register_account تستدعي REGISTER_ENDPOINT من config.py —
الافتراضي "https://garena.mock" (محاكاة). استبدلها فقط بنقطة نهاية
تملكها أو فُوِّضت باختبارها.
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

import config
import db


# ---------- توليد بيانات الاعتماد ----------
def generate_player_id(digits=None):
    """معرّف رقمي عشوائي (الرقم الأول غير صفري) شبيه بمعرّفات الضيف."""
    digits = digits or config.CRED_ID_DIGITS
    first = random.choice(string.digits[1:])
    return first + "".join(random.choices(string.digits, k=digits - 1))


def generate_access_token(nbytes=None):
    """توكن جلسة عشوائي آمن إحصائياً."""
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


# ---------- المفصل القابل للاستبدال ----------
async def register_account(session, player_id, access_token, proxy=None, **ctx):
    """
    ينفّذ طلب التسجيل الفعلي.

    الوضع الافتراضي (Mock): نجاح 85% + 429/5xx/403 عشوائية لتجربة الدورة
    كاملة (قائمة مهام -> توازٍ -> تخزين -> تحكم) دون شبكة حقيقية.

    للتوصيل بنقطة نهاية حقيقية تملكها: فعّل الكود المعلَّق بالأسفل.
    """
    if config.REGISTER_ENDPOINT.endswith(".mock") or not config.REGISTER_ENDPOINT:
        await asyncio.sleep(random.uniform(0.3, 1.0))
        r = random.random()
        if r < 0.85:
            return {"ok": True, "player_id": player_id, "access_token": access_token}
        if r < 0.92:
            raise RegRateLimited("429 mock")
        if r < 0.97:
            raise RegNetworkError("5xx mock")
        raise RegBlocked("403 mock")

    # ----- التوصيل الحقيقي (فعّله عند امتلاك/تفويض نقطة النهاية) -----
    payload = {"player_id": player_id, "access_token": access_token}
    headers = {
        "Content-Type": "application/json",
        "User-Agent": ctx.get("ua", config.USER_AGENT),
    }
    timeout = aiohttp.ClientTimeout(total=config.REG_TIMEOUT)
    async with session.post(
        config.REGISTER_ENDPOINT, json=payload, headers=headers, timeout=timeout,
        proxy=f"http://{proxy}" if proxy else None,
    ) as resp:
        if resp.status == 403:
            raise RegBlocked(f"403 blocked for {player_id}")
        if resp.status == 429:
            raise RegRateLimited(f"429 {resp.headers.get('Retry-After', '?')}")
        if resp.status >= 500:
            raise RegNetworkError(f"{resp.status} server error")
        data = await resp.json(content_type=None)
        return {
            "ok": True,
            "player_id": player_id,
            "access_token": data.get("access_token", access_token),
        }


# ---------- طبقة قاعدة البيانات (reg_queue) ----------
def _connect():
    return sqlite3.connect(config.DB_PATH, timeout=15)


def init_schema():
    """ينشئ جدول قائمة مهام التسجيل إن لم يوجد."""
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS reg_queue (
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
        con.execute("CREATE INDEX IF NOT EXISTS idx_regq_status ON reg_queue(status)")


def enqueue(count):
    """يضيف count مهمة تسجيل جديدة ويعيد معرّفاتها."""
    ids = []
    with _connect() as con:
        for _ in range(count):
            creds = generate_credentials()
            cur = con.execute(
                "INSERT INTO reg_queue (player_id, access_token) VALUES (?, ?)",
                (creds["player_id"], creds["access_token"]),
            )
            ids.append(cur.lastrowid)
    return ids


def _get_job(job_id):
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM reg_queue WHERE id=?", (job_id,)
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
        con.execute(f"UPDATE reg_queue SET {', '.join(sets)} WHERE id=?", vals)


def store_account(player_id, access_token):
    """يحفظ الحساب في accounts — يتجاهل التكرار بهدوء."""
    try:
        return db.add_account(player_id, access_token)
    except Exception as e:
        print(f"[registrar] تعذّر حفظ {player_id}: {e}")
        return False


def reg_queue_summary():
    """تقرير مهام التسجيل حسب الحالة."""
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT status, COUNT(*) n FROM reg_queue GROUP BY status"
        ).fetchall()
    return [dict(r) for r in rows]


def failed_jobs():
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM reg_queue WHERE status='failed' ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


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
            token = job["access_token"] or generate_access_token()
            proxy = self._next_proxy(player_id)
            started = time.monotonic()
            self.on_event(f"[+] تسجيل {player_id} عبر {proxy or 'مباشر'}")

            for attempt in range(1, config.REG_MAX_RETRIES + 1):
                try:
                    async with aiohttp.ClientSession() as session:
                        res = await register_account(
                            session, player_id, token, proxy=proxy,
                            ua=config.USER_AGENT, scope="auto",
                        )
                    token = res.get("access_token", token)
                    _mark(job_id, "done", token=token, attempts=attempt, proxy=proxy)
                    store_account(player_id, token)
                    self.results.append(RegResult(
                        player_id, True, token=token, attempts=attempt,
                        proxy=proxy or "", duration=time.monotonic() - started,
                    ))
                    self.on_event(f"[OK] {player_id} جاهز (محاولة {attempt})")
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
                    self.on_event(f"[~] {player_id} فشل شبكة ({e}) — إعادة (محاولة {attempt})")
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
    """يعيد جدولة المهام الفاشلة (failed -> pending)."""
    ids = [j["id"] for j in failed_jobs()]
    with _connect() as con:
        for i in ids:
            con.execute(
                "UPDATE reg_queue SET status='pending', error=NULL, attempts=0 WHERE id=?",
                (i,),
            )
    return ids


def start_registration(count=5, proxy_manager=None, retry_failed=False):
    """يشغّل دورة التسجيل في خيط خلفي ويعيد كائن الخيط للتتبع."""
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
