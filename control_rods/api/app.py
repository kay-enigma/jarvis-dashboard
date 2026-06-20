"""
FastAPI service.

Endpoints:

    GET /                     the dashboard (HTML)
    GET /api/plan             the full validated Plan as JSON
    GET /api/destinations     just Layer 1
    GET /api/quarter          just the current quarter (Layer 2)
    GET /api/health           liveness + which source is wired up
    POST /api/refresh         drop the cache and re-pull the source

Design notes:
    - The source (Google vs local) is resolved once via get_source() and
      the loaded Plan is cached in memory. A planning dashboard doesn't
      need a live Google call on every page load - that would be slow and
      burn quota. /api/refresh is the explicit "I just edited the sheet"
      button.
    - Every response is built from the *validated* Plan, so a malformed
      sheet fails at load time with a clear error, never as broken JSON.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from control_rods.pipeline import get_source
from control_rods.schema import Plan

app = FastAPI(
    title="Control Rods",
    description="A three-layer goal system: Destinations / Quarter / Annual.",
    version="1.0.0",
)

_FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/static", StaticFiles(directory=_FRONTEND / "static"), name="static")


# --- cached plan -----------------------------------------------------------

_cache: dict[str, Plan] = {}


def _load_plan(force: bool = False) -> Plan:
    if force or "plan" not in _cache:
        source = get_source()
        _cache["plan"] = source.load()
        _cache["source_description"] = source.description  # type: ignore[assignment]
    return _cache["plan"]


# --- routes ----------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Serve the single-page dashboard."""
    index = _FRONTEND / "templates" / "index.html"
    return index.read_text(encoding="utf-8")


@app.get("/api/plan")
def get_plan() -> JSONResponse:
    try:
        plan = _load_plan()
    except Exception as exc:  # surface validation/source errors cleanly
        raise HTTPException(status_code=502, detail=f"Could not load plan: {exc}")
    # mode='json' so dates/enums serialise to strings the frontend can read.
    return JSONResponse(plan.model_dump(mode="json"))


@app.get("/api/destinations")
def get_destinations() -> JSONResponse:
    plan = _load_plan()
    return JSONResponse([d.model_dump(mode="json") for d in plan.destinations])


@app.get("/api/quarter")
def get_quarter() -> JSONResponse:
    plan = _load_plan()
    if not plan.current_quarter:
        raise HTTPException(status_code=404, detail="No current quarter set.")
    return JSONResponse(plan.current_quarter.model_dump(mode="json"))


@app.get("/api/health")
def health() -> dict:
    try:
        plan = _load_plan()
        return {
            "status": "ok",
            "source": _cache.get("source_description", "unknown"),
            "destinations": len(plan.destinations),
            "quarter": plan.current_quarter.label if plan.current_quarter else None,
        }
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)}


@app.post("/api/refresh")
def refresh() -> dict:
    """Re-pull the source (call this after editing the Google Sheet)."""
    try:
        plan = _load_plan(force=True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {exc}")
    return {
        "status": "refreshed",
        "destinations": len(plan.destinations),
        "quarter": plan.current_quarter.label if plan.current_quarter else None,
        "generated_at": plan.generated_at,
    }
