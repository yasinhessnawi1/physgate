"""Two ends the binary names are a cause of their own outside a review, on the new pin only.

A request that outgrew the window ends ``prompt_too_long``; a structured answer refused
at the binary's own cap ends ``structured_output_retry_exhausted``. A review has always
named both, and the decomposition call names both from a table of its own on every pin. A
role session reads them as the cause every end without a name of its own gets, and on the
earlier pins it still does, so nothing those pins' runs record of a role session changes.
From 2.1.322 on each is recorded under the binary's own name.

The result objects are the ones measured through the real binaries, alike on both pins.
"""

from __future__ import annotations

from typing import Any

import pytest

from physgate.orchestrator.budget import (
    NAMED_END_VERSIONS,
    PROMPT_TOO_LONG,
    STRUCTURED_OUTPUT_EXHAUSTED,
    SessionEnd,
    classify_session_end,
)
from physgate.orchestrator.decompose import judge

MODEL = "claude-sonnet-5"
TOO_LONG: dict[str, Any] = {
    "type": "result",
    "subtype": "success",
    "is_error": True,
    "api_error_status": 400,
    "terminal_reason": "prompt_too_long",
    "result": "Prompt is too long",
    "num_turns": 2,
}
EXHAUSTED: dict[str, Any] = {
    "type": "result",
    "subtype": "error_max_structured_output_retries",
    "is_error": True,
    "terminal_reason": "structured_output_retry_exhausted",
    "errors": ["Failed to provide valid structured output after 5 attempts"],
    "num_turns": 6,
}
ENDS = {PROMPT_TOO_LONG: TOO_LONG, STRUCTURED_OUTPUT_EXHAUSTED: EXHAUSTED}
EARLIER = ["2.1.272", "2.1.283", "2.1.301"]


def test_the_pins_that_name_the_two_ends_are_the_new_one_alone() -> None:
    assert frozenset({"2.1.322"}) == NAMED_END_VERSIONS
    assert (PROMPT_TOO_LONG, STRUCTURED_OUTPUT_EXHAUSTED) == (
        "prompt_too_long",
        "structured_output_retry_exhausted",
    )


@pytest.mark.parametrize("name", sorted(ENDS))
def test_on_the_new_pin_a_role_session_s_end_carries_the_binary_s_name(name: str) -> None:
    end = classify_session_end(
        ENDS[name], exit_code=1, stopped_at_wall_clock=False, claude_version="2.1.322"
    )
    assert end == SessionEnd(outcome="infrastructure", cause=name)  # type: ignore[arg-type]


@pytest.mark.parametrize("version", [*EARLIER, None, "", "9.9.9"])
@pytest.mark.parametrize("name", sorted(ENDS))
def test_on_any_other_pin_it_is_the_cause_without_a_name_as_before(
    name: str, version: str | None
) -> None:
    end = classify_session_end(
        ENDS[name], exit_code=1, stopped_at_wall_clock=False, claude_version=version
    )
    assert end == SessionEnd(outcome="infrastructure", cause="unexpected_exit")
    # Exactly what a caller that names no pin gets, which is what the earlier pins recorded.
    assert end == classify_session_end(ENDS[name], exit_code=1, stopped_at_wall_clock=False)


@pytest.mark.parametrize("name", sorted(ENDS))
def test_the_name_is_taken_only_from_an_end_the_binary_marks_as_an_error(name: str) -> None:
    unmarked = {**ENDS[name], "is_error": False}
    end = classify_session_end(
        unmarked, exit_code=1, stopped_at_wall_clock=False, claude_version="2.1.322"
    )
    assert end.cause == "unexpected_exit"


def test_the_other_ends_read_alike_on_every_pin() -> None:
    overloaded = {"is_error": True, "terminal_reason": "api_error", "api_error_status": 529}
    turns = {"is_error": True, "terminal_reason": "max_turns"}
    done = {"is_error": False, "terminal_reason": "completed"}
    for version in (*EARLIER, "2.1.322"):
        for result, code, clock, cause in (
            (overloaded, 1, False, "api_error"),
            (turns, 1, False, "turn_limit"),
            (done, 0, False, None),
            (done, 1, False, "unexpected_exit"),
            (TOO_LONG, 1, True, "wall_clock"),
            (None, None, False, "no_result"),
        ):
            end = classify_session_end(
                result, exit_code=code, stopped_at_wall_clock=clock, claude_version=version
            )
            assert end.cause == cause, (version, cause)


def _decomposition(result: dict[str, Any], refused: str | None) -> str | None:
    return judge(
        result,
        exit_code=1,
        timed_out=False,
        model=MODEL,
        roles=["electrical"],
        answered=frozenset({MODEL}),
        brief="brief",
        refused=refused,
    )[0]


def test_the_decomposition_call_names_both_by_its_own_table_whatever_the_pin() -> None:
    # The plan call reads the binary's reason from a table of its own, which knows no pin:
    # a context the plan outgrew, and a schema the binary refused until it stopped asking.
    assert _decomposition(TOO_LONG, None) == "context_exceeded"
    assert _decomposition(EXHAUSTED, "the answer does not match the schema") == "schema_refused"


def test_a_decomposition_out_of_turns_after_a_refusal_is_a_schema_refusal() -> None:
    turns = {"is_error": True, "terminal_reason": "max_turns", "num_turns": 3}
    assert _decomposition(turns, "refused") == "schema_refused"
