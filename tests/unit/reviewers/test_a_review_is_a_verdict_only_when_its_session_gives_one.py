"""A review session's end is read for why it is not a verdict before any verdict is read.

The events and result fields here are the shapes measured on both pinned binaries
against the scripted endpoint: a compaction leaves ``compact_boundary`` events, an
oversized request ends with ``terminal_reason: prompt_too_long``, and a refusal
leaves a ``model_refusal_no_fallback`` event and ``stop_reason: refusal`` while
its ``terminal_reason`` is the generic ``api_error``. Each is named for what it
is: the generic classification would call the last two infrastructure, which the
loop retries.

And no review runs on less than the whole trajectory: an attempt without a seal,
or without the commit its change is read against, is refused before any session
is spawned, with nothing spent.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import IssuedSpec, MessageUsage, Usage
from physgate.orchestrator.run_config import HarnessState, ModelStrings, RunBounds, RunConfig
from physgate.reviewers.claude import (
    ClaudeReviewer,
    peak_context_tokens,
    review_prompt,
    unavailable_end,
)
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.packet import build_packet
from physgate.reviewers.rubric import Rubric, evaluation_words, parse_rubric

RUBRIC = Rubric(
    role="control",
    text=PLACEHOLDER,
    sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest(),
    items=parse_rubric(PLACEHOLDER),
)
COMPLETED = {"type": "result", "is_error": False, "terminal_reason": "completed"}


def _lines(*events: dict[str, Any]) -> str:
    return "".join(json.dumps(e) + "\n" for e in events)


def _end(stream_text: str, result: dict[str, Any] | None, exit_code: int | None = 0) -> Any:  # noqa: ANN401
    return unavailable_end(stream_text, result, exit_code=exit_code, timed_out=False)


def test_a_completed_session_is_one_a_verdict_may_come_from() -> None:
    assert _end(_lines(COMPLETED), COMPLETED) is None


def test_a_compaction_anywhere_is_not_a_verdict_even_when_the_session_completed() -> None:
    boundary = {"type": "system", "subtype": "compact_boundary", "compact_metadata": {}}
    assert _end(_lines(boundary, COMPLETED), COMPLETED)[0] == "compacted"


def test_an_oversized_request_is_context_exceeded_not_infrastructure() -> None:
    result = {
        "type": "result",
        "is_error": True,
        "terminal_reason": "prompt_too_long",
        "api_error_status": 400,
    }
    assert _end(_lines(result), result, exit_code=1)[0] == "context_exceeded"


@pytest.mark.parametrize("where", ["event", "result"])
def test_a_refusal_is_named_a_refusal_not_an_api_error(where: str) -> None:
    result = {"type": "result", "is_error": True, "terminal_reason": "api_error"}
    events: list[dict[str, Any]] = []
    if where == "event":
        events.append({"type": "system", "subtype": "model_refusal_no_fallback"})
    else:
        result["stop_reason"] = "refusal"
    assert _end(_lines(*events, result), result, exit_code=1)[0] == "refused"


def test_running_out_of_turns_is_no_verdict_and_after_a_schema_refusal_an_invalid_one() -> None:
    result = {"type": "result", "is_error": True, "terminal_reason": "max_turns"}
    assert _end(_lines(result), result, exit_code=1)[0] == "no_verdict"
    refusal = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": "Output does not match required schema: verdict",
                }
            ]
        },
    }
    cause, detail = _end(_lines(refusal, result), result, exit_code=1)
    assert cause == "invalid_verdict" and "does not match" in detail


@pytest.mark.parametrize(
    ("result", "timed_out"),
    [
        (None, False),
        ({"type": "result", "is_error": True, "terminal_reason": "api_error"}, False),
        (COMPLETED, True),
    ],
    ids=["no-result", "api-error", "wall-clock"],
)
def test_every_other_end_is_infrastructure(result: dict[str, Any] | None, timed_out: bool) -> None:
    text = _lines(result) if result else ""
    ended = unavailable_end(text, result, exit_code=1, timed_out=timed_out)
    assert ended is not None and ended[0] == "infrastructure"


def test_the_peak_context_is_the_largest_input_a_message_had() -> None:
    def message(n: str, inp: int, read: int, made: int) -> MessageUsage:
        return MessageUsage(
            message_id=n,
            usage=Usage(
                input_tokens=inp,
                output_tokens=999_999,
                cache_read_input_tokens=read,
                cache_creation_input_tokens=made,
            ),
        )

    usage = (message("a", 10, 100, 1), message("b", 5, 150, 2), message("c", 1, 20, 0))
    assert peak_context_tokens(usage) == 157
    assert peak_context_tokens(()) == 0


def _packet(tmp_path: Path, *, checks_off: bool) -> Any:  # noqa: ANN401
    attempt = make_attempt(tmp_path, stream(with_checks_off=checks_off))
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    return build_packet(
        tmp_path / "reviews" / "r0123456789ab",
        artefact_of(attempt),
        repo=attempt.worktree,
        base_commit=attempt.spec_commit,
        rubric=RUBRIC,
        library=library,
        spec=IssuedSpec(
            commit=attempt.spec_commit,
            path=SPEC,
            sha256=hashlib.sha256(ISSUED.encode()).hexdigest(),
        ),
    )


@pytest.mark.parametrize("checks_off", [True, False])
def test_the_prompt_names_every_file_to_read_and_says_nothing_it_must_not(
    tmp_path: Path, checks_off: bool
) -> None:
    packet = _packet(tmp_path, checks_off=checks_off)
    prompt = review_prompt("control", packet)
    assert evaluation_words(prompt) == []
    assert all(path in prompt for path in packet.required_reading)
    assert "StructuredOutput" in prompt
    if checks_off:
        assert packet.indicators
        assert all(hit.evidence in prompt for hit in packet.indicators)
    else:
        assert not packet.indicators and "no check switched off" in prompt


def _config() -> RunConfig:
    return RunConfig(
        run_id="run-1",
        seed=7,
        brief_sha256="a" * 64,
        gate_mode="on",
        models=ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"control": "claude-opus-5-5"},
            reviewers={"control": "claude-sonnet-5"},
        ),
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        token_ceiling=100_000,
        claude_version="2.1.272",
        target_head="b" * 40,
        endpoint="default",
        auth="api_key",
        reportable=False,
        harness=HarnessState(commit="c" * 40, clean=True, uncommitted_sha256=None),
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
    )


def _binary(tmp_path: Path) -> tuple[Path, Path]:
    """A stand-in binary that reports the pinned version and records every call."""
    calls = tmp_path / "calls.txt"
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\necho "$@" >> {calls}\necho "2.1.272 (Claude Code)"\n')
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary, calls


def _reviewer(tmp_path: Path, binary: Path, **overrides: Any) -> ClaudeReviewer:  # noqa: ANN401
    fields: dict[str, Any] = {
        "role": "control",
        "config": _config(),
        "rubric": RUBRIC,
        "library": tmp_path / "harness",
        "review_root": tmp_path / "rs",
        "repo": tmp_path / "target",
        "install_bin": tmp_path / "install" / "bin" / "physgate",
        "binary": str(binary),
        "base_url": None,
        "credential": Credential(mode="api_key", secret="sk-test-not-a-key"),
    }
    fields.update(overrides)
    return ClaudeReviewer(**fields)


@pytest.mark.parametrize(
    "missing", ["seal", "base commit", "trajectory file"], ids=["seal", "base", "file"]
)
def test_a_review_without_the_whole_trajectory_never_spawns_a_session(
    tmp_path: Path, missing: str
) -> None:
    attempt = make_attempt(tmp_path, stream())
    write_fixture(tmp_path / "harness", ("cross", "control"))
    overrides: dict[str, Any] = {"base_commit": attempt.spec_commit}
    if missing == "seal":
        overrides |= {"trajectory_sha256": None, "trajectory_length": None}
    elif missing == "base commit":
        overrides["base_commit"] = None
    artefact = artefact_of(attempt, **overrides)
    if missing == "trajectory file":
        attempt.trajectory.unlink()
    binary, calls = _binary(tmp_path)
    reviewer = _reviewer(tmp_path, binary)
    with pytest.raises(ReviewUnavailableError) as raised:
        reviewer.review(artefact)
    assert raised.value.cause == "unprepared"
    assert raised.value.session_id is None and raised.value.usage == ()
    # The binary was asked its version and nothing else; no session directory exists.
    assert calls.read_text().split("\n")[:-1] == ["--version"]
    assert not list((tmp_path / "rs").glob("*/session"))


def test_a_reviewer_runs_only_on_its_pinned_model_with_its_own_rubric(tmp_path: Path) -> None:
    binary, _ = _binary(tmp_path)
    assert _reviewer(tmp_path, binary).model == "claude-sonnet-5"
    with pytest.raises(ReviewError, match="pins no reviewer"):
        _reviewer(tmp_path, binary, role="firmware")
    other = RUBRIC.model_copy(update={"role": "firmware"})
    with pytest.raises(ReviewError, match="its own role's rubric"):
        _reviewer(tmp_path, binary, rubric=other)
