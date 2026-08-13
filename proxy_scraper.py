# -*- coding: utf-8 -*-
"""
proxy_scraper.py — جلب قوائم البروكسيات من المصادر المجانية
============================================================
يجلب عدة مصادر بالتوازي (asyncio + aiohttp) ويعيد قائمة
بالعناوين الصالحة ip:port بعد فلترة الأسطر.
"""
import asyncio
import re

import aiohttp

import config

# سطر صالح: ip:port أو proto://ip:port (نقبل http/socks4/socks5 ثم نحوّل)
_PROXY_RE = re.compile(
    r"^(?:[a-z0-9]+://)?([0-9]{1,3}(?:\.[0-9]{1,3}){3}):(\d{2,5})$", re.I
)


def _parse_lines(text):
    found = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _PROXY_RE.match(line)
        if m:
            ip, port = m.group(1), m.group(2)
            if all(0 <= int(o) <= 255 for o in ip.split(".")):
                found.add(f"{ip}:{port}")
    return found


async def _fetch_one(session, url, sem):
    async with sem:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with session.get(
                url, timeout=timeout, headers={"User-Agent": config.USER_AGENT}
            ) as resp:
                if resp.status != 200:
                    return url, []
                text = await resp.text(errors="ignore")
                return url, _parse_lines(text)
        except Exception:
            return url, []


async def fetch_all():
    """يجلب كل المصادر بالتوازي ويرجع dict {source: set(proxies)}."""
    sem = asyncio.Semaphore(min(5, len(config.PROXY_SOURCES)))
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_one(session, u, sem) for u in config.PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for r in results:
        if isinstance(r, Exception):
            continue
        url, proxies = r
        out[url] = proxies
    return out


def fetch_sync():
    """غلاف متزامن للاستخدام من خيط خلفي."""
    try:
        return asyncio.run(fetch_all())
    except RuntimeError:
        # في حال وجود loop قيد التشغيل — ننشئ واحداً جديداً في هذا الخيط
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(fetch_all())
        finally:
            loop.close()
