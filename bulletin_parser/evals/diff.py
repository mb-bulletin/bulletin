"""Compare two EvalRuns; surface regressions and improvements."""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import BulletinResult, EvalRun, FieldResult


@dataclass
class FieldDiff:
    field: str
    case_id: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass
class RunDiff:
    """Comparison of two EvalRuns."""
    before_id: str
    after_id: str
    overall_before: float
    overall_after: float
    regressions: list[FieldDiff] = field(default_factory=list)
    improvements: list[FieldDiff] = field(default_factory=list)
    unchanged: list[FieldDiff] = field(default_factory=list)
    missing_cases: list[str] = field(default_factory=list)
    new_cases: list[str] = field(default_factory=list)

    @property
    def overall_delta(self) -> float:
        return self.overall_after - self.overall_before


# A field-level change of < 0.01 is noise (the comparators have floating-point
# scoring); larger is signal.
NOISE_THRESHOLD = 0.01


def _index_fields(result: BulletinResult) -> dict[str, FieldResult]:
    return {f.field: f for f in result.fields}


def _index_cases(run: EvalRun) -> dict[str, BulletinResult]:
    return {r.case_id: r for r in run.per_case}


def diff_runs(before: EvalRun, after: EvalRun) -> RunDiff:
    """Compute the regression/improvement diff between two EvalRuns."""
    before_cases = _index_cases(before)
    after_cases = _index_cases(after)

    common = set(before_cases) & set(after_cases)
    missing = sorted(set(before_cases) - set(after_cases))
    new = sorted(set(after_cases) - set(before_cases))

    diff = RunDiff(
        before_id=before.run_id, after_id=after.run_id,
        overall_before=before.overall_score,
        overall_after=after.overall_score,
        missing_cases=missing, new_cases=new,
    )

    for case_id in sorted(common):
        b_fields = _index_fields(before_cases[case_id])
        a_fields = _index_fields(after_cases[case_id])
        for field_name in sorted(set(b_fields) | set(a_fields)):
            b = b_fields.get(field_name)
            a = a_fields.get(field_name)
            b_score = b.score if b else 0.0
            a_score = a.score if a else 0.0
            fd = FieldDiff(field=field_name, case_id=case_id,
                           before=b_score, after=a_score)
            if abs(fd.delta) < NOISE_THRESHOLD:
                diff.unchanged.append(fd)
            elif fd.delta < 0:
                diff.regressions.append(fd)
            else:
                diff.improvements.append(fd)

    # Sort by magnitude of regression (worst first) / improvement (best first)
    diff.regressions.sort(key=lambda d: d.delta)
    diff.improvements.sort(key=lambda d: -d.delta)
    return diff
