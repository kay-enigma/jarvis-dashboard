"""
Transform layer: raw rows -> validated schema objects.

These functions are deliberately *pure*: dict-of-strings in, schema
object out, no I/O. That makes them the easiest part of the system to
test exhaustively, and it means the same transforms run identically
whether the rows came from Google or a local CSV.

A note on the philosophy this encodes:
each row in the sheet is a flat record (because spreadsheets are flat),
and the job here is to lift that flat, stringly-typed data into the
typed, nested Plan structure - coercing types, normalising the little
human inconsistencies a spreadsheet always accumulates (stray spaces,
mixed case in an enum, an empty cell that should be None), and letting
Pydantic reject anything that can't be made well-formed.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from control_rods.schema import (
    AnnualEntry,
    Confidence,
    Destination,
    Engine,
    Quarter,
    QuarterTask,
    TaskStatus,
)


# --- small coercion helpers ------------------------------------------------


def _clean(value: Optional[str]) -> str:
    """Trim and collapse the whitespace a spreadsheet inevitably grows."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _none_if_blank(value: Optional[str]) -> Optional[str]:
    cleaned = _clean(value)
    return cleaned or None


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Accept the handful of date formats a human actually types."""
    raw = _clean(value)
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%b %Y", "%B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {raw!r}")


def _parse_float(value: Optional[str]) -> Optional[float]:
    """Money cells arrive as '340,000' or '$340000' or ''. Normalise."""
    raw = _clean(value).replace(",", "").replace("$", "").replace("CAD", "")
    raw = raw.strip()
    if not raw:
        return None
    return float(raw)


def _parse_enum(enum_cls, value: Optional[str], default=None):
    """Map a human-typed cell onto an enum, case/space-insensitively."""
    raw = _clean(value).lower().replace(" ", "_").replace("-", "_")
    if not raw:
        if default is not None:
            return default
        raise ValueError(f"Missing required {enum_cls.__name__} value.")
    try:
        return enum_cls(raw)
    except ValueError:
        valid = ", ".join(e.value for e in enum_cls)
        raise ValueError(
            f"{raw!r} is not a valid {enum_cls.__name__}. Expected one of: {valid}."
        )


# --- row -> object transforms ---------------------------------------------


def destination_from_row(row: dict) -> Destination:
    """One 'Destinations' tab row -> a Destination."""
    return Destination(
        id=_clean(row.get("id")),
        title=_clean(row.get("title")),
        detail=_clean(row.get("detail")),
        engine=_parse_enum(Engine, row.get("engine")),
        target_date=_parse_date(row.get("target_date")),
        confidence=_parse_enum(Confidence, row.get("confidence"), Confidence.LIKELY),
        target_value=_parse_float(row.get("target_value")),
        current_value=_parse_float(row.get("current_value")),
        unit=_none_if_blank(row.get("unit")),
    )


def task_from_row(row: dict) -> QuarterTask:
    """One 'Quarter' tab row -> a QuarterTask."""
    return QuarterTask(
        id=_clean(row.get("id")),
        title=_clean(row.get("title")),
        engine=_parse_enum(Engine, row.get("engine")),
        status=_parse_enum(TaskStatus, row.get("status"), TaskStatus.NOT_STARTED),
        serves_destination=_none_if_blank(row.get("serves_destination")),
        note=_clean(row.get("note")),
    )


def annual_entry_from_row(row: dict) -> AnnualEntry:
    """One 'AnnualLog' tab row -> an AnnualEntry."""
    return AnnualEntry(
        year=int(_clean(row.get("year"))),
        kept=_clean(row.get("kept")),
        changed=_clean(row.get("changed")),
        learned=_clean(row.get("learned")),
    )


def build_quarter(meta_row: dict, task_rows: list[dict]) -> Quarter:
    """Assemble the current Quarter from its meta row + task rows.

    `meta_row` carries the quarter-level fields (label, theme, dates);
    `task_rows` are the individual steps. Empty task rows (a blank line
    in the sheet) are skipped rather than erroring.
    """
    tasks = [task_from_row(r) for r in task_rows if _clean(r.get("id"))]
    return Quarter(
        label=_clean(meta_row.get("label")),
        theme=_clean(meta_row.get("theme")),
        start_date=_parse_date(meta_row.get("start_date")),
        end_date=_parse_date(meta_row.get("end_date")),
        tasks=tasks,
    )
