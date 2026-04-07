"""Handler for photo/image messages."""

import base64
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

import agent
import mcp_client
from handlers import log_metrics_and_reply

logger = logging.getLogger(__name__)


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.photo:
        return

    msg_id = str(message.message_id)
    current_time = datetime.now(timezone.utc).isoformat()

    await message.reply_text("🖼️ Processing image…")

    # Telegram sends multiple sizes; grab the highest resolution
    photo = message.photo[-1]
    file = await photo.get_file()
    file_bytes = await file.download_as_bytearray()
    file_b64 = base64.b64encode(file_bytes).decode("utf-8")

    try:
        existing = await mcp_client.list_metric_types()
    except Exception:
        existing = []

    try:
        metrics, summary = agent.extract_metrics(
            content=None,
            source_type="image",
            message_id=msg_id,
            current_time=current_time,
            existing_metrics=existing,
            image_data=file_b64,
            image_media_type="image/jpeg",
        )
    except Exception as e:
        logger.error("Image extraction failed: %s", e, exc_info=True)
        await message.reply_text(f"❌ Failed to process image: {e}")
        return

    await log_metrics_and_reply(message, metrics, summary)
