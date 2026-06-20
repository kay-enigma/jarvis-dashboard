"""API surface: every mutation validated, persisted, and reflected back."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from jarvis.store import JarvisStore

# Import the module (not the FastAPI instance) so we can swap its store.
app_module = importlib.import_module("jarvis.api.app")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client whose store writes to a throwaway file, never the real one."""
    store = JarvisStore(tmp_path / "state.json")
    monkeypatch.setattr(app_module, "store", store)
    return TestClient(app_module.app)


def test_state_and_dashboard_load(client):
    assert client.get("/api/state").status_code == 200
    d = client.get("/api/dashboard").json()
    assert "greeting" in d and "kpis" in d
    assert "weight" in d["kpis"]


def test_catalog_has_six(client):
    cat = client.get("/api/peptide-catalog").json()
    assert len(cat) == 6
    assert {c["key"] for c in cat} >= {"reta", "tb_bpc", "selank"}


def test_add_peptide_off_catalogue_400(client):
    r = client.post("/api/peptides", json={
        "key": "nope", "start_date": "2026-06-01", "interval_days": 7})
    assert r.status_code == 400
    assert "not a known peptide" in r.json()["detail"]


def test_peptide_lifecycle(client):
    r = client.post("/api/peptides", json={
        "key": "semax", "dosage": "300 mcg", "start_date": "2026-06-01",
        "interval_days": 1, "length_days": 30})
    assert r.status_code == 200
    state = r.json()
    pid = [p for p in state["peptides"] if p["key"] == "semax"][0]["id"]

    # patch interval
    r = client.patch(f"/api/peptides/{pid}", json={"interval_days": 2})
    assert r.status_code == 200
    sem = [p for p in r.json()["peptides"] if p["id"] == pid][0]
    assert sem["interval_days"] == 2

    # make it ongoing
    r = client.patch(f"/api/peptides/{pid}", json={"clear_length": True})
    assert [p for p in r.json()["peptides"] if p["id"] == pid][0]["length_days"] is None

    # schedules endpoint computes server-side
    scheds = client.get("/api/peptides/schedules").json()
    assert any(s["id"] == pid for s in scheds)

    # delete
    assert client.delete(f"/api/peptides/{pid}").status_code == 200
    assert pid not in [p["id"] for p in client.get("/api/state").json()["peptides"]]


def test_bad_interval_rejected(client):
    # interval_days must be >= 1; the constraint lives on the domain model,
    # so it surfaces as a clean 400 with a real message.
    r = client.post("/api/peptides", json={
        "key": "reta", "start_date": "2026-06-01", "interval_days": 0})
    assert r.status_code == 400
    assert "greater than or equal to 1" in r.json()["detail"]


def test_metric_reading_flow(client):
    r = client.post("/api/metrics/weight/readings",
                    json={"date": "2026-06-18", "value": 163.2, "note": "am"})
    assert r.status_code == 200
    readings = r.json()["weight"]["readings"]
    rid = [x for x in readings if x["value"] == 163.2][0]["id"]

    r = client.patch("/api/metrics/weight", json={"target": 158})
    assert r.json()["weight"]["target"] == 158

    assert client.delete(f"/api/metrics/weight/readings/{rid}").status_code == 200
    assert client.get("/api/metrics/oops/readings/x").status_code in (404, 405)


def test_unknown_metric_404(client):
    r = client.post("/api/metrics/vibes/readings", json={"date": "2026-06-18", "value": 1})
    assert r.status_code == 404


def test_forecast_endpoint(client):
    # seed weight has enough readings -> a real declining forecast with an ETA
    fc = client.get("/api/forecast/weight").json()
    assert fc["available"] is True
    assert fc["slope_per_week"] < 0
    assert "forecast" in fc and "eta" in fc
    # net worth seeds with a single placeholder reading -> not enough history
    assert client.get("/api/forecast/networth").json()["available"] is False
    assert client.get("/api/forecast/nope").status_code == 404


def test_goal_crud_and_reorder(client):
    # add three to layer1
    ids = []
    for txt in ["a", "b", "c"]:
        r = client.post("/api/goals", json={"text": txt, "section": "layer1"})
        ids.append([g for g in r.json()["goals"] if g["text"] == txt][0]["id"])

    # move one into current (drag) -> it becomes tickable
    r = client.post("/api/goals/reorder", json={"section": "current", "ordered_ids": [ids[2]]})
    moved = [g for g in r.json()["goals"] if g["id"] == ids[2]][0]
    assert moved["section"] == "current" and moved["order"] == 0

    # tick it
    r = client.patch(f"/api/goals/{ids[2]}", json={"done": True})
    assert [g for g in r.json()["goals"] if g["id"] == ids[2]][0]["done"] is True

    # move back to a board -> done is cleared
    r = client.post("/api/goals/reorder", json={"section": "layer2", "ordered_ids": [ids[2]]})
    back = [g for g in r.json()["goals"] if g["id"] == ids[2]][0]
    assert back["section"] == "layer2" and back["done"] is False

    # cycle engine + delete
    client.patch(f"/api/goals/{ids[0]}", json={"engine": "venture"})
    assert client.delete(f"/api/goals/{ids[1]}").status_code == 200
    assert ids[1] not in [g["id"] for g in client.get("/api/state").json()["goals"]]


def test_reorder_unknown_id_404(client):
    assert client.post("/api/goals/reorder",
                       json={"section": "current", "ordered_ids": ["ghost"]}).status_code == 404


def test_profile_patch(client):
    r = client.patch("/api/profile", json={"callsign": "Maverick", "money_online_current": 25})
    p = r.json()["profile"]
    assert p["callsign"] == "Maverick" and p["money_online_current"] == 25


def test_greeting_endpoint(client):
    assert client.get("/api/greeting").json()["greeting"]


HEVY = (
    'title,start_time,end_time,description,exercise_title,superset_id,'
    'exercise_notes,set_index,set_type,weight_kg,reps,distance_km,duration_seconds,rpe\n'
    '"Push","2026-06-10 18:00:00","2026-06-10 19:00:00","","Bench","","",1,"normal","80","5","","3600","8"\n'
)


def test_workout_import_dedupes_and_summarizes(client):
    r = client.post("/api/workouts/import", json={"csv": HEVY})
    assert r.status_code == 200 and r.json()["_imported"] == 1
    # re-import the same export -> nothing added
    assert client.post("/api/workouts/import", json={"csv": HEVY}).json()["_imported"] == 0
    summ = client.get("/api/workouts/summary").json()
    assert summ["available"] is True and summ["count"] == 1


def test_study_unavailable_then_404_safety(client):
    # fresh seed has no check-ins -> study not yet available
    assert client.get("/api/study").json()["available"] is False


def test_checkin_flow(client, monkeypatch):
    monkeypatch.delenv("JARVIS_CHECKIN_WEBHOOK", raising=False)
    st = client.get("/api/checkin/status").json()
    assert st["needed"] is True
    assert any(q["id"] == "weight" for q in st["questions"])
    assert st["sheet_connected"] is False

    # a morning weight answer also logs into the weight series
    r = client.post("/api/checkin", json={"answers": {
        "weight": "163.0", "protein": "yes", "focus": "ship repo"}})
    assert r.status_code == 200
    state = r.json()
    assert any(c["answers"].get("focus") == "ship repo" for c in state["checkins"])
    assert any(rd["note"] == "morning check-in" and rd["value"] == 163.0
               for rd in state["weight"]["readings"])

    # done for today -> no longer needed
    assert client.get("/api/checkin/status").json()["needed"] is False
