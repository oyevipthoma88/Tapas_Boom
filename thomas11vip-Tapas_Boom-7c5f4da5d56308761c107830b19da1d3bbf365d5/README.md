# 🤖 Tapas Boom v3 — Telegram OTP Bot

> Phone number enter karo → SMS, Call, WhatsApp — 50+ services ek saath!

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/thomas82822/Tapas_Boom)

---

## ⚡ v3 — 33 Jugaad + 50+ APIs

| Channel | APIs | Sources |
|---------|------|---------|
| 📩 SMS | 45+ | WAFA, BomBX, manual verify |
| 📞 Call | 15 | Housing, Treebo, NoBroker, 99acres... |
| 💬 WhatsApp | 14 | Myntra, Swiggy, JioMart, Nathabit... |

---

## 🛡️ 33 Jugaad — Heroku USA pe Working

| # | Jugaad | Faida |
|---|--------|-------|
| J01 | Indian Proxy (PROXY_URL) | **Sab traffic Indian IP se — calls ZAROOR aayengi** |
| J02 | Webhook mode | Polling se better for Heroku |
| J03 | /ping keepalive server | Dyno so nahi payega |
| J04 | Self-ping har 25 min | Heroku 30-min sleep block |
| J05 | 4 DNS servers fallback | Indian .in domains resolve hote hain |
| J06 | DNS in-memory cache | Repeat lookup zero |
| J07 | IPv6→A fallback | DNS reliability |
| J08 | 8 rotating UAs | Chrome/Samsung/Poco/OnePlus |
| J09 | 25 Indian IP ranges | Jio/Airtel/Vi/BSNL/ACT |
| J10 | Cloudflare bypass (CF-IPCountry:IN) | CF-protected sites |
| J11 | sec-ch-ua fingerprint | Modern Chrome Android |
| J12 | sec-fetch-* headers | Real XHR ki tarah |
| J13 | True-Client-IP + RFC7239 Forwarded | Extra IP spoof |
| J14 | Accept-Encoding gzip | Real browser |
| J15 | Retry 3× exponential backoff | Network hiccup heal |
| J16 | Asyncio semaphore 8 | Rate-limit protection |
| J17 | Per-host connection cap 4 | No server overwhelm |
| J18 | aiohttp CookieJar | Session cookies |
| J19 | connect(8s)/read(22s) timeout | US→India latency |
| J20 | OK status 200-206+302/303 | All success codes |
| J21 | Random name/email/device generator | User-info APIs |
| J22 | BLAST mode (/blast N rounds) | Multiple rounds |
| J23 | Smart keyword check | Body scan for OTP confirm |
| J24 | Per-API Content-Type | Correct headers |
| J25 | Referer+Origin matching | Anti-hotlink bypass |
| J26 | SSL verify=False | India cert issues |
| J27 | X-Request-ID UUID | Request tracking spoof |
| J28 | Keep-Alive + pool reuse | Performance |
| J29 | DNS cache flush 6hr | Stale cache prevent |
| J30 | /status command | Live health check |
| J31 | Parallel SMS+Call+WA | Ek saath teen channels |
| J32 | Progress message | UX |
| J33 | /blast command | Repeat bombing |

---

## 📞 Calls ke liye (SABSE ZAROORI)

**Option A — Indian Proxy (Best, 100% calls):**
```
Heroku Config Vars mein set karo:
PROXY_URL = http://username:password@indian-proxy-ip:port
```
Free proxy: [sslproxies.org](https://www.sslproxies.org/) → Country: India filter
Paid (best): BrightData / IPRoyal India Residential

**Option B — Termux (100% calls):**
```bash
TERMUX_MODE=1 python bot.py
```

**Option C — Bina proxy Heroku (SMS mostly, Calls 60-70%):**
Deploy karo aur test karo — bahut si services globally work karti hain

---

## 🚀 Heroku Deploy

### Method 1 — One-Click Button
Upar wala "Deploy to Heroku" button click karo.

### Method 2 — Manual
```bash
heroku create tapas-boom-yourname
heroku config:set TELEGRAM_BOT_TOKEN=your_token
heroku config:set PROXY_URL=http://user:pass@indian-proxy:port  # optional but recommended
heroku config:set WEBHOOK_URL=https://tapas-boom-yourname.herokuapp.com  # optional
git push heroku main
```

---

## 📱 Termux Setup (100% Working — Real Indian IP)

```bash
pkg update && pkg upgrade -y
pkg install python git -y
git clone https://github.com/thomas82822/Tapas_Boom.git
cd Tapas_Boom
pip install -r requirements.txt
cp .env.example .env
nano .env  # TELEGRAM_BOT_TOKEN + TERMUX_MODE=1 set karo
python bot.py
```

Background mein:
```bash
termux-wake-lock
nohup python bot.py > bot.log 2>&1 &
```

---

## 🤖 Bot Commands

| Command | Kya karta hai |
|---------|--------------|
| `/start` | Bot shuru karo |
| `/help` | Help + proxy info |
| `/status` | Live health — proxy/DNS/APIs |
| `/blast 7873110898 3` | 3 rounds full blast |

---

## 📁 Files

```
Tapas_Boom/
├── bot.py              # Main bot — 33 jugaad + 50+ APIs
├── Procfile            # Heroku web dyno
├── app.json            # Heroku deploy button config
├── runtime.txt         # Python 3.11
├── requirements.txt    # aiohttp + aiohttp-socks + dnspython
├── .env.example        # Template with all vars explained
└── README.md
```

---

## 🛠️ Environment Variables

| Variable | Required | Explanation |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | @BotFather se |
| `PROXY_URL` | ⚠️ Recommended | Indian proxy → calls ke liye |
| `WEBHOOK_URL` | Optional | Heroku app URL for webhook mode |
| `TERMUX_MODE` | Optional | `1` for Termux |
