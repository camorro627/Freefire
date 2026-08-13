# ============================================================
# proxy_manager.py — المدير الذكي للبروكسيات
# خيط daemon خلفي بحلقة asyncio خاصة: جلب ← تحقق ← استبدال تلقائي.
# الـ CLI لا ينتظر أبداً — كل العمليات الشبكية هنا في الخلفية.
# ============================================================
import asyncio
import logging
import threading
import time

import aiohttp

import proxy_scraper
from config import (
    AUTO_REFILL, MAX_PROXIES, MIN_PROXIES, PROXY_FAIL_THRESHOLD,
    PROXIES_FILE, PROXY_SOURCES, REFILL_INTERVAL, VALIDATION_CONCURRENCY,
    VALIDATION_TIMEOUT, VALIDATION_URL,
)
from proxy_pool import ProxyPool

log = logging.getLogger("proxy_manager")


class ProxyManager:
    def __init__(self, min_proxies=MIN_PROXIES, auto_refill=AUTO_REFILL):
        self.pool = ProxyPool(max_proxies=MAX_PROXIES,
                              fail_threshold=PROXY_FAIL_THRESHOLD)
        self.min_proxies = min_proxies
        self.auto_refill = auto_refill
        self._loop = None
        self._thread = None
        self._stop = threading.Event()

    # ---------------- دورة الحياة ----------------
    def start(self):
        """تشغيل الخيط الخلفي (يُستدعى مرة واحدة من master_cli)."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def schedule(self, coro):
        """جدولة coroutine على حلقة الخلفية — إرجاع فوري (غير محجوب)."""
        if self._loop:
            return asyncio.run_coroutine_threadsafe(coro, self._loop)
        return None

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # تحميل بروكسيات الملف اليدوي إن وُجد — كمصدر إضافي
        self._loop.create_task(self._load_manual_file())
        self._loop.run_until_complete(self._background())

    async def _background(self):
        if self.auto_refill:
            self._loop.create_task(self._refill_loop())
        while not self._stop.is_set():
            await asyncio.sleep(REFILL_INTERVAL)

    async def _load_manual_file(self):
        """قراءة proxies.txt (إن وُجد) وإضافته للمخزن — لا يمنع المصادر المجانية."""
        try:
            with open(PROXIES_FILE, "r", encoding="utf-8") as fh:
                urls = [ln.strip() for ln in fh
                        if ln.strip() and not ln.startswith("#")]
            if urls:
                added = self.pool.add(urls)
                log.info("بروكسيات يدوية من %s: %d", PROXIES_FILE, len(added))
        except FileNotFoundError:
            pass  # ملف اختياري

    async def _refill_loop(self):
        """حلقة إعادة التعبئة: إذا قلّ المخزون الحي عن الحد → جلب فوري."""
        while not self._stop.is_set():
            if self.auto_refill and self.pool.stats()["alive"] < self.min_proxies:
                log.info("المخزون الحي %d < الحد %d — جلب بروكسيات جديدة...",
                         self.pool.stats()["alive"], self.min_proxies)
                await self.refill()
            await asyncio.sleep(REFILL_INTERVAL)

    # ---------------- جلب + تحقق ----------------
    async def refill(self):
        """جلب من كل المصادر ← تحقق ← دمج الحيّ. يعيد عدد الناجحين."""
        raw = await proxy_scraper.fetch_sources(PROXY_SOURCES)
        if not raw:
            log.warning("لم تُجلب بروكسيات من أي مصدر (انترنت/مصادر؟)")
            return 0

        added = self.pool.add(raw)
        if not added:
            return 0

        ok = await self.validate(added)
        for url, latency in ok.items():
            self.pool.revive(url, latency)
        log.info("جلب %d جديد — %d حي بعد التحقق", len(added), len(ok))
        return len(ok)

    async def validate(self, urls):
        """تحقق متوازٍ: يعيد {url: latency} للناجح فقط."""
        sem = asyncio.Semaphore(VALIDATION_CONCURRENCY)
        async with aiohttp.ClientSession() as session:
            tasks = [self._check_one(session, u, sem) for u in urls]
            results = await asyncio.gather(*tasks)
        return {u: lat for u, lat in results if lat is not None}

    async def _check_one(self, session, url, sem):
        async with sem:
            start = time.monotonic()
            try:
                async with session.get(
                    VALIDATION_URL, proxy=url,
                    timeout=aiohttp.ClientTimeout(total=VALIDATION_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        return url, time.monotonic() - start
            except Exception:
                pass
            return url, None

    async def validate_all(self):
        """إعادة فحص كل الحيّ — إسقاط ما فشل (أمر يدوي)."""
        urls = self.pool.alive_urls()
        if not urls:
            return 0
        ok = await self.validate(urls)
        self.pool.revive_only(set(ok.keys()))
        log.info("تحقق شامل: %d/%d حي", len(ok), len(urls))
        return len(ok)

    # ---------------- واجهة للـ Worker (thread-safe) ----------------
    def get_for(self, player_id):
        return self.pool.get_for(player_id)

    def report_success(self, url, latency):
        self.pool.report_success(url, latency)

    def report_failure(self, url):
        self.pool.report_failure(url)

    # ---------------- المحلل ----------------
    def analyze(self):
        """تحليل سلوك البروكسيات الحية — متوسط زمن، معدل نجاح، مريبة."""
        snap = self.pool.snapshot()
        if not snap:
            return None
        latencies = [s[1] for s in snap if s[1] > 0]
        total_success = sum(s[2] for s in snap)
        total_fail = sum(s[3] for s in snap)
        total_ops = total_success + total_fail
        return {
            "alive": len(snap),
            "avg_latency": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "hit_rate": (total_success / total_ops) if total_ops else 0.0,
            "suspicious": sum(1 for s in snap if s[1] > 3.0 or s[4] >= PROXY_FAIL_THRESHOLD),
        }
