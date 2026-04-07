"""AI extraction engine — calls Claude to extract structured metrics from user input."""

import os
import json
import logging
from dataclasses import dataclass, asdict
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Omni-Track, a data extraction agent. Your job is to extract all measurable \
metrics from the user's input and return them as structured JSON.

Rules:
- Extract EVERY numerical/quantifiable value you find.
- If a PDF contains lab results, extract ALL rows, not just obvious ones.
- If a metric has no clear timestamp, use the current time (provided in context).
- Infer the category: biometric, financial, behavioral, or custom.
- Always use snake_case for metric names (e.g., blood_pressure_systolic).
- For compound metrics like blood pressure, split into separate entries \
(blood_pressure_systolic, blood_pressure_diastolic).
- If you are given a list of existing metric names, reuse them exactly when applicable.
- Return ONLY valid JSON. No explanation. No markdown fences.

Output format:
{
  "metrics": [
    {
      "name": "blood_pressure_systolic",
      "display_name": "BP Systolic",
      "value": 120,
      "unit": "mmHg",
      "category": "biometric",
      "timestamp": "2025-07-15T08:30:00",
      "notes": "Measured after 5 min rest"
    }
  ],
  "summary": "Brief human-readable confirmation of what was logged."
}"""


@dataclass
class Metric:
    name: str
    display_name: str
    value: float
    unit: Optional[str]
    category: str
    timestamp: str
    source_type: str
    source_ref: Optional[str]
    notes: Optional[str]


_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def extract_metrics(
    content: str | None,
    source_type: str,
    message_id: str,
    current_time: str,
    existing_metrics: list[dict] | None = None,
    image_data: str | None = None,
    image_media_type: str | None = None,
) -> tuple[list[Metric], str]:
    """Call Claude to extract metrics from content.

    Returns:
        Tuple of (list of Metric objects, summary string)
    """
    context_lines = [
        f"Current time: {current_time}",
        f"Source type: {source_type}",
        f"Telegram message ID: {message_id}",
    ]
    if existing_metrics:
        names = [m["name"] for m in existing_metrics]
        context_lines.append(f"Existing metric names (reuse when applicable): {json.dumps(names)}")

    context = "\n".join(context_lines)

    user_parts: list[dict] = []

    if image_data and image_media_type:
        user_parts.append({"type": "text", "text": context + "\n\n[Content follows — see attached image/document]"})
        user_parts.append({
            "type": "image",
            "source": {"type": "base64", "media_type": image_media_type, "data": image_data},
        })
    else:
        user_parts.append({"type": "text", "text": f"{context}\n\n[Content follows]\n{content}"})

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    logger.info("Calling %s for %s extraction (msg %s)", model, source_type, message_id)

    response = _get_client().messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_parts}],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if the model wrapped its output
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    data = json.loads(raw_text)

    metrics = []
    for m in data.get("metrics", []):
        metrics.append(
            Metric(
                name=m["name"],
                display_name=m["display_name"],
                value=float(m["value"]),
                unit=m.get("unit"),
                category=m["category"],
                timestamp=m.get("timestamp", current_time),
                source_type=source_type,
                source_ref=message_id,
                notes=m.get("notes"),
            )
        )

    summary = data.get("summary", f"Extracted {len(metrics)} metric(s)")
    logger.info("Extracted %d metrics: %s", len(metrics), summary)
    return metrics, summary
