"""
Google Sheets source - the production path.

Reads the plan live from a Google Sheet whose tabs mirror the CSV layout:

    Destinations   columns: id, title, detail, engine, target_date,
                            confidence, target_value, current_value, unit
    QuarterMeta    columns: label, theme, start_date, end_date   (one row)
    Quarter        columns: id, title, engine, status,
                            serves_destination, note
    AnnualLog      columns: year, kept, changed, learned

Auth uses a Google service account (recommended for a headless service):
share the Sheet with the service account's email as Viewer, drop the
service-account JSON key path in GOOGLE_APPLICATION_CREDENTIALS, and set
CONTROL_RODS_SHEET_ID to the spreadsheet id.

The heavy google deps are imported lazily inside load(), so the rest of
the project (and the test suite, and the local demo) never needs them
installed. You only pay for Google when you actually use Google.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from control_rods.pipeline.source import PlanSource
from control_rods.pipeline.transform import (
    annual_entry_from_row,
    build_quarter,
    destination_from_row,
)
from control_rods.schema import Plan

# Default tab + range names. Override via constructor if your sheet differs.
_RANGES = {
    "destinations": "Destinations!A1:Z1000",
    "quarter_meta": "QuarterMeta!A1:Z10",
    "quarter": "Quarter!A1:Z1000",
    "annual_log": "AnnualLog!A1:Z1000",
}

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _rows_to_dicts(values: list[list[str]]) -> list[dict]:
    """Google returns a list-of-lists with the header as row 0 and ragged
    rows (trailing empty cells are omitted). Normalise to list-of-dicts,
    padding short rows so every key is present."""
    if not values:
        return []
    header = [h.strip() for h in values[0]]
    out: list[dict] = []
    for raw in values[1:]:
        padded = list(raw) + [""] * (len(header) - len(raw))
        out.append(dict(zip(header, padded)))
    return out


class GoogleSheetSource(PlanSource):
    """Load the plan live from a Google Sheet."""

    def __init__(
        self,
        sheet_id: Optional[str] = None,
        credentials_path: Optional[str] = None,
        ranges: Optional[dict] = None,
    ):
        self.sheet_id = sheet_id or os.environ.get("CONTROL_RODS_SHEET_ID")
        self.credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self.ranges = ranges or _RANGES
        if not self.sheet_id:
            raise ValueError(
                "No sheet id. Set CONTROL_RODS_SHEET_ID or pass sheet_id=."
            )

    @property
    def description(self) -> str:
        return f"GoogleSheetSource(sheet={self.sheet_id[:8]}...)"

    def _service(self):
        # Lazy import: google libs are an optional extra.
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ImportError(
                "Google deps missing. Install with: pip install '.[google]'"
            ) from exc

        if not self.credentials_path:
            raise ValueError(
                "No credentials. Set GOOGLE_APPLICATION_CREDENTIALS to the "
                "service-account JSON key path."
            )
        creds = Credentials.from_service_account_file(
            self.credentials_path, scopes=_SCOPES
        )
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _fetch(self, service, range_name: str) -> list[dict]:
        resp = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=range_name)
            .execute()
        )
        return _rows_to_dicts(resp.get("values", []))

    def load(self) -> Plan:
        service = self._service()

        dest_rows = self._fetch(service, self.ranges["destinations"])
        quarter_meta_rows = self._fetch(service, self.ranges["quarter_meta"])
        quarter_task_rows = self._fetch(service, self.ranges["quarter"])
        annual_rows = self._fetch(service, self.ranges["annual_log"])

        destinations = [
            destination_from_row(r) for r in dest_rows if r.get("id", "").strip()
        ]
        current_quarter = None
        if quarter_meta_rows:
            current_quarter = build_quarter(quarter_meta_rows[0], quarter_task_rows)
        annual_log = [
            annual_entry_from_row(r) for r in annual_rows if r.get("year", "").strip()
        ]

        return Plan(
            owner="Operator",
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            destinations=destinations,
            current_quarter=current_quarter,
            annual_log=annual_log,
        )
