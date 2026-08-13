# -*- coding: utf-8 -*-
"""
proxy_pool.py — مخزن البروكسيات بنقاط سلوك thread-safe
=====================================================
كل بروكسي له سجل سلوك: زمن استجابة، معدل نجاح، عدّاد "مريب".
get_for() يوزّع الأفضل نقاطاً دائرياً بين الحسابات.
"""
import random
import threading
import time
from dataclasses import dataclass, field

import config


@dataclass
class ProxyInfo:
    address: str
    score: float = 10.0
    alive: bool = True
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    suspicious: int = 0
    total_time: float = 0.0
    checks: int = 0
    last_seen: float = field(default_factory=time.time)
    last_used: float = 0.0

    @property
    def avg_time(self):
        return self.total_time / self.checks if self.checks else 0.0


class ProxyPool:
    def __init__(self):
        self._proxies = {}
        self._lock = threading.RLock()
        self._rr_index = 0

    # ---------- إدارة المخزون ----------
    def add(self, address, score=None):
        address = address.strip()
        if not address or ":" not in address:
            return False
        with self._lock:
            if address in self._proxies:
                return False
            self._proxies[address] = ProxyInfo(address, score=score or 10.0)
            return True

    def alive_count(self):
        with self._lock:
            return sum(1 for p in self._proxies.values() if p.alive)

    def total(self):
        with self._lock:
            return len(self._proxies)

    def snapshot(self):
        """نسخة آمنة من كل البروكسيات مع إحصاءاتها."""
        with self._lock:
            return [ProxyInfo(**p.__dict__) for p in self._proxies.values()]

    def best(self, n=1):
        """أفضل n بروكسي حي حسب النقاط (ثم الأقل زمناً)."""
        with self._lock:
            alive = [p for p in self._proxies.values() if p.alive]
            ranked = sorted(alive, key=lambda p: (-p.score, p.avg_time))
            return [p.address for p in ranked[:n]]

    def get_for(self, key=None):
        """يوزّع دائرياً على أفضل البروكسيات (بروكسي واحد لكل حساب)."""
        with self._lock:
            alive = [p for p in self._proxies.values() if p.alive]
            if not alive:
                return None
            ranked = sorted(alive, key=lambda p: (-p.score, p.avg_time))
            top = ranked[: max(1, min(len(ranked), 50))]
            p = top[self._rr_index % len(top)]
            self._rr_index += 1
            p.last_used = time.time()
            return p.address

    # ---------- سلوك ----------
    def report_success(self, address, elapsed):
        with self._lock:
            p = self._proxies.get(address)
            if not p:
                return
            p.successes += 1
            p.consecutive_failures = 0
            p.checks += 1
            p.total_time += elapsed
            p.last_seen = time.time()
            p.score = min(p.score + 0.5, 20.0)
            if elapsed > config.PROXY_SUSPICIOUS_TIME:
                p.suspicious += 1
                p.score = max(p.score - 0.5, 0.0)

    def report_failure(self, address):
        with self._lock:
            p = self._proxies.get(address)
            if not p:
                return
            p.failures += 1
            p.consecutive_failures += 1
            p.score = max(p.score - 2.0, 0.0)
            if p.consecutive_failures >= config.PROXY_FAIL_THRESHOLD:
                p.alive = False
                p.score = 0.0

    def mark_dead(self, address):
        with self._lock:
            p = self._proxies.get(address)
            if p:
                p.alive = False
                p.score = 0.0

    def purge(self):
        """يسقط الميت وقديم السن، ويقص المخزون إلى السقف."""
        now = time.time()
        with self._lock:
            for addr, p in list(self._proxies.items()):
                if not p.alive:
                    del self._proxies[addr]
                    continue
                if now - p.last_seen > config.PROXY_MAX_AGE and p.checks > 0:
                    del self._proxies[addr]
            excess = len(self._proxies) - config.MAX_PROXIES
            if excess > 0:
                for addr in list(self._proxies)[:excess]:
                    del self._proxies[addr]

    def stats(self):
        """تحليل السلوك: متوسط زمن، معدل نجاح، عدّاد مريب."""
        snap = self.snapshot()
        alive = [p for p in snap if p.alive]
        if not alive:
            return {
                "total": len(snap),
                "alive": 0,
                "avg_time": 0.0,
                "success_rate": 0.0,
                "suspicious": 0,
            }
        total_attempts = sum(p.successes + p.failures for p in alive) or 1
        return {
            "total": len(snap),
            "alive": len(alive),
            "avg_time": round(sum(p.avg_time for p in alive) / len(alive), 3),
            "success_rate": round(
                sum(p.successes for p in alive) / total_attempts, 3
            ),
            "suspicious": sum(p.suspicious for p in alive),
        }
