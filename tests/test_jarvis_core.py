"""Core logic: schema, peptide scheduling, dashboard maths, store round-trip."""

from __future__ import annotations

from datetime import date

import pytest

from jarvis import dashboard as dash
from jarvis import peptides as ps
from jarvis.greetings import greeting
from jarvis.schema import (
    Engine,
    Goal,
    JarvisState,
    Metric,
    Peptide,
    Reading,
    Section,
)
from jarvis.seed import build_seed
from jarvis.store import JarvisStore


# --- schema ---------------------------------------------------------------

def test_peptide_rejects_unknown_key():
    with pytest.raises(ValueError):
        Peptide(key="creatine", start_date=date(2026, 1, 1), interval_days=7)


def test_peptide_accepts_catalogue_key():
    p = Peptide(key="reta", start_date=date(2026, 1, 1), interval_days=7)
    assert p.label == "Reta"


def test_goal_done_cleared_outside_current():
    g = Goal(text="x", section=Section.LAYER1, done=True)
    assert g.done is False  # pin-board cards are never "done"
    g2 = Goal(text="y", section=Section.CURRENT, done=True)
    assert g2.done is True


def test_duplicate_goal_ids_rejected():
    base = build_seed()
    dup = base.goals[0].model_copy()
    base.goals.append(dup)
    with pytest.raises(ValueError):
        JarvisState.model_validate(base.model_dump(mode="json"))


# --- peptide scheduling ----------------------------------------------------

def test_weekly_dose_lands_on_today():
    # 8 weeks after a Thursday start is exactly today
    pep = Peptide(key="reta", start_date=date(2026, 4, 23), interval_days=7)
    today = date(2026, 6, 18)
    s = ps.schedule(pep, today)
    assert s["is_today"] is True
    assert s["next_dose"] == "2026-06-18"
    # today's dose is upcoming, not yet counted as taken
    assert s["doses_done"] == 8


def test_next_dose_skips_to_future():
    pep = Peptide(key="reta", start_date=date(2026, 4, 23), interval_days=7)
    s = ps.schedule(pep, date(2026, 6, 19))
    assert s["next_dose"] == "2026-06-25"
    assert s["is_today"] is False
    assert s["days_until"] == 6


def test_finite_protocol_total_and_finish():
    pep = Peptide(key="bpc" if False else "tb_bpc", start_date=date(2026, 6, 1),
                  interval_days=3, length_days=10)
    assert ps.total_doses(pep) == 4  # 06-01, 04, 07, 10
    s = ps.schedule(pep, date(2026, 6, 18))
    assert s["finished"] is True
    assert s["next_dose"] is None
    assert s["progress_pct"] == 100.0


def test_upcoming_merges_and_flags_today():
    state = build_seed()  # seeds a daily example protocol covering 2026-06-18
    rows = ps.upcoming(state, date(2026, 6, 18), horizon_days=21)
    assert rows, "expected upcoming doses"
    assert rows[0]["is_today"] is True
    assert rows[0]["date"] == "2026-06-18"


# --- dashboard -------------------------------------------------------------

def test_dashboard_trend_direction_aware():
    weight = Metric(label="W", unit="lb", target=160, direction="down",
                    readings=[Reading(date=date(2026, 6, 1), value=170),
                              Reading(date=date(2026, 6, 8), value=167)])
    state = _minimal_state(weight=weight)
    out = dash.build(state, today=date(2026, 6, 8))
    wk = out["kpis"]["weight"]
    assert wk["delta"] == -3.0
    assert wk["trend_good"] is True  # down is good for weight


def test_dashboard_networth_up_is_good():
    nw = Metric(label="NW", unit="USD", target=300000, direction="up",
                readings=[Reading(date=date(2026, 6, 1), value=1000),
                          Reading(date=date(2026, 6, 8), value=1500)])
    state = _minimal_state(networth=nw)
    out = dash.build(state, today=date(2026, 6, 8))
    assert out["kpis"]["networth"]["trend_good"] is True


def test_dashboard_todos_only_current_section():
    state = build_seed()
    out = dash.build(state, today=date(2026, 6, 18))
    assert out["todo_total"] == len([g for g in state.goals if g.section == Section.CURRENT])


# --- greetings -------------------------------------------------------------

def test_greeting_substitutes_name_and_never_empty():
    for _ in range(50):
        g = greeting("Ace")
        assert g and "{name}" not in g


# --- forecast --------------------------------------------------------------

def _readings(pairs):
    return [Reading(date=date.fromisoformat(d), value=v) for d, v in pairs]


def test_linear_trend_recovers_slope():
    from jarvis import forecast as fc
    rs = _readings([("2026-06-01", 170), ("2026-06-08", 167),
                    ("2026-06-15", 164), ("2026-06-22", 161)])
    fit = fc.linear_trend(rs)
    assert round(fit["slope_per_day"], 4) == round(-3 / 7, 4)
    assert fit["r2"] == 1.0  # a perfect line


def test_eta_hits_target_in_future_only_when_heading_there():
    from jarvis import forecast as fc
    rs = _readings([("2026-06-01", 170), ("2026-06-08", 167),
                    ("2026-06-15", 164), ("2026-06-22", 161)])
    eta = fc.eta_to_target(rs, target=160, direction="down")
    assert eta and eta["reached"] is False and eta["days"] >= 1
    # losing weight but the "target" is above you, or wrong direction -> no ETA
    assert fc.eta_to_target(rs, target=160, direction="up") is None


def test_anomaly_isolates_single_spike():
    from jarvis import forecast as fc
    rs = _readings([("2026-06-01", 100), ("2026-06-02", 100), ("2026-06-03", 100),
                    ("2026-06-04", 100), ("2026-06-05", 140), ("2026-06-06", 100),
                    ("2026-06-07", 100), ("2026-06-08", 100)])
    flags = fc.anomalies(rs)
    assert len(flags) == 1 and flags[0]["value"] == 140


def test_summary_needs_minimum_history():
    from jarvis import forecast as fc
    assert fc.summary(Metric(label="W", unit="lb", direction="down",
                             readings=_readings([("2026-06-01", 170)])))["available"] is False
    out = fc.summary(Metric(label="W", unit="lb", target=160, direction="down",
                            readings=_readings([("2026-06-01", 170), ("2026-06-08", 167),
                                                ("2026-06-15", 164)])))
    assert out["available"] is True
    assert out["slope_per_week"] < 0 and out["forecast"]


# --- check-in --------------------------------------------------------------

def test_checkin_needed_logic():
    from jarvis import checkin
    s = build_seed()
    assert checkin.needs_checkin(s, date(2026, 6, 18)) is True
    s.profile.last_checkin_date = date(2026, 6, 18)
    assert checkin.needs_checkin(s, date(2026, 6, 18)) is False
    assert checkin.needs_checkin(s, date(2026, 6, 19)) is True  # new day


def test_push_to_sheet_noop_without_webhook(monkeypatch):
    from jarvis import checkin
    monkeypatch.delenv("JARVIS_CHECKIN_WEBHOOK", raising=False)
    assert checkin.push_to_sheet({"x": "1"}) is False


# --- store -----------------------------------------------------------------

def test_store_seeds_then_round_trips(tmp_path):
    store = JarvisStore(tmp_path / "state.json")
    assert not store.path.exists()
    state = store.load()  # seeds + writes
    assert store.path.exists()
    assert state.peptides[0].key in {"tb_bpc", "reta", "cjc_ipa", "ghk_cu", "semax", "selank"}

    def add(s):
        s.goals.append(Goal(text="ship it", section=Section.CURRENT, engine=Engine.SKILL))

    store.mutate(add)
    reloaded = store.load()
    assert any(g.text == "ship it" for g in reloaded.goals)


def test_store_mutation_revalidates(tmp_path):
    store = JarvisStore(tmp_path / "state.json")
    store.load()

    def break_it(s):
        s.peptides[0].interval_days = 0  # violates ge=1

    with pytest.raises(Exception):
        store.mutate(break_it)


# --- helpers ---------------------------------------------------------------

def _minimal_state(weight=None, networth=None):
    m = lambda lbl, d: Metric(label=lbl, direction=d, readings=[])
    return JarvisState(
        weight=weight or m("W", "down"),
        bodyfat=m("BF", "down"),
        networth=networth or m("NW", "up"),
    )
