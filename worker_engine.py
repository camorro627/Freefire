# -*- coding: utf-8 -*-
"""
worker_engine.py — محرك العمال (asyncio + aiohttp)
==================================================
* check_player: سحب ملف لاعب (Nickname / Level / Likes)
* mass_status: فحص كل الحسابات بالتوازي مع تقرير تقدم
* معالجة أخطاء السيرفر:
    403 → banned (لا إعادة محاولة)
    429 → احترام Retry-After وإلا تراجع أسي + jitter
    5xx → تراجع أسي 1s → 2s → 4s
    شبكة/بروكسي → إبلاغ المدير → استبدال البروكسي تلقائياً
"""
import asyncio
import random
import time
from dataclasses import dataclass

import aiohttp

import config
import db


@dataclass
class CheckResult:
    player_id: str
    ok: bool
    nickname: str = ""
    level: int = 0
    likes: int = 0
    status: str = ""
    error: str = ""
    proxy: str = ""
    attempts: int = 0
    elapsed: float = 0.0


def _backoff_delay(attempt):
    base = min(config.RETRY_BASE_DELAY * (2 ** (attempt - 1)), config.RETRY_MAX_DELAY)
    jitter = random.uniform(0, base * config.RETRY_JITTER)
    return base + jitter


class WorkerEngine:
    def __init__(self, proxy_manager=None, concurrency=None):
        self.pm = proxy_manager
        self.concurrency = concurrency or config.MAX_CONCURRENCY

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

    async def check_one(self, player_id, token, proxy=None):
        started = time.monotonic()
        for attempt in range(1, config.CHECK_MAX_RETRIES + 1):
            if proxy is None:
                proxy = self._next_proxy(player_id)
            try:
                timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        config.PLAYER_ENDPOINT,
                        params={"player_id": player_id, "access_token": token},
                        proxy=f"http://{proxy}" if proxy else None,
                        timeout=timeout,
                        headers={"User-Agent": config.USER_AGENT},
                    ) as resp:
                        if resp.status == 403:
                            self._mark(player_id, "banned")
                            return CheckResult(
                                player_id, False, status="banned", error="403",
                                proxy=proxy or "", attempts=attempt,
                                elapsed=time.monotonic() - started,
                            )
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After", "")
                            wait = float(retry_after) if retry_after.isdigit() else _backoff_delay(attempt)
                            await asyncio.sleep(min(wait, 10))
                            continue
                        if resp.status >= 500:
                            await asyncio.sleep(_backoff_delay(attempt))
                            continue
                        if 400 <= resp.status < 500:
                            return CheckResult(
                                player_id, False, error=f"HTTP {resp.status}",
                                proxy=proxy or "", attempts=attempt,
                                elapsed=time.monotonic() - started,
                            )
                        data = await resp.json(content_type=None)
                        elapsed = time.monotonic() - started
                        if self.pm and proxy:
                            self.pm.report_success(proxy, elapsed)
                        nickname = data.get("nickname") or data.get("name") or ""
                        level = data.get("level") or 0
                        likes = data.get("likes") or 0
                        self._mark(
                            player_id, "active",
                            last_result=f"{nickname} Lv{level} Likes{likes}",
                        )
                        return CheckResult(
                            player_id, True, nickname=nickname, level=level,
                            likes=likes, status="active", proxy=proxy or "",
                            attempts=attempt, elapsed=elapsed,
                        )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._report_failure(proxy)
                proxy = None  # المحاولة القادمة ببروكسي مختلف
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

    @staticmethod
    def _mark(player_id, status, **extra):
        try:
            db.update_account(
                player_id, status=status,
                last_check=time.strftime("%Y-%m-%d %H:%M:%S"), **extra,
            )
        except Exception:
            pass

    async def check_many(self, accounts, progress_cb=None):
        sem = asyncio.Semaphore(self.concurrency)
        results = []

        async def _wrapped(acc):
            async with sem:
                r = await self.check_one(acc["player_id"], acc["access_token"])
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


def check_player_sync(player_id, pm=None):
    acc = db.get_account(player_id)
    if not acc:
        return None
    return _run(WorkerEngine(pm).check_one(acc["player_id"], acc["access_token"]))


def mass_status_sync(pm=None, concurrency=None, progress_cb=None):
    accounts = db.all_active()
    if not accounts:
        return [], 0
    results = _run(WorkerEngine(pm, concurrency).check_many(accounts, progress_cb))
    return results, len(accounts)
