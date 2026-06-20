# JARVIS

A personal operations dashboard you open every morning. Six tabs — a
greeting + KPIs, peptides, body, money, the five-year plan, and a reserved
Claude module — over a Python/FastAPI backend that owns and persists its own
state. The pit-wall / reactor aesthetic and the "control rods withdrawn"
metaphor are deliberate: it's a reactor you run at full power.

It grew out of [`control_rods`](#origin-the-control-rods-pipeline) — the
read-only, Google-Sheets-fed three-layer planner — and keeps its DNA (schema
discipline, the floor/skill/venture/personal engine colour-coding) while
adding the thing a daily tool needs: you edit everything *in the app*, and it
saves itself.

```
pip install -e ".[dev]"
jarvis serve                 # dashboard at http://127.0.0.1:8000
```

or just double-click **`start-jarvis.command`** (macOS) — it boots the server
and opens your browser.

---

## What's in it

**Home** — a fresh, time-aware greeting every load (re-rollable), plus KPI
cards that link through to their tabs:

- **Net Worth**, **Weight**, **Body Fat %** — latest value, sparkline, and a
  direction-aware trend arrow (movement *toward* target is green whether the
  number should go up or down).
- **Peptides · Upcoming Doses** — the next doses across all active protocols,
  date-sorted, with **today highlighted uniquely** (amber + a TODAY badge).
- **Current TO-DO** — the live checklist from the No Control Rods board,
  tickable right here, linked to the board.
- **Money Made Online** — the hard-set `$0 / $100` milestone.

**Peptides** — add protocols from a fixed six-compound catalogue
(`TB/BPC · Reta · CJC/IPA · GHK-Cu · Semax · Selank`) and nothing else; an
off-list compound is rejected loudly. Per protocol: dose, start date, "every
N days", and protocol length (blank = ongoing). The schedule — next dose,
is-it-today, doses done/total, % through — is computed server-side in Python.

**Health & Gym** — logged weight & BF% history with trend charts, plus a
**forecast layer**: a least-squares trend projection (dashed line + ~95%
band), an **ETA-to-target** ("≈8 days to 160 lb"), a weekly trend rate, and
MAD-based **anomaly flags** for off-trend readings. Daily protein target and
an append-only reading log.

> A **morning check-in** fires on the first open of each day — weight,
> protein, training, energy, sleep, **deep-work hours, degging (wasted)
> hours**, and today's focus. Answers save locally and, if a Google Sheet
> webhook is configured, append a row to your sheet; a morning-weight answer
> also logs straight into the weight series. Deep-work and degging are the
> "lap-time" outputs the Garage studies.

**Workouts** — import your **Strong or Hevy** CSV export (format
auto-detected; re-importing only adds new sessions). Jarvis derives
training-load (tonnage) over time, **estimated-1RM strength curves** per
most-trained lift, and weekly frequency.

**Garage** — the self-study / setup sheet. Aligns daily inputs (sleep,
training volume, protein, training) against outputs (deep-work, degging,
energy) and reports **which lever moves which output** (Pearson r), plus a
**peak-day profile**: what your best output days have in common — the
repeatable setup to chase. Unlocks after ~6 days of check-ins.

**Money & Resources** — logged net-worth history + chart, editable targets
(liquid / total / big-purchase fund), a first-revenue milestone, and
the three-engine strategy (Floor / Skill / Venture + the rough math) carried
over from the roadmap.

**No Control Rods** — the five-year plan as a four-section board:

| Section | Behaviour |
|---|---|
| L1 Destinations | pin board (pointers) |
| L2 This Quarter | pin board (pointers) |
| L3 Annual Recalibration | pin board (pointers) |
| **Current Enhancements** | **checklist — tick boxes with a click sound** |

Add or remove goals in any section, **drag cards between sections**, and tag
each with an engine (click the tag to cycle). Only Current Enhancements is a
checklist; drag a goal into it to make it tickable, drag it back to a board
and it becomes a pointer again. The home TO-DO mirrors this section.

**Claude** — reserved placeholder for the assistant layer (wired to the same
state). "Further instructions pending."

---

## Architecture

```
jarvis/
  schema.py        Pydantic models — the contract for the whole state document
  store.py         JSON store: load → seed-on-first-run; atomic, re-validated writes
  seed.py          first-run data, populated from your real context
  peptides.py      schedule maths (derived, never stored — can't drift)
  forecast.py      time-series: linear trend, ETA-to-target, MAD anomaly flags
  workouts.py      Strong/Hevy CSV import + tonnage / e1RM strength analytics
  study.py         self-study: input↔output correlations + peak-day profile
  checkin.py       daily check-in questions + Google Sheets webhook sync
  greetings.py     the greeting pool + picker
  dashboard.py     pure functions → the home KPI bundle (trend logic lives here)
  api/app.py       FastAPI: read endpoints + validated, persisted mutations
  frontend/        index.html + static/{styles.css, app.js}  (no build step)
  cli.py           jarvis serve | where | reset
```

Design decisions worth knowing:

- **The app owns its state.** A single JSON document is the source of truth
  (the data is small and document-shaped — nested goals, peptides, logged
  readings — so a database would be theatre). Every write goes
  `load → mutate → re-validate → atomic save`, so a bad edit raises *before*
  it can touch the file, and a crash mid-write can't corrupt it.
- **Logic in Python, JS as a thin renderer.** Peptide schedules, trend
  direction, and KPI assembly are computed and tested server-side; the
  frontend mostly draws. Charts are hand-rolled SVG — no CDN, works offline.
- **Closed vocabularies fail loudly.** The peptide catalogue and the engine
  set are enums; a typo is a clean `400` with the valid options, not a silent
  broken card.
- **Mutations return the whole new state**, so the UI re-renders from one
  authoritative response and never drifts.

Your live data lives in `data/jarvis_state.json` (git-ignored; seeded on
first run). `jarvis where` prints the path; `jarvis reset` re-seeds it.
Point it elsewhere with the `JARVIS_DATA` env var.

---

## Google Sheets sync (optional)

No service-account JSON needed — the check-in posts to an Apps Script webhook:

1. In your Google Sheet: **Extensions → Apps Script**, paste:

   ```javascript
   function doPost(e) {
     var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
     var data = JSON.parse(e.postData.contents);
     var cols = ["date", "weight", "protein", "trained", "energy", "sleep", "deep_work", "degging", "focus"];
     if (sheet.getLastRow() === 0) sheet.appendRow(cols);
     sheet.appendRow(cols.map(function (c) { return data[c] || ""; }));
     return ContentService.createTextOutput(JSON.stringify({ ok: true }))
       .setMimeType(ContentService.MimeType.JSON);
   }
   ```

2. **Deploy → New deployment → Web app**, execute as you, access "Anyone",
   and copy the `/exec` URL.
3. Run Jarvis with it: `JARVIS_CHECKIN_WEBHOOK="<url>" jarvis serve`

Each morning check-in then appends a row. It's best-effort — if the webhook
is unset or down, the check-in still saves locally and the app never blocks.

---

## Tests

```
pytest -q          # 65 passing: 43 Jarvis (schema, scheduling, forecasting,
                   # Hevy parsing, e1RM, correlations, check-in, dashboard,
                   # store round-trip, full API surface) + 22 control_rods
```

What they actually pin down: a weekly dose landing exactly on "today", a
finite protocol reporting 100% and finished, direction-aware trend colour,
least-squares slope recovery and ETA-to-target, a robust anomaly detector
isolating a single spike, Hevy sessions grouped with warmups excluded from
tonnage, e1RM edge cases, correlation strength + peak-day separation, the
store re-validating a bad mutation, and every mutation endpoint round-tripping
through the real app.

---

## Origin: the control rods pipeline

`control_rods/` is the original deliverable — a read-only three-layer planner
that pulls from a Google Sheet (or local CSV / JSON snapshot) behind a clean
`PlanSource` seam, validates with Pydantic, and serves a pit-wall dashboard.
It still runs (`control-rods serve`) and still tells the "I can architect a
data pipeline, not just script" story. Jarvis is what it becomes when the
Sheet moves *into* the app and the plan becomes one tab of a daily cockpit.
