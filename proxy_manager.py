# -*- coding: utf-8 -*-
"""
proxy_manager.py — مدير البروكسيات (خيط خلفي)
=============================================
دورة ذكية: جلب → تحقق → دمج → تقييم، مع محلل سلوك.
كل العمليات في خيط خلفي حتى لا تنتظر أوامر CLI.
"""
import asyncio
import threading
import time

import aiohttp

import config
from proxy_pool import ProxyPool
from proxy_scraper import fetch_sync


class ProxyManager:
    def __init__(self, pool=None):
        self.pool = pool or ProxyPool()
        self.auto_refill = True
        self._stop = threading.Event()
        self._thread = None
        self.log = []

    # ---------- تشغيل الخيط ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="proxy-manager"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _log(self, msg):
        self.log.append((time.strftime("%H:%M:%S"), msg))
        self.log = self.log[-200:]

    def _loop(self):
        self._log("بدأ مدير البروكسيات")
        while not self._stop.is_set():
            try:
                if self.auto_refill and self.pool.alive_count() < config.MIN_PROXIES:
                    self._log("المخزون منخفض — جلب فوري من المصادر")
                    self._fetch_and_validate()
                self.pool.purge()
                self._log(f"المخزون الحي: {self.pool.alive_count()}/{self.pool.total()}")
            except Exception as e:
                self._log(f"خطأ في الدورة: {e}")
            self._stop.wait(config.PROXY_FETCH_INTERVAL)

    # ---------- جلب + تحقق ----------
    def fetch(self):
        """جلب فوري من المصادر (متزامن داخل الخيط)."""
        results = fetch_sync()
        total_new = 0
        for url, proxies in results.items():
            added = sum(1 for p in proxies if self.pool.add(p))
            total_new += added
            self._log(f"المصدر {url} → {len(proxies)} سطر، أُضيف {added} جديد")
        return total_new

    def validate(self):
        """يفحص كل البروكسيات الحية بالتوازي."""
        self._log("تحقق من البروكسيات...")
        try:
            asyncio.run(self._validate_async())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._validate_async())
            finally:
                loop.close()

    async def _validate_async(self):
        sem = asyncio.Semaphore(config.PROXY_VALIDATE_CONCURRENCY)
        addresses = [p.address for p in self.pool.snapshot() if p.alive]
        async with aiohttp.ClientSession() as session:
            tasks = [self._check_one(session, addr, sem) for addr in addresses]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_one(self, session, address, sem):
        async with sem:
            timeout = aiohttp.ClientTimeout(total=config.PROXY_VALIDATE_TIMEOUT)
            started = time.monotonic()
            try:
                async with session.get(
                    config.PROXY_VALIDATE_URL,
                    proxy=f"http://{address}",
                    timeout=timeout,
                    headers={"User-Agent": config.USER_AGENT},
                ) as resp:
                    if resp.status in (200, 204):
                        self.pool.report_success(address, time.monotonic() - started)
                    else:
                        self.pool.report_failure(address)
            except Exception:
                self.pool.report_failure(address)

    def _fetch_and_validate(self):
        self.fetch()
        self.validate()
        self.pool.purge()

    # ---------- واجهة الاستهلاك ----------
    def get_for(self, key=None):
        return self.pool.get_for(key)

    def report_failure(self, address):
        self.pool.report_failure(address)
        # إعادة تعبئة فورية عند نضوب المخزون
        if self.auto_refill and self.pool.alive_count() < config.MIN_PROXIES:
            threading.Thread(target=self._fetch_and_validate, daemon=True).start()

    def status(self):
        return self.pool.stats()
