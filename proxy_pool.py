# ============================================================
# proxy_pool.py — مخزن البروكسيات مع نقاط السلوك (thread-safe)
# كل تعديل تحت threading.Lock لأنه يُستخدم من أكثر من حلقة أحداث
# ============================================================
import threading
import time
from dataclasses import dataclass


@dataclass
class ProxyEntry:
    url: str
    alive: bool = True
    latency: float = 0.0          # متوسط زمن الاستجابة بالثواني
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    last_used: float = 0.0
    added_at: float = 0.0

    @property
    def score(self):
        """نقاط السلوك: زمن أقل + نجاح أكثر − إخفاقات متتالية = أعلى"""
        if not self.alive:
            return -1
        latency_penalty = min(self.latency * 10, 60) if self.latency > 0 else 20
        fail_penalty = self.consecutive_fails * 25
        return max(0, 100 - latency_penalty - fail_penalty)


class ProxyPool:
    def __init__(self, max_proxies=300, fail_threshold=2):
        self._entries = {}            # url -> ProxyEntry
        self._max = max_proxies
        self._fail_threshold = fail_threshold
        self._lock = threading.Lock()
        self._cursor = 0

    # ---------------- كتابة ----------------
    def add(self, urls):
        """إضافة بروكسيات جديدة (تجاهل الموجود) — يعيد ما أُضيف فعلاً."""
        added = []
        with self._lock:
            now = time.time()
            for u in urls:
                if u not in self._entries:
                    self._entries[u] = ProxyEntry(url=u, added_at=now)
                    added.append(u)
            # تقليم للسقف: الأفضل نقاطاً يبقى
            if len(self._entries) > self._max:
                ranked = sorted(self._entries.values(), key=lambda e: e.score, reverse=True)
                keep = {e.url for e in ranked[:self._max]}
                self._entries = {u: e for u, e in self._entries.items() if u in keep}
        return added

    def report_success(self, url, latency):
        """نجاح طلب عبر هذا البروكسي — يصفّر الإخفاقات ويحدّث المتوسط."""
        with self._lock:
            e = self._entries.get(url)
            if e:
                e.success_count += 1
                e.consecutive_fails = 0
                e.latency = latency if e.latency <= 0 else (e.latency * 0.7 + latency * 0.3)

    def report_failure(self, url):
        """فشل اتصال عبر هذا البروكسي — يُسقطه بعد العتبة."""
        with self._lock:
            e = self._entries.get(url)
            if e:
                e.fail_count += 1
                e.consecutive_fails += 1
                if e.consecutive_fails >= self._fail_threshold:
                    e.alive = False

    def revive(self, url, latency):
        """إعادة تفعيل بعد نجاح التحقق."""
        with self._lock:
            e = self._entries.get(url)
            if e:
                e.alive = True
                e.consecutive_fails = 0
                e.latency = latency

    # ---------------- قراءة ----------------
    def get_for(self, player_id):
        """أفضل بروكسي حي — توزيع دائري على الخمس الأوائل نقاطاً."""
        with self._lock:
            alive = [e for e in self._entries.values() if e.alive]
            if not alive:
                return None
            alive.sort(key=lambda e: e.score, reverse=True)
            top = alive[:max(1, len(alive) // 5)]
            entry = top[self._cursor % len(top)]
            self._cursor += 1
            entry.last_used = time.time()
            return entry.url

    def alive_urls(self):
        with self._lock:
            return [e.url for e in self._entries.values() if e.alive]

    def snapshot(self):
        """لقطة للتحليل: (url, latency, نجاح, فشل, إخفاقات متتالية)"""
        with self._lock:
            return [(e.url, e.latency, e.success_count, e.fail_count,
                     e.consecutive_fails) for e in self._entries.values() if e.alive]

    def revive_only(self, ok_urls):
        """بعد جولة تحقق: أعد تفعيل الناجح وأسقط الباقي."""
        with self._lock:
            for u, e in self._entries.items():
                e.alive = u in ok_urls
                if e.alive:
                    e.consecutive_fails = 0

    def stats(self):
        with self._lock:
            alive = sum(1 for e in self._entries.values() if e.alive)
            return {"total": len(self._entries), "alive": alive,
                    "dead": len(self._entries) - alive}
