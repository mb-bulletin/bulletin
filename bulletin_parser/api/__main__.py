"""
Launch the read-only API.

Usage:
    python -m bulletin_parser.api --db ./harness.db --pdfs ./pdfs
    python -m bulletin_parser.api --db ./harness.db --pdfs ./pdfs --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from ..harness.storage import Storage
from .app import create_app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default="harness.db", help="SQLite DB path (same one the harness writes)")
    p.add_argument("--pdfs", default="pdfs", help="PDF storage root (unused by API but required for Storage init)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true", help="Auto-reload (dev only)")
    args = p.parse_args(argv)

    storage = Storage(args.db, args.pdfs)
    app = create_app(storage)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
