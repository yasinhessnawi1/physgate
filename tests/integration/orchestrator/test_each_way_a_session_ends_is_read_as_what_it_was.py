"""Against every pinned binary: each way a session ends, and what each reader makes of it.

How a session ended is read from the binary's result event (``terminal_reason``,
``is_error``, ``api_error_status``, ``errors``) and its exit status. Each ending the
harness depends on is produced here by the real binary at the scripted endpoint, on the
reviewer's model string, and held to the values measured on that pin: the result event's
fields, the exit status, how a role session with that end is classified, why a review
with that end is no verdict, and why a decomposition call with that end gives no plan.

The table is per pin. Where two pins end a session differently, their entries differ;
a pin with no entry fails every row, so a new pin is measured before it is used.

- A finished session is the only completed one, and only with exit status 0.
- A hit turn limit, an API error and a refused credential are infrastructure, each named.
- A request that outgrew the window, with compaction off, ends ``prompt_too_long`` with
  no compaction request and no compaction marker: a review names it, never a verdict.
- A structured answer refused five times ends the session at the binary's own cap: a
  review names it an invalid verdict, never a verdict.
- A stop for usage credits ends the session as an API error at once: the binary asks
  for no summary and marks no compaction, with compaction off.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from plain_session import Ended, run_session
from scripted_endpoint import COMPACTION_MARKER, failure, text, tool

from physgate.orchestrator.budget import SANDBOX_UNAVAILABLE
from physgate.reviewers.claude import (
    PROMPT_TOO_LONG,
    STRUCTURED_OUTPUT_EXHAUSTED,
    schema_refusals,
)

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]

#: The result event has no such field.
ABSENT = "absent"

READ = tool("Read", file_path="a.txt")
#: The input figures of a message whose context is near the binary's window.
LARGE = {"input_tokens": 5, "cache_read_input_tokens": 195_000, "cache_creation_input_tokens": 2}
TOO_LONG = failure(400, "invalid_request_error", "prompt is too long: 210000 tokens > 200000")
#: The API's stop for a long-context request on an account without usage credits.
CREDITS_STOP = failure(
    429, "rate_limit_error", "Usage credits are required for long context requests."
)
NO_COMPACTION = {"DISABLE_COMPACT": "1"}


@dataclass(frozen=True)
class End:
    """One ending as measured: the result event, the exit, and what each reader makes of it."""

    terminal_reason: str
    is_error: bool
    api_error_status: int | str | None
    exit_code: int
    #: A role session's outcome and cause.
    role_session: tuple[str, str | None]
    #: Why a review is no verdict (``None``: a verdict may be read from it).
    review: str | None
    #: Why a decomposition call gives no plan.
    decomposition: str | None
    #: How many requests the session made.
    requests: int


#: Measured at the scripted endpoint on macOS, 12.11.2026; the two pins end alike.
_MEASURED: dict[str, End] = {
    # The end is taken; that this session carried no plan is the decomposition's next check.
    "completed": End(
        "completed", False, None, 0, ("completed", None), None, "no_structured_output", 2
    ),
    "max_turns": End(
        "max_turns",
        True,
        ABSENT,
        1,
        ("infrastructure", "turn_limit"),
        "no_verdict",
        "turn_limit",
        1,
    ),
    "api_error": End(
        "api_error",
        True,
        529,
        1,
        ("infrastructure", "api_error"),
        "infrastructure",
        "api_error",
        1,
    ),
    "refused_credential": End(
        "api_error",
        True,
        401,
        1,
        ("infrastructure", "credential_refused"),
        "infrastructure",
        "credential_refused",
        1,
    ),
    # Infrastructure for a role session and for the decomposition, under the cause every end
    # without a name of its own gets; a review names it.
    "prompt_too_long": End(
        PROMPT_TOO_LONG,
        True,
        400,
        1,
        ("infrastructure", "unexpected_exit"),
        "context_exceeded",
        "unexpected_exit",
        2,
    ),
    "structured_output_retry_exhausted": End(
        STRUCTURED_OUTPUT_EXHAUSTED,
        True,
        ABSENT,
        1,
        ("infrastructure", "unexpected_exit"),
        "invalid_verdict",
        "unexpected_exit",
        5,
    ),
    "usage_credits_stop": End(
        "api_error",
        True,
        429,
        1,
        ("infrastructure", "api_error"),
        "infrastructure",
        "api_error",
        3,
    ),
}
ENDS: dict[str, dict[str, End]] = {"2.1.301": dict(_MEASURED), "2.1.322": dict(_MEASURED)}

#: The binary's cap on refused structured answers, per pin.
REFUSALS_BEFORE_THE_CAP = {"2.1.301": 5, "2.1.322": 5}


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _in_order(steps: list[dict[str, Any]]) -> Any:  # noqa: ANN401 - the endpoint's own hook
    """Serve ``steps`` one per request, whatever the conversation holds; then a last word."""
    served = iter(steps)

    def step(_thread: str, _cwd: str, _done: int) -> dict[str, Any]:
        return next(served, text("done"))

    return step


def _produce(name: str, binary: str, work: Path) -> Ended:
    large_read = {**READ, "usage": LARGE}
    if name == "completed":
        return run_session(binary, work, [READ, text("done")])
    if name == "max_turns":
        return run_session(binary, work, [READ, text("done")], max_turns=1)
    if name == "api_error":
        return run_session(binary, work, [failure(529, "overloaded_error", "Overloaded")])
    if name == "refused_credential":
        refused = failure(401, "authentication_error", "invalid x-api-key")
        return run_session(binary, work, [refused])
    if name == "prompt_too_long":
        return run_session(binary, work, [large_read, TOO_LONG], env=NO_COMPACTION)
    if name == "structured_output_retry_exhausted":
        wrong = tool("StructuredOutput", answer="not an integer")
        return run_session(binary, work, [wrong] * 30, structured=True, max_turns=40)
    assert name == "usage_credits_stop", name
    return run_session(
        binary,
        work,
        [],
        env=NO_COMPACTION,
        subscription=True,
        on_request=_in_order([large_read, large_read, CREDITS_STOP, large_read]),
    )


@pytest.mark.parametrize("name", sorted(_MEASURED))
def test_the_end_is_what_was_measured_on_this_pin_and_each_reader_names_it(
    binary: str, tmp_path: Path, name: str
) -> None:
    ended = _produce(name, binary, tmp_path)
    assert ended.version in ENDS, f"no ending was measured on {ended.version}"
    expected = ENDS[ended.version][name]
    result = ended.result
    assert result is not None, ended.stderr
    assert result.get("terminal_reason") == expected.terminal_reason
    assert result.get("is_error") is expected.is_error
    assert result.get("api_error_status", ABSENT) == expected.api_error_status
    assert ended.exit_code == expected.exit_code
    role = ended.as_a_role_session()
    assert (role.outcome, role.cause) == expected.role_session
    assert ended.as_a_review() == expected.review
    assert ended.as_the_decomposition() == expected.decomposition
    assert len(ended.requests) == expected.requests
    # Nothing follows the result, and only a finished session is a completed one.
    assert ended.after_result == []
    assert (role.outcome == "completed") == (name == "completed")


def test_a_request_past_the_window_with_compaction_off_asks_for_no_summary(
    binary: str, tmp_path: Path
) -> None:
    ended = _produce("prompt_too_long", binary, tmp_path)
    assert not ended.compacted
    assert not any(COMPACTION_MARKER in r.last_user for r in ended.requests)
    assert (ended.result or {}).get("result") == "Prompt is too long"


def test_a_stop_for_usage_credits_ends_the_session_and_compacts_nothing(
    binary: str, tmp_path: Path
) -> None:
    ended = _produce("usage_credits_stop", binary, tmp_path)
    # The binary took the stop for what it is, and the stop was its last request: it asked
    # for no summary and went on with nothing.
    assert "Usage credits required" in str((ended.result or {}).get("result"))
    assert [("error" in (r.served or {})) for r in ended.requests] == [False, False, True]
    assert not ended.compacted
    assert not any(COMPACTION_MARKER in r.last_user for r in ended.requests)


def test_the_binary_ends_a_session_at_its_own_cap_on_refused_structured_answers(
    binary: str, tmp_path: Path
) -> None:
    ended = _produce("structured_output_retry_exhausted", binary, tmp_path)
    cap = REFUSALS_BEFORE_THE_CAP[ended.version]
    assert schema_refusals(ended.stdout) == cap and len(ended.requests) == cap
    result = ended.result or {}
    assert result.get("subtype") == "error_max_structured_output_retries"
    (told,) = result["errors"]
    assert told.startswith(f"Failed to provide valid structured output after {cap} attempts")
    assert "structured_output" not in result


def test_a_session_whose_required_sandbox_cannot_start_says_so_before_any_request(
    binary: str, tmp_path: Path
) -> None:
    """The sandbox's programs are taken off the session's search path, and it is required.

    On Linux the sandbox is two programs found on the search path, so the session refuses
    to start. On macOS it is a part of the system the binary addresses by its full path:
    a search path cannot take it away, and the session runs.
    """
    required = {
        "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False}
    }
    ended = run_session(
        binary,
        tmp_path,
        [tool("Bash", command="echo hi"), text("done")],
        settings=required,
        env={"PATH": str(Path(binary).parent)},
    )
    result = ended.result
    assert result is not None, ended.stderr
    role = ended.as_a_role_session()
    if sys.platform == "darwin":
        assert (role.outcome, ended.exit_code) == ("completed", 0)
        assert len(ended.requests) == 2
        return
    assert result.get("is_error") is True and ended.exit_code == 1
    assert any(str(e).startswith(SANDBOX_UNAVAILABLE) for e in result.get("errors") or [])
    assert ended.requests == ()
    assert (role.outcome, role.cause) == ("infrastructure", "sandbox_unavailable")
    assert ended.as_a_review() == "infrastructure"
    assert ended.as_the_decomposition() == "sandbox_unavailable"
