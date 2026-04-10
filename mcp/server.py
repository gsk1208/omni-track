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
        "SELECT name, display_name, unit, category, viz_type FROM metric_types ORDER BY category, name"
    )


# ── Tool 2: Upsert a reading ─────────────────────────────────────────────────


@mcp.tool()
def upsert_reading(
    metric_name: str,
    display_name: str,
    unit: Optional[str],
    category: str,
    timestamp: str,
    source_type: str,
    value: Optional[float] = None,
    source_ref: Optional[str] = None,
    notes: Optional[str] = None,
    viz_type: Optional[str] = None,
) -> dict:
    """Insert a metric reading. Auto-creates the metric type if it doesn't exist yet.

    Args:
        metric_name: snake_case unique key (e.g. "blood_pressure_systolic")
        display_name: Human-readable name (e.g. "BP Systolic")
        unit: Unit of measurement (e.g. "mmHg", "kg", "mg/dL") or null
        category: One of: biometric, financial, behavioral, custom, context
        timestamp: ISO-8601 when the measurement was taken (not ingestion time)
        source_type: One of: pdf, image, voice, text
        value: Numeric value of the reading (optional for context-only logs)
        source_ref: Optional reference ID (e.g. telegram message_id)
        notes: Optional context captured alongside the reading
        viz_type: Optional visualization type — 'bar', 'line', or 'pending'. Set on first ingestion.
    """
    # Auto-create metric type if it doesn't exist
    existing = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if existing:
        metric_type_id = existing["id"]
    else:
        vt = viz_type or "pending"
        result = db.execute_returning(
            "INSERT INTO metric_types (name, display_name, unit, category, viz_type) VALUES (?, ?, ?, ?, ?)",
            (metric_name, display_name, unit, category, vt),
        )
        metric_type_id = result["id"]
        logger.info("Created new metric type: %s (id=%s, viz=%s)", metric_name, metric_type_id, vt)

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


# ── Tool 9: Set visualization type ─────────────────────────────────────────────


@mcp.tool()
def set_viz_type(metric_name: str, viz_type: str) -> dict:
    """Set the visualization type for a metric.

    Call this after the agent classifies a metric's temporal pattern, or after
    a user chooses between bar chart and line graph.

    Args:
        metric_name: The snake_case metric name
        viz_type: 'bar' (daily totals, intermittent) or 'line' (continuous trends)
    """
    if viz_type not in ("bar", "line"):
        return {"status": "error", "message": "viz_type must be 'bar' or 'line'"}

    rows = db.execute(
        "UPDATE metric_types SET viz_type = ? WHERE name = ?",
        (viz_type, metric_name),
    )
    if rows == 0:
        return {"status": "error", "message": f"Metric '{metric_name}' not found"}
    return {"status": "ok", "metric_name": metric_name, "viz_type": viz_type}

# ── Tool 10: Set goal ─────────────────────────────────────────────────────────


@mcp.tool()
def set_goal(metric_name: str, target_value: float, target_direction: str) -> dict:
    """Set or update a daily goal for a metric.

    The scheduler/agent calls update_streak nightly to track consecutive days
    of meeting the goal. Use check_level_up to detect when the user is ready
    for a harder target.

    Args:
        metric_name: The snake_case metric name (must already exist)
        target_value: The daily target (e.g. 10 for push-ups, 8000 for steps)
        target_direction: 'gte' (at least X) or 'lte' (at most X)
    """
    if target_direction not in ("gte", "lte"):
        return {"status": "error", "message": "target_direction must be 'gte' or 'lte'"}

    mt = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if not mt:
        return {"status": "error", "message": f"Metric '{metric_name}' not found"}

    db.execute(
        """INSERT INTO metric_goals (metric_type_id, target_value, target_direction)
           VALUES (?, ?, ?)
           ON CONFLICT (metric_type_id)
           DO UPDATE SET target_value = excluded.target_value,
                         target_direction = excluded.target_direction,
                         updated_at = datetime('now')""",
        (mt["id"], target_value, target_direction),
    )

    # Initialize streak if not exists
    db.execute(
        """INSERT OR IGNORE INTO streaks (metric_type_id, current_streak, longest_streak)
           VALUES (?, 0, 0)""",
        (mt["id"],),
    )

    logger.info("Set goal for %s: %s %s", metric_name, target_direction, target_value)
    return {
        "status": "ok",
        "metric_name": metric_name,
        "target_value": target_value,
        "target_direction": target_direction,
    }


# ── Tool 11: Get goals ───────────────────────────────────────────────────────


@mcp.tool()
def get_goals() -> list[dict]:
    """Return all active goals with their current streak data.

    Each result includes: metric_name, display_name, target_value,
    target_direction, current_streak, longest_streak, last_active_date,
    and suggested_next (if a level-up has been computed).
    """
    return db.fetch_all("""
        SELECT mt.name AS metric_name, mt.display_name, mt.unit,
               mg.target_value, mg.target_direction, mg.suggested_next,
               COALESCE(s.current_streak, 0) AS current_streak,
               COALESCE(s.longest_streak, 0) AS longest_streak,
               s.last_active_date
        FROM metric_goals mg
        JOIN metric_types mt ON mg.metric_type_id = mt.id
        LEFT JOIN streaks s ON s.metric_type_id = mt.id
        ORDER BY mt.name
    """)


# ── Tool 12: Update streak ───────────────────────────────────────────────────


@mcp.tool()
def update_streak(metric_name: str, date: str) -> dict:
    """Recompute the streak for a metric on a given date.

    Call this nightly from the scheduler for each metric that has a goal.
    Checks if there's a reading on the given date that meets the goal target.
    If yes → increment streak; if no → reset streak to 0.

    Args:
        metric_name: The snake_case metric name
        date: The date to check (YYYY-MM-DD)
    """
    mt = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if not mt:
        return {"status": "error", "message": f"Metric '{metric_name}' not found"}

    goal = db.fetch_one(
        "SELECT target_value, target_direction FROM metric_goals WHERE metric_type_id = ?",
        (mt["id"],),
    )
    if not goal:
        return {"status": "error", "message": f"No goal set for '{metric_name}'"}

    # Check readings for the given date
    reading = db.fetch_one(
        """SELECT value FROM metric_readings
           WHERE metric_type_id = ? AND DATE(timestamp) = ?
           ORDER BY value DESC LIMIT 1""",
        (mt["id"], date),
    )

    met_goal = False
    if reading and reading["value"] is not None:
        if goal["target_direction"] == "gte":
            met_goal = reading["value"] >= goal["target_value"]
        else:
            met_goal = reading["value"] <= goal["target_value"]

    streak = db.fetch_one(
        "SELECT current_streak, longest_streak, last_active_date FROM streaks WHERE metric_type_id = ?",
        (mt["id"],),
    )

    current = streak["current_streak"] if streak else 0
    longest = streak["longest_streak"] if streak else 0

    if met_goal:
        current += 1
        if current > longest:
            longest = current
        last_active = date
    else:
        current = 0
        last_active = streak["last_active_date"] if streak else None

    db.execute(
        """INSERT INTO streaks (metric_type_id, current_streak, longest_streak, last_active_date, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT (metric_type_id)
           DO UPDATE SET current_streak = excluded.current_streak,
                         longest_streak = excluded.longest_streak,
                         last_active_date = excluded.last_active_date,
                         updated_at = datetime('now')""",
        (mt["id"], current, longest, last_active),
    )

    return {
        "status": "ok",
        "metric_name": metric_name,
        "date": date,
        "met_goal": met_goal,
        "reading_value": reading["value"] if reading else None,
        "current_streak": current,
        "longest_streak": longest,
    }


# ── Tool 13: Check level-up ──────────────────────────────────────────────────


@mcp.tool()
def check_level_up(metric_name: str) -> dict:
    """Check if a metric qualifies for a goal level-up.

    A level-up is suggested when the user's 7-day average exceeds the goal
    target by ≥ 20% for 7 consecutive qualifying days.

    Args:
        metric_name: The snake_case metric name
    """
    mt = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if not mt:
        return {"status": "error", "message": f"Metric '{metric_name}' not found"}

    goal = db.fetch_one(
        "SELECT target_value, target_direction FROM metric_goals WHERE metric_type_id = ?",
        (mt["id"],),
    )
    if not goal:
        return {"status": "error", "message": f"No goal set for '{metric_name}'"}

    streak = db.fetch_one(
        "SELECT current_streak FROM streaks WHERE metric_type_id = ?",
        (mt["id"],),
    )
    if not streak or streak["current_streak"] < 7:
        return {
            "status": "ok",
            "level_up": False,
            "reason": f"Current streak ({streak['current_streak'] if streak else 0}) < 7 days",
        }

    # Get last 7 readings
    readings = db.fetch_all(
        """SELECT value FROM metric_readings
           WHERE metric_type_id = ?
           ORDER BY timestamp DESC LIMIT 7""",
        (mt["id"],),
    )

    if len(readings) < 7:
        return {"status": "ok", "level_up": False, "reason": "Not enough readings (< 7)"}

    avg_val = sum(r["value"] for r in readings) / len(readings)
    target = goal["target_value"]
    threshold = target * 1.20

    if goal["target_direction"] == "gte":
        qualifies = avg_val >= threshold
    else:
        qualifies = avg_val <= target * 0.80  # For 'lte', exceeding by 20% means going 20% lower

    suggested = round(avg_val, 2)

    if qualifies:
        # Store the suggestion
        db.execute(
            "UPDATE metric_goals SET suggested_next = ? WHERE metric_type_id = ?",
            (suggested, mt["id"]),
        )

    return {
        "status": "ok",
        "level_up": qualifies,
        "current_target": target,
        "seven_day_avg": round(avg_val, 2),
        "threshold_needed": round(threshold, 2),
        "suggested_next": suggested if qualifies else None,
    }


# ── Tool 14: Rename metric ───────────────────────────────────────────────────


@mcp.tool()
def rename_metric(old_name: str, new_name: str, new_display_name: Optional[str] = None) -> dict:
    """Rename a metric type.

    Used when a first-time metric is logged and the agent asks a clarifying
    question to sub-categorize it (e.g. "blood_sugar" -> "blood_sugar_fasting").

    Args:
        old_name: The current snake_case metric name
        new_name: The new snake_case metric name
        new_display_name: Optional new human-readable display name
    """
    mt = db.fetch_one("SELECT id, display_name FROM metric_types WHERE name = ?", (old_name,))
    if not mt:
        return {"status": "error", "message": f"Metric '{old_name}' not found"}

    display_name = new_display_name or mt["display_name"]
    db.execute(
        "UPDATE metric_types SET name = ?, display_name = ? WHERE id = ?",
        (new_name, display_name, mt["id"]),
    )
    logger.info("Renamed metric from %s to %s", old_name, new_name)

    return {
        "status": "ok",
        "old_name": old_name,
        "new_name": new_name,
        "new_display_name": display_name,
    }


# ── Tool 15: Get metric context ──────────────────────────────────────────────


@mcp.tool()
def get_metric_context(metric_name: str, days: int = 30) -> list[dict]:
    """Retrieve all contextual notes logged alongside a metric over recent days.

    Args:
        metric_name: The snake_case metric name to fetch context for
        days: How many days back to look
    """
    mt = db.fetch_one("SELECT id FROM metric_types WHERE name = ?", (metric_name,))
    if not mt:
        return []

    return db.fetch_all(
        """SELECT timestamp, value, notes, source_type 
           FROM metric_readings 
           WHERE metric_type_id = ? AND timestamp >= DATE('now', '-' || ? || ' days')
             AND notes IS NOT NULL
           ORDER BY timestamp DESC""",
        (mt["id"], days),
    )


# ── Entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    db.init_db()
    logger.info("Starting Omni-Track MCP server on 0.0.0.0:8000 (SSE transport)")
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
