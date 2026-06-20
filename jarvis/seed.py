"""
First-run seed.

When the store finds no saved state, it builds this. Everything here is
populated from the operator's actual context (the cut, the Reta protocol, the
5-year plan / three engines) so Jarvis is useful the first time it opens —
then every value is editable in-app and your edits become the saved state.

The numbers are starting points, not gospel: net worth is an explicit
placeholder, the Reta dose is a placeholder to overwrite, etc. Notes call out
which ones to replace.
"""

from __future__ import annotations

from datetime import date, timedelta

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

    # ---- Weight: the cut, ~184 -> ~164, target 160.1 -----------------------
    weight = Metric(
        label="Weight",
        unit="lb",
        target=160.1,
        direction="down",
        readings=[
            _r("2026-04-23", 184.2, "8 weeks out"),
            _r("2026-04-30", 178.0),
            _r("2026-05-07", 173.3),
            _r("2026-05-14", 169.6),
            _r("2026-05-21", 167.5),
            _r("2026-05-28", 166.4),
            _r("2026-06-04", 165.1),
            _r("2026-06-11", 167.5, "carb/water bump"),
            _r("2026-06-15", 164.4),
            _r("2026-06-17", 164.1),
        ],
    )

    # ---- Body fat: rough estimates, target ~11% for a full six-pack --------
    bodyfat = Metric(
        label="Body fat",
        unit="%",
        target=11.0,
        direction="down",
        readings=[
            _r("2026-04-23", 22.0, "estimate"),
            _r("2026-05-14", 18.0, "estimate"),
            _r("2026-06-04", 16.0, "estimate"),
            _r("2026-06-17", 14.0, "photo read — upper 4 + obliques"),
        ],
    )

    # ---- Net worth: PLACEHOLDER — overwrite with your real number ----------
    networth = Metric(
        label="Net worth",
        unit="CAD",
        target=300_000,  # liquid target; 340k total incl. car (see Money tab)
        direction="up",
        readings=[
            _r(today.isoformat(), 0.0, "PLACEHOLDER — log your real net worth"),
        ],
    )

    # ---- Peptides: Reta active (the cut compound). Dose is a placeholder. ---
    peptides = [
        Peptide(
            id=new_id(),
            key="reta",
            dosage="0.5 mg",  # PLACEHOLDER — set your real dose
            start_date=date(2026, 4, 23),
            interval_days=7,  # GLP-class, weekly
            length_days=None,  # ongoing through the cut
            active=True,
            note="Cut compound. Holding dose, not climbing — last pounds want a shallow deficit.",
        ),
    ]

    # ---- Goals: the four-section board -------------------------------------
    goals: list[Goal] = []

    def add(text, section, engine=Engine.NONE, done=False, note="", order=0):
        goals.append(Goal(id=new_id(), text=text, section=section,
                          engine=engine, done=done, note=note, order=order))

    # Layer 1 — Destinations (pin board)
    add("PR secured (citizenship in sight)", Section.LAYER1, Engine.FLOOR, order=0,
        note="IELTS → PGWP → AAIP/CEC → PR. The floor under everything.")
    add("$340k generated — $300k liquid + parents' car", Section.LAYER1, Engine.FLOOR, order=1,
        note="Liquid in index funds, not cash. Car ~$40k carved out of the total.")
    add("Remote role at US-market pay", Section.LAYER1, Engine.SKILL, order=2,
        note="Live anywhere in Canada now; anywhere on earth after citizenship.")
    add("Parents' car — 20–30 lakh, ~2030", Section.LAYER1, Engine.VENTURE, order=3,
        note="~$40k CAD via Wise → INR. You as documented payer.")

    # Layer 2 — This Quarter (pin board)
    add("Finish the cut → land ~160 lean", Section.LAYER2, Engine.PERSONAL, order=0,
        note="Hold protocol, 160g protein, judge by the mirror not the scale.")
    add("Ship the Layer 2 repo (Airflow + dbt/Snowflake + FastAPI + Claude API)",
        Section.LAYER2, Engine.SKILL, order=1, note="The single highest-leverage artifact right now.")
    add("Finish dbt + Databricks certs", Section.LAYER2, Engine.SKILL, order=2)
    add("Book IELTS (gates PR — do it early)", Section.LAYER2, Engine.FLOOR, order=3)
    add("Lock a recurring savings transfer", Section.LAYER2, Engine.FLOOR, order=4)
    add("One merged OSS PR (dbt / Airflow / FastF1-adjacent)", Section.LAYER2, Engine.SKILL, order=5)

    # Layer 3 — Annual recalibration (pin board)
    add("2026 — Killed ResearchGrade on purpose", Section.LAYER3, Engine.VENTURE, order=0,
        note="Deliberate recalibration, not failure: a venture that endangered the PR floor "
             "was a ceiling not worth reaching for. Deviation = input.")
    add("2026 — Cut working; reta + 160g protein holding", Section.LAYER3, Engine.PERSONAL, order=1,
        note="Stage-1 jacked nearly done. Lean mass intact while losing ~2–3 lb/wk.")

    # Current Enhancements — the live checklist (the only section with ticks)
    add("Hit protein: 160g today", Section.CURRENT, Engine.PERSONAL, done=False, order=0)
    add("Train — log the session", Section.CURRENT, Engine.PERSONAL, done=False, order=1)
    add("Ship one commit to the Layer 2 repo", Section.CURRENT, Engine.SKILL, done=False, order=2)
    add("Book the IELTS slot", Section.CURRENT, Engine.FLOOR, done=False, order=3)
    add("30 min on the OSS PR", Section.CURRENT, Engine.SKILL, done=False, order=4)

    return JarvisState(
        profile=Profile(callsign="Operator"),
        weight=weight,
        bodyfat=bodyfat,
        networth=networth,
        peptides=peptides,
        goals=goals,
    )
