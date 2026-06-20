"""
Workout ingestion + analytics.

Capture happens in Hevy (best in-gym UX); Jarvis ingests the CSV export and
turns it into studyable telemetry. The parser is deliberately defensive about
column names and date formats because export formats drift — a missing column
degrades gracefully instead of throwing.

What we compute (all derived, never stored):
    volume_series   tonnage (Σ weight×reps) per session, over time
    strength curves estimated 1-rep max (Epley) per main lift, over time
    frequency       sessions in the last 7 / 28 days
"""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from .schema import JarvisState, Workout, WorkoutSet, new_id

# Header aliases — map Hevy's columns (and minor variants) to our fields.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d %b %Y, %H:%M",
    "%d %b %Y, %H:%M:%S",
    "%Y-%m-%d",
)


def _parse_dt(raw: str) -> Optional[date]:
    s = (raw or "").strip().strip('"')
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # last resort: leading ISO date
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _to_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _weight_column(fields: list[str]) -> tuple[str, str]:
    """Return (column_name, unit). Hevy uses weight_kg; some exports lbs."""
    for f in fields:
        lf = f.lower()
        if lf.startswith("weight_kg"):
            return f, "kg"
        if lf.startswith("weight_lb"):
            return f, "lb"
        if lf.startswith("weight"):
            return f, "kg"
    return "", "kg"


def parse_hevy_csv(text: str) -> list[Workout]:
    """Parse a Hevy workout export into Workouts. Rows are grouped into a
    session by (title, start_time); each row is one set."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    wcol, unit = _weight_column(reader.fieldnames)

    # group rows -> session key
    groups: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for row in reader:
        key = (row.get("title", ""), row.get("start_time", ""))
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    workouts: list[Workout] = []
    for key in order:
        rows = groups[key]
        first = rows[0]
        d = _parse_dt(first.get("start_time", ""))
        if d is None:
            continue
        durs = [_to_float(r.get("duration_seconds")) for r in rows]
        duration_min = round(max(durs) / 60, 1) if any(durs) else None

        sets = []
        for r in rows:
            ex = (r.get("exercise_title") or "").strip()
            if not ex:
                continue
            sets.append(WorkoutSet(
                exercise=ex,
                set_index=_to_int(r.get("set_index")),
                set_type=(r.get("set_type") or "normal").strip() or "normal",
                weight=_to_float(r.get(wcol)) if wcol else 0.0,
                reps=_to_int(r.get("reps")),
                rpe=(_to_float(r.get("rpe")) or None),
            ))
        if not sets:
            continue
        workouts.append(Workout(
            id=new_id(), date=d,
            title=(first.get("title") or "").strip(),
            start_time=(first.get("start_time") or "").strip(),
            weight_unit=unit,
            duration_min=duration_min,
            notes=(first.get("description") or "").strip(),
            sets=sets,
        ))
    return workouts


def _parse_duration(raw: str) -> Optional[float]:
    """Strong logs duration as text like '47min' or '1h 12min' -> minutes."""
    s = (raw or "").lower()
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*m", s)
    total, found = 0, False
    if h:
        total += int(h.group(1)) * 60
        found = True
    if m:
        total += int(m.group(1))
        found = True
    return float(total) if found else None


def parse_strong_csv(text: str, weight_unit: str = "lb") -> list[Workout]:
    """Parse a Strong app export. Columns: Date, Workout Name, Duration,
    Exercise Name, Set Order, Weight, Reps, Distance, Seconds, Notes,
    Workout Notes, RPE. 'Set Order' == 'W' marks a warmup. Strong has no unit
    column, so the unit is assumed (lb by default — what you log in)."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []

    groups: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    for row in reader:
        key = row.get("Date", "")
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    workouts: list[Workout] = []
    for key in order:
        rows = groups[key]
        first = rows[0]
        d = _parse_dt(first.get("Date", ""))
        if d is None:
            continue
        sets = []
        for r in rows:
            ex = (r.get("Exercise Name") or "").strip()
            if not ex:
                continue
            reps = _to_int(r.get("Reps"))
            weight = _to_float(r.get("Weight"))
            if reps == 0 and weight == 0:  # cardio / empty placeholder set
                continue
            so = (r.get("Set Order") or "").strip()
            sets.append(WorkoutSet(
                exercise=ex,
                set_index=int(so) if so.isdigit() else 0,
                set_type="warmup" if so.upper() == "W" else "normal",
                weight=weight,
                reps=reps,
                rpe=(_to_float(r.get("RPE")) or None),
            ))
        if not sets:
            continue
        workouts.append(Workout(
            id=new_id(), date=d,
            title=(first.get("Workout Name") or "").strip(),
            start_time=key,
            weight_unit=weight_unit,
            duration_min=_parse_duration(first.get("Duration", "")),
            notes=(first.get("Workout Notes") or "").strip(),
            sets=sets,
        ))
    return workouts


def parse_workouts_csv(text: str) -> list[Workout]:
    """Auto-detect the export format (Hevy or Strong) by its header and parse
    accordingly, so you can import whichever app you use."""
    head = (text.splitlines()[0].lower() if text.strip() else "")
    if "exercise_title" in head:           # Hevy
        return parse_hevy_csv(text)
    if "exercise name" in head:            # Strong
        return parse_strong_csv(text)
    raise ValueError(
        "Unrecognized CSV — expected a Hevy or Strong workout export."
    )


def merge_import(state: JarvisState, incoming: list[Workout]) -> int:
    """Add only sessions we haven't already imported (dedupe on start_time,
    falling back to date+title). Returns how many were added."""
    seen_start = {w.start_time for w in state.workouts if w.start_time}
    seen_fallback = {(w.date, w.title) for w in state.workouts}
    added = 0
    for w in incoming:
        if w.start_time and w.start_time in seen_start:
            continue
        if not w.start_time and (w.date, w.title) in seen_fallback:
            continue
        state.workouts.append(w)
        seen_start.add(w.start_time)
        seen_fallback.add((w.date, w.title))
        added += 1
    return added


# --- analytics -------------------------------------------------------------


def tonnage(w: Workout) -> float:
    """Total volume load: Σ weight×reps over working sets."""
    return round(sum(s.weight * s.reps for s in w.sets if s.set_type != "warmup"), 1)


def epley_e1rm(weight: float, reps: int) -> float:
    """Estimated 1-rep max (Epley). A single rep already *is* a 1RM, so
    reps==1 returns the weight itself rather than inflating it."""
    if reps <= 0 or weight <= 0:
        return 0.0
    if reps == 1:
        return weight
    return weight * (1 + reps / 30.0)


def all_time_prs(state: JarvisState) -> dict[str, dict]:
    """Per lift: best estimated 1RM ever and the date it was hit."""
    best: dict[str, dict] = {}
    for w in sorted(state.workouts, key=lambda w: w.date):
        for s in w.sets:
            e = epley_e1rm(s.weight, s.reps)
            if e <= 0:
                continue
            cur = best.get(s.exercise)
            if cur is None or e > cur["e1rm"]:
                best[s.exercise] = {"e1rm": round(e, 1), "date": w.date.isoformat()}
    return best


def recent_prs(state: JarvisState, today: date, days: int = 14,
               lifts: Optional[list[str]] = None) -> list[dict]:
    """PRs whose all-time best was set within the last `days` — i.e. you just
    hit a new best. Scoped to `lifts` if given (else all)."""
    prs = all_time_prs(state)
    out = []
    for lift, pr in prs.items():
        if lifts is not None and lift not in lifts:
            continue
        d = date.fromisoformat(pr["date"])
        if 0 <= (today - d).days <= days:
            out.append({"exercise": lift, "e1rm": pr["e1rm"], "date": pr["date"]})
    return sorted(out, key=lambda p: -p["e1rm"])


def exercise_frequency(state: JarvisState) -> list[dict]:
    """Every exercise seen, with how many sessions it appears in — feeds the
    lift picker."""
    freq: dict[str, int] = defaultdict(int)
    for w in state.workouts:
        for ex in {s.exercise for s in w.sets}:
            freq[ex] += 1
    return [{"exercise": e, "sessions": n}
            for e, n in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))]


def summary(state: JarvisState, top_lifts: int = 4) -> dict:
    ws = sorted(state.workouts, key=lambda w: w.date)
    if not ws:
        return {"available": False, "count": 0}

    unit = ws[-1].weight_unit
    volume_series = [
        {"date": w.date.isoformat(), "tonnage": tonnage(w),
         "sets": len([s for s in w.sets if s.set_type != "warmup"]),
         "title": w.title}
        for w in ws
    ]

    # frequency
    today = date.today()
    last7 = sum(1 for w in ws if (today - w.date).days < 7)
    last28 = sum(1 for w in ws if (today - w.date).days < 28)

    # which lifts to chart: pinned ones if set, else most-trained
    freq: dict[str, int] = defaultdict(int)
    for w in ws:
        for ex in {s.exercise for s in w.sets}:
            freq[ex] += 1
    pinned = [m for m in state.profile.main_lifts if m in freq]
    main = pinned or [ex for ex, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:top_lifts]]

    prs = all_time_prs(state)
    recent_pr_lifts = {p["exercise"] for p in recent_prs(state, today, days=14, lifts=main)}

    strength = []
    for ex in main:
        points = []
        for w in ws:
            best = max((epley_e1rm(s.weight, s.reps)
                        for s in w.sets if s.exercise == ex), default=0.0)
            if best > 0:
                points.append({"date": w.date.isoformat(), "value": round(best, 1)})
        if len(points) >= 1:
            first, last = points[0]["value"], points[-1]["value"]
            strength.append({
                "exercise": ex,
                "series": points,
                "current_e1rm": last,
                "delta": round(last - first, 1),
                "all_time": prs.get(ex, {}).get("e1rm"),
                "recent_pr": ex in recent_pr_lifts,
            })

    recent = [
        {"date": w.date.isoformat(), "title": w.title,
         "sets": len([s for s in w.sets if s.set_type != "warmup"]),
         "tonnage": tonnage(w), "duration_min": w.duration_min,
         "exercises": sorted({s.exercise for s in w.sets})}
        for w in reversed(ws[-12:])
    ]

    return {
        "available": True,
        "count": len(ws),
        "unit": unit,
        "sessions_7d": last7,
        "sessions_28d": last28,
        "per_week_28d": round(last28 / 4, 1),
        "volume_series": volume_series,
        "strength": strength,
        "recent": recent,
        "pinned": bool(pinned),
        "main_lifts": main,
    }


def daily_load(state: JarvisState) -> dict[str, float]:
    """Tonnage keyed by ISO date (summed if multiple sessions a day) — the
    training-load input the self-study view correlates against."""
    out: dict[str, float] = defaultdict(float)
    for w in state.workouts:
        out[w.date.isoformat()] += tonnage(w)
    return dict(out)
