# ============================================================
# master_cli.py — camorro Master CLI بواجهة cmd تفاعلية
# ============================================================
import asyncio
import cmd
import logging

import db
from config import DB_PATH, MIN_PROXIES
from proxy_manager import ProxyManager
from worker_engine import WorkerEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BANNER = r"""
   ___                                   ___
  / __|__ _ _ __ ___  _ _  ___  _ _ _ _ / _ \ _  _
 | (__/ _` | '_ \ '_ \| '_|/ _ \| '_| '_| (_) | || |
  \___\__,_| .__/ .__/|_|  \___/|_| |_|  \___/ \_,_|
           |_|  |_|       camorro — Master Control
"""

PAGE_SIZE = 20


class MasterCLI(cmd.Cmd):
    intro = BANNER + "\nاكتب help لعرض الأوامر المتاحة.\n"
    prompt = "camorro> "

    def __init__(self):
        super().__init__()
        db.init_db(DB_PATH)
        self.proxy_manager = ProxyManager(min_proxies=MIN_PROXIES)
        self.proxy_manager.start()
        print(f"[i] camorro جاهزة — {db.count_accounts()} حساب مسجّل"
              f" | بروكسي مانجر يعمل (الحد الأدنى {MIN_PROXIES} حي)")

    # ---------------- إدارة فردية ----------------
    def do_add_account(self, arg):
        """add_account <Player_ID> <Access_Token> — تسجيل حساب"""
        parts = arg.split()
        if len(parts) != 2:
            print("الاستخدام: add_account <Player_ID> <Access_Token>")
            return
        db.add_account(parts[0], parts[1])
        print(f"[+] تم تسجيل {parts[0]} — الإجمالي {db.count_accounts()}")

    def do_remove_account(self, arg):
        """remove_account <Player_ID> — حذف حساب"""
        if db.remove_account(arg.strip()):
            print(f"[-] تم حذف {arg.strip()}")
        else:
            print(f"[!] الحساب {arg.strip()} غير موجود")

    # ---------------- استيراد/تصدير جماعي ----------------
    def do_import_accounts(self, arg):
        """import_accounts <file.csv> — استيراد جماعي (player_id,access_token[,status])"""
        path = arg.strip()
        if not path:
            print("الاستخدام: import_accounts <file.csv>")
            return
        try:
            n = db.import_accounts_from_csv(path)
            print(f"[+] استُورد {n} حساب من {path} — الإجمالي {db.count_accounts()}")
        except FileNotFoundError:
            print(f"[!] الملف {path} غير موجود")
        except Exception as exc:
            print(f"[!] فشل الاستيراد: {exc}")

    def do_export_accounts(self, arg):
        """export_accounts [file.csv] — نسخة احتياطية لكل الحسابات"""
        path = arg.strip() or "accounts_backup.csv"
        n = db.export_accounts_to_csv(path)
        print(f"[+] صُدّر {n} حساب إلى {path}")

    # ---------------- عرض مع ترقيم صفحات ----------------
    def do_list_accounts(self, arg):
        """list_accounts [page] — عرض الحسابات مع ترقيم الصفحات"""
        try:
            page = max(1, int(arg.strip() or 1))
        except ValueError:
            page = 1
        total = db.count_accounts()
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        accounts = db.get_accounts_page(page, PAGE_SIZE)
        if not accounts:
            print("[!] لا توجد حسابات — استخدم add_account أو import_accounts")
            return
        print(f"=== الصفحة {page}/{pages} — الإجمالي {total} ===")
        print(f"{'Player_ID':<15} {'Status':<12} Last_Checked")
        print("-" * 45)
        for acc in accounts:
            print(f"{acc['player_id']:<15} {acc['status']:<12} {acc['last_checked'] or '-'}")
        if page < pages:
            print(f"[i] list_accounts {page + 1} للصفحة التالية")

    def do_count_accounts(self, arg):
        """count_accounts — عدد الحسابات حسب الحالة"""
        for st in ("active", "banned", "restricted", "error"):
            print(f"  {st:<12}: {db.count_accounts(st)}")
        print(f"  {'total':<12}: {db.count_accounts()}")

    # ---------------- فحص لاعب واحد ----------------
    def do_check_player(self, arg):
        """check_player <Player_ID> — جلب الملف (Level/Likes/Nickname) لحساب مسجّل"""
        account = db.get_account(arg.strip())
        if not account:
            print(f"[!] {arg.strip()} غير مسجّل محلياً")
            return
        results = asyncio.run(
            WorkerEngine([account], self.proxy_manager).run()
        )
        entry = results.get(account["player_id"], {})
        if entry.get("ok"):
            d = entry["data"]
            print(f"\n[+] {account['player_id']}:\n"
                  f"    Nickname : {d.get('nickname', '-')}\n"
                  f"    Level    : {d.get('level', '-')}\n"
                  f"    Likes    : {d.get('likes', '-')}")
        else:
            print(f"[!] فشل الفحص: {entry.get('error')}")

    # ---------------- تحكم جماعي (القلب) ----------------
    def do_mass_status(self, arg):
        """mass_status — فحص كل الحسابات بالتوازي مع تقرير تقدم"""
        accounts = db.get_all_accounts()
        if not accounts:
            print("[!] لا توجد حسابات — استخدم add_account أو import_accounts")
            return
        print(f"[i] جارٍ فحص {len(accounts)} حساب بالتوازي...")
        engine = WorkerEngine(accounts, self.proxy_manager)

        def _progress(done, total):
            if done % 10 == 0 or done == total:
                print(f"    تقدم: {done}/{total}")

        results = asyncio.run(engine.run(on_progress=_progress))

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

    # ---------------- البروكسيات الذكية ----------------
    def do_proxy_status(self, arg):
        """proxy_status — حالة المخزون + تحليل السلوك"""
        s = self.proxy_manager.pool.stats()
        a = self.proxy_manager.analyze()
        print(f"[i] إجمالي: {s['total']} | حي: {s['alive']} | ميت: {s['dead']} "
              f"(الحد: {self.proxy_manager.min_proxies})")
        if a:
            print(f"    متوسط زمن الاستجابة : {a['avg_latency'] * 1000:.0f} ms\n"
                  f"    معدل النجاح          : {a['hit_rate'] * 100:.1f}%\n"
                  f"    بروكسيات مريبة       : {a['suspicious']}")

    def do_fetch_proxies(self, arg):
        """fetch_proxies — جلب بروكسيات من المصادر المجانية (في الخلفية)"""
        if self.proxy_manager.schedule(self.proxy_manager.refill()):
            print("[i] جُدول في الخلفية — واصل العمل فوراً.")

    def do_validate_proxies(self, arg):
        """validate_proxies — إعادة فحص كل الحيّ (في الخلفية)"""
        if self.proxy_manager.schedule(self.proxy_manager.validate_all()):
            print("[i] جارٍ التحقق في الخلفية...")

    def do_auto_refill(self, arg):
        """auto_refill on|off — تشغيل/إيقاف إعادة التعبئة التلقائية"""
        arg = arg.strip().lower()
        if arg in ("on", "off"):
            self.proxy_manager.auto_refill = arg == "on"
            print(f"[i] إعادة التعبئة التلقائية: {'ON' if arg == 'on' else 'OFF'}")
        else:
            print("الاستخدام: auto_refill on|off")

    def do_show_proxies(self, arg):
        """show_proxies — أول 30 بروكسي حي مع زمن استجابتها"""
        snap = self.proxy_manager.pool.snapshot()
        if not snap:
            print("[!] لا توجد بروكسيات حية — انتظر التعبئة أو نفّذ fetch_proxies")
            return
        for i, (url, lat, ok_n, fail_n, consec) in enumerate(snap[:30], 1):
            print(f"{i:>3}. {url:<45} {lat * 1000:>5.0f}ms   نجاح={ok_n} فشل={fail_n}")
        if len(snap) > 30:
            print(f"    ... و{len(snap) - 30} أخرى")

    # ---------------- خروج ----------------
    def do_exit(self, arg):
        """exit — إنهاء الجلسة"""
        print("وداعاً.")
        return True

    def do_EOF(self, arg):
        return self.do_exit(arg)


if __name__ == "__main__":
    MasterCLI().cmdloop()
