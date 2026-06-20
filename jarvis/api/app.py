"""
Jarvis HTTP API.

Read:
    GET  /                              the single-page dashboard (HTML)
    GET  /api/state                     the full editable state
    GET  /api/dashboard                 computed home-page KPIs
    GET  /api/greeting                  one fresh greeting (re-roll button)
    GET  /api/peptide-catalog           the six selectable compounds
    GET  /api/health                    liveness + where state is stored

Write (all validated, all persisted atomically, all return the new state):
    Peptides   POST /api/peptides · PATCH/DELETE /api/peptides/{id}
    Metrics    POST/DELETE /api/metrics/{kind}/readings · PATCH /api/metrics/{kind}
    Goals      POST /api/goals · PATCH/DELETE /api/goals/{id} · POST /api/goals/reorder
    Profile    PATCH /api/profile

Design: every mutation goes through JarvisStore.mutate (load → apply →
re-validate → atomic save) and returns the whole fresh state, so the
frontend re-renders from one authoritative response and never drifts.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from .. import checkin as checkin_mod
from .. import dashboard as dash
from .. import forecast as fc
from .. import networth as nw_sheet
from .. import peptides as pep_sched
from .. import study as study_mod
from .. import workouts as wk
from ..greetings import greeting
from ..schema import (
    PEPTIDE_CATALOG,
    CheckIn,
    Engine,
    Goal,
    Peptide,
    Reading,
    Section,
    new_id,
    now_iso,
)
from ..store import JarvisStore

app = FastAPI(
    title="Jarvis",
    description="Personal operations dashboard — peptides, body, money, the 5-year plan.",
    version="1.0.0",
)

store = JarvisStore()

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=_FRONTEND / "static"), name="static")

_METRIC_FIELDS = {"weight": "weight", "bodyfat": "bodyfat", "networth": "networth"}


def _state_json() -> JSONResponse:
    return JSONResponse(store.load().model_dump(mode="json"))


def _validation_error(exc: Exception) -> HTTPException:
    """Turn a Pydantic/value error into a clean 400 with the real message."""
    if isinstance(exc, ValidationError):
        msgs = "; ".join(e["msg"] for e in exc.errors())
        return HTTPException(status_code=400, detail=msgs or str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (_FRONTEND / "index.html").read_text(encoding="utf-8")


@app.get("/api/state")
def get_state() -> JSONResponse:
    return _state_json()


@app.get("/api/dashboard")
def get_dashboard() -> JSONResponse:
    state = store.load()
    payload = dash.build(state)
    payload["greeting"] = greeting(state.profile.callsign)
    return JSONResponse(payload)


@app.get("/api/greeting")
def get_greeting() -> dict:
    return {"greeting": greeting(store.load().profile.callsign)}


@app.get("/api/checkin/status")
def checkin_status() -> dict:
    """Whether the daily check-in is still pending today, plus the questions
    to ask and whether a Sheet is wired up."""
    state = store.load()
    today = date.today()
    return {
        "needed": checkin_mod.needs_checkin(state, today),
        "date": today.isoformat(),
        "questions": checkin_mod.CHECKIN_QUESTIONS,
        "sheet_connected": checkin_mod.webhook_url() is not None,
    }


class CheckInIn(BaseModel):
    answers: dict[str, str] = {}


@app.post("/api/checkin")
def submit_checkin(body: CheckInIn) -> JSONResponse:
    today = date.today()
    answers = {k: v for k, v in body.answers.items() if v not in (None, "")}

    def apply(s):
        s.profile.last_checkin_date = today
        s.checkins.append(CheckIn(date=today, answers=answers, created_at=now_iso()))
        # A morning weight answer also logs into the weight series.
        raw = answers.get("weight")
        if raw:
            try:
                s.weight.readings.append(
                    Reading(date=today, value=float(raw), note="morning check-in")
                )
            except ValueError:
                pass

    store.mutate(apply)
    # Best-effort sync to the Google Sheet (never blocks the save).
    pushed = checkin_mod.push_to_sheet({"date": today.isoformat(), **answers})
    resp = store.load().model_dump(mode="json")
    resp["_sheet_pushed"] = pushed
    return JSONResponse(resp)


@app.get("/api/peptide-catalog")
def get_catalog() -> JSONResponse:
    return JSONResponse(
        [{"key": k, **v} for k, v in PEPTIDE_CATALOG.items()]
    )


@app.get("/api/peptides/schedules")
def get_peptide_schedules() -> JSONResponse:
    """Per-protocol schedule summary (next dose, today flag, doses
    done/total, % through) computed in Python from each peptide's fields."""
    today = date.today()
    state = store.load()
    return JSONResponse([pep_sched.schedule(p, today) for p in state.peptides])


@app.get("/api/health")
def health() -> dict:
    try:
        state = store.load()
        return {
            "status": "ok",
            "store": str(store.path),
            "peptides": len(state.peptides),
            "goals": len(state.goals),
            "updated_at": state.updated_at,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {"status": "degraded", "error": str(exc)}


# --------------------------------------------------------------------------
# Peptides
# --------------------------------------------------------------------------


class PeptideIn(BaseModel):
    key: str
    dosage: str = ""
    start_date: date
    interval_days: int
    length_days: Optional[int] = None
    active: bool = True
    note: str = ""


class PeptidePatch(BaseModel):
    dosage: Optional[str] = None
    start_date: Optional[date] = None
    interval_days: Optional[int] = None
    length_days: Optional[int] = None
    active: Optional[bool] = None
    note: Optional[str] = None
    clear_length: bool = False  # explicit "make it ongoing" flag


@app.post("/api/peptides")
def add_peptide(body: PeptideIn) -> JSONResponse:
    try:
        pep = Peptide(id=new_id(), **body.model_dump())
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    store.mutate(lambda s: s.peptides.append(pep))
    return _state_json()


@app.patch("/api/peptides/{pep_id}")
def update_peptide(pep_id: str, body: PeptidePatch) -> JSONResponse:
    fields = body.model_dump(exclude_unset=True)
    fields.pop("clear_length", None)

    def apply(s):
        for p in s.peptides:
            if p.id == pep_id:
                for k, v in fields.items():
                    setattr(p, k, v)
                if body.clear_length:
                    p.length_days = None
                return
        raise KeyError(pep_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No peptide {pep_id}")
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    return _state_json()


@app.delete("/api/peptides/{pep_id}")
def delete_peptide(pep_id: str) -> JSONResponse:
    def apply(s):
        before = len(s.peptides)
        s.peptides[:] = [p for p in s.peptides if p.id != pep_id]
        if len(s.peptides) == before:
            raise KeyError(pep_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No peptide {pep_id}")
    return _state_json()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


class ReadingIn(BaseModel):
    date: date
    value: float
    note: str = ""


class MetricPatch(BaseModel):
    target: Optional[float] = None
    unit: Optional[str] = None


def _metric_attr(kind: str) -> str:
    if kind not in _METRIC_FIELDS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown metric '{kind}'. Use one of: {', '.join(_METRIC_FIELDS)}.",
        )
    return _METRIC_FIELDS[kind]


@app.post("/api/metrics/{kind}/readings")
def add_reading(kind: str, body: ReadingIn) -> JSONResponse:
    attr = _metric_attr(kind)
    reading = Reading(id=new_id(), **body.model_dump())
    store.mutate(lambda s: getattr(s, attr).readings.append(reading))
    return _state_json()


@app.delete("/api/metrics/{kind}/readings/{reading_id}")
def delete_reading(kind: str, reading_id: str) -> JSONResponse:
    attr = _metric_attr(kind)

    def apply(s):
        m = getattr(s, attr)
        before = len(m.readings)
        m.readings[:] = [r for r in m.readings if r.id != reading_id]
        if len(m.readings) == before:
            raise KeyError(reading_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No reading {reading_id}")
    return _state_json()


# --------------------------------------------------------------------------
# Workouts (Hevy import) + self-study
# --------------------------------------------------------------------------


class WorkoutImport(BaseModel):
    csv: str


@app.post("/api/workouts/import")
def import_workouts(body: WorkoutImport) -> JSONResponse:
    """Ingest a Hevy or Strong CSV export (auto-detected); only
    previously-unseen sessions are added."""
    try:
        incoming = wk.parse_workouts_csv(body.csv)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}")
    added_box = {"n": 0}

    def apply(s):
        added_box["n"] = wk.merge_import(s, incoming)

    store.mutate(apply)
    resp = store.load().model_dump(mode="json")
    resp["_imported"] = added_box["n"]
    resp["_parsed"] = len(incoming)
    return JSONResponse(resp)


@app.delete("/api/workouts/{workout_id}")
def delete_workout(workout_id: str) -> JSONResponse:
    def apply(s):
        before = len(s.workouts)
        s.workouts[:] = [w for w in s.workouts if w.id != workout_id]
        if len(s.workouts) == before:
            raise KeyError(workout_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No workout {workout_id}")
    return _state_json()


@app.get("/api/workouts/summary")
def workouts_summary() -> JSONResponse:
    return JSONResponse(wk.summary(store.load()))


@app.get("/api/workouts/exercises")
def workouts_exercises() -> JSONResponse:
    """All exercises seen + session counts — feeds the lift picker."""
    return JSONResponse(wk.exercise_frequency(store.load()))


@app.get("/api/export")
def export_state():
    """Download the full state as a JSON backup."""
    payload = store.load().model_dump(mode="json")
    fname = f"jarvis-backup-{date.today().isoformat()}.json"
    return JSONResponse(payload, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})


@app.get("/api/study")
def study() -> JSONResponse:
    return JSONResponse(study_mod.summary(store.load()))


@app.get("/api/networth/sheet-status")
def networth_sheet_status() -> dict:
    return {"connected": nw_sheet.sheet_url() is not None}


@app.post("/api/networth/sync")
def networth_sync() -> JSONResponse:
    """Pull net worth from the money sheet and log it as today's reading
    (replacing an earlier reading from today if there is one)."""
    data = nw_sheet.fetch()
    if data is None:
        raise HTTPException(
            status_code=502,
            detail="Couldn't read the money sheet. Is it deployed to 'Anyone' and is JARVIS_NETWORTH_URL set?",
        )
    try:
        value = float(data["net_worth"])
    except (TypeError, ValueError, KeyError):
        raise HTTPException(status_code=502, detail="Sheet did not return a numeric net_worth.")

    today = date.today()

    def apply(s):
        m = s.networth
        todays = [r for r in m.readings if r.date == today]
        if todays:
            todays[-1].value = value
            todays[-1].note = "from money sheet"
        else:
            m.readings.append(Reading(id=new_id(), date=today, value=value, note="from money sheet"))

    store.mutate(apply)
    resp = store.load().model_dump(mode="json")
    resp["_synced"] = {
        "net_worth": value, "cash": data.get("cash"),
        "debt": data.get("debt"), "stocks_value": data.get("stocks_value"),
    }
    return JSONResponse(resp)


@app.get("/api/forecast/{kind}")
def get_forecast(kind: str) -> JSONResponse:
    """Linear-trend forecast, ETA-to-target, and anomaly flags for a metric,
    computed server-side in Python."""
    attr = _metric_attr(kind)
    metric = getattr(store.load(), attr)
    return JSONResponse(fc.summary(metric))


@app.patch("/api/metrics/{kind}")
def patch_metric(kind: str, body: MetricPatch) -> JSONResponse:
    attr = _metric_attr(kind)
    fields = body.model_dump(exclude_unset=True)

    def apply(s):
        m = getattr(s, attr)
        for k, v in fields.items():
            setattr(m, k, v)

    try:
        store.mutate(apply)
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    return _state_json()


# --------------------------------------------------------------------------
# Goals
# --------------------------------------------------------------------------


class GoalIn(BaseModel):
    text: str
    section: Section = Section.CURRENT
    engine: Engine = Engine.NONE
    note: str = ""


class GoalPatch(BaseModel):
    text: Optional[str] = None
    section: Optional[Section] = None
    engine: Optional[Engine] = None
    done: Optional[bool] = None
    note: Optional[str] = None
    order: Optional[int] = None


class ReorderIn(BaseModel):
    section: Section
    ordered_ids: list[str]


@app.post("/api/goals")
def add_goal(body: GoalIn) -> JSONResponse:
    def apply(s):
        # new goal lands at the end of its section
        last = max(
            [g.order for g in s.goals if g.section == body.section],
            default=-1,
        )
        s.goals.append(Goal(id=new_id(), order=last + 1, **body.model_dump()))

    try:
        store.mutate(apply)
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    return _state_json()


@app.patch("/api/goals/{goal_id}")
def update_goal(goal_id: str, body: GoalPatch) -> JSONResponse:
    fields = body.model_dump(exclude_unset=True)

    def apply(s):
        for g in s.goals:
            if g.id == goal_id:
                for k, v in fields.items():
                    setattr(g, k, v)
                return
        raise KeyError(goal_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No goal {goal_id}")
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    return _state_json()


@app.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: str) -> JSONResponse:
    def apply(s):
        before = len(s.goals)
        s.goals[:] = [g for g in s.goals if g.id != goal_id]
        if len(s.goals) == before:
            raise KeyError(goal_id)

    try:
        store.mutate(apply)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No goal {goal_id}")
    return _state_json()


@app.post("/api/goals/reorder")
def reorder_goals(body: ReorderIn) -> JSONResponse:
    """Apply a drag-drop result: every id in `ordered_ids` is moved into
    `section` and renumbered to match the given order. This is how a card
    dragged between boards both changes section and lands in the right slot."""
    target = body.section

    def apply(s):
        index = {g.id: g for g in s.goals}
        for pos, gid in enumerate(body.ordered_ids):
            g = index.get(gid)
            if g is None:
                raise KeyError(gid)
            g.section = target
            g.order = pos
            if target is not Section.CURRENT:
                g.done = False

    try:
        store.mutate(apply)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No goal {exc.args[0]}")
    return _state_json()


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


class ProfilePatch(BaseModel):
    callsign: Optional[str] = None
    protein_target_g: Optional[int] = None
    money_online_current: Optional[float] = None
    money_online_target: Optional[float] = None
    networth_liquid_target: Optional[float] = None
    networth_total_target: Optional[float] = None
    car_fund_target: Optional[float] = None
    main_lifts: Optional[list[str]] = None
    training_target_per_week: Optional[int] = None
    setup_sleep_target: Optional[float] = None
    setup_deepwork_target: Optional[float] = None
    setup_degging_max: Optional[float] = None


@app.patch("/api/profile")
def patch_profile(body: ProfilePatch) -> JSONResponse:
    fields = body.model_dump(exclude_unset=True)

    def apply(s):
        for k, v in fields.items():
            setattr(s.profile, k, v)

    try:
        store.mutate(apply)
    except (ValidationError, ValueError) as exc:
        raise _validation_error(exc)
    return _state_json()
