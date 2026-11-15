"""Against every pinned binary: a session driven past its compaction trigger, as each pin does it.

A reviewer may compact its conversation and carry on to a verdict only on a pin where what the
binary does at a compaction was measured. These rows measure it at the scripted endpoint, on the
reviewer's model string, with the verdict tool offered (``--json-schema``), in a non-interactive
session, and hold each pin to what it did. No model is called and no credential is loaded.

- B1: a context past the trigger is compacted: one compaction request, one ``compact_boundary``
  event whose ``compact_metadata`` names ``trigger``, ``pre_tokens``, ``post_tokens``,
  ``cumulative_dropped_tokens`` and ``duration_ms``; then the session goes on and gives its
  structured answer.
- B2: every request, the compaction's own and those after it, offers the same tools and the
  verdict tool with the same schema bytes.
- B3: the compaction call's usage is no message of the stream; the result's ``modelUsage``
  includes it, its ``usage`` does not, and after a resume ``modelUsage`` is the whole session's,
  the compaction counted once. The account read from the stream therefore differs from the
  binary's totals by exactly the compaction call.
- B4: the session-start hook runs again after the compaction with ``source: "compact"`` and the
  same session id, and the context it returns reaches the next request, without the one it
  returned at the start.
- B5: where the trigger sits against the context the last message reported, with the run's
  output cap and with a small one.
- B6: a compaction that cannot keep up ends the session at the binary's own limit, which a
  review names ``context_exceeded``: a context that refills at once (``rapid_refill_breaker``)
  and a compaction request refused as too long (``blocking_limit``).
- B7: a resume of a session that compacted starts from the summary, runs the session-start hook
  with ``source: "resume"`` and the same session id, and shows no boundary again.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from compaction_session import (
    COMPACT_USAGE,
    PROBE_CONTEXT,
    Ran,
    Session,
    usage_of,
)
from scripted_endpoint import COMPACTION_MARKER, failure, tool

from physgate.orchestrator.accounting import require_matching_totals
from physgate.orchestrator.decompose import read_stream
from physgate.orchestrator.exceptions import AccountingError
from physgate.reviewers.claude import CONTEXT_LIMITS, compactions_in, unavailable_end

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

#: A context past the trigger on every pin, as the last message reports it.
PAST = 999_000
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
MODEL_FIELDS = {
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_creation_input_tokens": "cacheCreationInputTokens",
}
METADATA = {"trigger", "pre_tokens", "post_tokens", "cumulative_dropped_tokens", "duration_ms"}
SUMMARY_OPENING = "This session is being continued from a previous conversation"
#: The run's own output cap (the example parameters, every experiment's) and a small one.
RUN_OUTPUT_CAP = 64_000


@dataclass(frozen=True)
class Pin:
    """What one pin did, as measured at the scripted endpoint on macOS, 16.11.2026."""

    #: ``pre_tokens`` less the context the last message reported: the binary's own estimate of
    #: what it added since.
    pre_over_reported: int
    #: ``post_tokens`` after a compaction answered with the endpoint's summary.
    post_tokens: int
    #: The least reported context that compacts, by output cap: the window (1,000,000) less the
    #: cap (counted up to 20,000) less about 3,000.
    first_compacting: dict[int, int]
    #: How many compaction requests the binary makes when each is refused as too long.
    refused_compaction_requests: int


PINS: dict[str, Pin] = {
    "2.1.301": Pin(
        pre_over_reported=25,
        post_tokens=588,
        first_compacting={1000: 995_968, RUN_OUTPUT_CAP: 976_968},
        refused_compaction_requests=2,
    ),
    "2.1.322": Pin(
        pre_over_reported=3,
        post_tokens=611,
        first_compacting={1000: 995_997, RUN_OUTPUT_CAP: 976_997},
        refused_compaction_requests=3,
    ),
}


@pytest.fixture(params=BINARIES, ids=lambda b: Path(b).name)
def binary(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def _read(context: int) -> dict[str, Any]:
    return {**tool("Read", file_path="a.txt"), "usage": usage_of(context)}


ANSWER = tool("StructuredOutput", answer=7)


def _pin(ran: Ran) -> Pin:
    assert ran.version in PINS, f"no compaction was measured on {ran.version}"
    return PINS[ran.version]


def _compacted_once(binary: str, work: Path) -> Ran:
    return Session(binary, work).run([_read(PAST), ANSWER])


def _stream_sum(stdout: str) -> dict[str, int]:
    _, usages, _ = read_stream(stdout)
    return {f: sum(int(getattr(u.usage, f)) for u in usages) for f in FIELDS}


def _model_usage(ran: Ran) -> dict[str, int]:
    (totals,) = ((ran.result or {}).get("modelUsage") or {}).values()
    return {f: int(totals[key]) for f, key in MODEL_FIELDS.items()}


def _schema(body: dict[str, Any]) -> str | None:
    for offered in body.get("tools") or []:
        if offered.get("name") == "StructuredOutput":
            return json.dumps(offered.get("input_schema"))
    return None


def _tools(body: dict[str, Any]) -> list[str]:
    return [str(t.get("name")) for t in body.get("tools") or []]


def _probe(body: dict[str, Any], source: str) -> bool:
    return (PROBE_CONTEXT + source) in json.dumps(body)


def test_b1_a_context_past_the_trigger_is_compacted_and_the_session_gives_its_answer(
    binary: str, tmp_path: Path
) -> None:
    ran = _compacted_once(binary, tmp_path)
    pin = _pin(ran)
    # One compaction request, the binary's own, between the read and the answer.
    assert ran.compaction_requests == (1,) and len(ran.bodies) == 3
    assert COMPACTION_MARKER in json.dumps(ran.bodies[1])
    (boundary,) = ran.boundaries
    metadata = boundary["compact_metadata"]
    assert set(metadata) == METADATA
    assert metadata["trigger"] == "auto"
    assert metadata["pre_tokens"] == PAST + pin.pre_over_reported
    assert metadata["post_tokens"] == pin.post_tokens
    assert metadata["cumulative_dropped_tokens"] == metadata["pre_tokens"] - pin.post_tokens
    assert isinstance(metadata["duration_ms"], int)
    # The binary says it is compacting, and that it succeeded, before the boundary.
    statuses = [
        (e.get("status"), e.get("compact_result"))
        for e in ran.events
        if e.get("type") == "system" and e.get("subtype") == "status"
    ]
    assert ("compacting", None) in statuses and (None, "success") in statuses
    # The session went on and gave its structured answer, a finished session.
    result = ran.result or {}
    assert (result.get("terminal_reason"), result.get("is_error")) == ("completed", False)
    assert result.get("structured_output") == {"answer": 7} and ran.exit_code == 0
    # The built reader takes the boundary's size, and names the end for each setting.
    assert compactions_in(ran.stdout) == (metadata["pre_tokens"],)
    on = unavailable_end(ran.stdout, result, exit_code=0, timed_out=False, compaction="on")
    off = unavailable_end(ran.stdout, result, exit_code=0, timed_out=False, compaction="off")
    assert on is None
    assert off is not None and off[0] == "compacted"


def test_b2_every_request_offers_the_same_tools_and_the_same_verdict_schema_bytes(
    binary: str, tmp_path: Path
) -> None:
    ran = _compacted_once(binary, tmp_path)
    _pin(ran)
    first = ran.bodies[0]
    assert _schema(first) is not None
    # Before the compaction, the compaction request itself, and after it.
    assert all(_schema(b) == _schema(first) for b in ran.bodies)
    assert all(_tools(b) == _tools(first) for b in ran.bodies)
    assert ran.after_compaction() and "StructuredOutput" in _tools(ran.after_compaction()[0])


def test_b3_the_compaction_call_is_in_the_binary_s_totals_and_no_message_of_the_stream(
    binary: str, tmp_path: Path
) -> None:
    session = Session(binary, tmp_path)
    ran = session.run([_read(PAST), ANSWER])
    _pin(ran)
    result = ran.result or {}
    streamed = _stream_sum(ran.stdout)
    # No message of the stream carries the compaction call's figures.
    _, usages, _ = read_stream(ran.stdout)
    assert len(usages) == 2
    assert all(u.usage.input_tokens != COMPACT_USAGE["input_tokens"] for u in usages)
    # The per-model totals are the stream's messages and the compaction call, each once.
    charged = {f: streamed[f] + COMPACT_USAGE[f] for f in FIELDS}
    assert _model_usage(ran) == charged
    # The result's own ``usage`` leaves the compaction call out, as the stream does.
    assert {f: int(result["usage"][f]) for f in FIELDS} == streamed
    # So the account read from the stream does not match the totals: the check refuses it.
    _, usage, _ = read_stream(ran.stdout)
    with pytest.raises(AccountingError) as refused:
        require_matching_totals(result, usage)
    assert refused.value.context["field"] == "input_tokens"
    # A resume's totals are the whole session's: the first invocation's, the compaction call
    # once, and the resume's own messages.
    resumed = session.run([tool("StructuredOutput", answer=8)], resume=True, prompt="again")
    again = _stream_sum(resumed.stdout)
    assert _model_usage(resumed) == {f: charged[f] + again[f] for f in FIELDS}
    _, more, _ = read_stream(resumed.stdout)
    assert all(u.usage.input_tokens != COMPACT_USAGE["input_tokens"] for u in more)


def test_b4_the_session_start_hook_runs_after_the_compaction_and_its_context_is_delivered(
    binary: str, tmp_path: Path
) -> None:
    ran = _compacted_once(binary, tmp_path)
    _pin(ran)
    assert [h.get("source") for h in ran.hook_inputs] == ["startup", "compact"]
    assert {h.get("session_id") for h in ran.hook_inputs} == {ran.session_id}
    names = [
        e.get("hook_name")
        for e in ran.events
        if e.get("type") == "system" and e.get("subtype") == "hook_started"
    ]
    assert names == ["SessionStart:startup", "SessionStart:compact"]
    # The session id is kept across the boundary, to the result.
    (boundary,) = ran.boundaries
    assert boundary["session_id"] == ran.session_id
    assert (ran.result or {}).get("session_id") == ran.session_id
    # The context the hook returned after the compaction reaches the next request, and the
    # one it returned at the start does not: the compaction dropped it.
    (after,) = ran.after_compaction()
    assert _probe(after, "compact") and not _probe(after, "startup")
    assert SUMMARY_OPENING in json.dumps(after)
    assert all(_probe(b, "startup") and not _probe(b, "compact") for b in ran.bodies[:2])


@pytest.mark.parametrize("cap", [1000, RUN_OUTPUT_CAP])
def test_b5_the_trigger_sits_where_it_was_measured_against_the_reported_context(
    binary: str, tmp_path: Path, cap: int
) -> None:
    env = {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(cap)}
    probe = Session(binary, tmp_path / "probe", probe=False)
    first = PINS.get(probe.version, PINS["2.1.301"]).first_compacting[cap]
    below = probe.run([_read(first - 1), ANSWER], env=env)
    _pin(below)
    at = Session(binary, tmp_path / "at", probe=False).run([_read(first), ANSWER], env=env)
    assert below.compaction_requests == () and below.boundaries == []
    assert len(at.compaction_requests) == 1 and len(at.boundaries) == 1
    (totals,) = ((at.result or {}).get("modelUsage") or {}).values()
    assert totals["contextWindow"] == 1_000_000


def test_b6a_a_context_that_refills_at_once_ends_at_the_binary_s_breaker(
    binary: str, tmp_path: Path
) -> None:
    ran = Session(binary, tmp_path).run([_read(PAST)] * 12, max_turns=30)
    _pin(ran)
    result = ran.result or {}
    assert result.get("terminal_reason") == "rapid_refill_breaker" in CONTEXT_LIMITS
    assert result.get("is_error") is True and ran.exit_code == 1
    assert str(result.get("result")).startswith("Autocompact is thrashing")
    # Three compactions, each followed by a context back over the trigger, then the stop.
    assert len(ran.compaction_requests) == 3 and len(ran.boundaries) == 3
    assert [h.get("source") for h in ran.hook_inputs] == ["startup", *["compact"] * 3]
    cut = unavailable_end(ran.stdout, result, exit_code=1, timed_out=False, compaction="on")
    assert cut is not None and cut[0] == "context_exceeded"
    # The totals include the three compaction calls, which the stream does not show.
    streamed = _stream_sum(ran.stdout)
    assert _model_usage(ran) == {f: streamed[f] + 3 * COMPACT_USAGE[f] for f in FIELDS}


def test_b6b_a_compaction_refused_as_too_long_ends_at_the_binary_s_limit(
    binary: str, tmp_path: Path
) -> None:
    too_long = failure(400, "invalid_request_error", "prompt is too long: 1010000 tokens > 1000000")
    ran = Session(binary, tmp_path).run([_read(PAST), ANSWER], compact_reply=too_long)
    pin = _pin(ran)
    result = ran.result or {}
    assert result.get("terminal_reason") == "blocking_limit" in CONTEXT_LIMITS
    assert result.get("is_error") is True and ran.exit_code == 1
    assert result.get("result") == "Prompt is too long"
    assert len(ran.compaction_requests) == pin.refused_compaction_requests
    assert ran.boundaries == [] and [h.get("source") for h in ran.hook_inputs] == ["startup"]
    failed = [
        (e.get("compact_result"), e.get("compact_error"))
        for e in ran.events
        if e.get("type") == "system" and e.get("subtype") == "status" and "compact_result" in e
    ]
    assert failed == [("failed", "exhausted")]
    cut = unavailable_end(ran.stdout, result, exit_code=1, timed_out=False, compaction="on")
    assert cut is not None and cut[0] == "context_exceeded"
    # No compaction was charged, so the stream's account matches the totals.
    _, usage, _ = read_stream(ran.stdout)
    require_matching_totals(result, usage)


def test_b7_a_resume_of_a_compacted_session_starts_from_its_summary(
    binary: str, tmp_path: Path
) -> None:
    session = Session(binary, tmp_path)
    first = session.run([_read(PAST), ANSWER])
    _pin(first)
    assert len(first.boundaries) == 1
    resumed = session.run([tool("StructuredOutput", answer=8)], resume=True, prompt="again")
    result = resumed.result or {}
    assert (result.get("terminal_reason"), result.get("structured_output")) == (
        "completed",
        {"answer": 8},
    )
    # The hook runs once more, with the resume's source and the same session id.
    assert [h.get("source") for h in resumed.hook_inputs] == ["startup", "compact", "resume"]
    assert {h.get("session_id") for h in resumed.hook_inputs} == {session.session_id}
    assert result.get("session_id") == session.session_id
    # The resumed conversation opens with the summary and what followed it: the compaction's
    # hook context is kept, the start's is not, and the read before the compaction is gone.
    opening = resumed.bodies[0]
    assert SUMMARY_OPENING in json.dumps(opening)
    assert _probe(opening, "compact") and _probe(opening, "resume")
    assert not _probe(opening, "startup")
    uses = [
        block.get("name")
        for message in opening.get("messages", [])
        if isinstance(message.get("content"), list)
        for block in message["content"]
        if block.get("type") == "tool_use"
    ]
    assert "Read" not in uses
    # The resumed stream shows no boundary: the compaction is counted once, by the first stream.
    assert resumed.boundaries == [] and compactions_in(resumed.stdout) == ()
    assert resumed.compaction_requests == ()
