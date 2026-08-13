# -*- coding: utf-8 -*-
"""
ff_api.py — الواجهات الحقيقية بدل garena.mock
=============================================
1) fetch_player : معلومات عامة لأي UID (Level / Rank / Clan / Signature)
                  عبر Free Fire Community API (مجاني بالتسجيل) + احتياطي.
                  عدد اللايكات يُجلب عبر واجهة الملف الشخصي الداخلية
                  (FF_INTERNAL_PROFILE_ENDPOINT) عند توفر JWT للحساب.
2) send_like    : إرسال لايك واحد للهدف عبر المزوّد المُهيّأ في config.py
                  (hlg | siambhau | internal)
3) build_like_message / _aes_cbc_encrypt :
                  بناء حمولة LikeProfile المشفّرة AES-CBC للواجهة الداخلية.
"""
import json

import aiohttp

import config


# ============================================================
# 1) جلب معلومات اللاعب (فحص أي UID — لا يتطلب تسجيل الحساب)
# ============================================================
async def fetch_player(session, uid, region=None, api_key=None, token=None):
    """يرجع قاموس معلومات اللاعب.

    الحقول عند النجاح: nickname / level / rank / region / clan / signature
    / pet_level / source. حقل likes يُملأ فقط عند ضبط
    FF_INTERNAL_PROFILE_ENDPOINT وتمرير token صالح.
    """
    region = (region or config.DEFAULT_REGION).lower()
    api_key = api_key if api_key is not None else config.FF_API_KEY
    out = {"uid": str(uid), "region": region.upper(),
           "source": None, "error": ""}

    # --- المسار العام: Community API ---
    try:
        headers = {"x-api-key": api_key} if api_key else {}
        timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
        async with session.get(
            config.FF_COMMUNITY_API,
            params={"region": region, "uid": str(uid)},
            headers=headers, timeout=timeout,
        ) as r:
            if r.status == 200:
                d = await r.json()
                b = d.get("basicInfo") or {}
                clan = d.get("clanBasicInfo") or {}
                out.update({
                    "nickname": b.get("nickname"),
                    "level": b.get("level"),
                    "rank": b.get("rank"),
                    "clan": clan.get("clanName"),
                    "clan_level": clan.get("clanLevel"),
                    "signature": (d.get("socialInfo") or {}).get("signature"),
                    "pet_level": (d.get("petInfo") or {}).get("level"),
                    "source": "community",
                })
            elif 400 <= r.status < 500:
                # خطأ دائم (مفتاح خاطئ/منطقة خاطئة) — لا فائدة من إعادة المحاولة
                out["error"] = f"HTTP {r.status}"
            else:
                out["error"] = f"HTTP {r.status}"
    except Exception as e:
        out["error"] = str(e)

    # --- مسار اللايكات (اختياري): الملف الشخصي الداخلي عبر JWT ---
    if token and config.FF_INTERNAL_PROFILE_ENDPOINT:
        try:
            timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
            async with session.post(
                config.FF_INTERNAL_PROFILE_ENDPOINT,
                json={"uid": str(uid), "region": region},
                headers={"Authorization": f"Bearer {token}",
                         "User-Agent": config.USER_AGENT},
                timeout=timeout,
            ) as r:
                if r.status == 200:
                    d = await r.json(content_type=None)
                    if isinstance(d, dict):
                        likes = (d.get("likeCount") or d.get("likes")
                                 or d.get("like_count"))
                        if likes is not None:
                            out["likes"] = likes
                        if out.get("source") is None:
                            out["source"] = "internal-profile"
        except Exception:
            pass

    # --- احتياطي: إحصائيات مباريات بدون مفتاح ---
    if out.get("source") is None and not out.get("error"):
        try:
            timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
            async with session.get(
                config.FF_STATS_FALLBACK,
                params={"region": region.upper(), "uid": str(uid)},
                timeout=timeout,
            ) as r:
                if r.status == 200:
                    out["stats"] = await r.json(content_type=None)
                    out["source"] = "stats-fallback"
        except Exception:
            pass
    return out


# ============================================================
# 2) إرسال اللايكات
# ============================================================
async def send_like(session, target_uid, region=None, token=None,
                    provider=None, sender_uid=None):
    """يرسل لايكاً واحداً للهدف. يرجع (ok, detail)."""
    provider = (provider or config.LIKE_PROVIDER).lower()
    region = (region or config.DEFAULT_REGION).lower()

    if provider == "hlg":
        return await _send_hlg(session, target_uid, region)
    if provider == "siambhau":
        return await _send_siambhau(session, target_uid, region, token)
    if provider == "internal":
        return await _send_internal(session, target_uid, region, token, sender_uid)
    return False, f"مزوّد غير معروف: {provider}"


async def _send_hlg(session, target_uid, region):
    """HL Gaming API — موثّق: يتطلب HLG_USERUID و HLG_API_KEY من لوحة التحكم."""
    if not (config.HLG_USERUID and config.HLG_API_KEY):
        return False, "HLG_USERUID/HLG_API_KEY غير مضبوطة في config.py"
    params = {
        "sectionName": config.HLG_LIKE_SECTION,
        "PlayerUid": str(target_uid),
        "region": region,
        "useruid": config.HLG_USERUID,
        "api": config.HLG_API_KEY,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
        async with session.get(config.HLG_BASE, params=params,
                               timeout=timeout) as r:
            if r.status == 200:
                return True, "ok"
            if r.status == 429:
                return False, "rate-limited"
            return False, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)


async def _send_siambhau(session, target_uid, region, token):
    """SiamBhau API — اختر: SIAMBHAU_BASE + SIAMBHAU_KEY + jwt للحساب."""
    if not (config.SIAMBHAU_BASE and config.SIAMBHAU_KEY):
        return False, "SIAMBHAU_BASE/SIAMBHAU_KEY غير مضبوطة في config.py"
    if not token:
        return False, "يتطلب jwt/access_token لحساب مسجّل"
    url = config.SIAMBHAU_BASE.rstrip("/") + config.SIAMBHAU_LIKE_PATH
    params = {"uid": str(target_uid), "jwt": token, "key": config.SIAMBHAU_KEY}
    try:
        timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
        async with session.get(url, params=params, timeout=timeout) as r:
            return (r.status == 200), f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)


async def _send_internal(session, target_uid, region, token, sender_uid):
    """نقطة LikeProfile الداخلية: حمولة like مشفّرة AES-CBC تُرسل مع JWT."""
    if not (config.FF_LIKE_ENDPOINT and config.FF_LIKE_KEY and config.FF_LIKE_IV):
        return False, "FF_LIKE_ENDPOINT/KEY/IV غير مضبوطة (راجع config.py)"
    if not token:
        return False, "يتطلب token لحساب مسجّل"
    payload = _aes_cbc_encrypt(
        build_like_message(target_uid, sender_uid, region),
        config.FF_LIKE_KEY, config.FF_LIKE_IV,
    )
    headers = {
        "Content-Type": "application/octet-stream",
        "Authorization": f"Bearer {token}",
        "User-Agent": config.USER_AGENT,
        "Content-Length": str(len(payload)),
    }
    try:
        timeout = aiohttp.ClientTimeout(total=config.CHECK_TIMEOUT)
        async with session.post(config.FF_LIKE_ENDPOINT, data=payload,
                                headers=headers, timeout=timeout) as r:
            if r.status == 200:
                return True, "ok"
            if r.status == 429:
                return False, "rate-limited"
            if r.status in (401, 403):
                return False, f"token مرفوض (HTTP {r.status})"
            return False, f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)


# ============================================================
# 3) بناء حمولة اللايك الداخلية (protobuf + AES-CBC)
# ============================================================
# أرقام حقول رسالة like (نمط like_pb2 في مشاريع like-and-guest-api).
# تتغير بين إصدارات اللعبة — اضبطها من التقاط حركة اللعبة الحالية.
_LIKE_FIELD_UID = 1      # varint: معرّف الهدف
_LIKE_FIELD_REGION = 2   # string: رمز المنطقة
_LIKE_FIELD_SENDER = 3   # varint: معرّف المُرسل


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_field(num, wire, payload):
    return _varint((num << 3) | wire) + payload


def _pb_varint_field(num, value):
    return _pb_field(num, 0, _varint(int(value)))


def _pb_string_field(num, value):
    raw = str(value).encode("utf-8")
    return _pb_field(num, 2, _varint(len(raw)) + raw)


def build_like_message(target_uid, sender_uid, region):
    msg = b""
    msg += _pb_varint_field(_LIKE_FIELD_UID, target_uid)
    msg += _pb_string_field(_LIKE_FIELD_REGION, region.lower())
    if sender_uid:
        msg += _pb_varint_field(_LIKE_FIELD_SENDER, sender_uid)
    return msg


def _aes_cbc_encrypt(data, key_hex, iv_hex):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding

    key = bytes.fromhex(key_hex)
    iv = bytes.fromhex(iv_hex)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padded) + enc.finalize()
