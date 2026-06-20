"""
The Race Report — a weekly debrief.

Compares the last 7 days against the 7 before it across body, training, and
output, and ends on a one-line verdict. This is the Sunday-night "how did the
stint go" read that turns daily logging into direction.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Optional

from . import workouts as wk
from .schema import JarvisState, Section


def _avg(checkins, key, lo, hi) -> Optional[float]:
    vals = []
    for c in checkins:
        if not (lo <= c.date <= hi):
            continue
        v = c.answers.get(key)
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            pass
    return round(mean(vals), 1) if vals else None


def _delta(cur, prev):
    if cur is None or prev is None:
        return None
    return round(cur - prev, 1)


def build(state: JarvisState, today: date) -> dict:
    this_lo, this_hi = today - timedelta(days=6), today
    prev_lo, prev_hi = today - timedelta(days=13), today - timedelta(days=7)

    # weight change over the week
    rs = state.weight.sorted_readings()
    wk_change = None
    if rs:
        in_week = [r for r in rs if this_lo <= r.date <= this_hi]
        if len(in_week) >= 2:
            wk_change = round(in_week[-1].value - in_week[0].value, 1)
        elif in_week:
            before = [r for r in rs if r.date < this_lo]
            if before:
                wk_change = round(in_week[-1].value - before[-1].value, 1)

    # training
    sess_this = [w for w in state.workouts if this_lo <= w.date <= this_hi]
    sess_prev = [w for w in state.workouts if prev_lo <= w.date <= prev_hi]
    ton_this = round(sum(wk.tonnage(w) for w in sess_this))
    ton_prev = round(sum(wk.tonnage(w) for w in sess_prev))
    prs = wk.recent_prs(state, today, days=7,
                        lifts=state.profile.main_lifts or None)

    # outputs
    dw_this = _avg(state.checkins, "deep_work", this_lo, this_hi)
    dw_prev = _avg(state.checkins, "deep_work", prev_lo, prev_hi)
    dg_this = _avg(state.checkins, "degging", this_lo, this_hi)
    dg_prev = _avg(state.checkins, "degging", prev_lo, prev_hi)

    # adherence
    ci_days = sum(1 for c in state.checkins if this_lo <= c.date <= this_hi)
    protein_days = sum(1 for c in state.checkins
                       if this_lo <= c.date <= this_hi
                       and str(c.answers.get("protein", "")).lower() == "yes")

    # quarter checklist
    cur = [g for g in state.goals if g.section == Section.CURRENT]
    cur_done = sum(1 for g in cur if g.done)

    # verdict
    bits = []
    if wk_change is not None:
        bits.append(f"{'down' if wk_change < 0 else 'up'} {abs(wk_change)} {state.weight.unit}")
    if dw_this is not None:
        bits.append(f"{dw_this}h/day deep work")
    if prs:
        bits.append(f"{len(prs)} PR{'s' if len(prs) > 1 else ''}")
    verdict = " · ".join(bits) if bits else "log a few days to get a debrief"

    return {
        "week_of": this_lo.isoformat(),
        "weight_change": wk_change,
        "weight_unit": state.weight.unit,
        "sessions": len(sess_this), "sessions_prev": len(sess_prev),
        "tonnage": ton_this, "tonnage_prev": ton_prev,
        "tonnage_unit": state.workouts[-1].weight_unit if state.workouts else "",
        "prs": prs,
        "deep_work_avg": dw_this, "deep_work_delta": _delta(dw_this, dw_prev),
        "degging_avg": dg_this, "degging_delta": _delta(dg_this, dg_prev),
        "checkin_days": ci_days, "protein_days": protein_days,
        "current_done": cur_done, "current_total": len(cur),
        "verdict": verdict,
    }
