"""
Time-series forecasting for the logged metrics.

Pure-Python, from first principles — no numpy/statsmodels — so it stays
dependency-light, offline, and fully testable, and so the maths is auditable
rather than a black box. Three things, all derived from a Metric's readings:

    linear_trend(readings)         least-squares slope/intercept + fit quality
    project(...)                   forward projection with an approximate band
    eta_to_target(...)             when the trend crosses the goal (or None)
    anomalies(readings)            EWMA residual z-scores → off-trend points
    summary(metric)                the render-ready bundle the API serves

Linear least-squares is the right model here: the underlying processes (a fat
cut, a savings curve) are locally linear, the user already reasons in
"lb/week" and "ETA to 160", and a straight line with a residual band answers
exactly that without over-fitting a handful of points.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from .schema import Metric, Reading

MIN_READINGS = 3            # below this, a trend line is meaningless
Z_FLAG = 3.5               # robust (MAD) |z| above this is flagged off-trend
EWMA_ALPHA = 0.4           # smoothing factor for the anomaly baseline
BAND_Z = 1.96             # ~95% approximate prediction band
_MAD_C = 0.6745           # makes MAD a consistent estimator of σ for normal data


def _xy(readings: list[Reading]) -> tuple[list[float], list[float], date]:
    """Map readings to (x = days since first reading, y = value)."""
    rs = sorted(readings, key=lambda r: r.date)
    origin = rs[0].date
    xs = [float((r.date - origin).days) for r in rs]
    ys = [r.value for r in rs]
    return xs, ys, origin


def linear_trend(readings: list[Reading]) -> Optional[dict]:
    """Ordinary least-squares fit. Returns slope (per day), intercept,
    R², and the residual standard deviation, or None if underdetermined."""
    xs, ys, origin = _xy(readings)
    n = len(xs)
    if n < 2:
        return None
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if denom == 0:  # all readings on the same day
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    preds = [intercept + slope * x for x in xs]
    rss = sum((y - p) ** 2 for y, p in zip(ys, preds))
    mean_y = sy / n
    tss = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1 - rss / tss if tss > 0 else 1.0
    resid_std = math.sqrt(rss / (n - 2)) if n > 2 else 0.0

    return {
        "slope_per_day": slope,
        "intercept": intercept,
        "origin": origin,
        "r2": round(r2, 3),
        "resid_std": resid_std,
        "last_x": xs[-1],
    }


def eta_to_target(readings: list[Reading], target: Optional[float],
                  direction: str) -> Optional[dict]:
    """When the fitted line crosses `target`, if it's heading that way.
    Returns {date, days} or None (no target / wrong direction / already there)."""
    if target is None:
        return None
    fit = linear_trend(readings)
    if not fit or fit["slope_per_day"] == 0:
        return None
    slope, intercept, origin = fit["slope_per_day"], fit["intercept"], fit["origin"]

    # Must be moving toward the target to have an ETA.
    moving_right_way = (slope < 0) if direction == "down" else (slope > 0)
    if not moving_right_way:
        return None

    x_hit = (target - intercept) / slope
    if x_hit <= fit["last_x"]:
        return {"date": None, "days": 0, "reached": True}
    eta_date = origin + timedelta(days=round(x_hit))
    return {"date": eta_date.isoformat(),
            "days": round(x_hit - fit["last_x"]),
            "reached": False}


def project(readings: list[Reading], horizon_days: int) -> list[dict]:
    """Forward points (weekly) from the last reading through `horizon_days`,
    each with an approximate ±band. Empty if no usable trend."""
    fit = linear_trend(readings)
    if not fit:
        return []
    slope, intercept, origin = fit["slope_per_day"], fit["intercept"], fit["origin"]
    band = BAND_Z * fit["resid_std"]
    out: list[dict] = []
    step = 7
    x = fit["last_x"]
    end = fit["last_x"] + horizon_days
    while x <= end:
        y = intercept + slope * x
        out.append({
            "date": (origin + timedelta(days=round(x))).isoformat(),
            "predicted": round(y, 2),
            "lower": round(y - band, 2),
            "upper": round(y + band, 2),
        })
        x += step
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def anomalies(readings: list[Reading]) -> list[dict]:
    """Off-trend points (e.g. a water/carb weight spike) via EWMA residuals
    scored with a robust median/MAD z. Robust scoring is the point: a single
    large outlier won't inflate its own scale and hide itself, the way a plain
    standard-deviation z does. Needs enough history to be meaningful."""
    rs = sorted(readings, key=lambda r: r.date)
    if len(rs) < 4:
        return []
    ewma = rs[0].value
    resids: list[tuple[Reading, float]] = []
    for r in rs[1:]:
        resids.append((r, r.value - ewma))
        ewma = EWMA_ALPHA * r.value + (1 - EWMA_ALPHA) * ewma

    vals = [d for _, d in resids]
    med = _median(vals)
    mad = _median([abs(d - med) for d in vals])
    flagged = []
    for r, d in resids:
        if mad > 0:
            z = _MAD_C * (d - med) / mad
        else:  # degenerate spread — fall back to plain σ
            mean = sum(vals) / len(vals)
            std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
            if std == 0:
                return []
            z = (d - mean) / std
        if abs(z) >= Z_FLAG:
            flagged.append({"id": r.id, "date": r.date.isoformat(),
                            "value": r.value, "z": round(z, 2)})
    return flagged


def summary(metric: Metric) -> dict:
    """Everything the forecast endpoint returns for one metric."""
    rs = metric.sorted_readings()
    if len(rs) < MIN_READINGS:
        return {"available": False,
                "reason": f"need at least {MIN_READINGS} readings to forecast"}

    fit = linear_trend(rs)
    eta = eta_to_target(rs, metric.target, metric.direction)
    # Project to the ETA (a little past it) when there is one, else a month.
    horizon = 28
    if eta and not eta.get("reached") and eta.get("days"):
        horizon = max(14, min(eta["days"] + 7, 365))
    forecast = project(rs, horizon)

    slope_day = fit["slope_per_day"]
    return {
        "available": True,
        "unit": metric.unit,
        "direction": metric.direction,
        "target": metric.target,
        "slope_per_day": round(slope_day, 4),
        "slope_per_week": round(slope_day * 7, 2),
        "r2": fit["r2"],
        "eta": eta,
        "forecast": forecast,
        "anomalies": anomalies(rs),
    }
