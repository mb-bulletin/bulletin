"""Runner: execute eval cases against the parser and produce an EvalRun."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Callable

from ..parser import DEFAULT_MODEL, SYSTEM_PROMPT, parse_bulletin
from ..schema import Bulletin
from .cases import all_cases
from .metrics import evaluate_bulletin, parse_failure_result
from .schema import BulletinResult, EvalCase, EvalRun


log = logging.getLogger(__name__)


def _prompt_hash() -> str:
    """Hash of the parser SYSTEM_PROMPT, so we can track which version of
    the prompt produced a given EvalRun."""
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def run_evals(
    *,
    model: str = DEFAULT_MODEL,
    cases: list[EvalCase] | None = None,
    parse_fn: Callable[[str], Bulletin] | None = None,
    run_id: str | None = None,
) -> EvalRun:
    """Run the parser against every eval case and return an EvalRun.

    `parse_fn` is injectable so tests can swap in a fake parser (the real
    parser calls the Anthropic API and costs money).
    """
    cases = cases or all_cases()
    parse = parse_fn or (lambda text: parse_bulletin(text, model=model))

    started = datetime.now(timezone.utc)
    per_case: list[BulletinResult] = []

    for case in cases:
        log.info("Running eval case: %s", case.id)
        try:
            actual = parse(case.source_text)
            result = evaluate_bulletin(case.id, case.expected, actual)
        except Exception as e:
            log.exception("parse failed for case %s", case.id)
            result = parse_failure_result(case.id, f"{type(e).__name__}: {e}")
        per_case.append(result)

    finished = datetime.now(timezone.utc)

    overall = sum(r.overall_score for r in per_case) / len(per_case) if per_case else 0.0

    parser_version = (per_case[0].fields and "1.0.0") if per_case else "1.0.0"
    # We dont need the actual parser_version from the Bulletin object;
    # what matters is the prompt_hash, which tracks prompt changes.

    return EvalRun(
        run_id=run_id or started.strftime("%Y%m%dT%H%M%SZ"),
        started_at=started,
        finished_at=finished,
        model=model,
        parser_version=parser_version,
        prompt_hash=_prompt_hash(),
        overall_score=overall,
        per_case=per_case,
    )


def save_run(run: EvalRun, path: str) -> None:
    with open(path, "w") as f:
        f.write(run.model_dump_json(indent=2))


def load_run(path: str) -> EvalRun:
    with open(path) as f:
        return EvalRun.model_validate_json(f.read())
