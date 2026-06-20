"""
Print the exact Google Sheet layout to recreate, tab by tab.

Run this, then build a Sheet with these four tabs and these headers,
share it with your service-account email as Viewer, and point
CONTROL_RODS_SHEET_ID at it. The column order does not matter (the
pipeline reads by header name), but the header *names* must match.

    python scripts/print_sheet_layout.py
"""

from pathlib import Path
import csv

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"

TABS = {
    "Destinations": "destinations.csv",
    "QuarterMeta": "quarter_meta.csv",
    "Quarter": "quarter.csv",
    "AnnualLog": "annual_log.csv",
}


def main() -> None:
    print("=" * 70)
    print("GOOGLE SHEET LAYOUT  -  create one Sheet with these four tabs")
    print("=" * 70)
    for tab, fname in TABS.items():
        path = SAMPLE / fname
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader)
            example = next(reader, None)
        print(f"\n--- TAB: {tab} ---")
        print("Headers (row 1):")
        for h in header:
            print(f"    - {h}")
        if example:
            print("Example row 2:")
            for h, v in zip(header, example):
                print(f"    {h:>20} : {v}")
    print("\n" + "=" * 70)
    print("Then: share with the service-account email (Viewer), set")
    print("  export CONTROL_RODS_SOURCE=google")
    print("  export CONTROL_RODS_SHEET_ID=<your sheet id>")
    print("  export GOOGLE_APPLICATION_CREDENTIALS=<path to key.json>")
    print("and run:  control-rods validate")
    print("=" * 70)


if __name__ == "__main__":
    main()
