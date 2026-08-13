# ============================================================
# config.py — الثوابت العامة (استبدلها بروابطك الحقيقية لاحقاً)
# ============================================================

# نقطة نهاية وهمية — استبدلها فقط عندما يكون لديك تفويض على الهدف
FREEFIRE_API_URL = "https://garena.mock"
FF_PROFILE_ENDPOINT = f"{FREEFIRE_API_URL}/api/v1/profile"
FF_SESSION_ENDPOINT = f"{FREEFIRE_API_URL}/api/v1/session/validate"

USER_AGENT = "Mozilla/5.0 (Linux; Android 13) FreeFire/1.99.2"

# مهلة الطلب الواحد بالثواني
REQUEST_TIMEOUT = 10

# الحد الأقصى للطلبات المتزامنة — لـ 100 حساب ارفعه تدريجياً إلى 30-50
MAX_CONCURRENCY = 30

# عدد محاولات إعادة الطلب عند أخطاء 429 / 5xx
RETRY_ATTEMPTS = 3

# فاصل زمني عشوائي بين الطلبات — توزيع حمل مهذّب على السيرفر
BASE_DELAY_MIN = 1.0
BASE_DELAY_MAX = 3.0

# ملفات
DB_PATH = "freefire.db"
PROXIES_FILE = "proxies.txt"

# ============================================================
# إدارة البروكسيات الذكية (Proxy Manager)
# ============================================================

# الحد الأدنى للبروكسيات الحية — تصميم 100 حساب => 100 بروكسي
MIN_PROXIES = 100
# سقف التخزين (يُقتلم بالأفضل نقاطاً)
MAX_PROXIES = 300
# ثوانٍ بين جولات إعادة التعبئة/التحقق في الخلفية
REFILL_INTERVAL = 45
# عدد الإخفاقات المتتالية قبل اعتبار البروكسي ميتاً
PROXY_FAIL_THRESHOLD = 2
# تفعيل إعادة التعبئة التلقائية
AUTO_REFILL = True

# نقطة تحقق عامة لاختبار حيوية البروكسي (تعيد 200 + IP)
VALIDATION_URL = "https://api.ipify.org?format=json"
VALIDATION_TIMEOUT = 6
VALIDATION_CONCURRENCY = 15

# المصادر المجانية — type=plain يعني سطر لكل proxy (host:port)
PROXY_SOURCES = [
    {"url": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "type": "plain"},
    {"url": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "type": "plain"},
    {"url": "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", "type": "plain"},
    {"url": "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all", "type": "plain"},
    {"url": "https://www.proxy-list.download/api/v1/get?type=http", "type": "plain"},
]
