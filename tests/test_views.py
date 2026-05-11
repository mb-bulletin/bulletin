"""
Tests for the today/schedule view computation.

These exercise the exception-merge logic against the hand-built
St Patrick's reference bulletin. No network, no API key.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bulletin_parser.api.views import (
    _services_on_date,
    schedule_view,
    today_view,
)
from bulletin_parser.schema import (
    Language,
    ScheduleException,
    ServiceKind,
    Weekday,
)
from test_schema import build_stpatricks_reference


TZ = "America/New_York"


def test_services_on_date_sunday():
    """Sunday 2026-05-10 should yield 5 Masses + 2 confessions at the main location."""
    b = build_stpatricks_reference()
    services = _services_on_date(b, date(2026, 5, 10))

    main_masses = [
        s for s in services
        if s.kind == ServiceKind.mass and s.location_id == "main"
    ]
    # 9am Spanish, 10:30am English, 12pm Italian, 5pm English (exception), 7pm English
    # The 5pm English is an ADDED exception, so it should be present on this date.
    assert len(main_masses) == 5, (
        f"expected 5 Masses at main on Sunday, got {len(main_masses)}: "
        f"{[(s.start_time, s.language) for s in main_masses]}"
    )

    main_confessions = [
        s for s in services
        if s.kind == ServiceKind.confession and s.location_id == "main"
    ]
    assert len(main_confessions) == 1, "Sunday confessions slot is 6:00-6:45pm"

    mpb_masses = [s for s in services if s.location_id == "mpb"]
    assert len(mpb_masses) == 2, "Most Precious Blood has 2 Sunday Masses"


def test_added_exception_appears_on_date():
    """The temporary 5pm Sunday Mass should show up on Sundays in its date range."""
    b = build_stpatricks_reference()

    # The exception is dated 2026-05-10, end_date 2026-05-24
    services_in_window = _services_on_date(b, date(2026, 5, 17))
    has_5pm = any(
        s.start_time == time(17, 0) and s.kind == ServiceKind.mass
        and s.location_id == "main" and s.is_exception
        for s in services_in_window
    )
    assert has_5pm, "5pm Sunday Mass should appear on 2026-05-17 (within exception window)"

    # AFTER the end_date, it should not appear
    services_after = _services_on_date(b, date(2026, 5, 31))
    has_5pm_after = any(
        s.start_time == time(17, 0) and s.kind == ServiceKind.mass
        and s.location_id == "main" and s.is_exception
        for s in services_after
    )
    assert not has_5pm_after, "5pm Sunday Mass should NOT appear after Pentecost (2026-05-24)"


def test_weekday_daily_mass():
    """Monday-Friday should have one daily Mass at 12:10pm at main."""
    b = build_stpatricks_reference()
    for d in [date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 15)]:
        services = _services_on_date(b, d)
        daily = [
            s for s in services
            if s.start_time == time(12, 10) and s.location_id == "main"
        ]
        assert len(daily) == 1, f"missing daily Mass on {d}: {services}"


def test_no_daily_mass_on_saturday():
    """The St Patrick's recurring schedule has no daily Mass on Saturday."""
    b = build_stpatricks_reference()
    services = _services_on_date(b, date(2026, 5, 16))
    daily = [s for s in services if s.start_time == time(12, 10)]
    assert len(daily) == 0


def test_today_view_remaining_services_filters_past():
    """Services earlier in the day than `now` should NOT appear in remaining."""
    b = build_stpatricks_reference()
    # Sunday 2026-05-10 at 11:00am ET — 9am Spanish and 10:30am English are done.
    now = datetime(2026, 5, 10, 11, 0, tzinfo=ZoneInfo(TZ))
    view = today_view(b, TZ, now=now)
    remaining_times = sorted(s.start_time for s in view.today_services_remaining)
    assert time(9, 0) not in remaining_times
    assert time(10, 30) not in remaining_times
    # 12pm Italian and onward should still be there
    assert time(12, 0) in remaining_times


def test_today_view_next_service_is_remaining_today_when_available():
    b = build_stpatricks_reference()
    now = datetime(2026, 5, 10, 11, 0, tzinfo=ZoneInfo(TZ))
    view = today_view(b, TZ, now=now)
    assert view.next_service is not None
    assert view.next_service.date == date(2026, 5, 10)


def test_today_view_next_service_rolls_to_tomorrow_when_today_done():
    """After the last Sunday Mass (7pm), next_service should be Monday 12:10pm."""
    b = build_stpatricks_reference()
    now = datetime(2026, 5, 10, 21, 0, tzinfo=ZoneInfo(TZ))  # 9pm Sunday
    view = today_view(b, TZ, now=now)
    assert view.next_service is not None
    assert view.next_service.date == date(2026, 5, 11)
    assert view.next_service.start_time == time(12, 10)


def test_today_view_surfaces_high_priority_announcements_only():
    """Only priority<=3 announcements should appear in the home view."""
    b = build_stpatricks_reference()
    now = datetime(2026, 5, 10, 7, 0, tzinfo=ZoneInfo(TZ))
    view = today_view(b, TZ, now=now)
    for a in view.high_priority_announcements:
        assert a.priority <= 3
    # The screening event is priority 2; verify it surfaces.
    titles = [a.title for a in view.high_priority_announcements]
    assert any("OSP Hospitality" in t for t in titles)


def test_today_view_intentions_for_today():
    """Mother's Day Sunday: all 5 Masses are 'for all mothers'."""
    b = build_stpatricks_reference()
    now = datetime(2026, 5, 10, 7, 0, tzinfo=ZoneInfo(TZ))
    view = today_view(b, TZ, now=now)
    assert len(view.todays_intentions) == 5
    assert all(mi.intention_for == "all mothers" for mi in view.todays_intentions)


def test_today_view_attaches_intentions_to_services():
    """Tuesday's 12:10pm has two intentions; the DatedService should list both."""
    b = build_stpatricks_reference()
    services = _services_on_date(b, date(2026, 5, 12))
    daily = [s for s in services if s.start_time == time(12, 10)]
    assert len(daily) == 1
    assert len(daily[0].intentions) == 2


def test_schedule_view_returns_seven_days():
    b = build_stpatricks_reference()
    now = datetime(2026, 5, 10, 7, 0, tzinfo=ZoneInfo(TZ))
    services = schedule_view(b, TZ, now=now, days=7)
    dates_present = {s.date for s in services}
    assert len(dates_present) == 7
    assert min(dates_present) == date(2026, 5, 10)
    assert max(dates_present) == date(2026, 5, 16)


def test_cancellation_removes_recurring_slot():
    """Manually inject a cancellation and verify the slot disappears that day."""
    b = build_stpatricks_reference()
    b = b.model_copy(update={
        "schedule_exceptions": list(b.schedule_exceptions) + [
            ScheduleException(
                kind="cancelled",
                date=date(2026, 5, 13),
                affects_service=ServiceKind.mass,
                affects_time=time(12, 10),
                description="No daily Mass — staff retreat",
                location_id="main",
            )
        ]
    })
    services = _services_on_date(b, date(2026, 5, 13))
    daily = [s for s in services if s.start_time == time(12, 10) and s.location_id == "main"]
    assert len(daily) == 0, "Cancelled Mass should not appear"

    # Other days unaffected
    services_tue = _services_on_date(b, date(2026, 5, 12))
    daily_tue = [s for s in services_tue if s.start_time == time(12, 10) and s.location_id == "main"]
    assert len(daily_tue) == 1


def test_moved_exception_changes_time():
    """A moved Mass appears at the new time, not the original."""
    b = build_stpatricks_reference()
    b = b.model_copy(update={
        "schedule_exceptions": list(b.schedule_exceptions) + [
            ScheduleException(
                kind="moved",
                date=date(2026, 5, 14),
                affects_service=ServiceKind.mass,
                affects_time=time(12, 10),
                new_time=time(19, 0),
                description="Mass moved to 7pm for Ascension vigil",
                location_id="main",
            )
        ]
    })
    services = _services_on_date(b, date(2026, 5, 14))
    # Original 12:10 should be gone, replaced by 7pm
    times_at_main = sorted(s.start_time for s in services if s.location_id == "main")
    assert time(12, 10) not in times_at_main
    assert time(19, 0) in times_at_main


def test_added_exception_does_not_fire_on_wrong_weekday():
    """A temporary Sunday-only Mass with a multi-week range must not appear on weekdays.

    Regression: previously, an added exception with date+end_date was firing
    on every day in the range, not just the same weekday as `date`.
    """
    b = build_stpatricks_reference()
    for d in [date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13),
              date(2026, 5, 14), date(2026, 5, 15)]:
        services = _services_on_date(b, d)
        exception_5pm = [
            s for s in services
            if s.start_time == time(17, 0) and s.is_exception
            and s.location_id == "main"
        ]
        assert len(exception_5pm) == 0, (
            f"5pm exception should not appear on {d} ({d.strftime('%A')})"
        )


def test_added_exception_does_fire_on_correct_weekday_within_range():
    b = build_stpatricks_reference()
    # Sunday 2026-05-17 is within the exception window
    services = _services_on_date(b, date(2026, 5, 17))
    exception_5pm = [
        s for s in services
        if s.start_time == time(17, 0) and s.is_exception
    ]
    assert len(exception_5pm) == 1


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll view tests passed.")
