# Free Fire Master Control — قالب تعليمي (Master-Worker)

أداة تحكم مركزي لحساباتك المسجلة في Free Fire، تعمل على Termux.
بنية **Master-Worker** بتنفيذ متوازٍ (`asyncio + aiohttp`) وقاعدة بيانات
محلية (`sqlite3`) وتدوير بروكسيات لتفادي حظر الأيبي.

> **نطاق الاستخدام:** الأداة تتعامل مع الحسابات المسجلة محلياً في قاعدة
> بياناتك فقط (add_account / check_player / mass_status). لا تستهدف حسابات
> طرف ثالث. نقطة النهاية `https://garena.mock` وهمية — استبدلها فقط
> بنقطة نهاية تملكها أو فُوِّضت باختبارها.

## البنية

```
freefire_control/
├── config.py          # الثوابت ونقاط النهاية (وهمية)
├── db.py              # طبقة sqlite3 (Player_ID / Access_Token / الحالة)
├── proxy_pool.py      # تدوير البروكسي من proxies.txt
├── worker_engine.py   # محرك asyncio + aiohttp + معالجة 403/429
├── master_cli.py      # وحدة التحكم المركزية (cmd)
├── proxies.txt        # بروكسي لكل سطر
├── requirements.txt
└── README.md
```

## التثبيت على Termux

```bash
pkg update && pkg upgrade -y
pkg install python -y
pip install -r requirements.txt
# لو فشل تثبيت aiohttp (يتطلب Rust):
pkg install rust binutils python-dev -y && pip install -r requirements.txt
```

## التشغيل

```bash
python master_cli.py
```

## الأوامر

| الأمر | الوصف |
|-------|-------|
| `add_account <ID> <Token>` | تسجيل حساب جديد في القاعدة |
| `remove_account <ID>` | حذف حساب |
| `list_accounts` | عرض الحسابات وحالاتها (active/banned/restricted/error) |
| `check_player <ID>` | جلب الملف (Nickname / Level / Likes) لحساب مسجّل |
| `mass_status` | فحص كل الحسابات بالتوازي — بروكسي مستقل لكل حساب |
| `reload_proxies` | إعادة قراءة `proxies.txt` |
| `show_proxies` | عرض البروكسيات المحمّلة |
| `exit` | إنهاء الجلسة |

## جلسة نموذجية

```
FF-Master> add_account 1001234567 eyJhbGciOiJIUzI1NiIs...
[+] تم تسجيل الحساب 1001234567
FF-Master> check_player 1001234567
[+] 1001234567:
    Nickname : xX_Shadow_Xx
    Level    : 67
    Likes    : 18420
FF-Master> mass_status
[i] جارٍ فحص 2 حساب بالتوازي...
=== النتائج: 2/2 ناجح ===
[+] 1001234567  xX_Shadow_Xx         Level=67 Likes=18420
[+] 1007654321  Silent_Sniper        Level=54 Likes=9901
```

## كيف يعمل؟

1. **Master (master_cli.py):** واجهة `cmd` تستقبل الأوامر، تقرأ الحسابات
   من `db.py`، وتمررها لمحرك التنفيذ.
2. **Worker (worker_engine.py):** كل حساب يصبح `coroutine` مستقلًا يطلق عبر
   `asyncio.gather` في نفس اللحظة. سيمافور يمنع تجاوز `MAX_CONCURRENCY`.
   قبل كل طلب فاصل عشوائي `random.uniform(1, 3)` لتوزيع الحمل.
3. **Proxy Rotation (proxy_pool.py):** بروكسي مربوط ثابت بكل حساب عبر
   `hash(player_id) % len(pool)` — يبقى الحساب على نفس الأيب طوال الجلسة
   بدلًا من التبديل العشوائي الذي قد يُشكك في الحساب.
4. **قاعدة البيانات (db.py):** `sqlite3` بخيط آمن (`threading.Lock`) يحفظ
   الحسابات والتوكنات والحالة الفورية (تحديثها يتم بعد كل طلب).

## معالجة أخطاء السيرفر

| الكود | المعنى | الإجراء |
|-------|--------|---------|
| `403` | حظر/تقييد | الحساب يُحوَّل لحالة `banned`، يتوقف فوراً (لا إعادة محاولة) |
| `429` | ضغط على السيرفر | احترام `Retry-After` إن وُجد، وإلا تراجع أسي + jitter |
| `5xx` | خطأ سيرفر | إعادة محاولة بتراجع أسي `1s → 2s → 4s` |
| شبكة/بروكسي معطّل | `aiohttp.ClientError` | إعادة محاولة ثم تسجيل الخطأ |

## ربط نقطة نهاية حقيقية لاحقاً

1. عدّل `FREEFIRE_API_URL` في `config.py`.
2. أضف دالة `_fetch_*` جديدة في `worker_engine.py` بنفس نمط `_fetch_profile`.
3. أي عملية جماعية جديدة (فحص، إحصائيات...) تستخدم نفس `_worker` و`ProxyPool`
   دون تغيير البنية.

## ملاحظات أداء

- `asyncio.run()` لكل أمر CLI مقبول؛ لخدمة مستمرة أنشئ حلقة حدث واحدة في
  خيط خلفي وأعد استخدام `ClientSession` (يمنع تسرب المقابس).
- `hash()` على النصوص مُملَّح لكل عملية تشغيل لكنه ثابت داخل الجلسة — كافٍ
  لربط الحساب بالبروكسي.
- عيّن `MAX_CONCURRENCY` حسب جودة بروكسياتك وشبكتك.
