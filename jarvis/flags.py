"""
Proactive flags.

The pit-wall radio: short, prioritized callouts surfaced on Home so insight
finds you instead of you digging through tabs. Wins (PRs, ETAs, streaks) and
warnings (stalls, rising degging) both bubble up. All best-effort — any
sub-signal that can't be computed is simply skipped.
"""

from __future__ import annotations

from datetime import date
from statistics import mean

from . import forecast as fc
from . import peptides as pep_sched
from . import workouts as wk
from .schema import JarvisState

# priority: lower shows first (actionable/warnings before wins)
_DOSE, _WARN, _ETA, _PR, _STREAK = 0, 1, 2, 3, 4


def _deg_series(state: JarvisState) -> list[float]:
    out = []
    for c in sorted(state.checkins, key=lambda c: c.date):
        v = c.answers.get("degging")
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


def build(state: JarvisState, today: date, limit: int = 5) -> list[dict]:
    flags: list[tuple[int, dict]] = []

    def add(prio, level, icon, text):
        flags.append((prio, {"level": level, "icon": icon, "text": text}))

    unit = state.workouts[-1].weight_unit if state.workouts else ""

    # dose today
    for p in state.peptides:
        if not p.active:
            continue
        s = pep_sched.schedule(p, today)
        if s["is_today"]:
            add(_DOSE, "info", "💊", f"{s['label']} dose today" + (f" · {p.dosage}" if p.dosage else ""))

    # weight: ETA close OR stalled
    wfc = fc.summary(state.weight)
    if wfc.get("available"):
        eta = wfc.get("eta")
        if eta and not eta.get("reached") and eta.get("days") is not None and eta["days"] <= 14:
            tgt = state.weight.target
            add(_ETA, "good", "🎯", f"~{eta['days']}d to {tgt} {state.weight.unit}".strip())
    rs = state.weight.sorted_readings()
    if len(rs) >= 2 and state.weight.target is not None:
        latest = rs[-1]
        prior = [r for r in rs if 7 <= (latest.date - r.date).days <= 16]
        if prior and abs(latest.value - prior[-1].value) < 0.6 and (latest.value - state.weight.target) > 1:
            add(_WARN, "warn", "⚠", f"Weight flat ~{(latest.date - prior[-1].date).days}d — nudge food or wait it out")

    # degging trend
    deg = _deg_series(state)
    if len(deg) >= 6:
        recent, prev = mean(deg[-3:]), mean(deg[-6:-3])
        if recent - prev >= 0.7:
            add(_WARN, "warn", "⚠", f"Degging trending up ({prev:.1f}→{recent:.1f}h)")
        elif prev - recent >= 0.7:
            add(_PR, "good", "📉", f"Degging dropping ({prev:.1f}→{recent:.1f}h)")

    # recent PRs (scoped to pinned lifts, else top-6 to cut machine noise)
    scope = state.profile.main_lifts or [e["exercise"] for e in wk.exercise_frequency(state)[:6]]
    for pr in wk.recent_prs(state, today, days=14, lifts=scope)[:2]:
        add(_PR, "good", "🏆", f"{pr['exercise']} PR · {pr['e1rm']} {unit}".strip())

    # check-in streak milestone
    from . import streaks
    cs = streaks.summary(state, today)["checkin_streak"]
    if cs >= 3:
        add(_STREAK, "good", "🔥", f"{cs}-day check-in streak")

    flags.sort(key=lambda t: t[0])
    return [f for _, f in flags][:limit]
