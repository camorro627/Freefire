# camorro — Free Fire Master Control

أداة تحكم مركزي لحساباتك المسجلة في Free Fire، تعمل على Termux. بنية **Master-Worker** بتنفيذ متوازٍ (`asyncio + aiohttp`)، قاعدة بيانات محلية (`sqlite3`)، ومدير بروكسيات ذكي يجلب ويحلل ويستبدل البروكسيات تلقائياً من مصادر مجانية — مصممة للتحكم بـ **100+ حساب**.

**ميزة جديدة:** التسجيل الذاتي `auto_register` — الأداة تنشئ N حساباً بنفسها (افتراضياً 5) وتخزنها محلياً ليتحكم بها السيد كأي حساب مستورد.

> **نطاق الاستخدام:** الأداة تتعامل مع الحسابات المسجلة محلياً في قاعدة بياناتك فقط (استيراد CSV / add_account / auto_register / check_player / mass_status). لا تستهدف حسابات طرف ثالث. نقطة النهاية `https://garena.mock` وهمية — استبدلها فقط بنقطة نهاية تملكها أو فُوِّضت باختبارها.

## البنية

```
freefire_control/
├── config.py              # الثوابت + إعدادات الـ 100 حساب والبروكسيات والتسجيل
├── db.py                  # sqlite3 + استيراد/تصدير CSV + ترقيم صفحات
├── proxy_scraper.py       # جلب القوائم من المصادر المجانية (متوازٍ)
├── proxy_pool.py          # مخزن بنقاط سلوك thread-safe
├── proxy_manager.py       # خيط خلفي: جلب/تحقق/استبدال تلقائي + محلل
├── worker_engine.py       # محرك asyncio + aiohttp + معالجة 403/429
├── registrar.py           # التسجيل الذاتي (Auto-Register)
├── master_cli.py          # واجهة camorro التفاعلية (cmd)
├── accounts_template.csv  # قالب استيراد جماعي
├── proxies.txt            # مصدر يدوي اختياري
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
| --- | --- |
| `add_account <ID> <Token>` | تسجيل حساب فردي |
| `remove_account <ID>` | حذف حساب |
| `import_accounts <file.csv>` | استيراد جماعي (player_id,access_token[,status]) |
| `export_accounts [file.csv]` | نسخة احتياطية لكل الحسابات |
| `list_accounts [page]` | عرض الحسابات مع ترقيم الصفحات |
| `count_accounts` | عدد الحسابات حسب الحالة |
| `check_player <ID>` | جلب الملف (Nickname / Level / Likes) |
| `mass_status` | فحص كل الحسابات بالتوازي مع تقرير تقدم |
| `proxy_status` | حالة المخزون + تحليل السلوك |
| `fetch_proxies` | جلب بروكسيات من المصادر المجانية (خلفية) |
| `validate_proxies` | إعادة فحص كل البروكسيات الحية (خلفية) |
| `auto_refill on\|off` | تشغيل/إيقاف إعادة التعبئة التلقائية |
| `show_proxies` | أول 30 بروكسي حي مع زمن استجابتها |
| `auto_register [N]` | ⬅ إنشاء N حساب تلقائياً (افتراضي 5) في الخلفية |
| `reg_status` | ⬅ تقرير مهام التسجيل (pending/done/failed) |
| `reg_retry` | ⬅ إعادة محاولة المهام الفاشلة فقط |
| `exit` | إنهاء الجلسة |

## دورة التسجيل الذاتي

```
auto_register 5
   └─> enqueue(5): توليد player_id + access_token عشوائي
        └─> RegistrationManager (توازي REG_CONCURRENCY=5)
             ├─> register_account(): Mock افتراضياً — نجاح 85% + 429/5xx/403
             │    └─> عند التوصيل الحقيقي: POST إلى REGISTER_ENDPOINT عبر بروكسي
             ├─> نجاح → reg_queue=done → store_account في accounts (active)
             ├─> 403 → failed نهائي (لا إعادة)
             ├─> 429/5xx → تراجع أسي + تهدئة عشوائية
             └─> فشل شبكة → إبلاغ مدير البروكسيات → استبدال تلقائي
كل الدورة في خيط خلفي — CLI لا ينتظر أبداً.
```

## دورة البروكسيات الذكية

```
Worker فشل اتصال عبر بروكسي X
   └─> report_failure(X)            ← إخفاق متتالي #1
        └─> إخفاق آخر → X ميت        ← يُسقط بعد العتبة (2)
             └─> المخزون الحي < 100؟
                  └─> نعم → جلب فوري من 5 مصادر بالتوازي
                       └─> تحقق (15 متزامن، مهلة 6 ث)
                            └─> الحيّ يُدمج ويُقيَّم بالنقاط
                                 └─> get_for() يوزّع الأفضل نقاطاً
```

* كل العمليات الشبكية في **خيط خلفي** — أوامر CLI لا تنتظر أبداً.
* بروكسي واحد لكل حساب: يوزّع دائرياً على أفضل البروكسيات نقاطاً.
* المحلل: متوسط زمن + معدل نجاح + عدّاد "مريبة" (زمن > 3 ث أو إخفاقات متتالية).

## معالجة أخطاء السيرفر

| الكود | المعنى | الإجراء |
| --- | --- | --- |
| `403` | حظر/تقييد | الحساب → `banned`، يتوقف فوراً (لا إعادة محاولة) |
| `429` | ضغط على السيرفر | احترام `Retry-After`، وإلا تراجع أسي + jitter |
| `5xx` | خطأ سيرفر | إعادة محاولة بتراجع أسي `1s → 2s → 4s` |
| شبكة/بروكسي | `ClientError` | إبلاغ المدير → استبدال البروكسي تلقائياً |

## ملاحظات لـ 100+ حساب

* `MIN_PROXIES = 100` في `config.py` — يساوي عدد حساباتك.
* `MAX_CONCURRENCY = 30` — ارفعه تدريجياً (30–50) حسب جودة البروكسيات.
* `REG_CONCURRENCY = 5` — ارفعه بحذر أثناء التسجيل الجماعي.
* للاستيراد الجماعي: جهّز `accounts.csv` بنفس صيغة `accounts_template.csv`.
* `freefire.db` تخزن التوكنات — أضفها إلى `.gitignore` ولا ترفعها للمستودع.
