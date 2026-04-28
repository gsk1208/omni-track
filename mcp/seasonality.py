"""Seasonality insights for Omni-Track metrics.

Computes weekday/weekend and month-of-year patterns from raw readings.

Design goal: deterministic, unit-testable logic that doesn't depend on SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_LABELS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def _parse_ts(ts: str) -> datetime:
    # Handle both ISO with 'Z' and naive ISO.
    s = (ts or "").strip()
    if not s:
        raise ValueError("missing timestamp")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _mean(xs: list[float]) -> float | None:
    if not xs:
        return None
    return sum(xs) / len(xs)


def _aggregate_daily(readings: Iterable[dict], mode: str) -> list[tuple[datetime, float]]:
    """Aggregate to daily points.

    mode:
      - 'sum' for bar-like metrics (daily totals)
      - 'mean' for line-like metrics (daily average)
    """
    by_day: dict[str, list[float]] = {}
    for r in readings:
        v = r.get("value")
        ts = r.get("timestamp")
        if v is None or ts is None:
            continue
        dt = _parse_ts(ts)
        day = dt.date().isoformat()
        by_day.setdefault(day, []).append(float(v))

    out: list[tuple[datetime, float]] = []
    for day in sorted(by_day.keys()):
        xs = by_day[day]
        if not xs:
            continue
        if mode == "sum":
            val = sum(xs)
        else:
            val = _mean(xs)
        if val is None:
            continue
        out.append((datetime.fromisoformat(day).replace(tzinfo=timezone.utc), float(val)))
    return out


def compute_seasonality(readings: list[dict], viz_type: str = "line") -> dict:
    """Return seasonality insights.

    Output shape:
      {
        weekday: [{dow,label,value,count}],  # Mon..Sun
        weekend_vs_weekday: {weekday_avg, weekend_avg, delta, delta_pct},
        month: [{month,label,value,count}]   # Jan..Dec
      }
    """

    mode = "sum" if (viz_type or "").lower() == "bar" else "mean"
    daily = _aggregate_daily(readings, mode=mode)
    if not daily:
        return {
            "weekday": [],
            "weekend_vs_weekday": {
                "weekday_avg": None,
                "weekend_avg": None,
                "delta": None,
                "delta_pct": None,
            },
            "month": [],
        }

    # weekday buckets: Mon=0..Sun=6
    dow_vals: dict[int, list[float]] = {i: [] for i in range(7)}
    month_vals: dict[int, list[float]] = {i: [] for i in range(1, 13)}
    for dt, v in daily:
        dow = dt.weekday()
        dow_vals[dow].append(float(v))
        month_vals[dt.month].append(float(v))

    weekday = []
    for dow in range(7):
        xs = dow_vals.get(dow, [])
        weekday.append(
            {
                "dow": dow,
                "label": DOW_LABELS[dow],
                "value": _mean(xs),
                "count": len(xs),
            }
        )

    weekday_xs = []
    weekend_xs = []
    for dow in range(7):
        xs = dow_vals.get(dow, [])
        if dow in (5, 6):
            weekend_xs.extend(xs)
        else:
            weekday_xs.extend(xs)
    weekday_avg = _mean(weekday_xs)
    weekend_avg = _mean(weekend_xs)
    delta = None
    delta_pct = None
    if weekday_avg is not None and weekend_avg is not None:
        delta = weekend_avg - weekday_avg
        if weekday_avg != 0:
            delta_pct = (delta / weekday_avg) * 100.0

    month = []
    for m in range(1, 13):
        xs = month_vals.get(m, [])
        month.append(
            {
                "month": m,
                "label": MONTH_LABELS[m - 1],
                "value": _mean(xs),
                "count": len(xs),
            }
        )

    return {
        "weekday": weekday,
        "weekend_vs_weekday": {
            "weekday_avg": weekday_avg,
            "weekend_avg": weekend_avg,
            "delta": delta,
            "delta_pct": delta_pct,
        },
        "month": month,
    }

