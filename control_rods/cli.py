"""
Command-line interface.

    control-rods serve              run the dashboard + API
    control-rods validate           load the configured source and report
    control-rods export plan.json   freeze the current source to a JSON snapshot

`validate` is the one to run right after editing the Google Sheet: it
loads through the full schema and prints exactly what's wrong if a row
is malformed, without needing the server up.
"""

from __future__ import annotations

import argparse
import json
import sys

from control_rods.pipeline import get_source


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "control_rods.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    source = get_source()
    print(f"Source: {source.description}")
    try:
        plan = source.load()
    except Exception as exc:
        print(f"\n  INVALID: {exc}\n", file=sys.stderr)
        return 1
    print(f"  OK - {len(plan.destinations)} destinations")
    if plan.current_quarter:
        q = plan.current_quarter
        print(f"  OK - quarter {q.label}: {len(q.tasks)} tasks, {q.completion_pct}% done")
    print(f"  OK - {len(plan.annual_log)} annual entries")
    print("\nPlan is valid.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    source = get_source()
    plan = source.load()
    payload = plan.model_dump(mode="json")
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"Wrote snapshot -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control-rods")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the dashboard + API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_val = sub.add_parser("validate", help="load and validate the source")
    p_val.set_defaults(func=_cmd_validate)

    p_exp = sub.add_parser("export", help="freeze the source to a JSON snapshot")
    p_exp.add_argument("out", help="output path, e.g. plan.json")
    p_exp.set_defaults(func=_cmd_export)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
