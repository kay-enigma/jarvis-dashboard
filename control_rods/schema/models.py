"""
Pydantic schema for the Control Rods planning system.

This module is the single source of truth for the *shape* of the data.
The Google Sheet is the source of truth for the *values*; this schema is
what guarantees those values are well-formed before anything downstream
(the API, the frontend) is allowed to see them.

Three layers, by design:

    Layer 1  Destinations   slow-moving end-states, no steps
    Layer 2  Quarter        the current 90 days, fully step-by-step
    Layer 3  Annual log     once-a-year recalibration entries

The whole point of the architecture is that a broken step can only ever
invalidate a single quarter, never the destinations. The schema enforces
that separation: Destinations and QuarterTasks are different types and
cannot leak into each other.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# --------------------------------------------------------------------------
# Enums - constrained vocabularies. Keeping these closed means a typo in the
# sheet ("in-progres") fails validation loudly instead of silently creating
# a new status nobody styled for.
# --------------------------------------------------------------------------


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"
    DROPPED = "dropped"


class Engine(str, Enum):
    """Which of the three engines a task or destination feeds.

    Mirrors the strategy: the Floor is the job + savings (guaranteed),
    the Skill bet compounds the income, the Venture is the high-variance
    ceiling. Tagging every task with its engine is what lets the dashboard
    show whether effort is actually distributed the way the plan intends -
    or whether the venture is quietly eating the floor again.
    """

    FLOOR = "floor"
    SKILL = "skill"
    VENTURE = "venture"
    PERSONAL = "personal"


class Confidence(str, Enum):
    """How locked-in a destination is. Destinations are not all equal:
    PR is near-certain given the plan; the venture ceiling is a bet."""

    LOCKED = "locked"
    LIKELY = "likely"
    STRETCH = "stretch"


# --------------------------------------------------------------------------
# Layer 1 - Destinations
# --------------------------------------------------------------------------


class Destination(BaseModel):
    """A fixed end-state. No steps live here on purpose.

    A destination answers 'what do I want', never 'what am I doing about it
    this week'. That second question belongs to Layer 2. Keeping steps out of
    this layer is what stops a missed task from feeling like the dream broke.
    """

    id: str = Field(..., description="Stable slug, e.g. 'pr_secured'.")
    title: str = Field(..., min_length=1)
    detail: str = Field("", description="One line on what 'done' means.")
    engine: Engine
    target_date: Optional[date] = Field(
        None, description="Soft horizon, not a deadline to fall behind."
    )
    confidence: Confidence = Confidence.LIKELY

    # Optional numeric target, used for the money destination so the
    # frontend can render a progress bar against a real number.
    target_value: Optional[float] = Field(
        None, description="Numeric goal (e.g. 340000 for the CAD target)."
    )
    current_value: Optional[float] = Field(
        None, description="Latest known value toward target_value."
    )
    unit: Optional[str] = Field(None, description="e.g. 'CAD'.")

    @model_validator(mode="after")
    def _progress_needs_a_target(self) -> "Destination":
        if self.current_value is not None and self.target_value is None:
            raise ValueError(
                f"Destination '{self.id}' has a current_value but no "
                f"target_value to measure it against."
            )
        return self

    @property
    def progress_pct(self) -> Optional[float]:
        """Percent complete, only if this is a numeric destination."""
        if self.target_value and self.target_value > 0 and self.current_value is not None:
            return round(min(self.current_value / self.target_value, 1.0) * 100, 1)
        return None


# --------------------------------------------------------------------------
# Layer 2 - Quarter + tasks
# --------------------------------------------------------------------------


class QuarterTask(BaseModel):
    """One concrete, checkable step inside the current 90 days.

    This is the only layer that is allowed to be granular and the only
    layer that is allowed to 'fail'. A task slipping is recoverable in
    weeks and never cascades upward.
    """

    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    engine: Engine
    status: TaskStatus = TaskStatus.NOT_STARTED
    # Optional link back to the destination this step serves, so the
    # dashboard can show "this week's work -> which end-state".
    serves_destination: Optional[str] = Field(
        None, description="id of the Destination this task advances."
    )
    note: str = ""

    @property
    def is_complete(self) -> bool:
        return self.status == TaskStatus.DONE


class Quarter(BaseModel):
    """The active 90-day plan. Exactly one is 'current' at a time."""

    label: str = Field(..., description="e.g. 'Q3 2026'.")
    theme: str = Field("", description="The one sentence this quarter is about.")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    tasks: list[QuarterTask] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dates_in_order(self) -> "Quarter":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(
                f"Quarter '{self.label}' ends before it starts."
            )
        return self

    @property
    def completion_pct(self) -> float:
        live = [t for t in self.tasks if t.status != TaskStatus.DROPPED]
        if not live:
            return 0.0
        done = sum(1 for t in live if t.is_complete)
        return round(done / len(live) * 100, 1)


# --------------------------------------------------------------------------
# Layer 3 - Annual recalibration log
# --------------------------------------------------------------------------


class AnnualEntry(BaseModel):
    """A once-a-year reflection. Deviation recorded here is treated as
    input for next year's quarters, not as failure."""

    year: int = Field(..., ge=2024, le=2100)
    kept: str = Field("", description="What's still the right destination.")
    changed: str = Field("", description="What you deliberately changed your mind on.")
    learned: str = Field("", description="What the year's deviations taught you.")


# --------------------------------------------------------------------------
# The full plan - what the API serves and the frontend consumes
# --------------------------------------------------------------------------


class Plan(BaseModel):
    """The assembled three-layer plan. This is the API contract."""

    owner: str = "Operator"
    generated_at: Optional[str] = None
    destinations: list[Destination] = Field(default_factory=list)
    current_quarter: Optional[Quarter] = None
    annual_log: list[AnnualEntry] = Field(default_factory=list)

    @field_validator("destinations")
    @classmethod
    def _unique_destination_ids(cls, v: list[Destination]) -> list[Destination]:
        ids = [d.id for d in v]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate destination ids: {sorted(dupes)}")
        return v

    @model_validator(mode="after")
    def _tasks_point_at_real_destinations(self) -> "Plan":
        """A task may name the destination it serves; if it does, that
        destination must exist. This is the referential-integrity check
        that makes the two layers a connected graph rather than two lists."""
        if not self.current_quarter:
            return self
        known = {d.id for d in self.destinations}
        for task in self.current_quarter.tasks:
            if task.serves_destination and task.serves_destination not in known:
                raise ValueError(
                    f"Task '{task.id}' serves unknown destination "
                    f"'{task.serves_destination}'. Known: {sorted(known)}"
                )
        return self
