"""Shared helpers for Telegram message handlers."""

import logging
from telegram import Message
from fastmcp import Client
import os, json

logger = logging.getLogger(__name__)

MCP_SSE_URL = os.environ.get("MCP_BASE_URL", "http://mcp:8000") + "/sse"


async def log_metrics_and_reply(message: Message, metrics: list, summary: str) -> None:
    """Upsert a batch of extracted Metric objects via MCP and reply to the user.

    Uses a single MCP session for all upserts to avoid repeated handshakes.
    """
    if not metrics:
        await message.reply_text("ℹ️ No measurable metrics found in your message.")
        return

    logged: list[str] = []
    errors: list[str] = []

    async with Client(MCP_SSE_URL) as client:
        for m in metrics:
            try:
                result = await client.call_tool("upsert_reading", {
                    "metric_name": m.name,
                    "display_name": m.display_name,
                    "value": m.value,
                    "unit": m.unit,
                    "category": m.category,
                    "timestamp": m.timestamp,
                    "source_type": m.source_type,
                    "source_ref": m.source_ref,
                    "notes": m.notes,
                })
                unit_str = f" {m.unit}" if m.unit else ""
                logged.append(f"{m.display_name}: {m.value}{unit_str}")
            except Exception as e:
                logger.error("Failed to upsert %s: %s", m.name, e)
                errors.append(f"{m.display_name}: {e}")

    lines = []
    if logged:
        lines.append("✅ Logged:")
        lines.extend(f"  • {entry}" for entry in logged)
    if errors:
        lines.append("\n⚠️ Errors:")
        lines.extend(f"  • {entry}" for entry in errors)
    if summary:
        lines.append(f"\n📝 {summary}")

    await message.reply_text("\n".join(lines))
