"""End-to-end pipeline tests against the bundled sample data + the API."""

from pathlib import Path

from fastapi.testclient import TestClient

from control_rods.pipeline import LocalFileSource
from control_rods.schema import Plan

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"


def test_local_source_loads_valid_plan():
    plan = LocalFileSource(SAMPLE).load()
    assert isinstance(plan, Plan)
    assert len(plan.destinations) == 4
    assert plan.current_quarter is not None
    assert plan.current_quarter.label == "Q3 2026"
    assert len(plan.current_quarter.tasks) == 7


def test_sample_tasks_reference_real_destinations():
    # If any task in the sample pointed at a non-existent destination,
    # Plan validation would have raised on load above. This asserts the
    # links actually resolve.
    plan = LocalFileSource(SAMPLE).load()
    known = {d.id for d in plan.destinations}
    for t in plan.current_quarter.tasks:
        if t.serves_destination:
            assert t.serves_destination in known


def test_money_destination_present_and_measurable():
    plan = LocalFileSource(SAMPLE).load()
    money = next(d for d in plan.destinations if d.id == "runway")
    assert money.target_value == 100000
    assert money.progress_pct is not None


def test_api_health_and_plan(monkeypatch):
    # Force the API to use the bundled local sample regardless of env.
    monkeypatch.setenv("CONTROL_RODS_SOURCE", "local")
    monkeypatch.setenv("CONTROL_RODS_DATA_DIR", str(SAMPLE))

    # Import after env is set so the cache starts clean.
    from control_rods.api.app import app, _cache
    _cache.clear()

    client = TestClient(app)

    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["destinations"] == 4

    plan = client.get("/api/plan").json()
    assert plan["owner"] == "Operator"
    assert len(plan["destinations"]) == 4

    quarter = client.get("/api/quarter").json()
    assert quarter["label"] == "Q3 2026"

    root = client.get("/")
    assert root.status_code == 200
    assert "CONTROL" in root.text
