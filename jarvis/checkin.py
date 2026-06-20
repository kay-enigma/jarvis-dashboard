"""
Daily check-in.

The home page asks these questions on the first open of each day. Answers
are saved locally (state.checkins) and, if a Google Sheet webhook is wired
up, appended as a row to your sheet.

Editing the questions: just change CHECKIN_QUESTIONS. Each has:
    id        stable key the answer is stored under
    prompt    the question text
    type      number | bool | scale | text   (drives the input the UI shows)
    maps_to   optional metric to also log the answer into (e.g. "weight")

Google Sheets sync (no service-account JSON needed):
    1. In your sheet:  Extensions → Apps Script
    2. Paste the doPost() snippet from the README, Deploy → Web app,
       "Anyone" can access, copy the /exec URL.
    3. Run Jarvis with that URL:  JARVIS_CHECKIN_WEBHOOK=<url> jarvis serve
    Each check-in is then POSTed as JSON and the script appends a row.
This is best-effort: if the webhook is unset or down, the check-in still
saves locally and the app never blocks on it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date

from .schema import JarvisState

CHECKIN_QUESTIONS: list[dict] = [
    {"id": "weight", "prompt": "Morning weight (lb)?", "type": "number", "maps_to": "weight"},
    {"id": "protein", "prompt": "Hit your 160g protein yesterday?", "type": "bool"},
    {"id": "trained", "prompt": "Did you train yesterday?", "type": "bool"},
    {"id": "energy", "prompt": "Energy & focus right now?", "type": "scale"},
    {"id": "sleep", "prompt": "Sleep quality last night?", "type": "scale"},
    # The "lap time" outputs — what the inputs above are studied against.
    {"id": "deep_work", "prompt": "Deep-work hours yesterday?", "type": "number"},
    {"id": "degging", "prompt": "Hours lost to degging yesterday?", "type": "number"},
    {"id": "focus", "prompt": "The one thing that matters today?", "type": "text"},
]


def needs_checkin(state: JarvisState, today: date) -> bool:
    """True on the first open of a day (no check-in logged for `today` yet)."""
    return state.profile.last_checkin_date != today


def webhook_url() -> str | None:
    return os.environ.get("JARVIS_CHECKIN_WEBHOOK") or None


def push_to_sheet(row: dict) -> bool:
    """Append a row to the Google Sheet via the Apps Script webhook.
    Returns True on success, False if unconfigured or the POST failed —
    never raises, so a sheet outage can't break the check-in."""
    url = webhook_url()
    if not url:
        return False
    try:
        data = json.dumps(row).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
