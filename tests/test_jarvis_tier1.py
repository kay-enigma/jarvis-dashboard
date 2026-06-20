"""Tier-1: streaks, PRs, setup score, race report, flags, dashboard bundle."""

from __future__ import annotations

from datetime import date, timedelta

from jarvis import dashboard, flags, report, streaks, study
from jarvis import workouts as wk
from jarvis.schema import CheckIn, JarvisState, Metric, Peptide, Profile, Reading, WorkoutSet, Workout

TODAY = date(2026, 6, 18)


def _state(**kw):
    m = lambda d="down": Metric(label="x", unit="lb", direction=d, readings=[])
    base = dict(weight=m(), bodyfat=m(),
                networth=Metric(label="n", unit="CAD", direction="up", readings=[]))
    base.update(kw)
    return JarvisState(**base)


def _ci(d, **ans):
    return CheckIn(date=d, answers={k: str(v) for k, v in ans.items()})


def _wo(d, lift, weight, reps, title="S"):
    return Workout(date=d, title=title, start_time=str(d),
                   weight_unit="lb", sets=[WorkoutSet(exercise=lift, weight=weight, reps=reps)])


# --- streaks ---------------------------------------------------------------

def test_checkin_and_protein_streaks():
    cis = [_ci(TODAY - timedelta(days=i), protein="yes" if i < 2 else "no")
           for i in range(4)]  # today, -1, -2, -3 all have check-ins
    s = streaks.summary(_state(checkins=cis), TODAY)
    assert s["checkin_streak"] == 4
    assert s["protein_streak"] == 2  # only today + yesterday were "yes"


def test_streak_breaks_on_gap():
    cis = [_ci(TODAY), _ci(TODAY - timedelta(days=3))]
    assert streaks.summary(_state(checkins=cis), TODAY)["checkin_streak"] == 1


# --- PRs -------------------------------------------------------------------

def test_recent_pr_detected():
    st = _state(workouts=[
        _wo(TODAY - timedelta(days=30), "Bench", 80, 5),
        _wo(TODAY - timedelta(days=3), "Bench", 100, 5),  # new best, recent
    ])
    prs = wk.recent_prs(st, TODAY, days=14)
    assert any(p["exercise"] == "Bench" for p in prs)
    # an old-only best is not "recent"
    old = _state(workouts=[_wo(TODAY - timedelta(days=40), "Squat", 150, 3)])
    assert wk.recent_prs(old, TODAY, days=14) == []


# --- setup score -----------------------------------------------------------

def test_setup_score_perfect_and_poor():
    p = Profile()  # sleep4, deepwork4, degging_max1
    good = study.setup_score({"sleep": "5", "deep_work": "5", "degging": "0", "protein": "yes"}, p)
    assert good["score"] == 100
    bad = study.setup_score({"sleep": "2", "deep_work": "1", "degging": "5", "protein": "no"}, p)
    assert bad["score"] < 35


# --- report ----------------------------------------------------------------

def test_race_report_counts_week():
    st = _state(
        workouts=[_wo(TODAY - timedelta(days=2), "Bench", 100, 5),
                  _wo(TODAY - timedelta(days=10), "Bench", 95, 5)],
        checkins=[_ci(TODAY - timedelta(days=1), deep_work="4", degging="1")],
    )
    r = report.build(st, TODAY)
    assert r["sessions"] == 1 and r["sessions_prev"] == 1
    assert r["deep_work_avg"] == 4.0
    assert "verdict" in r


# --- flags -----------------------------------------------------------------

def test_flags_dose_today_and_pr():
    st = _state(
        peptides=[Peptide(key="reta", start_date=TODAY, interval_days=7, dosage="0.5 mg")],
        workouts=[_wo(TODAY - timedelta(days=20), "Bench", 80, 5),
                  _wo(TODAY - timedelta(days=2), "Bench", 110, 5)],
    )
    out = flags.build(st, TODAY)
    txt = " ".join(f["text"] for f in out)
    assert "dose today" in txt
    assert "PR" in txt


# --- dashboard bundle ------------------------------------------------------

def test_dashboard_includes_tier1_blocks():
    d = dashboard.build(_state(checkins=[_ci(TODAY, sleep="4")]), TODAY)
    for key in ("streaks", "flags", "report", "setup"):
        assert key in d
