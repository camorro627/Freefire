# ============================================================
# proxy_scraper.py — جلب قوائم البروكسيات من المصادر المجانية
# كل المصادر تُجلب بالتوازي، والفشل في مصدر لا يوقف الباقي
# ============================================================
import asyncio
import re

import aiohttp

from config import PROXY_SOURCES, REQUEST_TIMEOUT, USER_AGENT

# host:port — يلتقط حتى لو كان داخل نص أطول
IP_PORT = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")


async def fetch_sources(sources=None):
    """جلب كل المصادر بالتوازي وإرجاع set موحّد (بدون تكرار)."""
    sources = sources or PROXY_SOURCES
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        tasks = [_fetch_one(session, s) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    merged = set()
    for r in results:
        if isinstance(r, set):
            merged |= r
    return merged


async def _fetch_one(session, source):
    """مصدر واحد — أي خطأ يعيد مجموعة فارغة بدل الانهيار."""
    try:
        async with session.get(source["url"]) as resp:
            if resp.status != 200:
                return set()
            text = await resp.text()
        return parse_plain(text)
    except Exception:
        return set()


def parse_plain(text):
    """تحليل نص 'سطر لكل بروكسي' → set من http://host:port"""
    proxies = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = IP_PORT.search(line)
        if m:
            proxies.add(f"http://{m.group(1)}:{m.group(2)}")
    return proxies
