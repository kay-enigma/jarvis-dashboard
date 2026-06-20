"""
Pull net worth from the Google Sheet money tracker.

The companion to the check-in *push*: this is a *pull*. The money sheet's
Apps Script exposes a doGet web app returning
{net_worth, cash, debt, stocks_value}; Jarvis fetches it on demand and logs
the number to the net-worth series. Configure with JARVIS_NETWORTH_URL.

Best-effort and read-only — a sheet outage just means "couldn't sync", never
a crash.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional


def sheet_url() -> Optional[str]:
    return os.environ.get("JARVIS_NETWORTH_URL") or None


def fetch() -> Optional[dict]:
    """GET the money sheet's JSON, or None if unset/unreachable/malformed."""
    url = sheet_url()
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            if not (200 <= resp.status < 300):
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, dict) or "net_worth" not in data:
        return None
    return data
