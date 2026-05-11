"""Field-level comparators for eval scoring.

Each Bulletin field has its own notion of equality:
- Times and dates: exact match.
- Names (intention_for, parish name): fuzzy text with light normalization.
- Announcement bodies: text similarity above threshold; paraphrase OK.
- Priority: within 1 of expected = full credit; within 2 = partial.
- Lists: matched by key function, then per-item checks.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from .schema import CheckResult


_HONORIFIC_NORMALIZATIONS = [
    (re.compile(r"\bSaint\b", re.IGNORECASE), "St."),
    (re.compile(r"\bSt\b(?!\.)", re.IGNORECASE), "St."),
    (re.compile(r"\bFather\b", re.IGNORECASE), "Fr."),
    (re.compile(r"\bReverend\b", re.IGNORECASE), "Rev."),
    (re.compile(r"\s+"), " "),
]


def normalize_name(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    for pattern, replacement in _HONORIFIC_NORMALIZATIONS:
        s = pattern.sub(replacement, s)
    s = s.strip().lower()
    s = re.sub(r"[^\w\s.'-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def text_similarity(a, b):
    na, nb = normalize_name(a), normalize_name(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def exact(expected, actual, note=""):
    if expected == actual:
        return CheckResult(score=1.0, expected=expected, actual=actual)
    return CheckResult(
        score=0.0, expected=expected, actual=actual,
        note=note or f"expected {expected!r}, got {actual!r}",
    )


def fuzzy_text(expected, actual, threshold=0.85, note=""):
    sim = text_similarity(expected, actual)
    score = 0.0 if sim < threshold else min(
        1.0, (sim - threshold) / max(1.0 - threshold, 1e-6) * 0.5 + 0.5
    )
    return CheckResult(
        score=score, expected=expected, actual=actual,
        note=note or f"similarity={sim:.2f} (threshold {threshold})",
    )


def near_number(expected, actual, tolerance=0.01):
    if actual is None:
        return CheckResult(score=0.0, expected=expected, actual=None, note="missing")
    diff = abs(expected - actual)
    if diff <= tolerance:
        return CheckResult(score=1.0, expected=expected, actual=actual)
    return CheckResult(
        score=max(0.0, 1.0 - diff / max(abs(expected), 1.0)),
        expected=expected, actual=actual, note=f"diff={diff:.4f}",
    )


def near_priority(expected, actual):
    if actual is None:
        return CheckResult(score=0.0, expected=expected, actual=None, note="missing")
    diff = abs(expected - actual)
    if diff <= 1:
        return CheckResult(score=1.0, expected=expected, actual=actual)
    if diff == 2:
        return CheckResult(score=0.5, expected=expected, actual=actual,
                           note=f"off by {diff}")
    return CheckResult(score=0.0, expected=expected, actual=actual,
                       note=f"off by {diff}")


def match_lists_by_key(expected, actual, key, compare):
    """Match expected to actual by key; compare each pair; report missing/extra."""
    expected_by_key = {key(e): e for e in expected}
    actual_by_key = {key(a): a for a in actual}

    expected_keys = set(expected_by_key)
    actual_keys = set(actual_by_key)

    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    matched = expected_keys & actual_keys

    checks = []
    for k in missing:
        checks.append(CheckResult(
            score=0.0, expected=expected_by_key[k], actual=None,
            note=f"missing item (key={k!r})",
        ))
    for k in extra:
        checks.append(CheckResult(
            score=0.0, expected=None, actual=actual_by_key[k],
            note=f"unexpected item (key={k!r})",
        ))
    for k in matched:
        checks.extend(compare(expected_by_key[k], actual_by_key[k]))

    return checks, len(missing), len(extra)


# Field-specific comparators. Each takes (expected, actual) Bulletin objects
# and returns (list[CheckResult], missing_count, extra_count).

def compare_liturgical_day(expected, actual):
    e, a = expected.liturgical_day, actual.liturgical_day
    checks = [
        fuzzy_text(e.name, a.name, note="liturgical_day.name"),
        exact(e.date, a.date, note="liturgical_day.date"),
    ]
    e_readings = set(r.strip() for r in e.readings)
    a_readings = set(r.strip() for r in a.readings)
    common = e_readings & a_readings
    readings_score = (len(common) / len(e_readings)) if e_readings else 1.0
    checks.append(CheckResult(
        score=readings_score, expected=sorted(e_readings),
        actual=sorted(a_readings),
        note=f"readings: {len(common)}/{len(e_readings)} matched",
    ))
    return checks, 0, 0


def compare_recurring_schedule(expected, actual):
    # Key by (weekday, start_time, location_id, kind). Language is NOT in
    # the key - mislabeling Spanish vs English should surface as a check
    # failure on a matched slot, not as missing+extra pair.
    def k(s):
        return (s.weekday.value, str(s.start_time), s.location_id, s.kind.value)

    def compare_slot(e, a):
        return [
            exact(e.language, a.language, note=f"slot {k(e)}: language"),
            exact(e.end_time, a.end_time, note=f"slot {k(e)}: end_time"),
        ]

    return match_lists_by_key(expected.recurring_schedule,
                              actual.recurring_schedule, k, compare_slot)


def compare_schedule_exceptions(expected, actual):
    def k(e):
        return (str(e.date), e.kind, e.affects_service.value, e.location_id)

    def compare_exc(e, a):
        return [
            exact(e.end_date, a.end_date, note="exception.end_date"),
            exact(e.new_time, a.new_time, note="exception.new_time"),
            exact(e.affects_time, a.affects_time, note="exception.affects_time"),
            fuzzy_text(e.description, a.description, threshold=0.6,
                       note="exception.description"),
        ]

    return match_lists_by_key(expected.schedule_exceptions,
                              actual.schedule_exceptions, k, compare_exc)


def compare_mass_intentions(expected, actual):
    def k(m):
        return (str(m.date), str(m.time), normalize_name(m.intention_for)[:40])

    def compare_intention(e, a):
        return [
            fuzzy_text(e.intention_for, a.intention_for,
                       threshold=0.85, note="intention_for"),
            fuzzy_text(e.requested_by, a.requested_by,
                       threshold=0.75, note="requested_by"),
            exact(e.is_deceased, a.is_deceased, note="is_deceased"),
        ]

    return match_lists_by_key(expected.mass_intentions,
                              actual.mass_intentions, k, compare_intention)


def compare_announcements(expected, actual):
    def k(a):
        return normalize_name(a.title)[:60]

    def compare_announcement(e, a):
        return [
            fuzzy_text(e.body, a.body, threshold=0.5,
                       note=f"announcement[{e.title!r}].body"),
            exact(e.category, a.category,
                  note=f"announcement[{e.title!r}].category"),
            near_priority(e.priority, a.priority),
            exact(e.event_date, a.event_date,
                  note=f"announcement[{e.title!r}].event_date"),
        ]

    return match_lists_by_key(expected.announcements,
                              actual.announcements, k, compare_announcement)


def compare_collections(expected, actual):
    def k(c):
        return c.location_id

    def compare_collection(e, a):
        return [near_number(e.amount_usd, a.amount_usd, tolerance=0.01)]

    return match_lists_by_key(expected.collections, actual.collections,
                              k, compare_collection)


def compare_parish(expected, actual):
    checks = [fuzzy_text(expected.parish.name, actual.parish.name,
                         threshold=0.9, note="parish.name")]

    def k(loc):
        return loc.id

    def compare_loc(e, a):
        return [fuzzy_text(e.name, a.name, threshold=0.85,
                           note=f"location[{e.id}].name")]

    loc_checks, miss, extra = match_lists_by_key(
        expected.parish.locations, actual.parish.locations, k, compare_loc,
    )
    return checks + loc_checks, miss, extra
