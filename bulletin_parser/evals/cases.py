"""The eval set.

To start, this contains the St Patricks real-bulletin case with the hand-built
reference Bulletin as expected output. Grow this set over time by adding new
case functions and listing them in all_cases().
"""
from __future__ import annotations
import sys
from pathlib import Path
from .schema import EvalCase

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "tests"))
from test_schema import build_stpatricks_reference  # noqa: E402
_FIXTURES_DIR = _PROJECT_ROOT / "fixtures"


def stpatricks_real():
    text = (_FIXTURES_DIR / "stpatricks_20260510.txt").read_text(encoding="utf-8")
    return EvalCase(
        id="stpatricks_20260510",
        flavor="real",
        description="St Patricks Old Cathedral NYC, Sixth Sunday of Easter 2026.",
        source_text=text,
        expected=build_stpatricks_reference(),
        notes="Two locations, four spoken languages, temporary-until-Pentecost exception.",
    )


def all_cases():
    return [stpatricks_real()]
