# ============================================================
# proxy_pool.py — مجمّع بروكسيات يُقرأ من proxies.txt
# الصيغة: سطر لكل بروكسي → http://user:pass@host:port أو host:port
# ============================================================
class ProxyPool:
    def __init__(self, proxies=None):
        self._proxies = list(proxies or [])
        self._cursor = 0

    @classmethod
    def from_file(cls, path="proxies.txt"):
        proxies = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        proxies.append(_normalize(line))
        except FileNotFoundError:
            pass  # العمل بدون بروكسيات مسموح (اتصال مباشر)
        return cls(proxies)

    def next(self):
        """بروكسي تالٍ بالتناوب الدائري (Round-Robin)."""
        if not self._proxies:
            return None
        proxy = self._proxies[self._cursor % len(self._proxies)]
        self._cursor += 1
        return proxy

    def get_for(self, player_id):
        """ربط ثابت: نفس الحساب يحصل على نفس البروكسي طوال الجلسة —
        يمنع تبديل البروكسي في منتصف عملية ويمنع ترابط الحسابات على أيب واحد."""
        if not self._proxies:
            return None
        return self._proxies[abs(hash(player_id)) % len(self._proxies)]

    def __len__(self):
        return len(self._proxies)


def _normalize(line):
    if "://" not in line:
        return f"http://{line}"
    return line
