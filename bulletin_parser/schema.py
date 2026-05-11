"""
Schema for a parsed Catholic parish bulletin.

This is the contract between the parser and any consuming application
(mobile app, web app, API). It is shaped around what a parishioner
actually wants to see — not around how bulletins happen to be laid out.

Design notes:
- Mass times are weekly recurring schedules + dated exceptions. Almost
  every bulletin has a "regular" schedule, plus parenthetical or boxed
  exceptions ("no daily Mass Friday," "temporary until Pentecost," etc.).
  We model both explicitly so the app can show "this week's actual times"
  rather than the boilerplate.
- Mass intentions are first-class. Many families look for them.
- Each parish bulletin can cover multiple worship sites (the example PDF
  covers both the Basilica and the Shrine of Most Precious Blood). We
  model `locations` rather than assuming one church per bulletin.
- Liturgical metadata (Sunday name, readings) is separated from
  parish-specific content so the app can choose whether to show it.
"""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# --- Enums ----------------------------------------------------------------

class Weekday(str, Enum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"


class Language(str, Enum):
    """ISO-ish language codes for Mass language. Add more as encountered."""
    english = "en"
    spanish = "es"
    italian = "it"
    vietnamese = "vi"
    latin = "la"
    polish = "pl"
    portuguese = "pt"
    french = "fr"
    tagalog = "tl"
    korean = "ko"
    chinese = "zh"
    other = "other"


class ServiceKind(str, Enum):
    mass = "mass"
    vigil_mass = "vigil_mass"
    confession = "confession"
    adoration = "adoration"
    rosary = "rosary"
    benediction = "benediction"
    novena = "novena"
    holy_hour = "holy_hour"
    other = "other"


# --- Time slots -----------------------------------------------------------

class RecurringSlot(BaseModel):
    """A regularly scheduled service — e.g., 'Sunday 10:30am English Mass'."""
    kind: ServiceKind
    weekday: Weekday
    start_time: time
    end_time: time | None = Field(
        default=None,
        description="Only set when the bulletin specifies a window (typical for confessions, adoration).",
    )
    language: Language | None = Field(
        default=None,
        description="Mass language. None when not specified or not applicable (e.g., confession).",
    )
    location_id: str = Field(
        description="References Location.id below. Use 'main' for single-location parishes.",
    )
    notes: str | None = Field(
        default=None,
        description="Free-form context the parishioner should see — e.g., 'Vigil', 'Children's choir'.",
    )


class ScheduleException(BaseModel):
    """
    A one-off change to the regular schedule for a specific date.

    Captures the things bulletins say in parenthetical asides:
    - 'No daily Mass Friday' -> kind=cancelled
    - 'temporary 5pm Mass until Pentecost' -> kind=added, with end_date
    - '12:10pm Mass moved to 7pm' -> kind=moved
    """
    kind: Literal["added", "cancelled", "moved", "modified"]
    date: date
    end_date: date | None = Field(
        default=None,
        description="For multi-day exceptions like 'temporary until Pentecost'.",
    )
    affects_service: ServiceKind
    affects_time: time | None = Field(
        default=None,
        description="The original time of the affected service, if applicable.",
    )
    new_time: time | None = Field(
        default=None,
        description="For 'moved' or 'added' exceptions.",
    )
    description: str = Field(description="Human-readable explanation for the app to display.")
    location_id: str = "main"


# --- Mass intentions ------------------------------------------------------

class MassIntention(BaseModel):
    """A specific Mass said for a named intention on a specific date."""
    date: date
    time: time
    intention_for: str = Field(
        description="The person or cause the Mass is offered for, e.g. 'Mary & Anne De Bonis'.",
    )
    requested_by: str | None = Field(
        default=None,
        description="The person who requested the intention, if named.",
    )
    is_deceased: bool = Field(
        default=False,
        description="True for 'eternal rest of...', 'in memory of...' etc.",
    )
    location_id: str = "main"


# --- Announcements --------------------------------------------------------

class AnnouncementCategory(str, Enum):
    event = "event"                    # dated, attendable
    schedule_change = "schedule_change" # cross-referenced with ScheduleException
    sacramental = "sacramental"        # marriage prep, baptism, RCIA, convalidation
    ministry = "ministry"              # book club, choir, volunteer
    stewardship = "stewardship"        # giving campaigns, collections
    safety = "safety"                  # victim assistance, safeguarding notices
    operational = "operational"        # gift shop hours, office closures
    other = "other"


class Announcement(BaseModel):
    title: str = Field(description="Short headline, ideally under 60 chars.")
    body: str = Field(description="Cleaned-up announcement text. Strip decorative emojis but keep meaning.")
    category: AnnouncementCategory
    event_date: date | None = Field(
        default=None,
        description="If this is a one-time event, when it happens.",
    )
    event_time: time | None = None
    location: str | None = Field(
        default=None,
        description="Free-form location string (e.g., '32 Prince St', 'Parish Hall').",
    )
    contact_email: str | None = None
    contact_phone: str | None = None
    register_url: str | None = None
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="1=must-see (this week's events, urgent), 10=evergreen filler. App sorts by this.",
    )


# --- Liturgical content ---------------------------------------------------

class LiturgicalDay(BaseModel):
    """Liturgical identity of the Sunday/feast this bulletin covers."""
    name: str = Field(description="e.g., 'Sixth Sunday of Easter'.")
    date: date
    readings: list[str] = Field(
        default_factory=list,
        description="Citations only — e.g., ['Acts 8:5-8, 14-17', '1 Peter 3:15-18', 'John 14:15-21']. "
                    "We don't store the full reading text — too much copyrighted material to redistribute.",
    )


# --- Parish structure -----------------------------------------------------

class Location(BaseModel):
    """A worship site covered by this bulletin."""
    id: str = Field(description="Stable identifier used to reference this location, e.g. 'main', 'mpb'.")
    name: str
    address: str | None = None
    phone: str | None = None
    website: str | None = None


class StaffMember(BaseModel):
    name: str
    role: str
    email: str | None = None


class Parish(BaseModel):
    name: str
    locations: list[Location]
    staff: list[StaffMember] = Field(default_factory=list)


# --- Top-level bulletin ---------------------------------------------------

class Collection(BaseModel):
    """A line from the 'last week's collection' report."""
    location_id: str
    amount_usd: float
    week_of: date | None = None


class Bulletin(BaseModel):
    """The full structured representation of one parish bulletin."""
    parish: Parish
    liturgical_day: LiturgicalDay
    week_starting: date = Field(
        description="The Sunday this bulletin is published for (or covers).",
    )

    recurring_schedule: list[RecurringSlot]
    schedule_exceptions: list[ScheduleException] = Field(default_factory=list)
    mass_intentions: list[MassIntention] = Field(default_factory=list)

    announcements: list[Announcement] = Field(default_factory=list)
    collections: list[Collection] = Field(default_factory=list)

    raw_text_sha256: str | None = Field(
        default=None,
        description="Hash of the source text — useful to detect duplicate parses and stale data.",
    )
    parser_version: str = "1.0.0"
    parsed_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp of when the parse happened.",
    )
