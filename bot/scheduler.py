"""Weekly insight generator — runs as a scheduled job inside the bot."""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

import anthropic
import mcp_client

logger = logging.getLogger(__name__)

INSIGHT_PROMPT = """You are an analyst reviewing the past 7 days of personal health and life metrics.
Here is the data:

{data}

Write a concise insight block (150–250 words) covering:
1. Notable trends (improving or declining metrics)
2. Any correlations worth flagging (e.g., fewer workouts coinciding with rising BP)
3. One concrete recommendation for the coming week

Write in second person, direct tone. No fluff."""


async def generate_weekly_insight() -> None:
    """Fetch the past week's data, generate an insight via Claude, and store it."""
    logger.info("Starting weekly insight generation")

    try:
        metric_types = await mcp_client.list_metric_types()
    except Exception as e:
        logger.error("Failed to fetch metric types: %s", e)
        return

    if not metric_types:
        logger.info("No metric types registered — skipping insight generation")
        return

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=7)

    all_readings: dict[str, list] = {}
    for mt in metric_types:
        try:
            readings = await mcp_client.get_readings(
                metric_name=mt["name"],
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
            )
            if readings:
                all_readings[mt.get("display_name", mt["name"])] = readings
        except Exception as e:
            logger.warning("Failed to fetch readings for %s: %s", mt["name"], e)

    if not all_readings:
        logger.info("No readings in the past 7 days — skipping insight")
        return

    # Generate insight via Claude
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": INSIGHT_PROMPT.format(data=json.dumps(all_readings, indent=2, default=str)),
        }],
    )

    insight_text = response.content[0].text.strip()

    # Week start = most recent Monday
    today = datetime.now(timezone.utc).date()
    week_start = today - timedelta(days=today.weekday())

    try:
        await mcp_client.log_insight(week_start=week_start.isoformat(), content=insight_text)
        logger.info("Weekly insight stored for week of %s", week_start)
    except Exception as e:
        logger.error("Failed to store insight: %s", e)
