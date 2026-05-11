"""Render EvalRuns and RunDiffs as readable markdown.

The point of the eval system is that you actually look at the output
when iterating on the prompt. JSON is for storage; markdown is for
reading.
"""
from __future__ import annotations

from io import StringIO

from .diff import RunDiff
from .schema import BulletinResult, EvalRun, FieldResult


def _fmt_score(s: float) -> str:
    return f"{s:.2%}"


def render_run(run: EvalRun) -> str:
    """Render a single EvalRun as markdown."""
    buf = StringIO()
    print(f"# Eval Run: `{run.run_id}`\n", file=buf)
    print(f"- **model**: `{run.model}`", file=buf)
    print(f"- **parser_version**: `{run.parser_version}`", file=buf)
    print(f"- **prompt_hash**: `{run.prompt_hash}`", file=buf)
    print(f"- **started**: {run.started_at.isoformat()}", file=buf)
    print(f"- **finished**: {run.finished_at.isoformat()}", file=buf)
    print(f"- **overall**: **{_fmt_score(run.overall_score)}** "
          f"({run.cases_passed}/{run.case_count} cases passed)\n", file=buf)

    for case in run.per_case:
        print(f"## Case: `{case.case_id}` — {_fmt_score(case.overall_score)}\n", file=buf)
        if not case.parse_succeeded:
            print(f"**Parse failed**: `{case.parse_error}`\n", file=buf)
            continue
        print("| Field | Score | Weight | Missing | Extra |", file=buf)
        print("|---|---:|---:|---:|---:|", file=buf)
        for f in case.fields:
            print(f"| `{f.field}` | {_fmt_score(f.score)} | {f.weight:.0f} | "
                  f"{f.missing_count} | {f.extra_count} |", file=buf)
        failed_checks = []
        for f in case.fields:
            for c in f.checks:
                if c.score < 0.95:
                    failed_checks.append((f.field, c))
        if failed_checks:
            print(f"\n### Failed checks ({len(failed_checks)}):\n", file=buf)
            for field_name, check in failed_checks[:20]:
                print(f"- `{field_name}`: {check.note}", file=buf)
            if len(failed_checks) > 20:
                print(f"- ...and {len(failed_checks) - 20} more", file=buf)
        print("", file=buf)
    return buf.getvalue()


def render_diff(diff: RunDiff) -> str:
    """Render a RunDiff as markdown."""
    buf = StringIO()
    delta = diff.overall_delta
    arrow = "[REGRESSION]" if delta < 0 else "[IMPROVEMENT]" if delta > 0 else "[NO CHANGE]"
    print(f"# Eval Diff: `{diff.before_id}` -> `{diff.after_id}`\n", file=buf)
    print(f"**Overall**: {_fmt_score(diff.overall_before)} -> "
          f"{_fmt_score(diff.overall_after)}  ({delta:+.2%}) {arrow}\n", file=buf)
    if diff.missing_cases:
        print(f"## Missing cases ({len(diff.missing_cases)})", file=buf)
        for c in diff.missing_cases:
            print(f"- `{c}`", file=buf)
        print("", file=buf)
    if diff.new_cases:
        print(f"## New cases ({len(diff.new_cases)})", file=buf)
        for c in diff.new_cases:
            print(f"- `{c}`", file=buf)
        print("", file=buf)
    if diff.regressions:
        print(f"## Regressions ({len(diff.regressions)})\n", file=buf)
        print("| Case | Field | Before | After | Delta |", file=buf)
        print("|---|---|---:|---:|---:|", file=buf)
        for d in diff.regressions:
            print(f"| `{d.case_id}` | `{d.field}` | {_fmt_score(d.before)} | "
                  f"{_fmt_score(d.after)} | **{d.delta:+.2%}** |", file=buf)
        print("", file=buf)
    if diff.improvements:
        print(f"## Improvements ({len(diff.improvements)})\n", file=buf)
        print("| Case | Field | Before | After | Delta |", file=buf)
        print("|---|---|---:|---:|---:|", file=buf)
        for d in diff.improvements:
            print(f"| `{d.case_id}` | `{d.field}` | {_fmt_score(d.before)} | "
                  f"{_fmt_score(d.after)} | {d.delta:+.2%} |", file=buf)
        print("", file=buf)
    if not diff.regressions and not diff.improvements:
        print("No field-level changes above the noise threshold.\n", file=buf)
    return buf.getvalue()
