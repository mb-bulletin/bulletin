"""Smoke test for the production ASGI entrypoint.

This is the module Docker calls. If it can't import, the container
won't start. It's worth a real test even though it's six lines.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient


def test_asgi_app_constructs_from_env_vars():
    """The asgi module reads DB/PDF paths from env vars and exposes `app`."""
    with tempfile.TemporaryDirectory() as td:
        os.environ["BULLETIN_DB_PATH"] = f"{td}/test.db"
        os.environ["BULLETIN_PDF_ROOT"] = f"{td}/pdfs"

        # Defer import to here so the env vars are picked up.
        # Force reload in case another test imported it first.
        for k in list(sys.modules):
            if k.startswith("bulletin_parser.api.asgi"):
                del sys.modules[k]
        from bulletin_parser.api import asgi  # type: ignore

        client = TestClient(asgi.app)
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

        # /v1/parishes works on an empty DB
        r = client.get("/v1/parishes")
        assert r.status_code == 200
        assert r.json() == {"parishes": [], "count": 0}


def test_asgi_defaults_are_under_data():
    """The default DB path lives under /data — the conventional location
    for the persistent volume in production. This is a regression test
    against accidentally pointing the defaults at, e.g., the cwd."""
    # We read the source rather than importing because the asgi module
    # constructs Storage at import time, which would write to /data.
    import inspect
    from bulletin_parser.api import asgi
    src = inspect.getsource(asgi)
    assert '"/data/harness.db"' in src
    assert '"/data/pdfs"' in src


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            fn()
            print(f"  + {name}")
        except Exception as e:
            failed += 1
            print(f"  - {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll asgi tests passed.")
