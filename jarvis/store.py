"""
The store.

A single JSON document on disk is the source of truth (you chose in-app
editing with local save). It's deliberately simple — the data is small and
document-shaped (nested goals, peptides, logged readings), so a JSON file is
the honest fit, not a database. It's also human-readable, trivially
backed-up, and could later be synced to a Sheet without changing this layer.

Two things make it safe:
  - every write goes through Pydantic, so a bad mutation raises before it
    can touch the file;
  - writes are atomic (temp file + os.replace), so a crash mid-save can
    never leave a half-written, unloadable state.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable

from .schema import JarvisState, now_iso
from .seed import build_seed


def default_data_path() -> Path:
    """Where the state lives. Override with the JARVIS_DATA env var."""
    env = os.environ.get("JARVIS_DATA")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[1] / "data" / "jarvis_state.json"


class JarvisStore:
    def __init__(self, path: Path | None = None):
        self.path = path or default_data_path()
        # Serialise writes — the launcher is single-user, but a double-click
        # or a quick succession of edits shouldn't be able to interleave.
        self._lock = threading.Lock()

    # -- read ---------------------------------------------------------------

    def load(self) -> JarvisState:
        """Load the saved state, seeding it on first ever run."""
        if not self.path.exists():
            state = build_seed()
            self.save(state)
            return state
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return JarvisState.model_validate(raw)

    # -- write --------------------------------------------------------------

    def save(self, state: JarvisState) -> JarvisState:
        state.updated_at = now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.model_dump(mode="json"), indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)  # atomic on POSIX
        return state

    def mutate(self, fn: Callable[[JarvisState], None]) -> JarvisState:
        """Load → apply `fn` → re-validate → save, under the write lock.

        `fn` mutates the state in place. Re-validating via model_dump +
        model_validate guarantees the mutation didn't produce something the
        schema would reject (e.g. an off-catalogue peptide) before it's
        persisted.
        """
        with self._lock:
            state = self.load()
            fn(state)
            state = JarvisState.model_validate(state.model_dump(mode="json"))
            return self.save(state)
