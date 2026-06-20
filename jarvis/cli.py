"""
Jarvis CLI.

    jarvis serve            run the dashboard + API (what the launcher calls)
    jarvis where            print where state is stored
    jarvis reset            re-seed the store (asks first)
"""

from __future__ import annotations

import argparse
import sys

from .store import JarvisStore


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "jarvis.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def _cmd_where(args: argparse.Namespace) -> int:
    store = JarvisStore()
    print(store.path)
    print("exists" if store.path.exists() else "not yet created (seeds on first run)")
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    store = JarvisStore()
    if store.path.exists() and not args.force:
        reply = input(f"Overwrite {store.path} with a fresh seed? [y/N] ")
        if reply.strip().lower() not in {"y", "yes"}:
            print("Aborted.")
            return 1
    if store.path.exists():
        store.path.unlink()
    store.load()  # triggers re-seed
    print(f"Re-seeded -> {store.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="run the dashboard + API")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    p_where = sub.add_parser("where", help="print the state file path")
    p_where.set_defaults(func=_cmd_where)

    p_reset = sub.add_parser("reset", help="re-seed the store")
    p_reset.add_argument("--force", action="store_true", help="don't ask")
    p_reset.set_defaults(func=_cmd_reset)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
