# -*- coding: utf-8 -*-
"""
master_cli.py — واجهة camorro التفاعلية (cmd)
=============================================
أوامر: add_account / remove_account / import_accounts / export_accounts /
list_accounts / count_accounts / check_player / mass_status /
send_likes / proxy_status / fetch_proxies / validate_proxies / auto_refill /
show_proxies / auto_register / reg_listen / reg_status / reg_retry / exit
"""
import cmd
import sys
import threading

import config
import db
from proxy_manager import ProxyManager
from worker_engine import (check_player_sync, mass_like_sync, mass_status_sync)


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
        "\n=== Free Fire Master Control (camorro) v1.1 ===\n"
        "check_player <ID> [region] لفحص أي لاعب | reg_listen لاستقبال "
        "حسابات الضيوف | send_likes <ID> لإرسال لايكات.\n"
    )
    prompt = "> "

    def __init__(self):
        super().__init__()
        db.init_db()
        self.pm = ProxyManager()
        self.pm.start()
        self.reg_thread = None
        self.listener = None

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
        pid = arg.strip()
        if not pid:
            print("الاستخدام: remove_account <player_id>")
            return
        print("حُذف الحساب" if db.remove_account(pid) else "الحساب غير موجود")

    def do_import_accounts(self, arg):
        """import_accounts <file.csv> — استيراد جماعي (player_id,access_token[,status])"""
        path = arg.strip()
        if not path:
            print("الاستخدام: import_accounts <file.csv>")
            return
        try:
            n = db.import_csv(path)
            print(f"استُورد {n} حساب جديد من {path}")
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
        """check_player <ID> [region] — فحص أي لاعب: Level / Rank / Clan / Likes"""
        parts = arg.split()
        if not parts:
            print("الاستخدام: check_player <player_id> [region]")
            return
        pid = parts[0]
        region = parts[1] if len(parts) > 1 else config.DEFAULT_REGION
        print(f"فحص {pid} ({region}) ...")
        r = check_player_sync(pid, region, self.pm)
        if not r or not r.ok:
            print(f"[X] {r.error if r else 'فشل الفحص'} — تأكد من FF_API_KEY والاتصال.")
            return
        likes = f" | Likes {r.likes}" if r.source == "internal-profile" else ""
        print(f"[OK] {r.nickname or '?'} | Level {r.level} | Rank {r.rank} "
              f"| Clan {r.clan or '-'}{likes} | {r.elapsed:.2f}s")

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
                print(f"[X] {r.player_id} | {r.error}")
        print(f"\nالنتيجة: {ok}/{total} نجحت.")

    # ---------- اللايكات ----------
    def do_send_likes(self, arg):
        """send_likes <target_uid> [region] [max_accounts] — لايك من كل حساب نشط"""
        parts = arg.split()
        if not parts:
            print("الاستخدام: send_likes <target_uid> [region] [max_accounts]")
            return
        target = parts[0]
        region = parts[1] if len(parts) > 1 else config.DEFAULT_REGION
        try:
            max_acc = int(parts[2]) if len(parts) > 2 else config.LIKE_MAX_ACCOUNTS
        except ValueError:
            max_acc = config.LIKE_MAX_ACCOUNTS

        print(f"إرسال لايكات إلى {target} ({region}) من حتى {max_acc} حساب ...")

        def cb(done, total, o):
            mark = "[OK]" if o.ok else "[X]"
            print(f"\r{mark} {o.player_id} ({done}/{total})", end="", flush=True)

        results, total = mass_like_sync(
            target, region, max_acc, self.pm,
            provider=config.LIKE_PROVIDER, progress_cb=cb,
        )
        if not total:
            print("\nلا توجد حسابات نشطة — استقبل حسابات أولاً: reg_listen ثم شغّل المزرعة.")
            return
        ok = sum(1 for r in results if r.ok)
        print(f"\nالنتيجة: {ok}/{total} لايك ناجح. "
              f"(المزوّد: {config.LIKE_PROVIDER})")

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

    # ---------- إنشاء/استقبال الحسابات ----------
    def do_reg_listen(self, arg):
        """reg_listen [port] — استقبال حسابات الضيوف من frida_guest.js (خلفية)"""
        port = int(arg.strip()) if arg.strip().isdigit() else config.REG_LISTEN_PORT
        from registrar import start_listener
        self.listener = start_listener(port=port)
        print(f"[CLI] المستمع يعمل على المنفذ {port}.")
        print(f"[CLI] على المحاكي: frida -U -f {PACKAGE_HINT} -l guest_farm/frida_guest.js")
        print(f"[CLI] ثم عدّل TERMUX_URL داخل السكربت إلى IP جهاز Termux.")

    def do_auto_register(self, arg):
        """auto_register [N] — طلب N حساب حقيقي من المزرعة (FF_FARM_ENDPOINT)"""
        try:
            count = int(arg.strip() or 5)
        except ValueError:
            count = 5
        from registrar import start_registration
        self.reg_thread = start_registration(count=count, proxy_manager=self.pm)
        print(f"[CLI] بدأت دورة طلب {count} حساب من المزرعة في الخلفية.")
        print("[CLI] إن لم تضبط FF_FARM_ENDPOINT استخدم reg_listen لاستقبال الحسابات من المحاكي.")

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
