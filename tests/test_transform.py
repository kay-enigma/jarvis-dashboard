"""Tests for the transform layer - coercing messy spreadsheet rows."""

from datetime import date

import pytest

from control_rods.pipeline.transform import (
    _parse_date,
    _parse_enum,
    _parse_float,
    destination_from_row,
    task_from_row,
)
from control_rods.schema import Engine, TaskStatus


def test_parse_money_strips_formatting():
    assert _parse_float("340,000") == 340000.0
    assert _parse_float("$ 40000") == 40000.0
    assert _parse_float("CAD 5000") == 5000.0
    assert _parse_float("") is None
    assert _parse_float("  ") is None


def test_parse_date_accepts_multiple_formats():
    assert _parse_date("2026-09-30") == date(2026, 9, 30)
    assert _parse_date("30/09/2026") == date(2026, 9, 30)
    assert _parse_date("Sep 2026") == date(2026, 9, 1)
    assert _parse_date("") is None


def test_parse_date_rejects_garbage():
    with pytest.raises(ValueError):
        _parse_date("not a date")


def test_parse_enum_is_case_and_space_insensitive():
    assert _parse_enum(Engine, " Floor ") == Engine.FLOOR
    assert _parse_enum(TaskStatus, "In-Progress") == TaskStatus.IN_PROGRESS
    assert _parse_enum(TaskStatus, "in progress") == TaskStatus.IN_PROGRESS


def test_parse_enum_uses_default_when_blank():
    assert _parse_enum(TaskStatus, "", TaskStatus.NOT_STARTED) == TaskStatus.NOT_STARTED


def test_parse_enum_rejects_unknown_value():
    with pytest.raises(ValueError):
        _parse_enum(Engine, "marketing")


def test_destination_from_row_full():
    row = {
        "id": "liquid_340k", "title": "$340k generated",
        "detail": "300k liquid plus car", "engine": "floor",
        "target_date": "2031-06-01", "confidence": "stretch",
        "target_value": "340,000", "current_value": "5000", "unit": "CAD",
    }
    d = destination_from_row(row)
    assert d.id == "liquid_340k"
    assert d.target_value == 340000
    assert d.progress_pct == round(5000 / 340000 * 100, 1)


def test_task_from_row_defaults_status():
    row = {"id": "t1", "title": "ship repo", "engine": "skill", "status": ""}
    t = task_from_row(row)
    assert t.status == TaskStatus.NOT_STARTED
    assert t.engine == Engine.SKILL


def test_task_blank_serves_becomes_none():
    row = {"id": "t1", "title": "x", "engine": "floor", "serves_destination": "  "}
    t = task_from_row(row)
    assert t.serves_destination is None
