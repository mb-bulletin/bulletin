"""Per-field weights and aggregation logic.

The weighting reflects what actually matters for the parishioner. A
missed Mass time is a P0; a paraphrased announcement is a P3. Weights
are tuned for *severity of regression*, not for how often the field
appears in bulletins.

The weights below sum to roughly 100 — that's just for human
readability; they're normalized in `aggregate` below.
"""
from __future__ import annotations

from typing import Callable

from .checks import (
    compare_announcements,
    compare_collections,
    compare_liturgical_day,
    compare_mass_intentions,
    compare_parish,
    compare_recurring_schedule,
    compare_schedule_exceptions,
)
from .schema import BulletinResult, CheckResult, FieldResult


# field -> (weight, comparator)
# Comparator signature: (expected_bulletin, actual_bulletin) ->
#   (list[CheckResult], missing_count, extra_count)
FIELD_SPEC: dict[str, tuple[float, Callable]] = {
    "recurring_schedule":    (30.0, compare_recurring_schedule),
    "schedule_exceptions":   (15.0, compare_schedule_exceptions),
    "mass_intentions":       (15.0, compare_mass_intentions),
    "announcements":         (15.0, compare_announcements),
    "liturgical_day":        ( 8.0, compare_liturgical_day),
    "parish":                ( 7.0, compare_parish),
    "collections":           ( 5.0, compare_collections),
}


def _average_score(checks: list[CheckResult]) -> float:
    if not checks:
        return 1.0  # No checks ran => nothing to disagree about
    return sum(c.score for c in checks) / len(checks)


def evaluate_bulletin(
    case_id: str, expected, actual, *,
    tokens_in: int | None = None, tokens_out: int | None = None,
) -> BulletinResult:
    """Run every field comparator and produce a BulletinResult."""
    field_results: list[FieldResult] = []
    total_weight = sum(w for w, _ in FIELD_SPEC.values())

    weighted_sum = 0.0
    for field_name, (weight, comparator) in FIELD_SPEC.items():
        checks, missing, extra = comparator(expected, actual)
        score = _average_score(checks)
        field_results.append(FieldResult(
            field=field_name, score=score, weight=weight,
            checks=checks, missing_count=missing, extra_count=extra,
        ))
        weighted_sum += score * weight

    overall = weighted_sum / total_weight if total_weight else 0.0
    return BulletinResult(
        case_id=case_id, overall_score=overall, fields=field_results,
        parse_succeeded=True, tokens_in=tokens_in, tokens_out=tokens_out,
    )


def parse_failure_result(case_id: str, error: str) -> BulletinResult:
    """When the parser raises, every field scores 0."""
    return BulletinResult(
        case_id=case_id, overall_score=0.0,
        fields=[
            FieldResult(field=name, score=0.0, weight=weight, checks=[
                CheckResult(score=0.0, note=f"parse failed: {error}")
            ])
            for name, (weight, _) in FIELD_SPEC.items()
        ],
        parse_succeeded=False, parse_error=error,
    )
