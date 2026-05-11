"""Production ASGI entrypoint for the API.

The `create_app` factory in `app.py` takes a Storage argument so tests
can pass a temporary DB. In production we want a single global app
bound to whatever the operator configured via env vars.

Env vars:
  BULLETIN_DB_PATH   - SQLite file path (default: /data/harness.db)
  BULLETIN_PDF_ROOT  - directory for stored PDFs (default: /data/pdfs)

Usage:
  uvicorn bulletin_parser.api.asgi:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os

from ..harness.storage import Storage
from .app import create_app


_DB_PATH = os.environ.get("BULLETIN_DB_PATH", "/data/harness.db")
_PDF_ROOT = os.environ.get("BULLETIN_PDF_ROOT", "/data/pdfs")

_storage = Storage(_DB_PATH, _PDF_ROOT)
app = create_app(_storage)
