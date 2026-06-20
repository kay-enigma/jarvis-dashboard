"""
Pipeline package.

Exposes the sources plus a `get_source()` factory that reads one env var
and hands back the right source. This is the only place the production /
local switch lives, so the API just calls get_source() and never branches
on environment itself.

    CONTROL_RODS_SOURCE = local   -> LocalFileSource(CONTROL_RODS_DATA_DIR)
    CONTROL_RODS_SOURCE = json    -> JSONSnapshotSource(CONTROL_RODS_JSON)
    CONTROL_RODS_SOURCE = google  -> GoogleSheetSource(env-configured)

Default is 'local' so a fresh clone runs against the bundled sample data
with zero setup.
"""

from __future__ import annotations

import os
from pathlib import Path

from control_rods.pipeline.google_source import GoogleSheetSource
from control_rods.pipeline.local_source import JSONSnapshotSource, LocalFileSource
from control_rods.pipeline.source import PlanSource

__all__ = [
    "GoogleSheetSource",
    "JSONSnapshotSource",
    "LocalFileSource",
    "PlanSource",
    "get_source",
]

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def get_source() -> PlanSource:
    """Build the configured source. See module docstring for env vars."""
    kind = os.environ.get("CONTROL_RODS_SOURCE", "local").strip().lower()

    if kind == "google":
        return GoogleSheetSource()
    if kind == "json":
        path = os.environ.get("CONTROL_RODS_JSON")
        if not path:
            raise ValueError("CONTROL_RODS_SOURCE=json needs CONTROL_RODS_JSON set.")
        return JSONSnapshotSource(path)
    if kind == "local":
        data_dir = os.environ.get("CONTROL_RODS_DATA_DIR", str(_DEFAULT_DATA_DIR))
        return LocalFileSource(data_dir)

    raise ValueError(
        f"Unknown CONTROL_RODS_SOURCE={kind!r}. Use 'local', 'json', or 'google'."
    )
