"""Omni-Track Telegram Bot — entry point.

Registers handlers for text, PDF, and image messages.
Starts a weekly scheduler for AI insight generation.
"""

import os
import logging
from datetime import time, timezone

from telegram.ext import ApplicationBuilder, MessageHandler, filters
from dotenv import load_dotenv

from handlers.text import handle_text
from handlers.pdf import handle_pdf
from handlers.image import handle_image
from scheduler import generate_weekly_insight

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("omni-track-bot")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required")

    app = ApplicationBuilder().token(token).build()

    # ── Register handlers (order matters: more specific first) ────────────
    # PDF documents
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    # Photos
    app.add_handler(MessageHandler(filters.PHOTO, handle_image))
    # Plain text (catch-all for text messages)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # ── Schedule weekly insight generation (Sunday 23:00 UTC) ─────────────
    job_queue = app.job_queue
    if job_queue is not None:
        job_queue.run_daily(
            callback=lambda ctx: ctx.application.create_task(generate_weekly_insight()),
            time=time(hour=23, minute=0, tzinfo=timezone.utc),
            days=(6,),  # Sunday
            name="weekly_insight",
        )
        logger.info("Weekly insight job scheduled for Sunday 23:00 UTC")

    logger.info("Omni-Track bot starting…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
