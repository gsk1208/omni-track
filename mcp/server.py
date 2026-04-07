"""Omni-Track MCP Server — exposes life-metric tools via SSE for any MCP-compatible agent.

Zero-install local mode: uses SQLite. For production, swap db.py to PostgreSQL.
"""

import logging
from typing import Optional
from datetime import datetime

from fastmcp import FastMCP
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("omni-track-mcp")

mcp = FastMCP(
    "Omni-Track",
    instructions=(
        "Life metrics tracking system. Stores and retrieves health, financial, "
        "and behavioral metrics in a time-series database. Self-extending schema — "
        "new metric types are created automatically on first upsert."
    ),
)


# ── Tool 1: List metric types ────────────────────────────────────────────────


@mcp.tool()
def list_metric_types() -> list[dict]:
    """List all registered metric types.

    Call this BEFORE upserting readings so you can reuse existing metric names
    and maintain consistent naming (snake_case).
    """
    return db.fetch_all(
        "SELECT name, display_name, unit, category FROM metric_types ORDER BY category, name"
    )


# ── Tool 2: Upsert a reading ─────────────────────────────────────────────────


@mcp.tool()
def upsert_reading(
    metric_name: str,
    display_name: str,
    value: float,
    unit: Optional[str],
    category: str,
    timestamp: str,
    source_type: str,
    source_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Insert a metric reading. Auto-creates the metric type if it doesn't exist yet.

    Args:
        metric_name: snake_case unique key (e.g. "blood_pressure_systolic")
        display_name: Human-readable name (e.g. "BP Systolic")
        value: Numeric value of the reading
        unit: Unit of measurement (e.g. "mmHg", "kg", "mg/dL") or null
        category: One of: biometric, financial, behavioral, custom
        timestamp: ISO-8601 when the measurement was taken (not ingestion time)
        source_type: One of: pdf, image, voice, text
        source_ref: Optional reference ID (e.g. telegram message_id)
        notes: Optional context captured alongside the reading
    """
    # Auto-create metric type if it doesn't exist
    existing = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if existing:
        metric_type_id = existing["id"]
    else:
        result = db.execute_returning(
            "INSERT INTO metric_types (name, display_name, unit, category) VALUES (?, ?, ?, ?)",
            (metric_name, display_name, unit, category),
        )
        metric_type_id = result["id"]
        logger.info("Created new metric type: %s (id=%s)", metric_name, metric_type_id)

    # Upsert reading (INSERT OR REPLACE for SQLite)
    db.execute(
        """INSERT INTO metric_readings (metric_type_id, value, timestamp, source_type, source_ref, notes)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (metric_type_id, timestamp)
           DO UPDATE SET value = excluded.value,
                         source_type = excluded.source_type,
                         source_ref  = excluded.source_ref,
                         notes       = excluded.notes,
                         ingested_at = datetime('now')""",
        (metric_type_id, value, timestamp, source_type, source_ref, notes),
    )

    # Fetch the reading id
    row = db.fetch_one(
        "SELECT id FROM metric_readings WHERE metric_type_id = ? AND timestamp = ?",
        (metric_type_id, timestamp),
    )
    reading_id = row["id"] if row else None

    logger.info("Upserted reading: %s = %s %s", metric_name, value, unit or "")
    return {"status": "ok", "metric_name": metric_name, "value": value, "reading_id": reading_id}


# ── Tool 3: Get readings (time-series) ───────────────────────────────────────


@mcp.tool()
def get_readings(
    metric_name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    """Fetch time-series readings for a specific metric.

    Args:
        metric_name: The snake_case metric name
        start_date: Optional ISO date/datetime for range start (inclusive)
        end_date: Optional ISO date/datetime for range end (inclusive)
    """
    query = """
        SELECT mr.value, mr.timestamp, mr.source_type, mr.notes, mt.unit
        FROM metric_readings mr
        JOIN metric_types mt ON mr.metric_type_id = mt.id
        WHERE mt.name = ?
    """
    params: list = [metric_name]

    if start_date:
        query += " AND mr.timestamp >= ?"
        params.append(start_date)
    if end_date:
        query += " AND mr.timestamp <= ?"
        params.append(end_date)

    query += " ORDER BY mr.timestamp ASC"
    return db.fetch_all(query, params)


# ── Tool 4: Get latest per metric ────────────────────────────────────────────


@mcp.tool()
def get_latest(category: Optional[str] = None) -> list[dict]:
    """Get the most recent reading for each metric, optionally filtered by category.

    Args:
        category: Optional — one of: biometric, financial, behavioral, custom
    """
    query = """
        SELECT mt.name, mt.display_name, mt.unit, mt.category,
               mr.value, mr.timestamp, mr.notes
        FROM metric_readings mr
        JOIN metric_types mt ON mr.metric_type_id = mt.id
        WHERE mr.id IN (
            SELECT mr2.id FROM metric_readings mr2
            JOIN metric_types mt2 ON mr2.metric_type_id = mt2.id
    """
    params = []
    if category:
        query += " WHERE mt2.category = ?"
        params.append(category)
    query += """
            GROUP BY mr2.metric_type_id
            HAVING mr2.timestamp = MAX(mr2.timestamp)
        )
    """
    if category:
        query += " AND mt.category = ?"
        params.append(category)
    query += " ORDER BY mt.name"
    return db.fetch_all(query, params)


# ── Tool 5: Get all latest ───────────────────────────────────────────────────


@mcp.tool()
def get_all_latest() -> list[dict]:
    """Returns the single most recent reading for every registered metric.

    Includes safe range bounds (min/max) if configured. Ideal for dashboard overviews.
    """
    return db.fetch_all("""
        SELECT mt.name, mt.display_name, mt.unit, mt.category,
               mr.value, mr.timestamp, mr.notes,
               sr.min_value AS safe_min, sr.max_value AS safe_max
        FROM metric_readings mr
        JOIN metric_types mt ON mr.metric_type_id = mt.id
        LEFT JOIN safe_ranges sr ON sr.metric_name = mt.name
        WHERE mr.id IN (
            SELECT mr2.id FROM metric_readings mr2
            GROUP BY mr2.metric_type_id
            HAVING mr2.timestamp = MAX(mr2.timestamp)
        )
        ORDER BY mt.name
    """)


# ── Tool 6: Log weekly insight ───────────────────────────────────────────────


@mcp.tool()
def log_insight(week_start: str, content: str) -> dict:
    """Store a weekly AI-generated insight block.

    Args:
        week_start: The Monday date of the insight week (YYYY-MM-DD)
        content: The insight text (150-250 words recommended)
    """
    db.execute(
        """INSERT INTO insights (week_start, content)
           VALUES (?, ?)
           ON CONFLICT (week_start)
           DO UPDATE SET content = excluded.content, generated_at = datetime('now')""",
        (week_start, content),
    )
    row = db.fetch_one("SELECT id, generated_at FROM insights WHERE week_start = ?", (week_start,))
    return {"status": "ok", "insight_id": row["id"], "week_start": week_start}


# ── Tool 7: Set safe range ───────────────────────────────────────────────────


@mcp.tool()
def set_safe_range(
    metric_name: str,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> dict:
    """Set or update the safe/reference range for a metric.

    Used by dashboards to draw threshold lines. For example:
    - fasting_blood_sugar: min=70, max=100 (mg/dL)
    - blood_pressure_systolic: min=90, max=120 (mmHg)

    Args:
        metric_name: The snake_case metric name
        min_value: Lower bound of safe range (null to leave unset)
        max_value: Upper bound of safe range (null to leave unset)
    """
    db.execute(
        """INSERT INTO safe_ranges (metric_name, min_value, max_value)
           VALUES (?, ?, ?)
           ON CONFLICT (metric_name)
           DO UPDATE SET min_value  = excluded.min_value,
                         max_value  = excluded.max_value,
                         updated_at = datetime('now')""",
        (metric_name, min_value, max_value),
    )
    return {"status": "ok", "metric_name": metric_name, "min": min_value, "max": max_value}


# ── Tool 8: Get safe ranges ──────────────────────────────────────────────────


@mcp.tool()
def get_safe_ranges(metric_name: Optional[str] = None) -> list[dict]:
    """Get configured safe/reference ranges for metrics.

    Args:
        metric_name: If provided, returns range for just this metric. Otherwise returns all.
    """
    if metric_name:
        result = db.fetch_one(
            "SELECT metric_name, min_value, max_value FROM safe_ranges WHERE metric_name = ?",
            (metric_name,),
        )
        return [result] if result else []
    return db.fetch_all("SELECT metric_name, min_value, max_value FROM safe_ranges ORDER BY metric_name")


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    logger.info("Starting Omni-Track MCP server on 0.0.0.0:8000 (SSE transport)")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
