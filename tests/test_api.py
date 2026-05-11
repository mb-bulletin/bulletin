"""
End-to-end HTTP tests for the API.

Uses FastAPI's TestClient (no real network). Builds a temporary SQLite
DB, seeds it with the hand-built St Patrick's bulletin, and hits every
endpoint.

Verifies:
  - status codes and basic response shape
  - ETag set on bulletin responses
  - 304 Not Modified on If-None-Match
  - Cache-Control headers present
  - 404s on missing parishes / missing dates
  - OpenAPI spec is generated and lists every endpoint
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from bulletin_parser.api import create_app
from bulletin_parser.harness.storage import Storage
from test_schema import build_stpatricks_reference


def _seed_db(tmp: Path) -> Storage:
    """Build a Storage with one parish and one parsed bulletin."""
    storage = Storage(tmp / "harness.db", tmp / "pdfs")
    storage.add_parish(
        id="ny-old-st-patricks",
        name="Basilica of St. Patrick's Old Cathedral",
        host_kind="ecatholic",
        ecatholic_id="11778",
        diocese="Archdiocese of New York",
        city="New York",
        state="NY",
        timezone="America/New_York",
        active=1,
    )
    storage.add_parish(
        id="inactive-parish",
        name="Inactive",
        host_kind="ecatholic",
        ecatholic_id="00000",
        active=0,
    )

    # Insert a fake bulletin row + a parsed_bulletins row
    bulletin = build_stpatricks_reference()
    fake_pdf = b"%PDF-1.4 fake\n" + b"x" * 100
    import hashlib
    sha = hashlib.sha256(fake_pdf).hexdigest()
    bulletin_id, _ = storage.save_bulletin(
        "ny-old-st-patricks", sha, fake_pdf,
        "https://files.ecatholic.com/11778/bulletins/20260510.pdf",
    )
    storage.save_parse(
        bulletin_id,
        parser_version=bulletin.parser_version,
        model="claude-opus-4-5",
        payload=bulletin.model_dump(mode="json"),
    )
    return storage


def _client(tmp: Path) -> TestClient:
    storage = _seed_db(tmp)
    app = create_app(storage)
    return TestClient(app)


# ---------- Tests ----------

def test_health_endpoint(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_openapi_spec_lists_all_endpoints(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    expected = {
        "/v1/parishes",
        "/v1/parishes/{parish_id}",
        "/v1/parishes/{parish_id}/today",
        "/v1/parishes/{parish_id}/bulletins/current",
        "/v1/parishes/{parish_id}/bulletins/{week_starting}",
        "/v1/parishes/{parish_id}/schedule",
        "/health",
    }
    missing = expected - set(paths.keys())
    assert not missing, f"OpenAPI missing endpoints: {missing}"


def test_list_parishes_returns_active_only_by_default(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["parishes"][0]["id"] == "ny-old-st-patricks"


def test_list_parishes_include_inactive(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?active_only=false")
    assert r.status_code == 200
    assert r.json()["count"] == 2


def test_get_parish(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Basilica of St. Patrick's Old Cathedral"
    assert body["timezone"] == "America/New_York"


def test_get_parish_404(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/does-not-exist")
    assert r.status_code == 404


def test_get_current_bulletin(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/bulletins/current")
    assert r.status_code == 200
    body = r.json()
    assert body["liturgical_day"]["name"] == "Sixth Sunday of Easter"
    # ETag and caching headers present
    assert r.headers.get("etag") is not None
    cc = r.headers.get("cache-control", "")
    assert "max-age=3600" in cc
    assert "stale-while-revalidate" in cc


def test_conditional_request_returns_304(tmp_path: Path):
    c = _client(tmp_path)
    r1 = c.get("/v1/parishes/ny-old-st-patricks/bulletins/current")
    etag = r1.headers["etag"]
    r2 = c.get(
        "/v1/parishes/ny-old-st-patricks/bulletins/current",
        headers={"If-None-Match": etag},
    )
    assert r2.status_code == 304


def test_get_bulletin_by_date(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/bulletins/2026-05-10")
    assert r.status_code == 200
    assert r.json()["week_starting"] == "2026-05-10"


def test_get_bulletin_by_unknown_date_404(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/bulletins/2026-01-04")
    assert r.status_code == 404


def test_today_endpoint(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/today")
    assert r.status_code == 200
    body = r.json()
    assert body["parish_id"] == "ny-old-st-patricks"
    # The shape we care about for the mobile UI
    assert "next_service" in body
    assert "today_services_remaining" in body
    assert "high_priority_announcements" in body
    assert "this_week_exceptions" in body
    # Today endpoint has a shorter cache TTL
    cc = r.headers.get("cache-control", "")
    assert "max-age=300" in cc


def test_schedule_endpoint(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/schedule?days=7")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 7
    assert isinstance(body["services"], list)
    # Verify every service has the contract fields
    for s in body["services"][:3]:
        for k in ("date", "start_time", "kind", "location_id"):
            assert k in s, f"missing field {k} in {s}"


def test_schedule_endpoint_validates_days(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes/ny-old-st-patricks/schedule?days=99")
    assert r.status_code == 400


def test_endpoints_404_when_parish_has_no_bulletin(tmp_path: Path):
    """An active parish in the roster but with no parsed bulletins yet."""
    storage = _seed_db(tmp_path)
    storage.add_parish(
        id="no-bulletin-yet", name="No Bulletin Yet",
        host_kind="ecatholic", ecatholic_id="55555", active=1,
        timezone="America/Chicago",
    )
    c = TestClient(create_app(storage))
    assert c.get("/v1/parishes/no-bulletin-yet").status_code == 200  # parish exists
    assert c.get("/v1/parishes/no-bulletin-yet/bulletins/current").status_code == 404
    assert c.get("/v1/parishes/no-bulletin-yet/today").status_code == 404
    assert c.get("/v1/parishes/no-bulletin-yet/schedule").status_code == 404


def test_head_returns_same_headers_as_get(tmp_path: Path):
    """HEAD requests should be supported (CDNs use them for cache validation)."""
    c = _client(tmp_path)
    get_resp = c.get("/v1/parishes/ny-old-st-patricks/bulletins/current")
    head_resp = c.head("/v1/parishes/ny-old-st-patricks/bulletins/current")
    assert head_resp.status_code == 200
    assert head_resp.headers.get("etag") == get_resp.headers.get("etag")
    assert head_resp.headers.get("cache-control") == get_resp.headers.get("cache-control")


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll API tests passed.")
