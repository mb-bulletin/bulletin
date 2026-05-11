"""Tests for the eval system - no API key, no network.

Covers:
  - check primitives (exact, fuzzy_text, near_priority, near_number)
  - list matching with missing/extra detection
  - field-level comparators on real Bulletin objects
  - end-to-end run with an injectable fake parse_fn
  - diff between two runs surfaces regressions vs improvements
  - markdown rendering produces non-empty, readable output
"""
from __future__ import annotations

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bulletin_parser.evals.checks import (
    compare_announcements,
    compare_mass_intentions,
    compare_recurring_schedule,
    exact,
    fuzzy_text,
    match_lists_by_key,
    near_priority,
    normalize_name,
    text_similarity,
)
from bulletin_parser.evals.diff import diff_runs
from bulletin_parser.evals.metrics import evaluate_bulletin, parse_failure_result
from bulletin_parser.evals.report import render_diff, render_run
from bulletin_parser.evals.runner import run_evals
from bulletin_parser.evals.schema import EvalCase, EvalRun
from bulletin_parser.schema import (
    Announcement,
    AnnouncementCategory,
    Language,
    MassIntention,
    ServiceKind,
    Weekday,
)
from test_schema import build_stpatricks_reference


# ---- normalize / similarity ----

def test_normalize_name_handles_honorifics():
    assert normalize_name("Saint John") == normalize_name("St. John")
    assert normalize_name("Father Smith") == normalize_name("Fr. Smith")


def test_text_similarity_paraphrase_friendly():
    # Paraphrased announcement bodies should still score high
    a = "Reception at 6pm, screening at 7pm. All welcome."
    b = "Reception at 6:00 PM and the screening begins at 7:00 PM. All are welcome!"
    assert text_similarity(a, b) > 0.6


def test_text_similarity_empty_both_full_credit():
    assert text_similarity(None, None) == 1.0
    assert text_similarity("", "") == 1.0


# ---- primitive comparators ----

def test_exact_pass():
    r = exact(5, 5)
    assert r.score == 1.0


def test_exact_fail():
    r = exact(5, 6)
    assert r.score == 0.0
    assert "5" in r.note and "6" in r.note


def test_fuzzy_text_above_threshold():
    r = fuzzy_text("St. John the Evangelist", "Saint John the Evangelist", threshold=0.85)
    assert r.score == 1.0


def test_fuzzy_text_below_threshold_zero():
    r = fuzzy_text("Hello world", "Goodbye moon", threshold=0.85)
    assert r.score == 0.0


def test_near_priority_within_1_full_credit():
    assert near_priority(3, 4).score == 1.0
    assert near_priority(3, 2).score == 1.0
    assert near_priority(3, 3).score == 1.0


def test_near_priority_off_by_2_partial():
    assert near_priority(3, 5).score == 0.5


def test_near_priority_far_off_zero():
    assert near_priority(2, 9).score == 0.0


# ---- list matching ----

def test_match_lists_detects_missing_and_extra():
    expected = [{"k": 1, "v": "a"}, {"k": 2, "v": "b"}, {"k": 3, "v": "c"}]
    actual = [{"k": 1, "v": "a"}, {"k": 2, "v": "b"}, {"k": 4, "v": "d"}]

    def key(x): return x["k"]
    def cmp(e, a): return [exact(e["v"], a["v"])]

    checks, missing, extra = match_lists_by_key(expected, actual, key, cmp)
    assert missing == 1  # k=3 expected but not present
    assert extra == 1    # k=4 present but not expected
    # 2 matched items each produce 1 check; plus 1 missing + 1 extra
    assert len(checks) == 4


# ---- field comparators on real Bulletin objects ----

def test_identical_bulletins_score_perfect():
    b = build_stpatricks_reference()
    result = evaluate_bulletin("self", b, b)
    assert result.overall_score >= 0.99
    for field in result.fields:
        assert field.score >= 0.99, f"{field.field}: {field.score}"


def test_missing_recurring_slot_drops_score():
    b = build_stpatricks_reference()
    # Drop one Mass time
    actual = b.model_copy(update={
        "recurring_schedule": [s for s in b.recurring_schedule
                               if not (s.weekday.value == "sunday"
                                       and str(s.start_time) == "10:30:00")]
    })
    checks, missing, extra = compare_recurring_schedule(b, actual)
    assert missing == 1
    assert extra == 0


def test_wrong_language_surfaces_as_check_failure():
    """Mislabeling Spanish as English should appear as a failed check,
    not as a missing+extra pair (the slot is still the right slot)."""
    b = build_stpatricks_reference()
    actual = b.model_copy(update={
        "recurring_schedule": [
            s.model_copy(update={"language": Language.english})
            if s.language == Language.spanish else s
            for s in b.recurring_schedule
        ]
    })
    checks, missing, extra = compare_recurring_schedule(b, actual)
    assert missing == 0
    assert extra == 0
    failed_language_checks = [c for c in checks if c.score < 1.0]
    assert len(failed_language_checks) >= 1


def test_announcement_priority_off_by_one_full_credit():
    b = build_stpatricks_reference()
    actual = b.model_copy(update={
        "announcements": [
            a.model_copy(update={"priority": min(10, a.priority + 1)})
            for a in b.announcements
        ]
    })
    checks, missing, extra = compare_announcements(b, actual)
    priority_checks = [c for c in checks if "off by" in c.note]
    assert priority_checks == [], "off-by-one priority should not flag"


# ---- end-to-end runner ----

def test_run_evals_with_perfect_parser():
    """Fake parse_fn that returns the expected Bulletin -> perfect run."""
    cases = [
        EvalCase(
            id="self_test",
            flavor="synthetic",
            description="self-comparison",
            source_text="dummy",
            expected=build_stpatricks_reference(),
        )
    ]
    run = run_evals(
        cases=cases,
        parse_fn=lambda text: build_stpatricks_reference(),
        run_id="test_perfect",
    )
    assert run.overall_score >= 0.99
    assert run.cases_passed == 1


def test_run_evals_with_failing_parser():
    """A parse_fn that raises should produce a parse_failure_result."""
    cases = [
        EvalCase(
            id="failing",
            flavor="synthetic",
            description="parser raises",
            source_text="x",
            expected=build_stpatricks_reference(),
        )
    ]

    def bad_parse(text):
        raise ValueError("synthetic failure")

    run = run_evals(cases=cases, parse_fn=bad_parse, run_id="test_fail")
    assert run.overall_score == 0.0
    assert run.per_case[0].parse_succeeded is False
    assert "synthetic failure" in run.per_case[0].parse_error


def test_run_evals_partial_success():
    """Parser drops one Mass intention -> score < 1 but > 0."""
    cases = [
        EvalCase(
            id="partial",
            flavor="synthetic",
            description="drops one intention",
            source_text="x",
            expected=build_stpatricks_reference(),
        )
    ]

    def partial_parse(text):
        b = build_stpatricks_reference()
        return b.model_copy(update={"mass_intentions": b.mass_intentions[1:]})

    run = run_evals(cases=cases, parse_fn=partial_parse, run_id="test_partial")
    assert 0.5 < run.overall_score < 1.0
    intention_field = next(f for f in run.per_case[0].fields
                           if f.field == "mass_intentions")
    assert intention_field.missing_count == 1


# ---- diff ----

def test_diff_detects_regression_and_improvement():
    case_id = "test"
    expected = build_stpatricks_reference()

    def make_run(run_id, actual_factory):
        return run_evals(
            cases=[EvalCase(id=case_id, flavor="synthetic",
                            description="d", source_text="x", expected=expected)],
            parse_fn=lambda t: actual_factory(),
            run_id=run_id,
        )

    perfect_run = make_run("v1", lambda: expected)
    # v2 drops a mass intention -> regression on mass_intentions
    def degraded():
        return expected.model_copy(update={
            "mass_intentions": expected.mass_intentions[1:]
        })
    degraded_run = make_run("v2", degraded)

    diff = diff_runs(perfect_run, degraded_run)
    assert diff.overall_delta < 0
    regression_fields = {d.field for d in diff.regressions}
    assert "mass_intentions" in regression_fields


def test_diff_renders_to_markdown():
    expected = build_stpatricks_reference()
    cases = [EvalCase(id="t", flavor="synthetic",
                      description="d", source_text="x", expected=expected)]
    run_a = run_evals(cases=cases, parse_fn=lambda t: expected, run_id="a")
    run_b = run_evals(cases=cases, parse_fn=lambda t: expected, run_id="b")
    diff = diff_runs(run_a, run_b)
    md = render_diff(diff)
    assert "Eval Diff" in md
    assert "a" in md and "b" in md


# ---- report rendering ----

def test_render_run_produces_markdown():
    cases = [EvalCase(id="t", flavor="synthetic", description="d",
                      source_text="x", expected=build_stpatricks_reference())]
    run = run_evals(cases=cases,
                    parse_fn=lambda t: build_stpatricks_reference(), run_id="r")
    md = render_run(run)
    assert "Eval Run" in md
    assert "100.00%" in md  # perfect score


def test_render_run_shows_failed_checks():
    expected = build_stpatricks_reference()
    bad = expected.model_copy(update={
        "mass_intentions": expected.mass_intentions[2:]
    })
    cases = [EvalCase(id="t", flavor="synthetic", description="d",
                      source_text="x", expected=expected)]
    run = run_evals(cases=cases, parse_fn=lambda t: bad, run_id="r")
    md = render_run(run)
    assert "Failed checks" in md
    assert "missing item" in md


if __name__ == "__main__":
    import traceback
    failed = 0
    tests = sorted(n for n in dir(sys.modules[__name__]) if n.startswith("test_"))
    for name in tests:
        fn = globals()[name]
        try:
            fn()
            print(f"  + {name}")
        except Exception as e:
            failed += 1
            print(f"  - {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
    if failed:
        print(f"\n{failed} test(s) failed")
        sys.exit(1)
    print("\nAll eval tests passed.")
