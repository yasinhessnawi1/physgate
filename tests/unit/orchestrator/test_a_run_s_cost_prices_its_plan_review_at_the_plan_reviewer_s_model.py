"""A run's cost prices its plan review at the plan reviewer's model, one line per round.

ARCH-150: the cost of every run. A run that reviews its plan spends reviewer tokens before any
subtask exists: the review's ``tokens_used`` lines are attributed to its session, and the
``design_review_ran`` line after them names that session, in its verdict or in why there is none.
The cost reader takes the model from that line, as it takes a subtask review's from its own, and
puts what each round's review spent under a label of its own, never under "(left over)".

The runs are made by the ``decompose`` command with the call and the plan's reviewer stood in for
(``replan_rig``): every call spends 10 input and 10 output tokens on the decomposition model
(claude-sonnet-5), every review 5 and 5 on the plan reviewer's (claude-opus-5-5). The operator
UI's cost route prices through the same reader and is held to it here too.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from replan_rig import DESIGN, Step, decompose
from ui_rig import context_over, fake_ui, serving

from physgate.evaluation.observe.cost import CostLine, load_price_sheet, price_events, price_run
from physgate.evaluation.observe.exceptions import ManifestError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.orchestrator.events import DesignReviewRan, Event, TokensUsed, read_events
from physgate.orchestrator.protocols import Usage

DATE = "2026-10-16"
DECOMPOSITION = "claude-sonnet-5"
LEFT_OVER = "(left over)"


def _ran(root: Path, design_review: str, steps: list[Step]) -> Path:
    ran = decompose(root, design_review, steps)
    assert ran.code == 0, ran.code
    return ran.run_dir


def _log(run_dir: Path) -> list[Event]:
    return list(read_events(run_dir / "events.jsonl"))


def _reviews(log: list[Event]) -> list[DesignReviewRan]:
    return [e for e in log if isinstance(e, DesignReviewRan)]


def _priced(how: Any) -> CostLine:  # noqa: ANN401 - the call that prices
    """The cost line ``how`` gives; a refusal fails the row on an assertion that names it."""
    line = outcome_of(how)
    if not isinstance(line, CostLine):
        pytest.fail(f"the run is not priced: {line!r}")
    return line


def _tokens(n_in: int, n_out: int) -> Usage:
    return Usage(
        input_tokens=n_in,
        output_tokens=n_out,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )


def _spent_by(log: list[Event], attribution: str) -> list[TokensUsed]:
    return [e for e in log if isinstance(e, TokensUsed) and e.attribution == attribution]


def test_one_passing_plan_review_is_priced_at_the_model_its_verdict_names(tmp_path: Path) -> None:
    run_dir = _ran(tmp_path, "on", [Step(review="pass")])
    log = _log(run_dir)
    [review] = _reviews(log)
    assert review.result is not None and review.result.verdict == "pass"
    # The review's own tokens line, before its verdict, names the session the verdict names.
    assert _spent_by(log, f"reviewer:{review.result.session_id}"), [e.kind for e in log]
    line = _priced(lambda: price_run(run_dir, load_price_sheet(DATE)))
    rows = {r.model: r.tokens for r in line.rows}
    assert rows == {DECOMPOSITION: _tokens(10, 10), DESIGN: _tokens(5, 5)}
    assert line.review_tokens == {"(plan review, round 1)": _tokens(5, 5)}
    assert LEFT_OVER not in line.review_tokens
    # 10 x 3 + 10 x 15 on the decomposition's model, 5 x 5 + 5 x 25 on the reviewer's, a million.
    by_model = {r.model: r.usd for r in line.rows}
    sheet = load_price_sheet(DATE).sheet.usd_per_mtok
    for model, tokens in rows.items():
        price = sheet[model]
        wanted = (tokens.input_tokens * price.input + tokens.output_tokens * price.output) / 10**6
        assert by_model[model] == wanted, model
    assert line.usd == sum(by_model.values(), Decimal(0))


def test_the_model_a_plan_review_reported_is_the_one_priced(tmp_path: Path) -> None:
    """Not the run's pinned reviewer: the verdict's own model, as a subtask review's is."""
    run_dir = _ran(tmp_path, "on", [Step(review="pass")])
    log = _log(run_dir)
    at = next(i for i, e in enumerate(log) if isinstance(e, DesignReviewRan))
    review = log[at]
    assert isinstance(review, DesignReviewRan) and review.result is not None
    reported = review.result.model_copy(update={"reviewer_model": "claude-haiku-4-5-20251001"})
    log[at] = review.model_copy(update={"result": reported})
    manifest = read_manifest(run_dir)
    line = _priced(
        lambda: price_events(manifest.config, manifest.manifest_id, log, load_price_sheet(DATE))
    )
    rows = {r.model: r.tokens for r in line.rows}
    assert rows == {DECOMPOSITION: _tokens(10, 10), "claude-haiku-4-5-20251001": _tokens(5, 5)}


def test_a_plan_review_with_no_verdict_is_priced_at_the_model_it_names(tmp_path: Path) -> None:
    run_dir = _ran(tmp_path, "on", [Step(review="no_verdict")])
    log = _log(run_dir)
    [review] = _reviews(log)
    assert review.unavailable is not None and review.result is None
    assert review.unavailable.session_id is not None
    assert review.unavailable.reviewer_model == DESIGN
    assert _spent_by(log, f"reviewer:{review.unavailable.session_id}")
    line = _priced(lambda: price_run(run_dir, load_price_sheet(DATE)))
    rows = {r.model: r.tokens for r in line.rows}
    assert rows == {DECOMPOSITION: _tokens(10, 10), DESIGN: _tokens(5, 5)}
    assert line.review_tokens == {"(plan review, round 1)": _tokens(5, 5)}


def _model_unnamed(run_dir: Path) -> list[Event]:
    """The run's log with its plan review's unavailable line naming no model."""
    log = _log(run_dir)
    at = next(i for i, e in enumerate(log) if isinstance(e, DesignReviewRan))
    review = log[at]
    assert isinstance(review, DesignReviewRan) and review.unavailable is not None
    unnamed = review.unavailable.model_copy(update={"reviewer_model": None})
    log[at] = review.model_copy(update={"unavailable": unnamed})
    return log


def test_a_plan_review_naming_no_model_is_priced_at_the_one_pinned_reviewer_model(
    tmp_path: Path,
) -> None:
    run_dir = _ran(tmp_path, "on", [Step(review="no_verdict")])
    log = _model_unnamed(run_dir)
    manifest = read_manifest(run_dir)
    assert set(manifest.config.models.reviewers.values()) == {DESIGN}
    line = _priced(
        lambda: price_events(manifest.config, manifest.manifest_id, log, load_price_sheet(DATE))
    )
    assert {r.model: r.tokens for r in line.rows}[DESIGN] == _tokens(5, 5)
    assert line.review_tokens == {"(plan review, round 1)": _tokens(5, 5)}


def test_a_plan_review_naming_no_model_among_reviewers_that_differ_is_refused(
    tmp_path: Path,
) -> None:
    run_dir = _ran(tmp_path, "on", [Step(review="no_verdict")])
    log = _model_unnamed(run_dir)
    manifest = read_manifest(run_dir)
    models = manifest.config.models.model_copy(
        update={"reviewers": {**manifest.config.models.reviewers, "electrical": DECOMPOSITION}}
    )
    config = manifest.config.model_copy(update={"models": models})
    with pytest.raises(ManifestError, match="which model the plan's review ran on"):
        price_events(config, manifest.manifest_id, log, load_price_sheet(DATE))


def test_each_round_s_plan_review_has_its_own_line(tmp_path: Path) -> None:
    run_dir = _ran(tmp_path, "repair:1", [Step(), Step()])
    log = _log(run_dir)
    reviews = _reviews(log)
    assert [r.round for r in reviews] == [1, 2]
    sessions = [r.result.session_id for r in reviews if r.result is not None]
    assert len(set(sessions)) == 2
    for session in sessions:
        assert _spent_by(log, f"reviewer:{session}")
    line = _priced(lambda: price_run(run_dir, load_price_sheet(DATE)))
    rows = {r.model: r.tokens for r in line.rows}
    assert rows == {DECOMPOSITION: _tokens(20, 20), DESIGN: _tokens(10, 10)}
    assert line.review_tokens == {
        "(plan review, round 1)": _tokens(5, 5),
        "(plan review, round 2)": _tokens(5, 5),
    }


def test_the_operator_ui_prices_a_plan_review_as_the_reader_does(tmp_path: Path) -> None:
    run_dir = _ran(tmp_path / "runs", "repair:1", [Step(), Step(review="pass")])
    ui = fake_ui(tmp_path / "checkout")
    with serving(context_over(tmp_path / "runs", ui_root=ui)) as live:
        status, _, body = live.request("GET", f"/api/runs/0/{run_dir.name}/cost/{DATE}")
    assert status == 200, body[:400]
    served = json.loads(body)
    assert served["review_tokens"] == {
        "(plan review, round 1)": _tokens(5, 5).model_dump(),
        "(plan review, round 2)": _tokens(5, 5).model_dump(),
    }
    rows = {r["model"]: r["tokens"] for r in served["rows"]}
    assert rows[DESIGN] == _tokens(10, 10).model_dump()
