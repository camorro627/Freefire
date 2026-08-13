# -*- coding: utf-8 -*-
"""
master_cli.py — واجهة camorro التفاعلية (cmd)
=============================================
أوامر: add_account / remove_account / import_accounts / export_accounts /
list_accounts / count_accounts / check_player / mass_status /
proxy_status / fetch_proxies / validate_proxies / auto_refill /
show_proxies / auto_register / reg_status / reg_retry / exit
"""
import cmd
import sys
import threading
import time

import config
import db
from proxy_manager import ProxyManager
from worker_engine import check_player_sync, mass_status_sync


def _print_table(rows, headers):
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join("{" + str(i) + ":<" + str(w) + "}" for i, w in enumerate(widths))
    print(fmt.format(*headers))
    print("-" * (sum(widths) + 2 * (len(headers) - 1)))
    for r in rows:
        print(fmt.format(*r))


class MasterCLI(cmd.Cmd):
    intro = (
        "\n=== Free Fire Master Control (camorro) ===\n"
        "اكتب help لعرض الأوامر. auto_register 5 لإنشاء حسابات تلقائياً.\n"
    )
    prompt = "> "

    def __init__(self):
        super().__init__()
        db.init_db()
        self.pm = ProxyManager()
        self.pm.start()
        self.reg_thread = None

    # ---------- الحسابات ----------
    def do_add_account(self, arg):
        """add_account <ID> <Token> — تسجيل حساب فردي"""
        parts = arg.split()
        if len(parts) < 2:
            print("الاستخدام: add_account <player_id> <access_token>")
            return
        pid, tok = parts[0], parts[1]
        print("تمت الإضافة" if db.add_account(pid, tok) else "الحساب موجود مسبقاً")

    def do_remove_account(self, arg):
        """remove_account <ID> — حذف حساب"""
        if not arg.strip():
            print("الاستخدام: remove_account <player_id>")
            return
        print("تم الحذف" if db.remove_account(arg.strip()) else "غير موجود")

    def do_import_accounts(self, arg):
        """import_accounts <file.csv> — استيراد جماعي (player_id,access_token[,status])"""
        if not arg.strip():
            print("الاستخدام: import_accounts <file.csv>")
            return
        try:
            n = db.import_csv(arg.strip())
            print(f"استُورد {n} حساب جديد.")
        except Exception as e:
            print(f"فشل الاستيراد: {e}")

    def do_export_accounts(self, arg):
        """export_accounts [file.csv] — نسخة احتياطية لكل الحسابات"""
        try:
            path, n = db.export_csv(arg.strip() or None)
            print(f"صُدّر {n} حساب إلى {path}")
        except Exception as e:
            print(f"فشل التصدير: {e}")

    def do_list_accounts(self, arg):
        """list_accounts [page] — عرض الحسابات مع ترقيم الصفحات"""
        try:
            page = int(arg.strip() or 1)
        except ValueError:
            page = 1
        rows, total = db.list_accounts(page)
        if not rows:
            print("لا توجد حسابات.")
            return
        _print_table(
            [
                (r["player_id"], r["status"], r["last_check"] or "-",
                 (r["last_result"] or "-")[:40])
                for r in rows
            ],
            ["ID", "الحالة", "آخر فحص", "آخر نتيجة"],
        )
        print(f"الصفحة {page} — الإجمالي {total}")

    def do_count_accounts(self, arg):
        """count_accounts — عدد الحسابات حسب الحالة"""
        for status, n in db.count_by_status().items():
            print(f"{status:<10} {n}")

    # ---------- الفحص ----------
    def do_check_player(self, arg):
        """check_player <ID> — جلب الملف (Nickname / Level / Likes)"""
        pid = arg.strip()
        if not pid:
            print("الاستخدام: check_player <player_id>")
            return
        print(f"فحص {pid} ...")
        r = check_player_sync(pid, self.pm)
        if not r:
            print("الحساب غير مسجل في قاعدة البيانات.")
            return
        if r.ok:
            print(f"[OK] {r.nickname or '?'} | Level {r.level} | Likes {r.likes} "
                  f"| عبر {r.proxy or 'مباشر'} | {r.elapsed:.2f}s")
        else:
            print(f"[X] {r.status or r.error} | عبر {r.proxy or 'مباشر'} | {r.elapsed:.2f}s")

    def do_mass_status(self, arg):
        """mass_status — فحص كل الحسابات بالتوازي مع تقرير تقدم"""
        def cb(done, total, res):
            mark = "[OK]" if res.ok else "[X]"
            print(f"\r{mark} {res.player_id} ({done}/{total})", end="", flush=True)

        print("فحص جماعي جارٍ ...")
        results, total = mass_status_sync(self.pm, progress_cb=cb)
        if not total:
            print("لا توجد حسابات نشطة.")
            return
        print("\n" + "-" * 40)
        ok = sum(1 for r in results if r.ok)
        for r in results:
            if r.ok:
                print(f"[OK] {r.player_id} | {r.nickname} | Lv{r.level} | {r.elapsed:.2f}s")
            else:
                print(f"[X] {r.player_id} | {r.status or r.error}")
        print(f"\nالنتيجة: {ok}/{total} نجحت.")

    # ---------- البروكسيات ----------
    def do_proxy_status(self, arg):
        """proxy_status — حالة المخزون + تحليل السلوك"""
        s = self.pm.status()
        print(f"الإجمالي: {s['total']} | حي: {s['alive']} | متوسط الزمن: {s['avg_time']}s "
              f"| معدل النجاح: {s['success_rate']:.0%} | مريبة: {s['suspicious']}")

    def do_fetch_proxies(self, arg):
        """fetch_proxies — جلب بروكسيات من المصادر المجانية (خلفية)"""
        print("جلب البروكسيات في الخلفية ...")
        threading.Thread(target=self.pm.fetch, daemon=True).start()

    def do_validate_proxies(self, arg):
        """validate_proxies — إعادة فحص كل البروكسيات الحية (خلفية)"""
        print("التحقق في الخلفية ...")
        threading.Thread(target=self.pm.validate, daemon=True).start()

    def do_auto_refill(self, arg):
        """auto_refill on|off — تشغيل/إيقاف إعادة التعبئة التلقائية"""
        mode = arg.strip().lower()
        if mode == "on":
            self.pm.auto_refill = True
            print("التعبئة التلقائية: ON")
        elif mode == "off":
            self.pm.auto_refill = False
            print("التعبئة التلقائية: OFF")
        else:
            print("الاستخدام: auto_refill on|off")

    def do_show_proxies(self, arg):
        """show_proxies — أول 30 بروكسي حي مع زمن استجابتها"""
        snap = sorted(self.pm.pool.snapshot(), key=lambda p: p.avg_time)[:30]
        _print_table(
            [
                (p.address, f"{p.avg_time:.3f}s", f"{p.score:.1f}",
                 f"{p.successes}/{p.failures}", "نعم" if p.alive else "لا")
                for p in snap
            ],
            ["البروكسي", "متوسط الزمن", "النقاط", "نجاح/فشل", "حي"],
        )

    # ---------- التسجيل الذاتي ----------
    def do_auto_register(self, arg):
        """auto_register [N] — إنشاء N حساب تلقائياً (افتراضي 5) ثم التحكم بها"""
        try:
            count = int(arg.strip() or 5)
        except ValueError:
            count = 5
        from registrar import start_registration
        self.reg_thread = start_registration(count=count, proxy_manager=self.pm)
        print(f"[CLI] بدأت دورة تسجيل {count} حساب في الخلفية. تابع بـ reg_status.")

    def do_reg_status(self, arg):
        """reg_status — تقرير مهام التسجيل (pending/done/failed)"""
        from registrar import reg_queue_summary
        rows = reg_queue_summary()
        if not rows:
            print("لا توجد مهام تسجيل.")
            return
        for row in rows:
            print(f"{row['status']:<10} {row['n']}")

    def do_reg_retry(self, arg):
        """reg_retry — إعادة محاولة المهام الفاشلة فقط"""
        from registrar import start_registration
        self.reg_thread = start_registration(retry_failed=True, proxy_manager=self.pm)
        print("[CLI] أُعيدت جدولة المهام الفاشلة.")

    # ---------- عام ----------
    def do_exit(self, arg):
        """exit — إنهاء الجلسة"""
        self.pm.stop()
        print("وداعاً.")
        return True

    def do_quit(self, arg):
        return self.do_exit(arg)

    def emptyline(self):
        pass


if __name__ == "__main__":
    try:
        MasterCLI().cmdloop()
    except KeyboardInterrupt:
        print("\nإنهاء ...")
        sys.exit(0)
