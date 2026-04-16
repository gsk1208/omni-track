"""Predictive analysis helpers.

V1 scope (step-by-step):
- Provide forecast points + confidence band for a single metric.
- Cadence-specific horizons:
  - daily: 7 points (daily)
  - weekly: 3 points (weekly)
  - monthly: 3 points (monthly)
  - other: 1 point

Model policy (per user): prefer more accurate but opaque ML.
Implementation here: lightweight regression + residual-based band.
(No external deps, numpy-only.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import math

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


def _to_dt(ts: str) -> datetime:
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
    return [(datetime.fromisoformat(d), m[d]) for d in days]


def as_series(readings: List[dict], viz_type: str) -> List[Tuple[datetime, float]]:
    if viz_type == "bar":
        return aggregate_daily(readings)
    pts = [(_to_dt(r["timestamp"]), float(r["value"])) for r in readings if r.get("value") is not None]
    pts.sort(key=lambda x: x[0])
    return pts


def _step_days(cadence: str) -> int:
    if cadence == "weekly":
        return 7
    if cadence == "monthly":
        return 30
    return 1


def horizon_points(cadence: str) -> int:
    if cadence == "daily":
        return 7
    if cadence == "weekly":
        return 3
    if cadence == "monthly":
        return 3
    return 1


def detect_cadence(series: List[Tuple[datetime, float]]) -> str:
    """Detect cadence from median delta in recent points."""
    if len(series) < 6:
        return "other"
    dts = [t for t, _ in series[-11:]]
    deltas = []
    for i in range(1, len(dts)):
        d = (dts[i] - dts[i - 1]).days
        if d > 0:
            deltas.append(d)
    if not deltas:
        return "other"
    deltas.sort()
    med = deltas[len(deltas) // 2]
    if med >= 25:
        return "monthly"
    if med >= 6:
        return "weekly"
    if med <= 2:
        return "daily"
    return "other"


@dataclass
class Forecast:
    points: List[dict]  # {timestamp,value,low,high}
    model: str
    cadence: str


def forecast_ml(series: List[Tuple[datetime, float]], cadence: str) -> Forecast:
    """Lightweight ML-ish: ridge regression on time index with residual band.

    For daily, uses last N points (up to 120). For weekly/monthly, uses up to 36.
    """
    if np is None:
        return Forecast(points=[], model="unavailable", cadence=cadence)

    n = len(series)
    if n < 10:
        return Forecast(points=[], model="need_more_data", cadence=cadence)

    max_n = 120 if cadence == "daily" else 36
    series = series[-max_n:]
    y = np.array([v for _, v in series], dtype=float)
    x = np.arange(len(y), dtype=float)

    # Features: [1, t, t^2] (gives a bit of curvature)
    X = np.column_stack([np.ones_like(x), x, x**2])

    # Ridge
    lam = 1.0
    XtX = X.T @ X
    beta = np.linalg.solve(XtX + lam * np.eye(X.shape[1]), X.T @ y)

    yhat = X @ beta
    resid = y - yhat
    sigma = float(np.std(resid)) if len(resid) > 2 else 0.0

    h = horizon_points(cadence)
    step = _step_days(cadence)
    last_t = series[-1][0]

    pts = []
    for i in range(1, h + 1):
        t_idx = float(len(y) - 1 + i)
        Xt = np.array([1.0, t_idx, t_idx**2], dtype=float)
        pred = float(Xt @ beta)
        # 95% band from residual std (simple, opaque-enough)
        low = pred - 1.96 * sigma
        high = pred + 1.96 * sigma
        ts = (last_t + timedelta(days=step * i)).date().isoformat()
        pts.append({"timestamp": ts, "value": pred, "low": low, "high": high})

    return Forecast(points=pts, model="ridge(poly2)", cadence=cadence)
