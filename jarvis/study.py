"""
Self-study: the transfer function.

This is the F1 part. It aligns your daily signals — inputs (sleep, training
volume, protein, training y/n) against outputs (deep-work hours, degging
hours, energy) — and reports:

    correlations    which lever moves which output, and how strongly
    peak_profile    what your *best output days* have in common
                    (the setup that reproduces a "2018 Singapore" day)
    series          deep-work and degging over time

Pearson r is the right first tool: cheap, interpretable, and honest about
small samples (it simply withholds a verdict until there's enough data).
Correlation isn't causation — these are leads to test, not laws.
"""

from __future__ import annotations

import math
from typing import Optional

from . import workouts as wk
from .schema import JarvisState

MIN_DAYS = 6      # below this, no study — not enough to say anything
MIN_PAIRS = 6     # min paired points for a correlation

LABELS = {
    "sleep": "sleep",
    "energy": "energy",
    "deep_work": "deep-work hours",
    "degging": "degging hours",
    "protein": "hitting protein",
    "trained": "training",
    "training_load": "training volume",
}

# (input, output) relationships worth surfacing.
PAIRS = [
    ("sleep", "deep_work"),
    ("sleep", "degging"),
    ("sleep", "energy"),
    ("training_load", "energy"),
    ("training_load", "deep_work"),
    ("trained", "deep_work"),
    ("protein", "energy"),
    ("energy", "deep_work"),
    ("energy", "degging"),
]

_PROFILE_INPUTS = ["sleep", "training_load", "energy", "protein", "trained"]


def _num(ans: dict, key: str) -> Optional[float]:
    """Pull a numeric signal out of a check-in answer dict."""
    if key not in ans:
        return None
    v = ans[key]
    if key in ("protein", "trained"):
        return 1.0 if str(v).strip().lower() in ("yes", "true", "1") else 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _frame(state: JarvisState) -> list[dict]:
    """One row per check-in date with whatever numeric signals it has, plus
    that day's training volume (0 = rest day)."""
    load = wk.daily_load(state)
    rows = []
    for ci in sorted(state.checkins, key=lambda c: c.date):
        iso = ci.date.isoformat()
        row = {"date": iso}
        for key in ("sleep", "energy", "deep_work", "degging", "protein", "trained"):
            val = _num(ci.answers, key)
            if val is not None:
                row[key] = val
        row["training_load"] = load.get(iso, 0.0)
        rows.append(row)
    return rows


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def _reading(a: str, b: str, r: float) -> str:
    """Plain-language interpretation of a correlation."""
    more = "more" if r > 0 else "less"
    return f"more {LABELS[a]} → {more} {LABELS[b]}"


def correlations(rows: list[dict]) -> list[dict]:
    out = []
    for a, b in PAIRS:
        pairs = [(row[a], row[b]) for row in rows if a in row and b in row]
        if len(pairs) < MIN_PAIRS:
            continue
        r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
        if r is None:
            continue
        out.append({
            "input": a, "output": b,
            "input_label": LABELS[a], "output_label": LABELS[b],
            "r": round(r, 2), "n": len(pairs),
            "strength": "strong" if abs(r) >= 0.5 else "moderate" if abs(r) >= 0.3 else "weak",
            "reading": _reading(a, b, r),
        })
    out.sort(key=lambda d: -abs(d["r"]))
    return out


def peak_profile(rows: list[dict], output: str = "deep_work") -> Optional[dict]:
    """Split days into best vs worst by `output`, then show how each input
    differs — i.e. what your peak days are made of."""
    have = [row for row in rows if output in row]
    if len(have) < MIN_DAYS:
        # fall back to energy if deep_work is too sparse
        if output != "energy":
            return peak_profile(rows, "energy")
        return None
    have.sort(key=lambda row: row[output])
    k = max(2, len(have) // 3)
    worst, best = have[:k], have[-k:]

    deltas = []
    for sig in _PROFILE_INPUTS:
        bt = [row[sig] for row in best if sig in row]
        wt = [row[sig] for row in worst if sig in row]
        if len(bt) < 2 or len(wt) < 2:
            continue
        mb, mw = sum(bt) / len(bt), sum(wt) / len(wt)
        deltas.append({
            "input": sig, "input_label": LABELS[sig],
            "best": round(mb, 1), "worst": round(mw, 1),
            "delta": round(mb - mw, 1),
        })
    deltas.sort(key=lambda d: -abs(d["delta"]))
    return {
        "output": output, "output_label": LABELS[output],
        "n_best": len(best), "n_worst": len(worst), "deltas": deltas,
    }


def _series(rows: list[dict], key: str) -> list[dict]:
    return [{"date": row["date"], "value": row[key]} for row in rows if key in row]


def setup_score(answers: dict, profile) -> Optional[dict]:
    """Grade one day against your 'ideal day' setup — the recipe behind your
    peak days. Components are weighted; partial credit where it makes sense.
    Returns the 0-100 score plus a per-component breakdown, or None if the
    day has nothing scorable."""
    comps = []
    sl = _num(answers, "sleep")
    if sl is not None and profile.setup_sleep_target > 0:
        comps.append({"k": "sleep", "got": min(1.0, sl / profile.setup_sleep_target) * 25, "max": 25})
    dw = _num(answers, "deep_work")
    if dw is not None and profile.setup_deepwork_target > 0:
        comps.append({"k": "deep_work", "got": min(1.0, dw / profile.setup_deepwork_target) * 30, "max": 30})
    dg = _num(answers, "degging")
    if dg is not None:
        cap = profile.setup_degging_max
        if dg <= cap:
            got = 25.0
        else:
            got = max(0.0, 25.0 * (1 - (dg - cap) / (cap + 2)))
        comps.append({"k": "degging", "got": got, "max": 25})
    pr = _num(answers, "protein")
    if pr is not None:
        comps.append({"k": "protein", "got": 20.0 if pr >= 1 else 0.0, "max": 20})
    if not comps:
        return None
    got = sum(c["got"] for c in comps)
    mx = sum(c["max"] for c in comps)
    return {
        "score": round(got / mx * 100) if mx else 0,
        "components": [{"k": c["k"], "label": LABELS.get(c["k"], c["k"]),
                        "pct": round(c["got"] / c["max"] * 100)} for c in comps],
    }


def setup_scores(state: JarvisState) -> dict:
    """Today's setup score (latest check-in) + 7-day average + a trend series."""
    rows = sorted(state.checkins, key=lambda c: c.date)
    if not rows:
        return {"available": False}
    series = []
    for c in rows:
        sc = setup_score(c.answers, state.profile)
        if sc:
            series.append({"date": c.date.isoformat(), "value": sc["score"]})
    if not series:
        return {"available": False}
    latest = setup_score(rows[-1].answers, state.profile)
    last7 = [p["value"] for p in series[-7:]]
    return {
        "available": True,
        "today": latest["score"] if latest else None,
        "components": latest["components"] if latest else [],
        "avg7": round(sum(last7) / len(last7)),
        "series": series,
    }


def summary(state: JarvisState) -> dict:
    rows = _frame(state)
    usable = [r for r in rows if len(r) > 2]  # more than just date + load
    if len(usable) < MIN_DAYS:
        return {"available": False, "have": len(usable), "need": MIN_DAYS}
    return {
        "available": True,
        "days": len(usable),
        "correlations": correlations(rows),
        "peak_profile": peak_profile(rows),
        "deep_work_series": _series(rows, "deep_work"),
        "degging_series": _series(rows, "degging"),
        "setup": setup_scores(state),
    }
