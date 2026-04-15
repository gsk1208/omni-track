"""Simple forecasting + cross-metric driver scoring (Phase: predictive-analysis).

Design goals:
- Server-side compute (dashboard stays simple)
- Works with sparse data
- Provides point forecast + confidence band
- Provides top drivers using recent-lag correlations (quick, explainable-ish)

This is intentionally lightweight (numpy-only).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import math


def _to_dt(ts: str) -> datetime:
    # timestamps stored like '2026-04-11T08:00:00'
    return datetime.fromisoformat(ts.replace("Z", ""))


def _day_key(dt: datetime) -> str:
    return dt.date().isoformat()


def aggregate_daily(readings: List[dict]) -> List[Tuple[datetime, float]]:
    m: Dict[str, float] = {}
    for r in readings:
        v = r.get("value")
        if v is None:
            continue
        dt = _to_dt(r["timestamp"])
        k = _day_key(dt)
        m[k] = m.get(k, 0.0) + float(v)
    days = sorted(m.keys())
    out = []
    for d in days:
        out.append((datetime.fromisoformat(d), m[d]))
    return out


def as_series(readings: List[dict], viz_type: str) -> List[Tuple[datetime, float]]:
    if viz_type == "bar":
        return aggregate_daily(readings)
    pts = []
    for r in readings:
        v = r.get("value")
        if v is None:
            continue
        pts.append((_to_dt(r["timestamp"]), float(v)))
    pts.sort(key=lambda x: x[0])
    return pts


def mean(xs: List[float]) -> float:
    return sum(xs) / len(xs)


def std(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    v = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(max(v, 0.0))


def corr(a: List[float], b: List[float]) -> float:
    if len(a) != len(b) or len(a) < 3:
        return 0.0
    ma, mb = mean(a), mean(b)
    da = [x - ma for x in a]
    db = [x - mb for x in b]
    num = sum(x * y for x, y in zip(da, db))
    den = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    return float(num / den) if den else 0.0


@dataclass
class Forecast:
    points: List[dict]  # {timestamp,value,low,high}
    model: str
    horizon: int
    granularity: str


def forecast_baseline(series: List[Tuple[datetime, float]], horizon: int, cadence: str = "daily") -> Forecast:
    """Opaque-ish but stable: rolling mean + volatility-based band.

    cadence:
      - daily: horizon points, 1 day step
      - weekly: horizon points, 7 day step
      - monthly: horizon points, 30 day step (approx)
      - other: 1 point
    """
    ys = [y for _, y in series]
    if len(ys) < 7:
        return Forecast(points=[], model="baseline", horizon=horizon, granularity=cadence)

    window = min(30, len(ys))
    base = mean(ys[-window:])
    vol = std(ys[-window:])

    last_t = series[-1][0]
    step_days = 1
    if cadence == "weekly":
        step_days = 7
    elif cadence == "monthly":
        step_days = 30

    pts = []
    for i in range(1, horizon + 1):
        t = last_t + timedelta(days=step_days * i)
        pts.append(
            {
                "timestamp": t.date().isoformat(),
                "value": base,
                "low": base - 1.96 * vol,
                "high": base + 1.96 * vol,
            }
        )
    return Forecast(points=pts, model="rolling-mean", horizon=horizon, granularity=cadence)


def driver_scores(
    target_name: str,
    target_series: List[Tuple[datetime, float]],
    other_series: Dict[str, List[Tuple[datetime, float]]],
) -> List[dict]:
    """Score drivers by correlation of recent aligned daily series.

    Returns top drivers with lag=0 and lag=1 day correlations.
    """

    # align by day keys
    def to_map(s):
        return {_day_key(t): y for t, y in s}

    tmap = to_map(target_series)
    if len(tmap) < 10:
        return []

    out = []
    for name, s in other_series.items():
        if name == target_name:
            continue
        smap = to_map(s)
        keys = sorted(set(tmap.keys()) & set(smap.keys()))
        if len(keys) < 10:
            continue
        ta = [tmap[k] for k in keys]
        sa = [smap[k] for k in keys]
        c0 = corr(sa, ta)
        # lag-1: yesterday driver vs today target
        keys_l1 = [k for k in keys[1:]]
        sa1 = [smap[k_prev] for k_prev in keys[:-1]]
        ta1 = [tmap[k] for k in keys_l1]
        c1 = corr(sa1, ta1)
        score = max(abs(c0), abs(c1))
        out.append({"metric": name, "corr0": c0, "corr1": c1, "score": score})

    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:5]
