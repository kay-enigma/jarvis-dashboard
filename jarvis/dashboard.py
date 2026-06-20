"""
Dashboard assembly.

Pure functions that turn the raw state into the render-ready KPI bundle the
home page shows. Keeping this in Python (not the frontend) means the trend
maths and the "is movement toward target good?" logic are testable and the
JS stays a thin renderer.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from . import flags as flags_mod
from . import peptides as pep_sched
from . import report as report_mod
from . import streaks as streaks_mod
from . import study as study_mod
from .schema import JarvisState, Metric, Section


def _metric_kpi(metric: Metric) -> dict:
    """Latest value + trend for one logged series.

    `trend_good` is True when the most recent move is *toward* the target,
    accounting for direction (down is good for weight/BF, up for net worth),
    so the UI can paint the arrow green/red correctly either way.
    """
    latest = metric.latest
    prev = metric.previous
    out: dict = {
        "label": metric.label,
        "unit": metric.unit,
        "target": metric.target,
        "direction": metric.direction,
        "latest": None,
        "latest_date": None,
        "delta": None,
        "trend_good": None,
        "to_target": None,
        "pct_to_target": None,
        "count": len(metric.readings),
    }
    if latest is None:
        return out

    out["latest"] = latest.value
    out["latest_date"] = latest.date.isoformat()

    if prev is not None:
        delta = round(latest.value - prev.value, 2)
        out["delta"] = delta
        if delta == 0:
            out["trend_good"] = None
        elif metric.direction == "down":
            out["trend_good"] = delta < 0
        else:
            out["trend_good"] = delta > 0

    if metric.target is not None:
        out["to_target"] = round(latest.value - metric.target, 2)
        if metric.direction == "up" and metric.target > 0:
            out["pct_to_target"] = round(min(latest.value / metric.target, 1.0) * 100, 1)
        elif metric.direction == "down":
            # progress from the first logged reading down toward the target
            first = metric.sorted_readings()[0].value
            span = first - metric.target
            if span > 0:
                done = first - latest.value
                out["pct_to_target"] = round(max(0.0, min(done / span, 1.0)) * 100, 1)
    return out


def _series(metric: Metric) -> list[dict]:
    return [
        {"date": r.date.isoformat(), "value": r.value}
        for r in metric.sorted_readings()
    ]


def build(state: JarvisState, today: Optional[date] = None) -> dict:
    """The full home-page payload."""
    today = today or date.today()

    todos = [
        {
            "id": g.id,
            "text": g.text,
            "done": g.done,
            "engine": g.engine.value,
        }
        for g in state.goals_in(Section.CURRENT)
    ]
    todo_done = sum(1 for t in todos if t["done"])

    p = state.profile
    return {
        "today": today.isoformat(),
        "callsign": p.callsign,
        "kpis": {
            "networth": {**_metric_kpi(state.networth),
                         "liquid_target": p.networth_liquid_target,
                         "total_target": p.networth_total_target,
                         "series": _series(state.networth)},
            "weight": {**_metric_kpi(state.weight), "series": _series(state.weight)},
            "bodyfat": {**_metric_kpi(state.bodyfat), "series": _series(state.bodyfat)},
            "money_online": {
                "current": p.money_online_current,
                "target": p.money_online_target,
                "pct": round(min(p.money_online_current / p.money_online_target, 1.0) * 100, 1)
                if p.money_online_target else 0.0,
            },
        },
        "peptides_upcoming": pep_sched.upcoming(state, today),
        "todos": todos,
        "todo_done": todo_done,
        "todo_total": len(todos),
        "protein_target_g": p.protein_target_g,
        # Tier-1 additions
        "streaks": streaks_mod.summary(state, today),
        "flags": flags_mod.build(state, today),
        "report": report_mod.build(state, today),
        "setup": study_mod.setup_scores(state),
    }
