# 🤖 Tapas Boom v4.3 — Telegram OTP Bot

> Phone number bhejo → SMS + Call + WhatsApp OTPs, 50+ services ek saath.
> **Proxy-free, relay-free, jugaad-free — sirf direct API calls.**

---

## ✨ v4.3 — Kya naya hai

- ❌ **Relay pool hata diya** — koi CORS-relay fallback nahi, koi force-relay
  host list nahi, koi auto-blacklist nahi.
- ❌ **33-jugaad doc hata diya** — code se jo jugaad ab use nahi ho raha
  wo documentation bhi gone.
- ✅ Har API **directly** hit hoti hai (aiohttp + rotating UA + retry).
- ✅ Naye debug tools: `/debug` aur `/test` — kis API ne kya status/body
  diya wo saaf dikh jaata hai.
- ✅ User-added APIs: `/addapi` ya `.txt` file upload karke bulk add.

---

## 🚀 Quick Start

```bash
git clone https://github.com/oyevipthoma88/Tapas_Boom.git
cd Tapas_Boom
pip install -r requirements.txt
cp .env.example .env
# .env me TELEGRAM_BOT_TOKEN set karo
python bot.py
```

`python-telegram-bot >= 20`, `aiohttp >= 3.9`, `python-dotenv` — bas itni
dependencies.

---

## 📱 Termux (100% real Indian IP)

```bash
pkg update && pkg upgrade -y
pkg install python git -y
git clone https://github.com/oyevipthoma88/Tapas_Boom.git
cd Tapas_Boom
pip install -r requirements-termux.txt
cp .env.example .env
nano .env      # TELEGRAM_BOT_TOKEN daalo
python bot.py
```

Background:
```bash
termux-wake-lock
nohup python bot.py > bot.log 2>&1 &
```

---

## ☁️ Deploy

### Heroku (one-click)
[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/oyevipthoma88/Tapas_Boom)

```bash
heroku create tapas-boom-yourname
heroku config:set TELEGRAM_BOT_TOKEN=xxxxx
heroku config:set WEBHOOK_URL=https://tapas-boom-yourname.herokuapp.com  # optional
git push heroku main
```

### Fly.io (India egress — `bom` region recommended)
Repo me `Dockerfile` + `fly.toml` ready hai:
```bash
fly launch --no-deploy
fly secrets set TELEGRAM_BOT_TOKEN=xxxxx
fly deploy
```

### Docker
```bash
docker build -t tapas-boom .
docker run -e TELEGRAM_BOT_TOKEN=xxxxx tapas-boom
```

---

## 🤖 Bot Commands

| Command | Kaam |
|---|---|
| `/start` | Bot shuru + menu |
| `/help` | Help + usage |
| `/status` | Live health — kaunsa API up/down |
| `/stats` | Aggregate success/fail counts |
| `/recover` | Failed APIs ko dobara enable karo |
| `/sms <mobile>` | Sirf SMS blast |
| `/call <mobile>` | Sirf Call blast |
| `/wa <mobile>` | Sirf WhatsApp blast |
| `/blast <mobile> [rounds]` | Sab teen channels, N rounds |
| `/debug <mobile>` | Har API ka HTTP status + body dikhata hai |
| `/test <mobile> <api_name>` | Ek specific API live test karo |
| `/addapi ...` | Naya API register karo (spec paste karo) |
| Upload `.txt` | Bulk API specs upload karke ek saath add |

---

## 🛠️ Environment Variables

| Variable | Zaroori? | Kaam |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | @BotFather se lo |
| `WEBHOOK_URL` | ⛔ Optional | Set karoge to webhook mode, warna long-polling |
| `PORT` | ⛔ Optional | Default `8443` (webhook mode) |
| `PING_URL` | ⛔ Optional | UptimeRobot/BetterUptime waali URL — self-ping ke liye |

`.env.example` me sab likha hai.

---

## 📁 Repo Layout

```
Tapas_Boom/
├── bot.py                  # Main bot — 50+ APIs, direct calls only
├── premium_buttons.py      # Inline keyboard factory
├── requirements.txt        # Production deps
├── requirements-termux.txt # Termux-specific deps
├── Procfile                # Heroku
├── Dockerfile              # Docker / Fly.io
├── fly.toml                # Fly.io config (bom region)
├── app.json                # Heroku deploy button
├── worker.js               # Optional Cloudflare Worker relay (opt-in)
├── .env.example
└── README.md
```

`artifacts/`, `lib/`, `scripts/`, `pnpm-workspace.yaml` — Node/TS
sandbox aur helper workspaces, bot chalane ke liye zaroori nahi.

---

## 🧭 Design Notes

- **Direct-only calls**: har request `aiohttp` se seedha provider ko jaati
  hai. Rotating UA, retry-with-backoff, per-host connection cap — bas.
- **Health tracking**: fail ho rahi APIs auto-mute ho jaati hain; `/recover`
  se wapas on kar sakte ho.
- **User APIs**: `/addapi` ya text file — spec parse hoke same runtime me
  register ho jaati hai; restart ki zaroorat nahi.
- **Webhook ya polling**: `WEBHOOK_URL` set to webhook, warna long-polling.

---

## ⚠️ Disclaimer

Sirf apne khud ke numbers pe testing / educational use ke liye. Kisi
aur ko spam / harass karne ke liye use karna illegal hai — jo bhi karoge,
apni responsibility.
