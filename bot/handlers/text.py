"""Handler for plain text messages."""

import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

import agent
import mcp_client
from handlers import log_metrics_and_reply

logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    text = message.text
    msg_id = str(message.message_id)
    current_time = datetime.now(timezone.utc).isoformat()

    # Fetch existing metric types so the agent reuses consistent names
    try:
        existing = await mcp_client.list_metric_types()
    except Exception:
        existing = []

    try:
        metrics, summary = agent.extract_metrics(
            content=text,
            source_type="text",
            message_id=msg_id,
            current_time=current_time,
            existing_metrics=existing,
        )
    except Exception as e:
        logger.error("Agent extraction failed: %s", e, exc_info=True)
        await message.reply_text(f"❌ Failed to extract metrics: {e}")
        return

    await log_metrics_and_reply(message, metrics, summary)
