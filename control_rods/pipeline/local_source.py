"""
Local file source.

Reads the plan from a directory of CSV files that mirror the Google Sheet
tabs exactly (destinations.csv, quarter.csv, quarter_meta.csv, annual_log.csv).

This is the source used by tests, CI, demos, and anytime you're offline.
Because it produces the *same* validated Plan as the Google source, every
other layer behaves identically against it - you can develop the entire
frontend and API with zero Google credentials, then flip one env var to
go live.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from control_rods.pipeline.source import PlanSource
from control_rods.pipeline.transform import (
    annual_entry_from_row,
    build_quarter,
    destination_from_row,
)
from control_rods.schema import Plan


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class LocalFileSource(PlanSource):
    """Load the plan from a directory of CSVs."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)

    @property
    def description(self) -> str:
        return f"LocalFileSource({self.data_dir})"

    def load(self) -> Plan:
        dest_rows = _read_csv(self.data_dir / "destinations.csv")
        quarter_task_rows = _read_csv(self.data_dir / "quarter.csv")
        quarter_meta_rows = _read_csv(self.data_dir / "quarter_meta.csv")
        annual_rows = _read_csv(self.data_dir / "annual_log.csv")

        destinations = [destination_from_row(r) for r in dest_rows if r.get("id", "").strip()]

        current_quarter = None
        if quarter_meta_rows:
            current_quarter = build_quarter(quarter_meta_rows[0], quarter_task_rows)

        annual_log = [annual_entry_from_row(r) for r in annual_rows if r.get("year", "").strip()]

        # Plan's own validators run here: duplicate-id check + the
        # referential-integrity check that tasks point at real destinations.
        return Plan(
            owner="Kay",
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            destinations=destinations,
            current_quarter=current_quarter,
            annual_log=annual_log,
        )


class JSONSnapshotSource(PlanSource):
    """Load a previously-exported Plan JSON (the pipeline's own output).

    Useful as a frozen artifact: export once from Google, commit the JSON,
    and the dashboard runs against a stable snapshot with no live calls.
    """

    def __init__(self, json_path: str | Path):
        self.json_path = Path(json_path)

    @property
    def description(self) -> str:
        return f"JSONSnapshotSource({self.json_path})"

    def load(self) -> Plan:
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        return Plan.model_validate(data)
