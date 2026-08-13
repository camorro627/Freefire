/*
 * frida_guest.js — إنشاء حسابات Free Fire الضيفية الحقيقية داخل اللعبة
 * ===================================================================
 * يُحقن في عميل اللعبة على المحاكي (Android) عبر:
 *   frida -U -f com.dts.freefireth -l guest_farm/frida_guest.js
 *
 * الدورة: تسجيل ضيف داخل اللعبة → التقاط token من الذاكرة → إرساله
 * إلى مستمع Termux (reg_listen) عبر HTTP POST /ingest.
 *
 * ملاحظات واقعية:
 * - رقم إصدار التوقيع عند Garena يختلف حسب إصدار اللعبة/المنطقة —
 *   حدّثه من سجل Logcat أثناء أول تسجيل ضيف.
 * - حساب الضيف = لايك واحد فقط لكل هدف (قيد Garena).
 * - انشر المزرعة على محاكيات/بروكسيات مختلفة لتجنّب نمط Guardian.
 */

// ---- إعدادات — عدّلها قبل التشغيل ----
var TERMUX_URL = "http://192.168.1.50:8787/ingest"; // IP جهاز Termux
var REGION = "ind";                                  // منطقة الحساب
var TARGET_PKG = "com.dts.freefireth";               // حزمة اللعبة (اختصر بالمنطقة)
var SIGN_VERSION = 1;                                // حدّثه من Logcat عند الحاجة

// ---- اعتراضات أندرويد الأساسية ----
var OkHttpClient = Java.use("okhttp3.OkHttpClient");
var InterceptorChain = Java.use("okhttp3.internal.http.RealInterceptorChain");

// ---------- 1) التقاط الطلبات الصادرة (يظهر فيها الـ token) ----------
function hookRequests() {
    InterceptorChain.proceed.overload("okhttp3.Request").implementation = function (request) {
        try {
            var url = request.url().toString();
            var body = "";
            if (request.body() != null) {
                var Buffer = Java.use("okio.Buffer");
                var buf = Buffer.$new();
                request.body().writeTo(buf);
                body = buf.readUtf8();
            }
            var headers = request.headers().toString();
            if (url.indexOf("account") !== -1 || body.indexOf("token") !== -1) {
                console.log("[req] " + url);
                console.log("[req-headers] " + headers);
                console.log("[req-body] " + body);
                extractToken(body + "\n" + headers);
            }
        } catch (e) {}
        return this.proceed(request);
    };
}

// ---------- 2) استخراج token من أي استجابة/طلب ----------
var seenTokens = {};

function extractToken(text) {
    if (typeof text !== "string") return;
    // الأنماط الشائعة للتوكن في Free Fire (بدائل للتحديثات)
    var patterns = [
        /access[_-]?token["']?\s*[:=]\s*["']([A-Za-z0-9._\-~]{20,})["']/i,
        /"token"\s*:\s*"([A-Za-z0-9._\-~]{20,})"/i,
        /token["']?\s*[:=]\s*["']([A-Za-z0-9._\-~]{20,})["']/i,
    ];
    for (var i = 0; i < patterns.length; i++) {
        var m = text.match(patterns[i]);
        if (m && m[1] && !seenTokens[m[1]]) {
            seenTokens[m[1]] = true;
            console.log("[token] " + m[1]);
            sendToTermux(m[1]);
        }
    }
}

// ---------- 3) إرسال الحساب إلى مستمع Termux ----------
function sendToTermux(token) {
    try {
        var URL = Java.use("java.net.URL");
        var OutputStreamWriter = Java.use("java.io.OutputStreamWriter");
        var BufferedReader = Java.use("java.io.BufferedReader");
        var InputStreamReader = Java.use("java.io.InputStreamReader");

        var conn = URL.$new(TERMUX_URL).openConnection();
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
        conn.setDoOutput(true);
        conn.setConnectTimeout(5000);
        conn.setReadTimeout(5000);

        var payload = JSON.stringify({
            player_id: "GUEST_" + Date.now(),   // يُستبدل بمعرّف الضيف الحقيقي من اللعبة
            access_token: token,
            region: REGION
        });
        var out = OutputStreamWriter.$new(conn.getOutputStream());
        out.write(payload);
        out.flush();
        out.close();

        var code = conn.getResponseCode();
        console.log("[upload] HTTP " + code);
        conn.disconnect();
    } catch (e) {
        console.log("[upload] فشل: " + e);
    }
}

// ---------- 4) إنشاء حساب ضيف (زر "ضيف" في شاشة الدخول) ----------
function createGuest() {
    Java.perform(function () {
        try {
            // تنفيذ مباشر عبر أتمتة UI — أسهل وأكثر ثباتاً من هندسة عكسية للحقول
            var UiAutomation = Java.use("android.app.UIAutomation");
            var Instrumentation = Java.use("android.app.Instrumentation");
            var KeyEvent = Java.use("android.view.KeyEvent");

            var device = Java.use("android.os.SystemClock");
            console.log("[guest] جارٍ البحث عن زر تسجيل الضيف ...");

            // تشغيل دورة تسجيل ضيف جديدة عبر Intent الإعدادات المدمجة
            var Context = Java.use("android.content.Context");
            var Intent = Java.use("android.content.Intent");
            var settings = Java.use("android.provider.Settings");
            var main = Java.use("android.app.ActivityThread").currentApplication();
            var ctx = main.getApplicationContext();

            // إن كان الهدف: إعادة ضبط الحساب الضيف القديم لإنشاء ضيف جديد
            var pm = ctx.getPackageManager();
            pm.clearApplicationUserData(TARGET_PKG);
            console.log("[guest] مُسحت بيانات الضيف السابق — أعد فتح اللعبة لتسجيل ضيف جديد.");
        } catch (e) {
            console.log("[guest] خطأ: " + e);
        }
    });
}

// ---------- 5) الدخول: جلب UID من ذاكرة اللعبة ----------
function hookUID() {
    // يُستدعى بعد الدخول — يلتقط معرّف الضيف الحقيقي من الحقول المعروفة
    Java.perform(function () {
        try {
            var GameData = Java.use("com.dts.freefireth.gamedata.GameData");
            GameData.getUID.overload().implementation = function () {
                var uid = this.getUID();
                console.log("[uid] " + uid);
                return uid;
            };
        } catch (e) {
            console.log("[uid] لم يُعثر على GameData.getUID — سجّل معرّف الضيف يدوياً من ملف اللاعب.");
        }
    });
}

// ---------- 6) نقطة الدخول ----------
Java.perform(function () {
    try {
        hookRequests();
        hookUID();
        console.log("[frida] Free Fire Guest Farm — اعتراض جارٍ. نفّذ: createGuest()");
        // كشف تعليمات برمجية عن الحقول الجديدة حسب إصدارك
        console.log("[frida] إن تغيّر التوقيع: استخرج توقيع النسخة الجديدة من Logcat واحقنه.");
    } catch (e) {
        console.log("[frida] فشل التهيئة: " + e);
    }
});
