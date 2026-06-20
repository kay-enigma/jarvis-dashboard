"""
Peptide schedule maths.

Everything here is *derived* from a Peptide's four stored fields
(start_date, interval_days, length_days, dosage). Nothing is persisted, so a
schedule can never drift out of sync with its inputs — change the interval
and every downstream date recomputes.

The two things the dashboard needs:

    dose_dates(pep, ...)   the full list of scheduled dose dates
    schedule(pep, today)   a summary: next dose, is-it-today, days until,
                           doses done / remaining, % through the protocol
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .schema import PEPTIDE_CATALOG, JarvisState, Peptide


def _end_date(pep: Peptide) -> Optional[date]:
    """Last day the protocol is valid, or None if ongoing."""
    if pep.length_days is None:
        return None
    return pep.start_date + timedelta(days=pep.length_days - 1)


def dose_dates(pep: Peptide, until: date) -> list[date]:
    """All scheduled dose dates from start through `until` (inclusive),
    respecting the protocol length if one is set."""
    end = _end_date(pep)
    hard_stop = min(until, end) if end else until
    if hard_stop < pep.start_date:
        return []
    out: list[date] = []
    d = pep.start_date
    step = timedelta(days=pep.interval_days)
    while d <= hard_stop:
        out.append(d)
        d += step
    return out


def total_doses(pep: Peptide) -> Optional[int]:
    """How many doses the whole protocol contains, or None if ongoing."""
    end = _end_date(pep)
    if end is None:
        return None
    return len(dose_dates(pep, end))


def next_dose(pep: Peptide, today: date) -> Optional[date]:
    """The first scheduled dose on or after `today`, or None if the protocol
    has already finished."""
    end = _end_date(pep)
    if end and today > end:
        return None
    if today <= pep.start_date:
        return pep.start_date
    # Walk forward from start in interval steps to the first date >= today.
    delta = (today - pep.start_date).days
    steps = delta // pep.interval_days
    candidate = pep.start_date + timedelta(days=steps * pep.interval_days)
    if candidate < today:
        candidate += timedelta(days=pep.interval_days)
    if end and candidate > end:
        return None
    return candidate


def schedule(pep: Peptide, today: date) -> dict:
    """A render-ready summary of where this protocol stands today."""
    meta = PEPTIDE_CATALOG[pep.key]
    end = _end_date(pep)
    nxt = next_dose(pep, today)
    is_today = nxt == today
    days_until = (nxt - today).days if nxt else None

    total = total_doses(pep)
    done = 0
    if today >= pep.start_date:
        # doses strictly before today have been taken; today's counts once due
        taken_through = today if (end is None or today <= end) else end
        done = len(dose_dates(pep, taken_through))
        if is_today:
            done -= 1  # today's dose is upcoming, not yet taken
    progress_pct = None
    if total:
        progress_pct = round(min(done / total, 1.0) * 100, 1)

    finished = bool(end and today > end)

    return {
        "id": pep.id,
        "key": pep.key,
        "label": meta["label"],
        "full": meta["full"],
        "blurb": meta["blurb"],
        "dosage": pep.dosage,
        "interval_days": pep.interval_days,
        "length_days": pep.length_days,
        "start_date": pep.start_date.isoformat(),
        "end_date": end.isoformat() if end else None,
        "active": pep.active,
        "note": pep.note,
        "next_dose": nxt.isoformat() if nxt else None,
        "is_today": is_today,
        "days_until": days_until,
        "doses_done": done,
        "doses_total": total,
        "progress_pct": progress_pct,
        "finished": finished,
    }


def upcoming(state: JarvisState, today: date, horizon_days: int = 21,
             limit: int = 6) -> list[dict]:
    """Merged, date-sorted list of the next doses across all active
    protocols — what the home-page peptide KPI renders. Each entry flags
    whether it falls today so the UI can light it up uniquely."""
    until = today + timedelta(days=horizon_days)
    rows: list[dict] = []
    for pep in state.peptides:
        if not pep.active:
            continue
        meta = PEPTIDE_CATALOG[pep.key]
        for d in dose_dates(pep, until):
            if d < today:
                continue
            rows.append({
                "peptide_id": pep.id,
                "key": pep.key,
                "label": meta["label"],
                "dosage": pep.dosage,
                "date": d.isoformat(),
                "days_until": (d - today).days,
                "is_today": d == today,
            })
    rows.sort(key=lambda r: (r["date"], r["label"]))
    return rows[:limit]
