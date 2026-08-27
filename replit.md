# Tapas Boom Bot

A small Telegram status bot with a deployment health endpoint. The project intentionally contains no third-party OTP, SMS, voice-call, WhatsApp, proxy, relay, or arbitrary-URL request functionality.

## Run

Install the Python dependency with `pip install -r requirements.txt`, set `TELEGRAM_BOT_TOKEN`, and run `python bot.py`. The optional `PORT` variable controls the health endpoint and defaults to `8443`.

## Commands

The bot supports `/start`, `/help`, and `/status`. Messages that are not commands receive a safe informational reply.

## Deployment

`Dockerfile`, `Procfile`, `app.json`, and `fly.toml` provide deployment metadata for Python hosting providers. The health endpoint responds on `/` and `/health`-compatible hosting checks through the configured port.

## Security note

No user-provided URL, phone number, API specification, or uploaded file is executed or forwarded. External request integrations remain disabled by design.
