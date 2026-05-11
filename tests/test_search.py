"""Tests for the /v1/parishes search endpoints.

Uses FastAPI's TestClient against a temporary SQLite DB seeded with a
small geographic spread of parishes. No network, no API key.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from bulletin_parser.api import create_app
from bulletin_parser.harness.storage import Storage


def _seed(tmp: Path) -> Storage:
    """Seed three parishes spread geographically across the US."""
    storage = Storage(tmp / "harness.db", tmp / "pdfs")

    # NYC
    storage.add_parish(
        id="ny-old-st-patricks",
        name="Basilica of St. Patrick's Old Cathedral",
        host_kind="ecatholic", ecatholic_id="11778",
        diocese="Archdiocese of New York",
        city="New York", state="NY",
        timezone="America/New_York",
        address="263 Mulberry Street",
        postal_code="10012",
        latitude=40.7224, longitude=-73.9956,
        active=1,
    )
    # Brooklyn (close to NYC for the near-search test)
    storage.add_parish(
        id="ny-st-james-brooklyn",
        name="Co-Cathedral of St. Joseph",
        host_kind="ecatholic", ecatholic_id="22222",
        diocese="Diocese of Brooklyn",
        city="Brooklyn", state="NY",
        timezone="America/New_York",
        address="856 Pacific Street",
        postal_code="11238",
        latitude=40.6814, longitude=-73.9740,
        active=1,
    )
    # Chicago (far from NYC)
    storage.add_parish(
        id="il-holy-name",
        name="Holy Name Cathedral",
        host_kind="ecatholic", ecatholic_id="33333",
        diocese="Archdiocese of Chicago",
        city="Chicago", state="IL",
        timezone="America/Chicago",
        address="735 N State St",
        postal_code="60654",
        latitude=41.8961, longitude=-87.6286,
        active=1,
    )
    # Inactive
    storage.add_parish(
        id="x-inactive", name="Inactive Church",
        host_kind="ecatholic", ecatholic_id="0", active=0,
    )
    return storage


def _client(tmp: Path) -> TestClient:
    return TestClient(create_app(_seed(tmp)))


# ---- text search ----------------------------------------------------------

def test_text_search_by_parish_name(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=Patrick")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["parishes"][0]["id"] == "ny-old-st-patricks"


def test_text_search_by_city(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=Brooklyn")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_text_search_by_state(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=NY")
    assert r.status_code == 200
    body = r.json()
    # Two active NY parishes
    assert body["count"] == 2


def test_text_search_excludes_inactive(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=Inactive")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_text_search_no_match_returns_empty(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=NotARealParishName")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_text_search_includes_location_fields(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?q=Patrick")
    p = r.json()["parishes"][0]
    assert p["latitude"] is not None
    assert p["longitude"] is not None
    assert p["postal_code"] == "10012"


# ---- postal_code search ---------------------------------------------------

def test_postal_code_exact_match(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?postal_code=10012")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["parishes"][0]["id"] == "ny-old-st-patricks"


def test_postal_code_no_match(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?postal_code=99999")
    assert r.json()["count"] == 0


# ---- near search ----------------------------------------------------------

def test_near_returns_parishes_within_radius_with_distance(tmp_path: Path):
    c = _client(tmp_path)
    # Times Square. Both NYC + Brooklyn parishes are within 25km.
    r = c.get("/v1/parishes?near=40.7580,-73.9855&radius_km=25")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    # Closest first
    ids = [p["id"] for p in body["parishes"]]
    assert ids[0] == "ny-old-st-patricks"  # Mulberry is closer to Times Square
    # All results have distance_km populated
    for p in body["parishes"]:
        assert p["distance_km"] is not None
        assert 0 < p["distance_km"] < 25


def test_near_respects_radius_filter(tmp_path: Path):
    c = _client(tmp_path)
    # 5km radius around Times Square excludes Brooklyn (~8.5km away)
    r = c.get("/v1/parishes?near=40.7580,-73.9855&radius_km=5")
    body = r.json()
    ids = {p["id"] for p in body["parishes"]}
    assert "ny-old-st-patricks" in ids
    assert "ny-st-james-brooklyn" not in ids


def test_near_chicago_finds_only_chicago(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?near=41.8781,-87.6298&radius_km=10")
    body = r.json()
    assert body["count"] == 1
    assert body["parishes"][0]["id"] == "il-holy-name"


def test_near_validates_format(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?near=not-a-coord")
    assert r.status_code == 400


def test_near_validates_range(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?near=120,200")
    assert r.status_code == 400


def test_near_validates_radius(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes?near=40.7,-74&radius_km=0")
    assert r.status_code == 400
    r = c.get("/v1/parishes?near=40.7,-74&radius_km=9999")
    assert r.status_code == 400


def test_near_skips_ungeocoded_parishes(tmp_path: Path):
    """A parish without coordinates must not appear in near-search results."""
    storage = _seed(tmp_path)
    storage.add_parish(
        id="ungeocoded", name="No Coords Church",
        host_kind="ecatholic", ecatholic_id="0",
        city="New York", state="NY",
        active=1,
        # no lat/lng
    )
    c = TestClient(create_app(storage))
    r = c.get("/v1/parishes?near=40.7580,-73.9855&radius_km=50")
    ids = {p["id"] for p in r.json()["parishes"]}
    assert "ungeocoded" not in ids


# ---- plain list still works ----------------------------------------------

def test_plain_list_unaffected(tmp_path: Path):
    c = _client(tmp_path)
    r = c.get("/v1/parishes")
    body = r.json()
    assert body["count"] == 3  # 3 active parishes


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            with tempfile.TemporaryDirectory() as td:
                fn(Path(td))
            print(f"  + {name}")
        except Exception as e:
            failed += 1
            print(f"  - {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll search tests passed.")
