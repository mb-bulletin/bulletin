"""Tests for the geocoder pipeline.

Uses a fake Geocoder implementation; never touches the network.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bulletin_parser.harness.storage import Storage
from bulletin_parser.seeder.geocoder import (
    GeocodeError,
    GeocodeResult,
    geocode_pending,
)


class FakeGeocoder:
    """Returns canned coordinates by query string; raises for unknown queries."""

    def __init__(self, mapping: dict[str, GeocodeResult],
                 transient_for: set[str] | None = None):
        self.mapping = mapping
        self.transient_for = transient_for or set()
        self.calls: list[str] = []

    def geocode(self, address: str) -> GeocodeResult:
        self.calls.append(address)
        if address in self.transient_for:
            raise GeocodeError("simulated 503", transient=True)
        if address in self.mapping:
            return self.mapping[address]
        raise GeocodeError("no match", transient=False)


def _seed_parishes(storage: Storage) -> None:
    storage.add_parish(
        id="ny-old-st-patricks",
        name="Basilica of St. Patrick's Old Cathedral",
        host_kind="ecatholic", ecatholic_id="11778",
        city="New York", state="NY",
        address="263 Mulberry Street, New York, NY 10012",
        active=1,
    )
    storage.add_parish(
        id="il-st-jane",
        name="St. Jane Frances",
        host_kind="ecatholic", ecatholic_id="55555",
        city="Chicago", state="IL",
        # no address field set; the geocoder will fall back to name+city+state
        active=1,
    )
    storage.add_parish(
        id="xx-broken",
        name="Imaginary Parish",
        host_kind="ecatholic", ecatholic_id="99999",
        active=1,
    )


def test_geocode_pending_writes_coordinates_back(tmp_path: Path):
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    _seed_parishes(storage)

    fake = FakeGeocoder({
        "263 Mulberry Street, New York, NY 10012": GeocodeResult(40.722, -73.996),
        "St. Jane Frances, Chicago, IL":             GeocodeResult(41.881, -87.62),
    })
    stats = geocode_pending(storage, geocoder=fake)

    assert stats["geocoded"] == 2
    assert stats["failed_hard"] == 1
    assert stats["failed_transient"] == 0

    # Check the rows were updated
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT latitude, longitude, geocoded_at FROM parishes WHERE id=?",
            ("ny-old-st-patricks",),
        ).fetchone()
        assert abs(row["latitude"] - 40.722) < 1e-6
        assert abs(row["longitude"] - (-73.996)) < 1e-6
        assert row["geocoded_at"] is not None

        # Failure case
        row = conn.execute(
            "SELECT latitude, geocode_failed FROM parishes WHERE id=?",
            ("xx-broken",),
        ).fetchone()
        assert row["latitude"] is None
        assert row["geocode_failed"] == 1


def test_geocode_skips_already_geocoded(tmp_path: Path):
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    storage.add_parish(
        id="x", name="Already Done", host_kind="ecatholic",
        ecatholic_id="1", active=1,
    )
    # Pre-set coordinates
    with storage.connect() as conn:
        conn.execute("UPDATE parishes SET latitude=1.0, longitude=2.0 WHERE id=?", ("x",))

    fake = FakeGeocoder({})  # would fail if called
    stats = geocode_pending(storage, geocoder=fake)
    assert stats["geocoded"] == 0
    assert fake.calls == []  # the row was filtered out by the SQL


def test_geocode_does_not_retry_hard_failures_by_default(tmp_path: Path):
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    storage.add_parish(
        id="x", name="Test", host_kind="ecatholic",
        ecatholic_id="1", city="Nowhere", active=1,
    )
    fake = FakeGeocoder({})
    geocode_pending(storage, geocoder=fake)
    # Second run: should skip the now-failed parish
    stats = geocode_pending(storage, geocoder=FakeGeocoder({"Test, Nowhere": GeocodeResult(0, 0)}))
    assert stats["geocoded"] == 0


def test_geocode_retry_failed_flag(tmp_path: Path):
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    storage.add_parish(
        id="x", name="Test", host_kind="ecatholic",
        ecatholic_id="1", city="Nowhere", active=1,
    )
    geocode_pending(storage, geocoder=FakeGeocoder({}))
    # Now retry with --retry-failed equivalent
    fake = FakeGeocoder({"Test, Nowhere": GeocodeResult(1.5, 2.5)})
    stats = geocode_pending(storage, geocoder=fake, retry_failed=True)
    assert stats["geocoded"] == 1
    with storage.connect() as conn:
        row = conn.execute("SELECT latitude FROM parishes WHERE id=?", ("x",)).fetchone()
        assert row["latitude"] == 1.5


def test_geocode_transient_failure_does_not_mark_failed(tmp_path: Path):
    """Transient (5xx, network) failures should leave the row pending."""
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    storage.add_parish(
        id="x", name="Test", host_kind="ecatholic",
        ecatholic_id="1", city="Nowhere", active=1,
    )
    fake = FakeGeocoder({}, transient_for={"Test, Nowhere"})
    stats = geocode_pending(storage, geocoder=fake)
    assert stats["geocoded"] == 0
    assert stats["failed_transient"] == 1
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT geocode_failed FROM parishes WHERE id=?", ("x",)
        ).fetchone()
        # Should NOT be marked as a hard failure
        assert (row["geocode_failed"] or 0) == 0


def test_geocode_limit(tmp_path: Path):
    storage = Storage(tmp_path / "h.db", tmp_path / "p")
    for i in range(5):
        storage.add_parish(
            id=f"p{i}", name=f"Parish {i}", host_kind="ecatholic",
            ecatholic_id=str(i), city="X", active=1,
        )
    fake = FakeGeocoder({f"Parish {i}, X": GeocodeResult(i, i) for i in range(5)})
    stats = geocode_pending(storage, geocoder=fake, limit=2)
    assert stats["geocoded"] == 2


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
    print("\nAll geocoder tests passed.")
