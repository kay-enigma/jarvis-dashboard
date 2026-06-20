"""
Jarvis state schema.

This is the single source of truth for the *shape* of everything Jarvis
stores. Unlike the read-only Control Rods plan (which was fed by a Google
Sheet), Jarvis owns its own state: you edit it inside the app, so the schema
here is what guarantees a bad edit fails loudly at the API boundary instead
of corrupting the saved file.

One JSON document holds the whole operator state:

    profile     callsign + the hard-set targets and counters
    weight      logged body-weight readings (history -> trend charts)
    bodyfat     logged BF% readings
    networth    logged net-worth readings
    peptides    active protocols, each a dose + schedule
    goals       the four-section "No Control Rods" board

The four goal sections map to the three-layer plan plus the working set:

    layer1   Destinations          rarely change          (pin board)
    layer2   This Quarter          the current 90 days     (pin board)
    layer3   Annual Recalibration  once-a-year reflection  (pin board)
    current  Current Enhancements  the live checklist      (tick boxes)

Only `current` items are meant to be checked off; the other three are
pointers you move between boards.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def new_id() -> str:
    """Short, stable, collision-safe id for a record."""
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Shared vocabularies
# --------------------------------------------------------------------------


class Engine(str, Enum):
    """Which strategic engine a goal feeds — carried over from the roadmap so
    the board stays colour-coded the same way the plan was: Floor (job +
    savings, guaranteed), Skill (compounds income), Venture (the ceiling),
    Personal (the body / health work). NONE for anything unclassified."""

    FLOOR = "floor"
    SKILL = "skill"
    VENTURE = "venture"
    PERSONAL = "personal"
    NONE = "none"


class Section(str, Enum):
    LAYER1 = "layer1"   # Destinations
    LAYER2 = "layer2"   # This Quarter
    LAYER3 = "layer3"   # Annual recalibration
    CURRENT = "current"  # Current Enhancements (the checklist)


# --------------------------------------------------------------------------
# Peptides
# --------------------------------------------------------------------------

# The closed catalogue. You can only add protocols from these six — a typo
# or an off-list compound fails validation instead of silently appearing.
PEPTIDE_CATALOG: dict[str, dict[str, str]] = {
    "tb_bpc": {
        "label": "TB / BPC",
        "full": "TB-500 / BPC-157",
        "blurb": "Recovery — soft-tissue & gut repair",
    },
    "reta": {
        "label": "Reta",
        "full": "Retatrutide",
        "blurb": "GLP-class — appetite & fat loss",
    },
    "cjc_ipa": {
        "label": "CJC / IPA",
        "full": "CJC-1295 / Ipamorelin",
        "blurb": "GH secretagogue — recovery & sleep",
    },
    "ghk_cu": {
        "label": "GHK-Cu",
        "full": "GHK-Copper",
        "blurb": "Skin, collagen & healing",
    },
    "semax": {
        "label": "Semax",
        "full": "Semax",
        "blurb": "Nootropic — focus & neuroprotection",
    },
    "selank": {
        "label": "Selank",
        "full": "Selank",
        "blurb": "Anxiolytic — calm & focus",
    },
}

PEPTIDE_KEYS = tuple(PEPTIDE_CATALOG.keys())


class Peptide(BaseModel):
    """One running protocol: a dose, a start date, an interval and a length.

    The schedule (next dose, today, doses remaining) is *derived* from these
    four fields in peptides.py — it is never stored, so it can't drift out of
    sync with the inputs.
    """

    id: str = Field(default_factory=new_id)
    key: str = Field(..., description="Catalogue key — must be one of PEPTIDE_KEYS.")
    dosage: str = Field("", description="Free text, e.g. '0.5 mg' or '250 mcg'.")
    start_date: date
    interval_days: int = Field(..., ge=1, description="Dose every N days.")
    length_days: Optional[int] = Field(
        default=None, ge=1, description="Protocol length in days; None = ongoing."
    )
    active: bool = True
    note: str = ""

    @field_validator("key")
    @classmethod
    def _known_key(cls, v: str) -> str:
        if v not in PEPTIDE_CATALOG:
            raise ValueError(
                f"'{v}' is not a known peptide. Choose one of: "
                f"{', '.join(PEPTIDE_KEYS)}."
            )
        return v

    @property
    def label(self) -> str:
        return PEPTIDE_CATALOG[self.key]["label"]


# --------------------------------------------------------------------------
# Metrics (weight / bodyfat / net worth) — logged history
# --------------------------------------------------------------------------


class Reading(BaseModel):
    id: str = Field(default_factory=new_id)
    date: date
    value: float
    note: str = ""


class Metric(BaseModel):
    """A logged series with a target and a 'good direction'.

    direction='down' means lower is better (weight, BF%); 'up' means higher
    is better (net worth). The dashboard uses it to colour the trend arrow:
    movement toward the target is always green regardless of sign.
    """

    label: str
    unit: str = ""
    target: Optional[float] = None
    direction: str = Field("down", pattern="^(up|down)$")
    readings: list[Reading] = Field(default_factory=list)

    def sorted_readings(self) -> list[Reading]:
        return sorted(self.readings, key=lambda r: r.date)

    @property
    def latest(self) -> Optional[Reading]:
        s = self.sorted_readings()
        return s[-1] if s else None

    @property
    def previous(self) -> Optional[Reading]:
        s = self.sorted_readings()
        return s[-2] if len(s) >= 2 else None


# --------------------------------------------------------------------------
# Goals — the four-section board
# --------------------------------------------------------------------------


class Goal(BaseModel):
    id: str = Field(default_factory=new_id)
    text: str = Field(..., min_length=1)
    section: Section = Section.CURRENT
    engine: Engine = Engine.NONE
    done: bool = False  # only meaningful in the `current` section
    note: str = ""
    order: int = 0  # position within its section

    @model_validator(mode="after")
    def _done_only_in_current(self) -> "Goal":
        # A pointer card on a pin board is never "done" — only the working
        # checklist tracks completion. Normalise rather than reject so moving
        # a checked item back to a board just quietly clears the tick.
        if self.section is not Section.CURRENT:
            self.done = False
        return self


# --------------------------------------------------------------------------
# Profile + the whole state document
# --------------------------------------------------------------------------


class WorkoutSet(BaseModel):
    exercise: str
    set_index: int = 0
    set_type: str = "normal"  # normal / warmup / dropset / failure
    weight: float = 0.0       # in the parent Workout's weight_unit
    reps: int = 0
    rpe: Optional[float] = None


class Workout(BaseModel):
    """One training session, imported from Hevy (or added by hand)."""

    id: str = Field(default_factory=new_id)
    date: date
    title: str = ""               # session name, e.g. "Push A"
    start_time: str = ""          # raw source timestamp — used to dedupe imports
    weight_unit: str = "kg"       # Hevy exports kg by default
    duration_min: Optional[float] = None
    notes: str = ""
    sets: list[WorkoutSet] = Field(default_factory=list)


class CheckIn(BaseModel):
    """One morning check-in. Answers are stored as display strings keyed by
    question id (see checkin.CHECKIN_QUESTIONS); the raw values are also used
    at submit time to e.g. append a morning weight reading."""

    id: str = Field(default_factory=new_id)
    date: date
    answers: dict[str, str] = Field(default_factory=dict)
    created_at: Optional[str] = None


class Profile(BaseModel):
    callsign: str = "Operator"
    protein_target_g: int = Field(160, ge=0)

    # Set to today's date once the daily check-in is completed, so the
    # questionnaire only fires on the first open of each day.
    last_checkin_date: Optional[date] = None

    # Hard-set "money made online" counter (manual for now, feature later).
    money_online_current: float = Field(0, ge=0)
    money_online_target: float = Field(100, gt=0)

    # Narrative targets surfaced on the Money tab (edit to your own).
    networth_liquid_target: float = 100_000
    networth_total_target: float = 100_000
    car_fund_target: float = 0

    # Training + the "ideal day" setup the daily score is graded against.
    main_lifts: list[str] = Field(default_factory=list)  # pinned for strength curves
    training_target_per_week: int = 4
    setup_sleep_target: float = 4.0      # 1-5 scale
    setup_deepwork_target: float = 4.0   # hours
    setup_degging_max: float = 1.0       # hours


class JarvisState(BaseModel):
    """The whole operator state — the one document the store persists."""

    version: int = 1
    updated_at: Optional[str] = None
    profile: Profile = Field(default_factory=Profile)

    weight: Metric
    bodyfat: Metric
    networth: Metric

    peptides: list[Peptide] = Field(default_factory=list)
    goals: list[Goal] = Field(default_factory=list)
    checkins: list[CheckIn] = Field(default_factory=list)
    workouts: list[Workout] = Field(default_factory=list)

    @field_validator("peptides")
    @classmethod
    def _unique_peptide_ids(cls, v: list[Peptide]) -> list[Peptide]:
        ids = [p.id for p in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"Duplicate peptide ids: {dupes}")
        return v

    @field_validator("goals")
    @classmethod
    def _unique_goal_ids(cls, v: list[Goal]) -> list[Goal]:
        ids = [g.id for g in v]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"Duplicate goal ids: {dupes}")
        return v

    def goals_in(self, section: Section) -> list[Goal]:
        return sorted(
            [g for g in self.goals if g.section == section],
            key=lambda g: (g.order, g.text.lower()),
        )
