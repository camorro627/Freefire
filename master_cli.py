# ============================================================
# master_cli.py — Master CLI بواجهة cmd تفاعلية
# ============================================================
import asyncio
import cmd

import db
from config import DB_PATH, PROXIES_FILE
from proxy_pool import ProxyPool
from worker_engine import WorkerEngine

BANNER = r"""
  __ _ _ __ ___  __ _ _   _| | __ _ _ __   __| | ___ _ __
 / _` | '__/ _ \/ _` | | | | |/ _` | '_ \ / _` |/ _ \ '__|
| (_| | | |  __/ (_| | |_| | | (_| | | | | (_| |  __/ |
 \__, |_|  \___|\__,_|\__,_|_|\__,_|_| |_|\__,_|\___|_|
 |___/   Free Fire Master Control — قالب تعليمي
"""


class MasterCLI(cmd.Cmd):
    intro = BANNER + "\nاكتب help لعرض الأوامر المتاحة.\n"
    prompt = "FF-Master> "

    def __init__(self):
        super().__init__()
        db.init_db(DB_PATH)
        self.proxy_pool = ProxyPool.from_file(PROXIES_FILE)
        print(f"[i] تم تحميل {len(self.proxy_pool)} بروكسي من {PROXIES_FILE}")

    # ---------------- إدارة قاعدة البيانات ----------------
    def do_add_account(self, arg):
        """add_account <Player_ID> <Access_Token> — تسجيل حساب جديد"""
        parts = arg.split()
        if len(parts) != 2:
            print("الاستخدام: add_account <Player_ID> <Access_Token>")
            return
        player_id, token = parts
        db.add_account(player_id, token)
        print(f"[+] تم تسجيل الحساب {player_id}")

    def do_remove_account(self, arg):
        """remove_account <Player_ID> — حذف حساب من القاعدة"""
        player_id = arg.strip()
        if db.remove_account(player_id):
            print(f"[-] تم حذف {player_id}")
        else:
            print(f"[!] الحساب {player_id} غير موجود")

    def do_list_accounts(self, arg):
        """list_accounts — عرض كل الحسابات المسجلة وحالاتها"""
        accounts = db.get_all_accounts()
        if not accounts:
            print("[!] لا توجد حسابات مسجلة. استخدم add_account أولاً.")
            return
        print(f"{'Player_ID':<15} {'Status':<12} {'Proxy':<25} Last_Checked")
        print("-" * 70)
        for acc in accounts:
            print(f"{acc['player_id']:<15} {acc['status']:<12} "
                  f"{(acc['proxy'] or '-'):<25} {acc['last_checked'] or '-'}")

    # ---------------- فحص لاعب واحد ----------------
    def do_check_player(self, arg):
        """check_player <Player_ID> — جلب الملف (Level/Likes/Nickname) لحساب مسجّل"""
        player_id = arg.strip()
        account = db.get_account(player_id)
        if not account:
            print(f"[!] {player_id} غير مسجّل محلياً — الأداة تعمل على الحسابات المسجلة فقط.")
            return

        engine = WorkerEngine([account], self.proxy_pool)
        results = asyncio.run(engine.run())

        entry = results.get(player_id, {})
        if entry.get("ok"):
            data = entry["data"]
            print(f"\n[+] {player_id}:")
            print(f"    Nickname : {data.get('nickname', '-')}")
            print(f"    Level    : {data.get('level', '-')}")
            print(f"    Likes    : {data.get('likes', '-')}")
        else:
            print(f"[!] فشل الفحص: {entry.get('error')}")

    # ---------------- عملية جماعية متوازية ----------------
    def do_mass_status(self, arg):
        """mass_status — فحص كل الحسابات المسجلة بالتوازي (Master-Worker)"""
        accounts = db.get_all_accounts()
        if not accounts:
            print("[!] لا توجد حسابات مسجلة. استخدم add_account أولاً.")
            return

        print(f"[i] جارٍ فحص {len(accounts)} حساب بالتوازي...")
        engine = WorkerEngine(accounts, self.proxy_pool)
        results = asyncio.run(engine.run())

        ok = sum(1 for r in results.values() if r["ok"])
        print(f"\n=== النتائج: {ok}/{len(accounts)} ناجح ===")
        for pid, r in sorted(results.items()):
            mark = "[+]" if r["ok"] else "[-]"
            if r["ok"]:
                d = r["data"]
                print(f"{mark} {pid:<15} {d.get('nickname', '-'):<20} "
                      f"Level={d.get('level', '-')} Likes={d.get('likes', '-')}")
            else:
                print(f"{mark} {pid:<15} {r['error']}")

    # ---------------- البروكسيات ----------------
    def do_reload_proxies(self, arg):
        """reload_proxies — إعادة قراءة ملف proxies.txt"""
        self.proxy_pool = ProxyPool.from_file(PROXIES_FILE)
        print(f"[i] تم إعادة التحميل: {len(self.proxy_pool)} بروكسي")

    def do_show_proxies(self, arg):
        """show_proxies — عرض البروكسيات المحمّلة"""
        if len(self.proxy_pool) == 0:
            print("[!] لا توجد بروكسيات (يعمل الاتصال المباشر).")
            return
        for i, p in enumerate(self.proxy_pool._proxies, 1):
            print(f"{i:>3}. {p}")

    # ---------------- خروج ----------------
    def do_exit(self, arg):
        """exit — إنهاء الجلسة"""
        print("وداعاً.")
        return True

    def do_EOF(self, arg):
        return self.do_exit(arg)


if __name__ == "__main__":
    MasterCLI().cmdloop()
