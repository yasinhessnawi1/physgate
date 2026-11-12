"""The pinned binary's own endings, as captured from it, are charged to the designer or reviewer.

Two endings a designer causes reach the plan call under names that every other session reads as
the instrument's: a plan cut at the output cap (the binary retries, then ends ``api_error`` with
the result's ``api_error: max_output_tokens``), and a prompt that outgrew the window, stopped by
the binary's own check before any request (``blocking_limit``; the binary groups
``rapid_refill_breaker`` and ``prompt_too_long`` with it as context limits). Both are the plan's
no-plan outcome. On the review's side the same endings are the review's own (no verdict, the
context exceeded), as is a verdict the binary could not parse, and so hold the run rather than
void it.

The streams are 2.1.301's against the scripted endpoint (31.10.2026), with the run directory's
prefix replaced. A refusal answered by a fallback model is the plan's refusal, not a model
mismatch; the run-level voids have names; and the start check's refusals name what was refused,
the plan's own content first where both the plan and the library are at fault.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator import exceptions
from physgate.orchestrator.exceptions import GitError
from physgate.reviewers.claude import unavailable_end

RECORDED = Path(__file__).parent / "recorded"
CAPPED = RECORDED / "plan_call_at_the_output_cap_2.1.301.stdout.jsonl"
OUTGROWN = RECORDED / "plan_call_whose_prompt_outgrew_the_window_2.1.301.stdout.jsonl"
MODEL = "claude-sonnet-5"


def _endings() -> Any:  # noqa: ANN401 - the module
    return importlib.import_module("physgate.orchestrator.endings")


def _judged(stdout: str) -> tuple[str | None, str]:
    result, _usage, answered = decompose.read_stream(stdout)
    cause, detail, *_ = decompose.judge(
        result,
        exit_code=1,
        timed_out=False,
        model=MODEL,
        roles=("electrical",),
        answered=answered,
        brief="Build a robot.\n",
        refused=decompose.schema_refusal(stdout),
        declined=decompose.model_declined(stdout),
    )
    return cause, detail


def _result(stdout: str) -> dict[str, Any]:
    result, *_ = decompose.read_stream(stdout)
    assert result is not None
    return result


def test_the_captured_streams_are_the_endings_they_are_named_for() -> None:
    capped = _result(CAPPED.read_text())
    assert (capped["terminal_reason"], capped.get("api_error")) == (
        "api_error",
        "max_output_tokens",
    )
    outgrown = _result(OUTGROWN.read_text())
    assert (outgrown["terminal_reason"], outgrown["result"]) == (
        "blocking_limit",
        "Prompt is too long",
    )


def test_a_plan_cut_at_the_output_cap_is_the_designer_s_no_plan() -> None:
    cause, detail = _judged(CAPPED.read_text())
    assert cause == "no_structured_output", (cause, detail)
    assert "output" in detail
    assert _endings().plan_class(cause, budget_set=False) == "no_plan"


@pytest.mark.parametrize("reason", ["blocking_limit", "rapid_refill_breaker"])
def test_a_prompt_that_outgrew_the_window_is_the_designer_s_no_plan(reason: str) -> None:
    text = OUTGROWN.read_text().replace('"blocking_limit"', json.dumps(reason))
    cause, _ = _judged(text)
    assert cause == "context_exceeded", cause
    assert _endings().plan_class(cause, budget_set=False) == "no_plan"


def test_a_refusal_answered_by_a_fallback_model_is_the_plan_s_refusal() -> None:
    result = {"type": "result", "is_error": True, "terminal_reason": "api_error"}
    cause, *_ = decompose.judge(
        {**result, "stop_reason": "refusal", "num_turns": 1},
        exit_code=1,
        timed_out=False,
        model=MODEL,
        roles=("electrical",),
        answered=frozenset({"claude-opus-5-5"}),
        brief="Build a robot.\n",
    )
    assert cause == "refused"


@pytest.mark.parametrize(
    ("stream", "reason", "cause"),
    [
        (CAPPED, None, "no_verdict"),
        (OUTGROWN, None, "context_exceeded"),
        (OUTGROWN, "rapid_refill_breaker", "context_exceeded"),
        (OUTGROWN, "malformed_tool_use_exhausted", "invalid_verdict"),
    ],
    ids=["output-cap", "blocking-limit", "rapid-refill", "malformed-tool-use"],
)
def test_the_same_endings_of_a_review_are_the_review_s_own_and_hold(
    stream: Path, reason: str | None, cause: str
) -> None:
    text = stream.read_text()
    if reason is not None:
        text = text.replace('"blocking_limit"', json.dumps(reason))
    found = unavailable_end(text, _result(text), exit_code=1, timed_out=False)
    assert found is not None and found[0] == cause, found
    assert _endings().review_class(found[0]) == "unavailable"


def test_the_run_level_voids_are_named() -> None:
    named = getattr(_endings(), "RUN_VOIDS", None)
    assert named == frozenset(
        {"accounting_mismatch", "killed", "plan_digest_mismatch", "record_missing"}
    ), named


def _startable(monkeypatch: pytest.MonkeyPatch, *, node: str, library: Exception | None) -> Any:  # noqa: ANN401
    stand_ins: dict[str, Any] = {
        "_planned_subtasks": [],
        "_contract_pairs": None,
        "_brief_words": (),
        "read_library": {},
        "series_library": {},
    }
    for name, value in stand_ins.items():
        monkeypatch.setattr(decompose, name, lambda *_, value=value, **__: value)

    def fits(*_: Any, **__: Any) -> None:  # noqa: ANN401
        if library is not None:
            raise library

    monkeypatch.setattr(decompose, "_require_library_fits", fits)

    class Node:
        id = node

    class Planned:
        interface_nodes = (Node(),)

    config = type("C", (), {"target_head": "h"})()
    return outcome_of(
        lambda: decompose.require_startable(
            Planned(),  # type: ignore[arg-type]
            config=config,
            target_repo=Path("/nowhere"),
            library=None,
            brief="b",
        )
    )


def test_a_git_failure_in_the_library_check_is_the_library_s_refusal_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found = _startable(
        monkeypatch, node="iface.bus", library=GitError("git cannot read the target's commit")
    )
    assert isinstance(found, exceptions.LibraryRefusedError), found
    assert found.cause == "library_refused"


def test_with_the_plan_and_the_library_both_at_fault_the_plan_s_content_is_refused_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = exceptions.DecompositionError("the target holds other bytes where the library goes")
    found = _startable(monkeypatch, node="../escape", library=library)
    assert isinstance(found, exceptions.PlanRefusedError), found
    # Each fault alone is refused as itself: the order, not one guard, decides.
    alone = _startable(monkeypatch, node="iface.bus", library=library)
    assert isinstance(alone, exceptions.LibraryRefusedError), alone
