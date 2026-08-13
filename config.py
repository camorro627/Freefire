# -*- coding: utf-8 -*-
"""
config.py — الثوابت والإعدادات العامة للأداة
============================================
Free Fire Master Control — إعدادات التحكم بـ 100+ حساب.
النسخة 1.1: استُبدلت نقاط garena.mock الوهمية بواجهات حقيقية.
"""
import os

# ---------- قاعدة البيانات ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "freefire.db")
ACCOUNTS_TABLE = "accounts"
REG_QUEUE_TABLE = "reg_queue"

# ---------- الشبكة العامة ----------
MAX_CONCURRENCY = 30          # حد التوازي أثناء الفحص الجماعي (30–50 حسب جودة البروكسيات)
CHECK_TIMEOUT = 10            # مهلة الطلب (ثانية)
USER_AGENT = "ff-control/1.1"

# ---------- المناطق ----------
DEFAULT_REGION = os.environ.get("FF_REGION", "ind")
REGION_CODES = {
    "ind": "India", "bd": "Bangladesh", "pk": "Pakistan", "sg": "Singapore",
    "id": "Indonesia", "th": "Thailand", "vn": "Vietnam", "br": "Brazil",
    "us": "USA", "ru": "Russia", "me": "Middle East", "tw": "Taiwan",
    "cis": "CIS", "kr": "Korea", "eg": "Egypt", "sa": "Saudi Arabia",
}

# ---------- واجهة معلومات اللاعب العامة (فحص أي UID — حقيقية) ----------
# مجانية: سجّل مفتاحاً في developers.freefirecommunity.com ثم ضعه في FF_API_KEY
FF_COMMUNITY_API = "https://developers.freefirecommunity.com/api/v1/info"
FF_API_KEY = os.environ.get("FF_API_KEY", "")
# احتياطي بدون مفتاح (إحصائيات مباريات فقط)
FF_STATS_FALLBACK = "https://free-ff-api-src-5plp.onrender.com/api/v1/playerstats"
# واجهة الملف الشخصي الداخلية عبر JWT (مصدر عدد اللايكات) — اختيارية
# تُستخرج من التقاط حركة اللعبة؛ تُترك فارغة إن لم تتوفر بعد
FF_INTERNAL_PROFILE_ENDPOINT = os.environ.get("FF_INTERNAL_PROFILE_ENDPOINT", "")

# ---------- إرسال اللايكات ----------
# المزوّد 1: HL Gaming API (موثّق — useruid + api من لوحة التحكم)
HLG_BASE = "https://proapis.hlgamingofficial.com/main/games/freefire/account/api"
HLG_USERUID = os.environ.get("HLG_USERUID", "")
HLG_API_KEY = os.environ.get("HLG_API_KEY", "")
HLG_LIKE_SECTION = os.environ.get("HLG_LIKE_SECTION", "sendLike")
# المزوّد 2: SiamBhau API (اختياري)
SIAMBHAU_BASE = os.environ.get("SIAMBHAU_BASE", "")
SIAMBHAU_KEY = os.environ.get("SIAMBHAU_KEY", "")
SIAMBHAU_LIKE_PATH = os.environ.get("SIAMBHAU_LIKE_PATH", "/like/send_like")
# المزوّد 3: نقطة LikeProfile الداخلية المشفّرة AES-CBC
# (ثوابتها تُستخرج من التقاط حركة اللعبة أو من مشروع kaifcodec/freefire-like-and-guest-api)
FF_LIKE_ENDPOINT = os.environ.get("FF_LIKE_ENDPOINT", "")
FF_LIKE_KEY = os.environ.get("FF_LIKE_KEY", "")   # مفتاح AES بصيغة hex
FF_LIKE_IV = os.environ.get("FF_LIKE_IV", "")     # IV بصيغة hex

LIKE_PROVIDER = os.environ.get("FF_LIKE_PROVIDER", "hlg")   # hlg | siambhau | internal
LIKE_MAX_ACCOUNTS = int(os.environ.get("FF_LIKE_MAX_ACCOUNTS", "100"))
LIKE_RPS = float(os.environ.get("FF_LIKE_RPS", "2.0"))      # طلبات/ثانية (تجنّب 429)

# ---------- مزرعة الضيوف (إنشاء حسابات حقيقية) ----------
# frida_guest.js على المحاكي يرسل الحسابات إلى هذا المستمع على Termux
REG_LISTEN_HOST = "0.0.0.0"
REG_LISTEN_PORT = int(os.environ.get("FF_REG_PORT", "8787"))
REG_INGEST_PATH = "/ingest"
# عنوان خدمة المزرعة (إن وُجدت خدمة HTTP تخلق حسابات ضيف، مثل
# freefire-jwt-generator-api أو واجهة خاصة بك). تُترك فارغة للاعتماد على المستمع.
FF_FARM_ENDPOINT = os.environ.get("FF_FARM_ENDPOINT", "")

# ---------- البروكسيات ----------
MIN_PROXIES = 100             # الحد الأدنى للمخزون الحي
MAX_PROXIES = 300             # سقف المخزون
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]
PROXY_VALIDATE_CONCURRENCY = 15
PROXY_VALIDATE_TIMEOUT = 6
PROXY_VALIDATE_URL = "http://www.gstatic.com/generate_204"
PROXY_FETCH_INTERVAL = 300
PROXY_VALIDATE_INTERVAL = 600
PROXY_MIN_SCORE = 1.0
PROXY_FAIL_THRESHOLD = 2
PROXY_SUSPICIOUS_TIME = 3.0
PROXY_MAX_AGE = 900

# ---------- التسجيل الذاتي ----------
REG_CONCURRENCY = 5
REG_TIMEOUT = 15
REG_MAX_RETRIES = 3
REG_DELAY_MIN = 0.5
REG_DELAY_MAX = 2.0
CRED_ID_DIGITS = 11           # طول معرّف المهمة فقط (المعرّف الحقيقي يأتي من المزرعة)
CRED_TOKEN_BYTES = 24

# ---------- إعادة المحاولة ----------
CHECK_MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 8.0
RETRY_JITTER = 0.3
