"""
First-run seed.

When the store finds no saved state, it builds this. It's a generic, ready-to-
edit example so the app is useful and demoable the first time it opens — then
every value is editable in-app and your edits become the saved state. Replace
these placeholders with your own goals, metrics, and protocols.
"""

from __future__ import annotations

from datetime import date

from .schema import (
    Engine,
    Goal,
    JarvisState,
    Metric,
    Peptide,
    Profile,
    Reading,
    Section,
    new_id,
)


def _r(d: str, v: float, note: str = "") -> Reading:
    return Reading(id=new_id(), date=date.fromisoformat(d), value=v, note=note)


def build_seed(today: date | None = None) -> JarvisState:
    today = today or date.today()

    # ---- Weight: an example cut, target 165 --------------------------------
    weight = Metric(
        label="Weight",
        unit="lb",
        target=165.0,
        direction="down",
        readings=[
            _r("2026-04-23", 185.0, "starting point"),
            _r("2026-04-30", 181.5),
            _r("2026-05-07", 178.0),
            _r("2026-05-14", 175.5),
            _r("2026-05-21", 173.0),
            _r("2026-05-28", 171.5),
            _r("2026-06-04", 170.0),
            _r("2026-06-11", 171.0, "water fluctuation"),
            _r("2026-06-17", 169.0),
        ],
    )

    # ---- Body fat: example estimates, target 12% ---------------------------
    bodyfat = Metric(
        label="Body fat",
        unit="%",
        target=12.0,
        direction="down",
        readings=[
            _r("2026-04-23", 22.0, "estimate"),
            _r("2026-05-14", 19.0, "estimate"),
            _r("2026-06-04", 17.0, "estimate"),
            _r("2026-06-17", 15.5, "estimate"),
        ],
    )

    # ---- Net worth: PLACEHOLDER — set your own number/target ---------------
    networth = Metric(
        label="Net worth",
        unit="USD",
        target=100_000,
        direction="up",
        readings=[
            _r(today.isoformat(), 0.0, "PLACEHOLDER — log your real number"),
        ],
    )

    # ---- Peptides: one example protocol — edit or remove -------------------
    peptides = [
        Peptide(
            id=new_id(),
            key="tb_bpc",
            dosage="250 mcg",  # PLACEHOLDER — set your real dose
            start_date=date(2026, 6, 1),
            interval_days=1,
            length_days=30,
            active=True,
            note="Example protocol — edit dose/schedule or remove.",
        ),
    ]

    # ---- Goals: the four-section board (generic examples) ------------------
    goals: list[Goal] = []

    def add(text, section, engine=Engine.NONE, done=False, note="", order=0):
        goals.append(Goal(id=new_id(), text=text, section=section,
                          engine=engine, done=done, note=note, order=order))

    # Layer 1 — Destinations (pin board)
    add("Financial runway secured", Section.LAYER1, Engine.FLOOR, order=0,
        note="Your north-star number, invested — not idle cash.")
    add("Career milestone reached", Section.LAYER1, Engine.SKILL, order=1,
        note="The role / level you're aiming for.")
    add("Peak physical condition", Section.LAYER1, Engine.PERSONAL, order=2,
        note="Lean and strong, sustainably.")
    add("Launch something of your own", Section.LAYER1, Engine.VENTURE, order=3,
        note="A product/venture with real traction.")

    # Layer 2 — This Quarter (pin board)
    add("Finish the current training block", Section.LAYER2, Engine.PERSONAL, order=0)
    add("Ship the portfolio project", Section.LAYER2, Engine.SKILL, order=1,
        note="The single highest-leverage artifact right now.")
    add("Earn a key certification", Section.LAYER2, Engine.SKILL, order=2)
    add("Lock a recurring savings transfer", Section.LAYER2, Engine.FLOOR, order=3)
    add("Open-source contribution (one merged PR)", Section.LAYER2, Engine.SKILL, order=4)

    # Layer 3 — Annual recalibration (pin board)
    add("2026 — Dropped a project that didn't fit", Section.LAYER3, Engine.VENTURE, order=0,
        note="Deliberate recalibration, not failure. Deviation = input.")
    add("2026 — Health habits holding", Section.LAYER3, Engine.PERSONAL, order=1)

    # Current Enhancements — the live checklist (only section with ticks)
    add("Hit your protein target today", Section.CURRENT, Engine.PERSONAL, done=False, order=0)
    add("Train — log the session", Section.CURRENT, Engine.PERSONAL, done=False, order=1)
    add("Ship one commit to the project", Section.CURRENT, Engine.SKILL, done=False, order=2)
    add("One deep-work block, no distractions", Section.CURRENT, Engine.SKILL, done=False, order=3)
    add("Review the plan for 5 minutes", Section.CURRENT, Engine.FLOOR, done=False, order=4)

    return JarvisState(
        profile=Profile(callsign="Operator"),
        weight=weight,
        bodyfat=bodyfat,
        networth=networth,
        peptides=peptides,
        goals=goals,
    )
