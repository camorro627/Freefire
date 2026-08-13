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

# الحد الأقصى للطلبات المتزامنة (سيمافور)
MAX_CONCURRENCY = 10

# عدد محاولات إعادة الطلب عند أخطاء 429 / 5xx
RETRY_ATTEMPTS = 3

# فاصل زمني عشوائي بين الطلبات — توزيع حمل مهذّب على السيرفر
BASE_DELAY_MIN = 1.0
BASE_DELAY_MAX = 3.0

# ملفات
DB_PATH = "freefire.db"
PROXIES_FILE = "proxies.txt"
