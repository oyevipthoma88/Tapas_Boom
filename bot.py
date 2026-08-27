"""Tapas Boom Telegram bot.

This project intentionally contains no third-party OTP, SMS, voice-call, or
WhatsApp request integrations. It provides only basic bot status/help replies
and a lightweight health endpoint for deployment monitoring.
"""

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    raise SystemExit(
        "TELEGRAM_BOT_TOKEN missing! Set it in the deployment environment."
    )

PORT = int(os.environ.get("PORT", 8443))


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Help", callback_data="help"),
                InlineKeyboardButton("Status", callback_data="status"),
            ]
        ]
    )


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Tapas Boom is running.\n\n"
        "The external OTP, SMS, voice-call, WhatsApp, proxy, and custom-URL "
        "request features have been removed.\n\n"
        "Use /help for available commands.",
        reply_markup=_menu(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Available commands:\n\n"
        "/start — show the bot overview\n"
        "/help — show this help message\n"
        "/status — show runtime status\n\n"
        "This bot does not send OTPs or make automated requests to third-party "
        "services."
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Bot status: online\n"
        "External request integrations: disabled\n"
        "OTP/SMS/call/WhatsApp endpoints: 0"
    )


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "I only provide status and help information now. Use /help to see the "
        "available commands."
    )


async def handle_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "help":
        await query.edit_message_text(
            "Available commands:\n\n"
            "/start — show the bot overview\n"
            "/help — show this help message\n"
            "/status — show runtime status\n\n"
            "External OTP and arbitrary URL request features are disabled."
        )
    elif query.data == "status":
        await query.edit_message_text(
            "Bot status: online\n"
            "External request integrations: disabled\n"
            "OTP/SMS/call/WhatsApp endpoints: 0"
        )


def _start_health_server() -> None:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Tapas Boom bot is running")

        def do_HEAD(self) -> None:  # noqa: N802
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args) -> None:
            return

    def serve() -> None:
        try:
            HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()
        except Exception as exc:
            logger.warning("Health server stopped: %s", exc)

    threading.Thread(target=serve, daemon=True).start()
    logger.info("Health server listening on port %d", PORT)


def main() -> None:
    _start_health_server()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info(
        "Tapas Boom started in safe mode; external OTP/SMS/call/WhatsApp "
        "integrations are disabled"
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
