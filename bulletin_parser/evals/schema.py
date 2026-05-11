"""Schema for the eval system.

Layering, leaf-to-root:
  CheckResult     - one comparator's verdict
  FieldResult     - aggregated checks for one Bulletin field
  BulletinResult  - all field results for one eval case
  EvalRun         - all case results for one evaluation run

EvalCase carries source text + expected Bulletin. Flavor 'real' means
hand-curated from a production bulletin; 'synthetic' means we wrote both
the text and the expected output to exercise a specific edge case.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schema import Bulletin


class CheckResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    expected: Any | None = None
    actual: Any | None = None
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.score >= 0.99


class FieldResult(BaseModel):
    field: str
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0)
    checks: list[CheckResult] = Field(default_factory=list)
    missing_count: int = 0
    extra_count: int = 0


class BulletinResult(BaseModel):
    case_id: str
    overall_score: float = Field(ge=0.0, le=1.0)
    fields: list[FieldResult]
    parse_succeeded: bool = True
    parse_error: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class EvalRun(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime
    model: str
    parser_version: str
    prompt_hash: str | None = None
    overall_score: float
    per_case: list[BulletinResult]

    @property
    def case_count(self) -> int:
        return len(self.per_case)

    @property
    def cases_passed(self) -> int:
        return sum(1 for r in self.per_case if r.overall_score >= 0.95)


class EvalCase(BaseModel):
    id: str
    flavor: Literal["real", "synthetic"]
    description: str
    source_text: str
    expected: Bulletin
    notes: str = ""
