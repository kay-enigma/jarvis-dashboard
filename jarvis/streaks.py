"""
Streaks & adherence.

Habit mechanics — the behaviour loop that actually lowers degging. All derived
from check-in dates and workout dates. A streak is "alive" if the last entry
was today or yesterday (so you don't lose it just because today's check-in
isn't in yet).
"""

from __future__ import annotations

from datetime import date, timedelta

from .schema import JarvisState


def _run_to(dates: set[date], today: date) -> int:
    """Consecutive days ending today or yesterday."""
    if today in dates:
        cur = today
    elif (today - timedelta(days=1)) in dates:
        cur = today - timedelta(days=1)
    else:
        return 0
    n = 0
    while cur in dates:
        n += 1
        cur -= timedelta(days=1)
    return n


def _best_run(dates: set[date]) -> int:
    """Longest consecutive run ever."""
    if not dates:
        return 0
    best = run = 1
    prev = None
    for d in sorted(dates):
        if prev is not None and (d - prev).days == 1:
            run += 1
        elif prev is not None:
            run = 1
        best = max(best, run)
        prev = d
    return best


def _checkin_dates(state: JarvisState) -> set[date]:
    return {c.date for c in state.checkins}


def _protein_dates(state: JarvisState) -> set[date]:
    return {c.date for c in state.checkins
            if str(c.answers.get("protein", "")).strip().lower() == "yes"}


def summary(state: JarvisState, today: date) -> dict:
    ci = _checkin_dates(state)
    pr = _protein_dates(state)
    train_week = sum(1 for w in state.workouts if 0 <= (today - w.date).days < 7)
    target = state.profile.training_target_per_week
    return {
        "checkin_streak": _run_to(ci, today),
        "checkin_best": _best_run(ci),
        "protein_streak": _run_to(pr, today),
        "training_week": train_week,
        "training_target": target,
        "training_pct": round(min(train_week / target, 1.0) * 100) if target else 0,
    }
