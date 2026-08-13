# -*- coding: utf-8 -*-
"""
worker_engine.py — محرك العمال (asyncio + aiohttp)
==================================================
* check_one : سحب ملف لاعب عبر ff_api (أي UID — Level / Rank / Clan / Likes)
* like_many : إرسال لايك من كل حساب نشط للهدف (لايك واحد لكل حساب لكل هدف)
* معالجة الأخطاء:
    429 → احترام Retry-After وإلا تراجع أسي + jitter
    5xx → تراجع أسي 1s → 2s → 4s
    4xx دائم (مفتاح/منطقة/توكن) → فشل فوري بلا إعادة محاولة
    شبكة/بروكسي → إبلاغ المدير → استبدال البروكسي تلقائياً
"""
import asyncio
import random
import time
from dataclasses import dataclass

import aiohttp

import config
import db
import ff_api


@dataclass
class CheckResult:
    player_id: str
    ok: bool
    nickname: str = ""
    level: int = 0
    likes: int = 0
    rank: int = 0
    clan: str = ""
    region: str = ""
    source: str = ""
    status: str = ""
    error: str = ""
    proxy: str = ""
    attempts: int = 0
    elapsed: float = 0.0


@dataclass
class LikeOutcome:
    player_id: str
    ok: bool
    detail: str = ""
    proxy: str = ""
    elapsed: float = 0.0


def _backoff_delay(attempt):
    base = min(config.RETRY_BASE_DELAY * (2 ** (attempt - 1)), config.RETRY_MAX_DELAY)
    jitter = random.uniform(0, base * config.RETRY_JITTER)
    return base + jitter


class WorkerEngine:
    def __init__(self, proxy_manager=None, concurrency=None):
        self.pm = proxy_manager
        self.concurrency = concurrency or config.MAX_CONCURRENCY
        # Python 3.10+ يربط asyncio.Lock بكائن الحلقة عند أول استخدام فقط
        self._pace_lock = asyncio.Lock()
        self._last_like = 0.0

    # ---------- بروكسيات ----------
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
    def _mark(player_id, status, **extra):
        try:
            db.update_account(
                player_id, status=status,
                last_check=time.strftime("%Y-%m-%d %H:%M:%S"), **extra,
            )
        except Exception:
            pass

    # ---------- فحص لاعب ----------
    async def check_one(self, player_id, token=None, region=None, proxy=None):
        started = time.monotonic()
        region = region or config.DEFAULT_REGION
        for attempt in range(1, config.CHECK_MAX_RETRIES + 1):
            if proxy is None:
                proxy = self._next_proxy(player_id)
            try:
                async with aiohttp.ClientSession() as session:
                    info = await ff_api.fetch_player(
                        session, player_id, region=region, token=token)
                if info and info.get("source"):
                    elapsed = time.monotonic() - started
                    if self.pm and proxy:
                        self.pm.report_success(proxy, elapsed)
                    likes = info.get("likes")
                    r = CheckResult(
                        player_id, True,
                        nickname=info.get("nickname") or "",
                        level=info.get("level") or 0,
                        likes=likes if likes is not None else 0,
                        rank=info.get("rank") or 0,
                        clan=info.get("clan") or "",
                        region=region,
                        source=info.get("source") or "",
                        status="active", proxy=proxy or "",
                        attempts=attempt, elapsed=elapsed,
                    )
                    if token:
                        self._mark(
                            player_id, "active",
                            last_result=f"{r.nickname} Lv{r.level} R{r.rank}",
                        )
                    return r
                # خطأ دائم (4xx: مفتاح/منطقة خاطئة) — لا فائدة من إعادة المحاولة
                if info and "HTTP 4" in (info.get("error") or ""):
                    return CheckResult(
                        player_id, False, error=info.get("error", ""),
                        proxy=proxy or "", attempts=attempt,
                        elapsed=time.monotonic() - started,
                    )
                if attempt < config.CHECK_MAX_RETRIES:
                    await asyncio.sleep(_backoff_delay(attempt))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._report_failure(proxy)
                proxy = None
                if attempt < config.CHECK_MAX_RETRIES:
                    await asyncio.sleep(_backoff_delay(attempt))
                else:
                    return CheckResult(
                        player_id, False, error=str(e), proxy="",
                        attempts=attempt, elapsed=time.monotonic() - started,
                    )
        return CheckResult(
            player_id, False, error="max retries", proxy=proxy or "",
            attempts=config.CHECK_MAX_RETRIES,
            elapsed=time.monotonic() - started,
        )

    async def check_many(self, accounts, progress_cb=None):
        sem = asyncio.Semaphore(self.concurrency)
        results = []

        async def _wrapped(acc):
            async with sem:
                r = await self.check_one(
                    acc["player_id"], token=acc.get("access_token"))
                results.append(r)
                if progress_cb:
                    progress_cb(len(results), len(accounts), r)

        await asyncio.gather(*(_wrapped(a) for a in accounts), return_exceptions=True)
        return results

    # ---------- إرسال لايكات ----------
    async def _pace(self):
        """يوزّع الطلبات بمرور الزمن لاحترام LIKE_RPS وتجنّب 429."""
        now = time.monotonic()
        async with self._pace_lock:
            wait = self._last_like + (1.0 / max(config.LIKE_RPS, 0.1)) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_like = time.monotonic()

    async def like_one(self, account, target_uid, region, provider):
        started = time.monotonic()
        proxy = self._next_proxy(account["player_id"])
        for attempt in range(1, config.CHECK_MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    ok, detail = await ff_api.send_like(
                        session, target_uid, region,
                        token=account.get("access_token"),
                        provider=provider,
                        sender_uid=account["player_id"],
                    )
                if ok:
                    if self.pm and proxy:
                        self.pm.report_success(proxy, time.monotonic() - started)
                    self._mark(account["player_id"], "active",
                               last_result=f"like→{target_uid} ok")
                    return LikeOutcome(
                        account["player_id"], True, detail=detail,
                        proxy=proxy or "", elapsed=time.monotonic() - started,
                    )
                # توكن مرفوض = الحساب غير صالح — علّمه وانتقل
                if ("token مرفوض" in detail or "401" in detail
                        or "403" in detail):
                    self._mark(account["player_id"], "invalid",
                               last_result=f"token مرفوض ({target_uid})")
                    return LikeOutcome(
                        account["player_id"], False, detail=detail,
                        proxy=proxy or "", elapsed=time.monotonic() - started,
                    )
                return LikeOutcome(
                    account["player_id"], False, detail=detail,
                    proxy=proxy or "", elapsed=time.monotonic() - started,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._report_failure(proxy)
                proxy = None
                if attempt < config.CHECK_MAX_RETRIES:
                    await asyncio.sleep(_backoff_delay(attempt))
                else:
                    return LikeOutcome(
                        account["player_id"], False, detail=str(e),
                        elapsed=time.monotonic() - started,
                    )
        return LikeOutcome(
            account["player_id"], False, detail="max retries",
            elapsed=time.monotonic() - started,
        )

    async def like_many(self, accounts, target_uid, region, provider,
                        progress_cb=None):
        sem = asyncio.Semaphore(min(self.concurrency, 10))
        results = []

        async def _wrapped(acc):
            async with sem:
                await self._pace()
                r = await self.like_one(acc, target_uid, region, provider)
                results.append(r)
                if progress_cb:
                    progress_cb(len(results), len(accounts), r)

        await asyncio.gather(*(_wrapped(a) for a in accounts), return_exceptions=True)
        return results


# ---------- غلافات متزامنة للـ CLI ----------
def _run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def check_player_sync(player_id, region=None, pm=None):
    """فحص أي لاعب بالمعرّف — لا يتطلب تسجيله في قاعدة البيانات.
    يمرّر token تلقائياً إن كان الحساب مسجّلاً (لجلب اللايكات عبر
    الواجهة الداخلية عند ضبط FF_INTERNAL_PROFILE_ENDPOINT)."""
    token = None
    acc = db.get_account(player_id)
    if acc:
        token = acc.get("access_token")
    return _run(WorkerEngine(pm).check_one(player_id, token=token, region=region))


def mass_status_sync(pm=None, concurrency=None, progress_cb=None):
    accounts = db.all_active()
    if not accounts:
        return [], 0
    engine = WorkerEngine(pm, concurrency)

    async def _main():
        sem = asyncio.Semaphore(engine.concurrency)
        results = []

        async def _w(acc):
            async with sem:
                r = await engine.check_one(acc["player_id"],
                                           token=acc["access_token"])
                results.append(r)
                if progress_cb:
                    progress_cb(len(results), len(accounts), r)

        await asyncio.gather(*(_w(a) for a in accounts), return_exceptions=True)
        return results

    results = _run(_main())
    return results, len(accounts)


def mass_like_sync(target_uid, region=None, max_accounts=None, pm=None,
                   provider=None, progress_cb=None):
    """يرسل لايكاً من كل حساب نشط للهدف. يرجع (results, total)."""
    accounts = db.all_active()
    if max_accounts:
        accounts = accounts[:max_accounts]
    if not accounts:
        return [], 0
    engine = WorkerEngine(pm)
    results = _run(engine.like_many(
        accounts, target_uid, region or config.DEFAULT_REGION,
        provider or config.LIKE_PROVIDER, progress_cb,
    ))
    return results, len(accounts)
