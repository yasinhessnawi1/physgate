"""Every way a design round can end is named, and classified in code into one class.

A round's plan call and its start check end in a plan, in a plan's no-plan outcome with its cause
(the designer's), or in infrastructure (the instrument's). A round's review, recorded apart from
its plan, ends in a verdict, in no verdict with its cause (the review's outcome), in
infrastructure, or in a held-out exposure. Every terminal reason the pinned binary (2.1.301) can
end the plan call with maps to a named cause, so no designer failure falls into a catch-all an
experiment would class as infrastructure. A start check refused on the plan's own content is the
plan's outcome; one refused on the library or the target repository is infrastructure.
"""

from __future__ import annotations

import importlib
import typing
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of

import physgate.orchestrator.decompose as decompose
from physgate.knowledge.library import LibraryError
from physgate.orchestrator import exceptions
from physgate.orchestrator.exceptions import DecompositionError

ROLES = ("electrical",)
MODEL = "claude-sonnet-5"

#: Every terminal reason 2.1.301 can end a session with, read from the binary on 31.10.2026
#: (`strings` over ~/pinned/claude-2.1.301-macos: its two lists of terminal reasons), with the
#: cause the plan call names for it. ``completed`` is judged on the answer, below.
TERMINAL: dict[str, str] = {
    "blocking_limit": "context_exceeded",
    "rapid_refill_breaker": "context_exceeded",
    "prompt_too_long": "context_exceeded",
    "image_error": "harness_stopped",
    "model_error": "api_error",
    "api_error": "api_error",
    "malformed_tool_use_exhausted": "malformed_output",
    "aborted_streaming": "harness_stopped",
    "aborted_tools": "harness_stopped",
    "stop_hook_prevented": "harness_stopped",
    "hook_stopped": "harness_stopped",
    "tool_deferred": "harness_stopped",
    "max_turns": "turn_limit",
    "background_requested": "harness_stopped",
    "budget_exhausted": "budget_exhausted",
    "structured_output_retry_exhausted": "schema_refused",
    "tool_deferred_unavailable": "harness_stopped",
    "turn_setup_failed": "harness_stopped",
}

#: The plan's side of the table: each cause a round's plan call or start check ends with.
PLAN_TABLE: dict[str, str] = {
    "no_structured_output": "no_plan",
    "invalid_plan": "no_plan",
    "schema_refused": "no_plan",
    "wall_clock": "no_plan",
    "turn_limit": "no_plan",
    "malformed_output": "no_plan",
    "context_exceeded": "no_plan",
    "refused": "no_plan",
    "plan_refused": "no_plan",
    "model_mismatch": "infrastructure",
    "api_error": "infrastructure",
    "credential_refused": "infrastructure",
    "sandbox_unavailable": "infrastructure",
    "managed_settings_changed": "infrastructure",
    "no_result": "infrastructure",
    "unexpected_exit": "infrastructure",
    "usage_limit": "infrastructure",
    "harness_stopped": "infrastructure",
    "library_refused": "infrastructure",
}

#: The review's side: a verdict, the review's own outcome, infrastructure, or an exposure.
REVIEW_TABLE: dict[str, str] = {
    "pass": "verdict",
    "fail": "verdict",
    "blocked": "verdict",
    "refused": "unavailable",
    "no_verdict": "unavailable",
    "invalid_verdict": "unavailable",
    "reading_incomplete": "unavailable",
    "compacted": "unavailable",
    "context_exceeded": "unavailable",
    "infrastructure": "infrastructure",
    "unprepared": "infrastructure",
    "invocation_error": "infrastructure",
    "model_separation": "infrastructure",
    "held_out_exposed": "exposure",
}


def _values(alias: Any) -> set[str]:  # noqa: ANN401 - a Literal, or a union of them
    """Every value a Literal, or a union of Literals, admits."""
    found: set[str] = set()
    for arg in typing.get_args(alias):
        found |= _values(arg) if typing.get_args(arg) else {arg}
    return found


def _endings() -> Any:  # noqa: ANN401 - the module, or None in a tree without it
    try:
        return importlib.import_module("physgate.orchestrator.endings")
    except ModuleNotFoundError:
        return None


def _judged(result: dict[str, Any] | None, **kw: Any) -> str | None:  # noqa: ANN401
    cause, *_ = decompose.judge(
        result,
        exit_code=kw.pop("exit_code", 1),
        timed_out=kw.pop("timed_out", False),
        model=MODEL,
        roles=ROLES,
        answered=frozenset({MODEL}),
        brief="Build a robot.\n",
        **kw,
    )
    return cause


@pytest.mark.parametrize(("reason", "cause"), sorted(TERMINAL.items()))
def test_every_terminal_reason_of_the_plan_call_is_a_named_cause(reason: str, cause: str) -> None:
    result = {"type": "result", "is_error": True, "terminal_reason": reason, "num_turns": 1}
    assert _judged(result) == cause


def test_the_table_of_terminal_reasons_is_the_pinned_binary_s_whole_list() -> None:
    # The binary's lists, as read on 31.10.2026, completed among them: nothing left out.
    assert sorted([*TERMINAL, "completed"]) == sorted(
        [
            *("blocking_limit", "rapid_refill_breaker", "prompt_too_long", "image_error"),
            *("model_error", "api_error", "malformed_tool_use_exhausted", "aborted_streaming"),
            *("aborted_tools", "stop_hook_prevented", "hook_stopped", "tool_deferred"),
            *("max_turns", "background_requested", "completed", "budget_exhausted"),
            *("structured_output_retry_exhausted", "tool_deferred_unavailable"),
            "turn_setup_failed",
        ]
    )
    mapped = getattr(decompose, "TERMINAL_CAUSES", None)
    assert mapped is not None, "the plan call names no cause per terminal reason"
    assert {r: c for r, c in mapped.items()} == {
        r: c for r, c in TERMINAL.items() if r not in ("max_turns", "api_error")
    }


def test_a_reason_the_binary_does_not_list_is_an_unexpected_exit() -> None:
    result = {"type": "result", "is_error": True, "terminal_reason": "a_new_reason"}
    assert _judged(result) == "unexpected_exit"


def test_a_model_that_declines_to_plan_is_the_plan_s_refusal() -> None:
    result = {
        "type": "result",
        "is_error": False,
        "terminal_reason": "completed",
        "stop_reason": "refusal",
        "num_turns": 1,
    }
    assert _judged(result, exit_code=0) == "refused"
    declined = getattr(decompose, "model_declined", None)
    assert declined is not None, "the plan call reads no model refusal from its stream"
    stream = '{"type":"system","subtype":"model_refusal_notice"}\n{"type":"result"}\n'
    assert declined(stream) is True
    assert declined('{"type":"system","subtype":"init"}\n') is False
    quiet = {**result, "stop_reason": "end_turn"}
    assert _judged(quiet, exit_code=0, declined=True) == "refused"
    assert _judged(quiet, exit_code=0) == "no_structured_output"


def test_the_plan_call_s_wall_clock_is_the_designer_s_no_plan() -> None:
    assert _judged(None, timed_out=True, exit_code=None) == "wall_clock"
    endings = _endings()
    assert endings is not None, "no ending is classified"
    assert endings.plan_class("wall_clock", budget_set=False) == "no_plan"


def test_every_ending_is_classified_as_the_table_says() -> None:
    endings = _endings()
    assert endings is not None, "no ending is classified"
    assert _values(endings.PlanCause) == set(PLAN_TABLE) | {"budget_exhausted"}
    assert _values(endings.ReviewCause) == set(REVIEW_TABLE)
    for cause, kind in PLAN_TABLE.items():
        for budget_set in (False, True):
            assert endings.plan_class(cause, budget_set=budget_set) == kind, cause
    for cause, kind in REVIEW_TABLE.items():
        assert endings.review_class(cause) == kind, cause
    assert endings.plan_class(None, budget_set=False) == "plan"
    # Every cause the plan call names is classified: none falls outside the table.
    assert _values(decompose.FailureCause) <= _values(endings.PlanCause)


def test_a_spent_budget_is_the_designer_s_only_when_the_run_set_it() -> None:
    endings = _endings()
    assert endings is not None, "no ending is classified"
    assert endings.plan_class("budget_exhausted", budget_set=True) == "no_plan"
    assert endings.plan_class("budget_exhausted", budget_set=False) == "infrastructure"


def test_unprepared_is_infrastructure_never_the_designer_s() -> None:
    endings = _endings()
    assert endings is not None, "no ending is classified"
    assert endings.review_class("unprepared") == "infrastructure"
    found = endings.round_ending(None, "unprepared", budget_set=False)
    assert (found.plan_class, found.review_class) == ("plan", "infrastructure")


def test_the_review_s_ending_is_recorded_apart_from_the_plan_s() -> None:
    endings = _endings()
    assert endings is not None, "no ending is classified"
    found = endings.round_ending(None, "no_verdict", budget_set=False)
    assert (found.plan_cause, found.plan_class) == (None, "plan")
    assert (found.review_cause, found.review_class) == ("no_verdict", "unavailable")
    passed = endings.round_ending(None, "pass", budget_set=False)
    assert passed.review_class == "verdict" and passed.canary is None
    held = endings.round_ending(None, "fail", budget_set=False, canary="review_material")
    assert held.review_class == "verdict" and held.canary == "review_material"


@pytest.mark.parametrize(
    "made",
    [
        # A review is asked only of a plan; a round with no plan has no review's ending.
        lambda e: e.round_ending("invalid_plan", "fail", budget_set=False),
        lambda e: e.round_ending("api_error", "pass", budget_set=False),
        # A plan's round always ends its review one way or another.
        lambda e: e.round_ending(None, None, budget_set=False),
        # The canary is looked for only in findings a re-plan would carry: a non-pass verdict's.
        lambda e: e.round_ending(None, "pass", budget_set=False, canary="held_out"),
        lambda e: e.round_ending(None, "no_verdict", budget_set=False, canary="held_out"),
        # A class the cause does not have.
        lambda e: e.RoundEnding(
            plan_cause="wall_clock",
            plan_class="infrastructure",
            review_cause=None,
            review_class=None,
        ),
        lambda e: e.RoundEnding(
            plan_cause=None,
            plan_class="plan",
            review_cause="unprepared",
            review_class="unavailable",
        ),
    ],
    ids=[
        "review-of-no-plan",
        "review-of-void",
        "plan-unreviewed",
        "canary-on-pass",
        "canary-on-no-verdict",
        "plan-class",
        "review-class",
    ],
)
def test_a_round_ending_the_code_could_not_reach_is_refused(made: Any) -> None:  # noqa: ANN401
    endings = _endings()
    assert endings is not None, "no ending is classified"
    found = outcome_of(lambda: made(endings))
    assert isinstance(found, ValueError), found


def _startable(monkeypatch: pytest.MonkeyPatch, failing: str) -> Any:  # noqa: ANN401
    """require_startable with every check passing but ``failing``, which refuses."""

    def refuse(*_: Any, **__: Any) -> Any:  # noqa: ANN401
        if failing == "read_library":
            raise LibraryError("a planned role's curated file is missing", role="electrical")
        raise DecompositionError(f"{failing} refused it")

    def passing(value: Any) -> Any:  # noqa: ANN401
        return lambda *_, **__: value

    checks = {
        "_planned_subtasks": passing([]),
        "_contract_pairs": passing(None),
        "_brief_words": passing(()),
        "read_library": passing({}),
        "series_library": passing({}),
        "_require_library_fits": passing(None),
    }
    for name, stand_in in checks.items():
        monkeypatch.setattr(decompose, name, refuse if name == failing else stand_in)

    class Planned:
        interface_nodes: tuple[Any, ...] = ()

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


@pytest.mark.parametrize(
    ("failing", "cause"),
    [
        ("_planned_subtasks", "plan_refused"),
        ("_contract_pairs", "plan_refused"),
        ("_brief_words", "plan_refused"),
        ("read_library", "library_refused"),
        ("_require_library_fits", "library_refused"),
    ],
)
def test_a_start_check_names_whether_the_plan_or_the_library_was_refused(
    monkeypatch: pytest.MonkeyPatch, failing: str, cause: str
) -> None:
    found = _startable(monkeypatch, failing)
    refused: dict[str, type[Exception] | None] = {
        "plan_refused": getattr(exceptions, "PlanRefusedError", None),
        "library_refused": getattr(exceptions, "LibraryRefusedError", None),
    }
    kind = refused[cause]
    assert kind is not None, f"no exception names {cause}"
    assert isinstance(found, kind), found
    assert isinstance(found, DecompositionError)  # what every caller already catches
    assert getattr(found, "cause", None) == cause
    other = next(k for name, k in refused.items() if name != cause)
    assert other is None or not isinstance(found, other)


def test_a_node_id_that_is_no_node_id_is_the_plan_s_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stand_ins: dict[str, Any] = {
        "_planned_subtasks": [],
        "_contract_pairs": None,
        "_brief_words": (),
        "read_library": {},
        "series_library": {},
        "_require_library_fits": None,
    }
    for name, value in stand_ins.items():
        monkeypatch.setattr(decompose, name, lambda *_, value=value, **__: value)

    class Node:
        id = "../escape"

    class Planned:
        interface_nodes = (Node(),)

    config = type("C", (), {"target_head": "h"})()
    found = outcome_of(
        lambda: decompose.require_startable(
            Planned(),  # type: ignore[arg-type]
            config=config,
            target_repo=Path("/nowhere"),
            library=None,
            brief="b",
        )
    )
    refused = getattr(exceptions, "PlanRefusedError", None)
    assert refused is not None, "no exception names plan_refused"
    assert isinstance(found, refused), found
