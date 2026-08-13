# -*- coding: utf-8 -*-
"""
config.py — الثوابت والإعدادات العامة للأداة
============================================
Free Fire Master Control — إعدادات التحكم بـ 100+ حساب.
"""
import os

# ---------- قاعدة البيانات ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "freefire.db")
ACCOUNTS_TABLE = "accounts"
REG_QUEUE_TABLE = "reg_queue"

# ---------- الشبكة العامة ----------
MAX_CONCURRENCY = 30          # حد التوازي أثناء الفحص الجماعي (30–50 حسب جودة البروكسيات)
CHECK_TIMEOUT = 10            # مهلة طلب الفحص (ثانية)
USER_AGENT = "ff-control/1.0"

# ---------- نقاط النهاية ----------
# تحذير: garena.mock وهمية — استبدلها فقط بنقطة نهاية تملكها أو فُوِّضت باختبارها.
API_BASE = os.environ.get("FF_API_BASE", "https://garena.mock")
PLAYER_ENDPOINT = f"{API_BASE}/player"
REGISTER_ENDPOINT = os.environ.get("FF_REGISTER_ENDPOINT", f"{API_BASE}/register")

# ---------- البروكسيات ----------
MIN_PROXIES = 100             # الحد الأدنى للمخزون الحي (يساوي عدد الحسابات)
MAX_PROXIES = 300             # سقف المخزون
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]
PROXY_VALIDATE_CONCURRENCY = 15   # توازي التحقق من البروكسيات
PROXY_VALIDATE_TIMEOUT = 6        # مهلة اختبار البروكسي (ثانية)
PROXY_VALIDATE_URL = "http://www.gstatic.com/generate_204"  # نقطة اختبار خفيفة
PROXY_FETCH_INTERVAL = 300        # جلب دوري كل 5 دقائق (ثانية)
PROXY_VALIDATE_INTERVAL = 600     # إعادة فحص دورية كل 10 دقائق
PROXY_MIN_SCORE = 1.0             # تحت هذه النقطة يُسقط البروكسي
PROXY_FAIL_THRESHOLD = 2          # إخفاقات متتالية = ميت
PROXY_SUSPICIOUS_TIME = 3.0       # زمن > 3 ث = "مريب"
PROXY_MAX_AGE = 900               # يُسقط البروكسي بعد 15 دقيقة بلا نجاح

# ---------- التسجيل الذاتي (Auto-Register) ----------
REG_CONCURRENCY = 5           # حد التوازي أثناء التسجيل
REG_TIMEOUT = 15              # مهلة طلب التسجيل (ثانية)
REG_MAX_RETRIES = 3
REG_DELAY_MIN = 0.5           # تهدئة عشوائية بين المحاولات (ثانية)
REG_DELAY_MAX = 2.0
CRED_ID_DIGITS = 11           # طول معرّف اللاعب (مثل معرّفات الضيف)
CRED_TOKEN_BYTES = 24         # حجم التوكن العشوائي

# ---------- إعادة المحاولة ----------
CHECK_MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0        # أساس التراجع الأسي (1s → 2s → 4s)
RETRY_MAX_DELAY = 8.0
RETRY_JITTER = 0.3            # نسبة الاهتزاز العشوائي
