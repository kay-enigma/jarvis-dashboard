"""Tests for the schema layer - the validation contract."""

import pytest
from pydantic import ValidationError

from control_rods.schema import (
    Confidence,
    Destination,
    Engine,
    Plan,
    Quarter,
    QuarterTask,
    TaskStatus,
)


def test_numeric_destination_computes_progress():
    d = Destination(
        id="runway",
        title="Financial runway secured",
        engine=Engine.FLOOR,
        confidence=Confidence.STRETCH,
        target_value=100000,
        current_value=25000,
        unit="USD",
    )
    assert d.progress_pct == 25.0


def test_progress_caps_at_100():
    d = Destination(
        id="x", title="x", engine=Engine.FLOOR,
        target_value=100, current_value=250,
    )
    assert d.progress_pct == 100.0


def test_non_numeric_destination_has_no_progress():
    d = Destination(id="pr", title="PR secured", engine=Engine.FLOOR)
    assert d.progress_pct is None


def test_current_value_without_target_is_rejected():
    with pytest.raises(ValidationError):
        Destination(id="x", title="x", engine=Engine.FLOOR, current_value=10)


def test_quarter_completion_ignores_dropped():
    q = Quarter(
        label="Q3 2026",
        tasks=[
            QuarterTask(id="a", title="a", engine=Engine.SKILL, status=TaskStatus.DONE),
            QuarterTask(id="b", title="b", engine=Engine.SKILL, status=TaskStatus.NOT_STARTED),
            QuarterTask(id="c", title="c", engine=Engine.SKILL, status=TaskStatus.DROPPED),
        ],
    )
    # 1 done of 2 live (dropped excluded) -> 50%
    assert q.completion_pct == 50.0


def test_quarter_rejects_backwards_dates():
    from datetime import date
    with pytest.raises(ValidationError):
        Quarter(label="Q", start_date=date(2026, 9, 1), end_date=date(2026, 7, 1))


def test_plan_rejects_duplicate_destination_ids():
    with pytest.raises(ValidationError):
        Plan(destinations=[
            Destination(id="dup", title="a", engine=Engine.FLOOR),
            Destination(id="dup", title="b", engine=Engine.SKILL),
        ])


def test_plan_rejects_task_pointing_at_unknown_destination():
    q = Quarter(label="Q", tasks=[
        QuarterTask(id="t", title="t", engine=Engine.SKILL, serves_destination="ghost"),
    ])
    with pytest.raises(ValidationError):
        Plan(destinations=[Destination(id="real", title="r", engine=Engine.FLOOR)], current_quarter=q)


def test_plan_accepts_task_pointing_at_real_destination():
    q = Quarter(label="Q", tasks=[
        QuarterTask(id="t", title="t", engine=Engine.SKILL, serves_destination="real"),
    ])
    plan = Plan(
        destinations=[Destination(id="real", title="r", engine=Engine.FLOOR)],
        current_quarter=q,
    )
    assert plan.current_quarter.tasks[0].serves_destination == "real"
