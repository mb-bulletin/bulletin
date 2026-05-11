"""
Today/schedule computation.

This is where the parsed Bulletin gets transformed into the answer to
"what does the parishioner need to see right now?" — the only piece of
real business logic in the API.

Two views are computed here:

1. **today()** — for the home screen. Given a parish and the current
   instant (in the parish's timezone), returns:
     - the next upcoming Mass (or "today's remaining Masses")
     - schedule exceptions affecting today or the rest of this week
     - high-priority announcements (priority <= 3)
     - mass intentions for today (if any)

2. **schedule()** — for the "schedule" tab. Given a parish, returns the
   next 7 days as a list of dated services, with recurring slots
   instantiated on each weekday and exceptions applied (cancellations
   removed, additions inserted, moves reflected). The mobile UI renders
   this directly.

The merge logic for exceptions is the tricky bit and has its own tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Iterable
from zoneinfo import ZoneInfo

from ..schema import (
    Announcement,
    Bulletin,
    Language,
    MassIntention,
    ScheduleException,
    ServiceKind,
    Weekday,
)

# Map our Weekday enum to date.weekday() integers (Mon=0..Sun=6).
_WEEKDAY_TO_INT = {
    Weekday.monday: 0,
    Weekday.tuesday: 1,
    Weekday.wednesday: 2,
    Weekday.thursday: 3,
    Weekday.friday: 4,
    Weekday.saturday: 5,
    Weekday.sunday: 6,
}


@dataclass(frozen=True)
class DatedService:
    """A specific service on a specific date (post-exception merge)."""
    date: date
    start_time: time
    end_time: time | None
    kind: ServiceKind
    language: Language | None
    location_id: str
    notes: str | None = None
    is_exception: bool = False  # True if this slot came from a ScheduleException
    intentions: list[str] = field(default_factory=list)  # textual summaries

    @property
    def starts_at(self) -> datetime:
        # Naive — caller attaches tzinfo via _localize if needed.
        return datetime.combine(self.date, self.start_time)


@dataclass(frozen=True)
class TodayView:
    """What the mobile home screen renders."""
    parish_id: str
    as_of: datetime                       # the instant 'today' was computed at
    today: date
    today_services_remaining: list[DatedService]
    next_service: DatedService | None     # convenience: first remaining service today, else next upcoming
    this_week_exceptions: list[ScheduleException]
    high_priority_announcements: list[Announcement]
    todays_intentions: list[MassIntention]


# ---- Helpers ----

def _parish_now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _services_on_date(
    bulletin: Bulletin, target_date: date
) -> list[DatedService]:
    """All services scheduled to occur on `target_date`, after exceptions.

    Algorithm:
      1. Start with recurring slots whose weekday matches.
      2. Apply cancellations and moves keyed to this date.
      3. Append additions whose date range covers this date.

    Note: We treat the bulletin's `week_starting` as the canonical "this
    week"; for dates outside that week we still apply the recurring
    schedule (because that's the steady state) but we don't apply
    exceptions outside their stated date range. This matters when the
    `schedule()` view extends into a future week.
    """
    weekday_int = target_date.weekday()
    out: list[DatedService] = []

    # Build a set of (start_time, location_id, kind) keys for cancellations/moves
    # applying to this date, so we can filter recurring slots.
    cancellations: set[tuple[time | None, str, ServiceKind]] = set()
    moves: dict[tuple[time | None, str, ServiceKind], ScheduleException] = {}
    additions: list[ScheduleException] = []

    for exc in bulletin.schedule_exceptions:
        if not _exception_applies_on(exc, target_date):
            continue
        key = (exc.affects_time, exc.location_id, exc.affects_service)
        if exc.kind == "cancelled":
            cancellations.add(key)
        elif exc.kind == "moved":
            moves[key] = exc
        elif exc.kind == "modified":
            # We treat 'modified' as "still happens, surface the note"; the
            # original slot is kept but flagged via this_week_exceptions.
            pass
        elif exc.kind == "added":
            additions.append(exc)

    # Recurring slots that match the weekday
    for slot in bulletin.recurring_schedule:
        if _WEEKDAY_TO_INT[slot.weekday] != weekday_int:
            continue
        key = (slot.start_time, slot.location_id, slot.kind)
        if key in cancellations:
            continue
        if key in moves:
            mv = moves[key]
            out.append(DatedService(
                date=target_date,
                start_time=mv.new_time or slot.start_time,
                end_time=slot.end_time,
                kind=slot.kind,
                language=slot.language,
                location_id=slot.location_id,
                notes=f"Moved: {mv.description}",
                is_exception=True,
            ))
        else:
            out.append(DatedService(
                date=target_date,
                start_time=slot.start_time,
                end_time=slot.end_time,
                kind=slot.kind,
                language=slot.language,
                location_id=slot.location_id,
                notes=slot.notes,
            ))

    # Additions
    for add in additions:
        if add.new_time is None:
            continue  # malformed; skip
        # If the addition has a date range (end_date set), it means
        # "every occurrence of this weekday within the range" — e.g. a
        # temporary Sunday Mass added until Pentecost should fire on
        # Sundays only, not every day. We use add.date's weekday as the
        # canonical weekday for the recurring addition.
        if add.end_date is not None and add.date.weekday() != target_date.weekday():
            continue
        out.append(DatedService(
            date=target_date,
            start_time=add.new_time,
            end_time=None,
            kind=add.affects_service,
            language=None,
            location_id=add.location_id,
            notes=add.description,
            is_exception=True,
        ))

    # Mass intentions: attach to matching service slot if any
    intentions_by_time: dict[tuple[date, time, str], list[str]] = {}
    for mi in bulletin.mass_intentions:
        if mi.date != target_date:
            continue
        key = (mi.date, mi.time, mi.location_id)
        intentions_by_time.setdefault(key, []).append(_intention_summary(mi))

    out_with_intentions: list[DatedService] = []
    for s in out:
        key = (s.date, s.start_time, s.location_id)
        if key in intentions_by_time:
            out_with_intentions.append(DatedService(
                date=s.date, start_time=s.start_time, end_time=s.end_time,
                kind=s.kind, language=s.language, location_id=s.location_id,
                notes=s.notes, is_exception=s.is_exception,
                intentions=intentions_by_time[key],
            ))
        else:
            out_with_intentions.append(s)

    out_with_intentions.sort(key=lambda s: s.start_time)
    return out_with_intentions


def _exception_applies_on(exc: ScheduleException, target: date) -> bool:
    """True if this exception covers `target`."""
    if exc.end_date is None:
        return exc.date == target
    return exc.date <= target <= exc.end_date


def _intention_summary(mi: MassIntention) -> str:
    prefix = "✝ " if mi.is_deceased else ""
    base = f"{prefix}{mi.intention_for}"
    if mi.requested_by:
        return f"{base} (req. by {mi.requested_by})"
    return base


# ---- Public views ----

def today_view(bulletin: Bulletin, parish_tz: str, *,
               now: datetime | None = None) -> TodayView:
    """Compute the TodayView for a parish given its bulletin and timezone."""
    now = now or _parish_now(parish_tz)
    today = now.date()
    services_today = _services_on_date(bulletin, today)
    remaining = [s for s in services_today if s.start_time >= now.time()]

    # Find next_service: first remaining today, or first upcoming over next 7 days.
    next_service: DatedService | None = remaining[0] if remaining else None
    if next_service is None:
        for offset in range(1, 8):
            future_services = _services_on_date(bulletin, today + timedelta(days=offset))
            if future_services:
                next_service = future_services[0]
                break

    # This week's exceptions (today through Saturday of this week, or end_date)
    week_end = today + timedelta(days=(6 - today.weekday()))  # Sunday of THIS week
    if today.weekday() == 6:  # Sunday
        week_end = today + timedelta(days=6)
    week_exceptions = [
        e for e in bulletin.schedule_exceptions
        if _exception_applies_on(e, today) or (
            e.end_date is None and today <= e.date <= week_end
        ) or (
            e.end_date is not None and e.date <= week_end and e.end_date >= today
        )
    ]

    high_pri = sorted(
        [a for a in bulletin.announcements if a.priority <= 3],
        key=lambda a: a.priority,
    )

    todays_intentions = [
        mi for mi in bulletin.mass_intentions if mi.date == today
    ]

    return TodayView(
        parish_id=bulletin.parish.name,  # caller overrides with actual id
        as_of=now,
        today=today,
        today_services_remaining=remaining,
        next_service=next_service,
        this_week_exceptions=week_exceptions,
        high_priority_announcements=high_pri,
        todays_intentions=todays_intentions,
    )


def schedule_view(bulletin: Bulletin, parish_tz: str, *,
                  now: datetime | None = None, days: int = 7
                  ) -> list[DatedService]:
    """The next `days` days of services for a parish, exceptions merged in."""
    now = now or _parish_now(parish_tz)
    today = now.date()
    out: list[DatedService] = []
    for i in range(days):
        out.extend(_services_on_date(bulletin, today + timedelta(days=i)))
    return out
