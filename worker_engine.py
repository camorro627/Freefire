# ============================================================
# worker_engine.py — محرك Master-Worker (asyncio + aiohttp)
# ============================================================
import asyncio
import logging
import random

import aiohttp

import db
from config import (
    BASE_DELAY_MAX,
    BASE_DELAY_MIN,
    FF_PROFILE_ENDPOINT,
    MAX_CONCURRENCY,
    REQUEST_TIMEOUT,
    RETRY_ATTEMPTS,
    USER_AGENT,
)

log = logging.getLogger("worker")


class ForbiddenError(Exception):
    """HTTP 403 — الحساب محظور أو مفقود الصلاحية."""


class RateLimitedError(Exception):
    """HTTP 429 — تم الضغط على السيرفر."""


class WorkerEngine:
    """يشغّل مهمة لكل حساب كـ coroutine متوازٍ.

    accounts:   قائمة حسابات (قواميس من db.get_all_accounts())
    proxy_pool: كائن ProxyPool — بروكسي مستقل لكل حساب
    max_concurrency: حد التوازي الفعلي (سيمافور)
    delay:      (الحد الأدنى, الحد الأقصى) للفاصل العشوائي
    """

    def __init__(self, accounts, proxy_pool, max_concurrency=MAX_CONCURRENCY,
                 delay=(BASE_DELAY_MIN, BASE_DELAY_MAX)):
        self.accounts = accounts
        self.proxy_pool = proxy_pool
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.delay = delay
        self.results = {}

    async def run(self):
        """تنفيذ كل مهام الحسابات بالتوازي وإرجاع dict بالنتائج."""
        self.results = {}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            tasks = [self._worker(session, acc) for acc in self.accounts]
            await asyncio.gather(*tasks, return_exceptions=True)

        return self.results

    # ------------------------------------------------
    # المهمة المنفّذة لكل حساب (Worker)
    # ------------------------------------------------
    async def _worker(self, session, account):
        player_id = account["player_id"]
        proxy = self.proxy_pool.get_for(player_id)

        # السيمافور يحدّ عدد الطلبات المتزامنة الفعلية
        async with self.semaphore:
            # فاصل زمني عشوائي قبل كل طلب
            await asyncio.sleep(random.uniform(*self.delay))
            try:
                data = await self._fetch_profile(session, account, proxy)
                self.results[player_id] = {"ok": True, "data": data}
                db.set_status(player_id, "active")
                db.touch(player_id)
                log.info("OK %s عبر %s", player_id, proxy or "direct")
            except ForbiddenError:
                self.results[player_id] = {"ok": False, "error": "403 — محظور/مقيد"}
                db.set_status(player_id, "banned")
            except RateLimitedError:
                self.results[player_id] = {"ok": False, "error": "429 — ضغط على السيرفر"}
                db.set_status(player_id, "restricted")
            except Exception as exc:
                self.results[player_id] = {"ok": False, "error": str(exc)}
                db.set_status(player_id, "error")
                log.exception("فشل %s", player_id)

    # ------------------------------------------------
    # الطلب الفعلي مع معالجة أخطاء Garena (403/429/5xx)
    # ------------------------------------------------
    async def _fetch_profile(self, session, account, proxy):
        url = f"{FF_PROFILE_ENDPOINT}/{account['player_id']}"  # نقطة وهمية
        headers = {"Authorization": f"Bearer {account['access_token']}"}

        last_exc = None
        for attempt in range(RETRY_ATTEMPTS):
            try:
                async with session.get(url, headers=headers, proxy=proxy) as resp:
                    if resp.status == 200:
                        return await resp.json()

                    if resp.status == 403:
                        raise ForbiddenError()

                    if resp.status == 429:
                        retry_after = _retry_after(
                            resp.headers.get("Retry-After"), attempt
                        )
                        log.warning("429 لحساب %s — انتظار %.1f ثانية",
                                    account["player_id"], retry_after)
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status >= 500:
                        await asyncio.sleep(_backoff(attempt))  # خطأ سيرفر
                        continue

                    raise RuntimeError(f"استجابة غير متوقعة HTTP {resp.status}")

            except aiohttp.ClientError as exc:
                last_exc = exc  # انقطاع شبكة / بروكسي معطّل
                log.warning("خطأ شبكة (محاولة %d): %s", attempt + 1, exc)
                await asyncio.sleep(_backoff(attempt))

        raise last_exc or RuntimeError("فشلت كل محاولات الطلب")


def _backoff(attempt, base=1.0):
    """تراجع أسي + اهتزاز عشوائي (Exponential Backoff with Jitter)."""
    return base * (2 ** attempt) + random.uniform(0, 0.5)


def _retry_after(header_value, attempt):
    """احترام ترويسة Retry-After إن وُجدت، وإلا تراجع أسي."""
    try:
        return max(int(header_value), 1)
    except (TypeError, ValueError):
        return _backoff(attempt)
