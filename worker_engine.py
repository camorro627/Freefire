async def run(self, on_progress=None):
        """تنفيذ كل مهام الحسابات بالتوازي مع استدعاء on_progress(done, total)."""
        self.results = {}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            tasks = [self._worker(session, acc) for acc in self.accounts]
            done = 0
            total = len(tasks)
            # as_completed يعطي أول نتيجة جاهزة — تقدم مباشر بدل انتظار الكل
            for coro in asyncio.as_completed(tasks):
                await coro  # _worker يبتلع كل الأخطاء داخلياً
                done += 1
                if on_progress:
                    on_progress(done, total)
        return self.results
