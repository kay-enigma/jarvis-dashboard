"""Workout ingestion/analytics and the self-study correlation engine."""

from __future__ import annotations

from datetime import date

from jarvis import study, workouts as wk
from jarvis.schema import CheckIn, JarvisState, Metric

HEVY_CSV = """title,start_time,end_time,description,exercise_title,superset_id,exercise_notes,set_index,set_type,weight_kg,reps,distance_km,duration_seconds,rpe
"Push A","2026-06-10 18:00:00","2026-06-10 19:00:00","","Bench Press","","",0,"warmup","40","10","","3600",""
"Push A","2026-06-10 18:00:00","2026-06-10 19:00:00","","Bench Press","","",1,"normal","80","5","","3600","8"
"Push A","2026-06-10 18:00:00","2026-06-10 19:00:00","","Bench Press","","",2,"normal","80","5","","3600","9"
"Pull A","2026-06-12 18:00:00","2026-06-12 19:00:00","","Deadlift","","",0,"normal","120","3","","3000","9"
"""


def _empty_state(**kw):
    m = lambda: Metric(label="x", direction="down", readings=[])
    return JarvisState(weight=m(), bodyfat=m(),
                       networth=Metric(label="n", direction="up", readings=[]), **kw)


# --- parsing ---------------------------------------------------------------

def test_parse_groups_sessions_and_sets():
    ws = wk.parse_hevy_csv(HEVY_CSV)
    assert len(ws) == 2
    push = ws[0]
    assert push.title == "Push A"
    assert push.date == date(2026, 6, 10)
    assert push.weight_unit == "kg"
    assert len(push.sets) == 3  # warmup + 2 working
    assert push.duration_min == 60.0


def test_tonnage_excludes_warmup():
    push = wk.parse_hevy_csv(HEVY_CSV)[0]
    assert wk.tonnage(push) == 800.0  # 80*5 + 80*5, warmup ignored


def test_epley_e1rm():
    assert round(wk.epley_e1rm(80, 5), 1) == 93.3
    assert wk.epley_e1rm(100, 1) == 100.0
    assert wk.epley_e1rm(0, 5) == 0.0


def test_merge_dedupes_on_reimport():
    s = _empty_state()
    first = wk.merge_import(s, wk.parse_hevy_csv(HEVY_CSV))
    again = wk.merge_import(s, wk.parse_hevy_csv(HEVY_CSV))
    assert first == 2 and again == 0
    assert len(s.workouts) == 2


STRONG_CSV = """Date,Workout Name,Duration,Exercise Name,Set Order,Weight,Reps,Distance,Seconds,Notes,Workout Notes,RPE
2023-10-15 09:15:12,"Legs",47min,"Squat (Barbell)",W,70.0,12.0,0,0.0,"","",
2023-10-15 09:15:12,"Legs",47min,"Squat (Barbell)",1,165.0,12.0,0,0.0,,,
2023-10-15 09:15:12,"Legs",47min,"Squat (Barbell)",2,165.0,10.0,0,0.0,,,
2023-10-17 10:00:00,"Push",1h 5min,"Bench Press (Barbell)",1,135.0,8.0,0,0.0,,,
"""


def test_parse_strong_format():
    ws = wk.parse_strong_csv(STRONG_CSV)
    assert len(ws) == 2
    legs = ws[0]
    assert legs.title == "Legs" and legs.date == date(2023, 10, 15)
    assert legs.weight_unit == "lb" and legs.duration_min == 47.0
    # warmup ('W') excluded from tonnage; working sets: 165*12 + 165*10
    assert wk.tonnage(legs) == 3630.0
    assert ws[1].duration_min == 65.0  # "1h 5min"


def test_auto_detect_dispatches():
    assert len(wk.parse_workouts_csv(STRONG_CSV)) == 2     # Strong
    assert len(wk.parse_workouts_csv(HEVY_CSV)) == 2       # Hevy
    import pytest
    with pytest.raises(ValueError):
        wk.parse_workouts_csv("foo,bar\n1,2\n")


def test_summary_shapes():
    s = _empty_state()
    wk.merge_import(s, wk.parse_hevy_csv(HEVY_CSV))
    out = wk.summary(s)
    assert out["available"] is True and out["count"] == 2
    assert {x["exercise"] for x in out["strength"]} == {"Bench Press", "Deadlift"}
    assert out["volume_series"][0]["tonnage"] == 800.0


# --- self-study ------------------------------------------------------------

def _checkins_sleep_drives_deepwork():
    sleeps = [2, 3, 4, 5, 3, 4, 5, 2]
    cis = []
    for i, sl in enumerate(sleeps):
        cis.append(CheckIn(
            date=date(2026, 6, 1 + i),
            answers={"sleep": str(sl), "deep_work": str(sl * 1.5),
                     "degging": str(6 - sl)},
        ))
    return cis


def test_correlation_detects_strong_relationship():
    s = _empty_state(checkins=_checkins_sleep_drives_deepwork())
    out = study.summary(s)
    assert out["available"] is True
    sd = next(c for c in out["correlations"] if c["input"] == "sleep" and c["output"] == "deep_work")
    assert sd["r"] >= 0.9 and sd["strength"] == "strong"
    # sleep should anti-correlate with degging
    sg = next(c for c in out["correlations"] if c["input"] == "sleep" and c["output"] == "degging")
    assert sg["r"] <= -0.9


def test_peak_profile_separates_best_days():
    s = _empty_state(checkins=_checkins_sleep_drives_deepwork())
    prof = study.summary(s)["peak_profile"]
    sleep_delta = next(d for d in prof["deltas"] if d["input"] == "sleep")
    assert sleep_delta["delta"] > 0  # best deep-work days have more sleep


def test_study_unavailable_without_enough_history():
    s = _empty_state(checkins=[CheckIn(date=date(2026, 6, 1), answers={"sleep": "4"})])
    out = study.summary(s)
    assert out["available"] is False and out["need"] == study.MIN_DAYS
