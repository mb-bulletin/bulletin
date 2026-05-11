"""
Tests that don't require an API key.

These validate the schema and that a hand-constructed Bulletin matching
the St. Patrick's fixture round-trips correctly. The parser itself
(which calls the Anthropic API) is exercised by `demo.py`.
"""

from __future__ import annotations

import json
from datetime import date, time
from pathlib import Path

from bulletin_parser.schema import (
    Announcement,
    AnnouncementCategory,
    Bulletin,
    Collection,
    Language,
    LiturgicalDay,
    Location,
    MassIntention,
    Parish,
    RecurringSlot,
    ScheduleException,
    ServiceKind,
    StaffMember,
    Weekday,
)


def build_stpatricks_reference() -> Bulletin:
    """
    Hand-built structured representation of the St. Patrick's 2026-05-10
    bulletin. This is what the parser *should* produce for that fixture.
    """
    return Bulletin(
        parish=Parish(
            name="The Basilica of St. Patrick's Old Cathedral",
            locations=[
                Location(
                    id="main",
                    name="The Basilica of St. Patrick's Old Cathedral",
                    address="263 Mulberry Street, New York, NY 10012",
                    phone="(212) 226-8075",
                    website="oldcathedral.org",
                ),
                Location(
                    id="mpb",
                    name="Shrine Church of the Most Precious Blood",
                    address="113 Baxter Street, New York, NY 10013",
                ),
            ],
            staff=[
                StaffMember(name="Rev. Daniel Ray, LC", role="Pastor"),
                StaffMember(
                    name="Rev. Luigi Portarulo",
                    role="Parochial Vicar - Italian Community",
                ),
                StaffMember(
                    name="Anthony Cregan",
                    role="Business Manager",
                    email="anthony@oldcathedral.org",
                ),
                StaffMember(
                    name="Rosa Jimenez",
                    role="Secretary & Wedding Coordinator",
                    email="rosa@oldcathedral.org",
                ),
            ],
        ),
        liturgical_day=LiturgicalDay(
            name="Sixth Sunday of Easter",
            date=date(2026, 5, 10),
            readings=["Acts 8:5-8, 14-17", "1 Peter 3:15-18", "John 14:15-21"],
        ),
        week_starting=date(2026, 5, 10),
        recurring_schedule=[
            # Basilica weekly Masses
            RecurringSlot(
                kind=ServiceKind.vigil_mass,
                weekday=Weekday.saturday,
                start_time=time(17, 0),
                language=Language.english,
                location_id="main",
            ),
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(9, 0),
                language=Language.spanish,
                location_id="main",
            ),
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(10, 30),
                language=Language.english,
                location_id="main",
            ),
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(12, 0),
                language=Language.italian,
                location_id="main",
            ),
            # NOTE: the 5pm Sunday Mass is "temporary until Pentecost" — we
            # do NOT include it in the recurring schedule; it's an exception.
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(19, 0),
                language=Language.english,
                location_id="main",
            ),
            # Daily Masses Mon-Fri
            *[
                RecurringSlot(
                    kind=ServiceKind.mass,
                    weekday=wd,
                    start_time=time(12, 10),
                    language=Language.english,
                    location_id="main",
                )
                for wd in [
                    Weekday.monday, Weekday.tuesday, Weekday.wednesday,
                    Weekday.thursday, Weekday.friday,
                ]
            ],
            # Confessions
            RecurringSlot(
                kind=ServiceKind.confession,
                weekday=Weekday.saturday,
                start_time=time(16, 15),
                end_time=time(16, 45),
                location_id="main",
            ),
            RecurringSlot(
                kind=ServiceKind.confession,
                weekday=Weekday.sunday,
                start_time=time(18, 0),
                end_time=time(18, 45),
                location_id="main",
            ),
            # Most Precious Blood
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(12, 0),
                language=Language.english,
                location_id="mpb",
            ),
            RecurringSlot(
                kind=ServiceKind.mass,
                weekday=Weekday.sunday,
                start_time=time(14, 0),
                language=Language.vietnamese,
                location_id="mpb",
            ),
        ],
        schedule_exceptions=[
            ScheduleException(
                kind="added",
                date=date(2026, 5, 10),
                end_date=date(2026, 5, 24),
                affects_service=ServiceKind.mass,
                new_time=time(17, 0),
                description=(
                    "Temporary 5:00pm English Mass on Sundays until "
                    "Pentecost (May 24)."
                ),
                location_id="main",
            ),
        ],
        mass_intentions=[
            MassIntention(
                date=date(2026, 5, 9),
                time=time(17, 0),
                intention_for="Mary & Anne De Bonis, Celeste & Isabella Tangora",
                requested_by="Antoinette",
            ),
            # Mother's Day — 5 Masses, all "for all mothers"
            *[
                MassIntention(
                    date=date(2026, 5, 10),
                    time=t,
                    intention_for="all mothers",
                )
                for t in [time(9, 0), time(10, 30), time(12, 0), time(17, 0), time(19, 0)]
            ],
            MassIntention(
                date=date(2026, 5, 11), time=time(12, 10),
                intention_for="Andrew & Irene Chan",
                requested_by="Robert & Virginia Lugo",
            ),
            MassIntention(
                date=date(2026, 5, 12), time=time(12, 10),
                intention_for="Maria Filomena Nuñez",
                requested_by="Agustina Rodriguez",
                is_deceased=True,
            ),
            MassIntention(
                date=date(2026, 5, 12), time=time(12, 10),
                intention_for="Fausto Ortiz",
                requested_by="family",
            ),
            MassIntention(
                date=date(2026, 5, 13), time=time(12, 10),
                intention_for="Irene & Andrew Chan",
                requested_by="family",
            ),
            MassIntention(
                date=date(2026, 5, 14), time=time(12, 10),
                intention_for="Karael Cruz",
                requested_by="family",
            ),
            MassIntention(
                date=date(2026, 5, 15), time=time(12, 10),
                intention_for="Angelina Torrisi",
                requested_by="Eric Skae",
            ),
            MassIntention(
                date=date(2026, 5, 16), time=time(17, 0),
                intention_for="GiGi Boetto",
                requested_by="Shauna Simonot",
            ),
        ],
        announcements=[
            Announcement(
                title="OSP Hospitality Presents: The Saints",
                body=(
                    "Film screening with reception. Reception at 6:00 PM, "
                    "screening at 7:00 PM. All are welcome, bring a friend!"
                ),
                category=AnnouncementCategory.event,
                event_date=date(2026, 5, 13),
                event_time=time(18, 0),
                register_url="https://luma.com/j2ydh30q",
                priority=2,
            ),
            Announcement(
                title="Marriage Convalidation",
                body=(
                    "Married by the state but not yet by the Catholic "
                    "Church? Reach out about having your marriage "
                    "convalidated. This allows you to receive communion at "
                    "Mass. Doesn't require a big ceremony. No one is turned "
                    "away for inability to pay."
                ),
                category=AnnouncementCategory.sacramental,
                contact_email="rosa@oldcathedral.org",
                priority=5,
            ),
            Announcement(
                title="Book Club: The City of God",
                body=(
                    "Sundays at 5:50pm, 32 Prince St. Beginning May 10, "
                    "studying The City of God by Saint Augustine."
                ),
                category=AnnouncementCategory.ministry,
                event_date=date(2026, 5, 10),
                event_time=time(17, 50),
                location="32 Prince St",
                priority=4,
            ),
            Announcement(
                title="Victim Assistance",
                body=(
                    "To report alleged abuse, contact Eileen Mulcahy at "
                    "646-794-2949 or victimsassistance@archny.org, or the "
                    "NY County DA's Office at 212-335-9373."
                ),
                category=AnnouncementCategory.safety,
                contact_email="victimsassistance@archny.org",
                contact_phone="646-794-2949",
                priority=6,
            ),
            Announcement(
                title="Recurring Giving via WeShare",
                body=(
                    "Set up weekly or monthly recurring donations through "
                    "WeShare to support the parish even when away."
                ),
                category=AnnouncementCategory.stewardship,
                priority=7,
            ),
            Announcement(
                title="Catacombs by Candlelight Tours",
                body=(
                    "90-minute tour through two centuries of history. "
                    "Visit oldcathedral.org/tours."
                ),
                category=AnnouncementCategory.operational,
                priority=8,
            ),
            Announcement(
                title="Gift Shop Open",
                body=(
                    "266 Mulberry Street, Thursday-Monday 10am-5pm. "
                    "Also shop online."
                ),
                category=AnnouncementCategory.operational,
                priority=9,
            ),
            Announcement(
                title="Burial Services at the Basilica",
                body=(
                    "Limited niches available in the only operating "
                    "Catholic graveyard and catacombs in Manhattan. Contact "
                    "Frank Alfieri."
                ),
                category=AnnouncementCategory.operational,
                contact_email="frank@oldcathedral.org",
                contact_phone="(212) 226-8075",
                priority=8,
            ),
        ],
        collections=[
            Collection(location_id="main", amount_usd=9123.36),
            Collection(location_id="mpb", amount_usd=668.0),
        ],
    )


# -- Tests --

def test_reference_validates():
    """The hand-built reference Bulletin must be valid."""
    b = build_stpatricks_reference()
    assert b.parish.name.startswith("The Basilica")
    assert len(b.parish.locations) == 2
    assert any(loc.id == "mpb" for loc in b.parish.locations)


def test_roundtrip_json():
    """Bulletin -> JSON -> Bulletin must be a no-op."""
    b1 = build_stpatricks_reference()
    js = b1.model_dump_json()
    b2 = Bulletin.model_validate_json(js)
    assert b2 == b1


def test_temporary_mass_is_an_exception_not_a_recurring_slot():
    """
    The 5pm Sunday English Mass is temporary until Pentecost. It should
    appear in schedule_exceptions, not recurring_schedule.
    """
    b = build_stpatricks_reference()
    sunday_5pm_recurring = [
        s for s in b.recurring_schedule
        if s.weekday == Weekday.sunday and s.start_time == time(17, 0)
    ]
    assert len(sunday_5pm_recurring) == 0, (
        "5pm Sunday Mass should NOT be in the recurring schedule"
    )
    exceptions = [
        e for e in b.schedule_exceptions if e.new_time == time(17, 0)
    ]
    assert len(exceptions) == 1


def test_multilingual_masses_distinguished():
    """All four spoken languages should appear in the schedule."""
    b = build_stpatricks_reference()
    langs = {s.language for s in b.recurring_schedule if s.language}
    assert {Language.english, Language.spanish, Language.italian, Language.vietnamese} <= langs


def test_mass_intentions_include_multiple_intentions_same_slot():
    """Tuesday's 12:10pm has two intentions — both should be captured."""
    b = build_stpatricks_reference()
    tuesday = [m for m in b.mass_intentions if m.date == date(2026, 5, 12)]
    assert len(tuesday) == 2
    assert any(m.is_deceased for m in tuesday)


def test_deceased_flag():
    """'For the eternal rest of...' should be marked is_deceased=True."""
    b = build_stpatricks_reference()
    nunez = [m for m in b.mass_intentions if "Nuñez" in m.intention_for]
    assert len(nunez) == 1
    assert nunez[0].is_deceased is True


def test_announcements_sorted_by_priority_for_app():
    """The app sorts by priority — verify the priority field is meaningful."""
    b = build_stpatricks_reference()
    by_priority = sorted(b.announcements, key=lambda a: a.priority)
    # The most urgent announcement should be the event happening this week
    assert by_priority[0].category == AnnouncementCategory.event


def test_collection_per_location():
    b = build_stpatricks_reference()
    assert len(b.collections) == 2
    main = next(c for c in b.collections if c.location_id == "main")
    assert main.amount_usd == 9123.36


if __name__ == "__main__":
    # Run all tests
    import sys
    failed = 0
    for name in dir(sys.modules[__name__]):
        if name.startswith("test_"):
            fn = globals()[name]
            try:
                fn()
                print(f"  ✓ {name}")
            except AssertionError as e:
                failed += 1
                print(f"  ✗ {name}: {e}")
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
