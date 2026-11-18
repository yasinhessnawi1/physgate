"""A response the binary cut short at an API error is recorded on its own line, and not charged.

A review session's network broke mid-response. Its first response completed. Its second had a
``message_start`` (the usage it started with), streamed some thinking, and was then closed by
the binary itself: a ``message_stop`` whose stream event carries ``abandoned_blocks`` naming that
response, with no ``message_delta`` and no assistant message for it. The binary then wrote its
own "API Error" message and a result with ``is_error`` and ``terminal_reason: api_error``. The
result's ``modelUsage`` charges the first response alone; its top-level ``usage`` adds the cut
one. The per-message account kept the cut response's starting usage and was held to
``modelUsage`` with strict equality, so the session's end, an API error with a retry path of its
own, became a refused run.

Now the cut response is a line of its own, marked abandoned: in the record, never in a charged
sum, and the session's end is read as the API error it was. Every completed response is still
held to the totals exactly, and a cut response in a session that did not end in an API error is
still refused. The stream below is built by hand from that description, in the shapes the
pinned binary writes; it is no copy of a run's transcript.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeReviewer, Rig, plan
from orch_helpers import make_config

import physgate.orchestrator.decompose as decompose
import physgate.reviewers.claude as claude
from physgate.orchestrator.accounting import TokenAccount, compaction_line, require_matching_totals
from physgate.orchestrator.budget import classify_session_end
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, Installed, captured_from
from physgate.orchestrator.events import (
    EventLog,
    ReviewUnavailable,
    RunStarted,
    SessionEnded,
    TokensUsed,
    read_events,
)
from physgate.orchestrator.exceptions import AccountingError, ReviewUnavailableError
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.run_config import RunBounds
from physgate.orchestrator.usage_limit import session_end
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric

MODEL = "claude-sonnet-5"
ERROR_TEXT = "API Error: Connection refused (ECONNREFUSED)"

#: The first response: complete, its final usage in its ``message_delta``.
FIRST_START = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 46710,
    "cache_read_input_tokens": 0,
    "output_tokens": 1,
}
FIRST_FINAL = {**FIRST_START, "output_tokens": 180}
#: The second response, cut short: only the usage it started with.
CUT_START = {
    "input_tokens": 2,
    "cache_creation_input_tokens": 55515,
    "cache_read_input_tokens": 0,
    "output_tokens": 1,
}
#: What the binary charged: the first response alone.
CHARGED = {
    "inputTokens": 2,
    "outputTokens": 180,
    "cacheReadInputTokens": 0,
    "cacheCreationInputTokens": 46710,
}


def _line(**fields: Any) -> str:  # noqa: ANN401 - the binary's own untyped events
    return json.dumps(fields)


def _stream_event(event: dict[str, Any], **outer: Any) -> str:  # noqa: ANN401 - the same
    return _line(type="stream_event", event=event, parent_tool_use_id=None, **outer)


def _result(
    model_usage: dict[str, int],
    *,
    is_error: bool = True,
    terminal: str = "api_error",
) -> str:
    totals = {MODEL: dict(model_usage)}
    return _line(
        type="result",
        subtype="success",
        is_error=is_error,
        terminal_reason=terminal,
        num_turns=2,
        result=ERROR_TEXT if is_error else "done",
        # The top-level usage adds the cut response; the per-model totals do not.
        usage={
            "input_tokens": 4,
            "output_tokens": 180,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 102225,
        },
        modelUsage={k: {**v, "contextWindow": 1_000_000} for k, v in totals.items()},
    )


def cut_stream(  # noqa: PLR0913 - one stand-in stream, each of its parts a choice of a row
    *,
    result: str | None = None,
    cut_delta: bool = False,
    cut_assistant: bool = False,
    marker: str | None = "msg_02",
    with_marker: bool = True,
    answering: str = MODEL,
) -> str:
    """The session: one complete response, one cut short, the binary's own error, its result."""
    first = [
        _line(type="system", subtype="init", model=answering, session_id="s"),
        _stream_event(
            {"type": "message_start", "message": {"id": "msg_01", "usage": FIRST_START}},
            api_message_id="msg_01",
        ),
        _stream_event(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}
        ),
        _line(
            type="assistant",
            message={
                "id": "msg_01",
                "model": answering,
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {}}],
                "usage": FIRST_START,
            },
            parent_tool_use_id=None,
        ),
        _stream_event({"type": "content_block_stop", "index": 0}),
        _stream_event({"type": "message_delta", "usage": FIRST_FINAL}, api_message_id="msg_01"),
        _stream_event({"type": "message_stop"}, api_message_id="msg_01"),
        _line(
            type="user",
            message={
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "x"}],
            },
            parent_tool_use_id=None,
        ),
    ]
    cut = [
        _stream_event(
            {"type": "message_start", "message": {"id": "msg_02", "usage": CUT_START}},
            api_message_id="msg_02",
        ),
        _stream_event(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
            api_message_id="msg_02",
        ),
        _stream_event(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "Reading the plan"},
            },
            api_message_id="msg_02",
        ),
    ]
    if cut_assistant:
        cut.append(
            _line(
                type="assistant",
                message={
                    "id": "msg_02",
                    "model": answering,
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "Reading the plan"}],
                    "usage": CUT_START,
                },
                parent_tool_use_id=None,
            )
        )
    if cut_delta:
        cut.append(
            _stream_event(
                {"type": "message_delta", "usage": {**CUT_START, "output_tokens": 40}},
                api_message_id="msg_02",
            )
        )
    stop: dict[str, Any] = {"api_message_id": "msg_02"}
    if with_marker:
        named = {} if marker is None else {"api_message_id": marker}
        stop["abandoned_blocks"] = {**named, "from_block_index": 0}
    cut.append(_stream_event({"type": "message_stop"}, **stop))
    error = _line(
        type="assistant",
        message={
            "id": "5e0c2a51-0000-4000-8000-000000000000",
            "model": "<synthetic>",
            "role": "assistant",
            "content": [{"type": "text", "text": ERROR_TEXT}],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
        parent_tool_use_id=None,
        error="unknown",
        is_api_error_message=True,
    )
    end = _result(CHARGED) if result is None else result
    return "\n".join([*first, *cut, error, end]) + "\n"


def _abandoned(line: MessageUsage) -> bool:
    return bool(getattr(line, "abandoned", False))


def _refusal(result: dict[str, Any] | None, usages: tuple[MessageUsage, ...]) -> object:
    try:
        require_matching_totals(result, usages)
    except AccountingError as exc:
        return exc
    return None


def _usage(started: dict[str, int]) -> Usage:
    return Usage(**started)


# --- the stream and the account -------------------------------------------------------------


def test_the_cut_response_is_its_own_line_marked_abandoned_with_the_usage_it_started_with() -> None:
    result, usages, answered = decompose.read_stream(cut_stream())
    by_id = {u.message_id: u for u in usages}
    assert by_id["msg_01"].usage == _usage(FIRST_FINAL) and not _abandoned(by_id["msg_01"])
    assert by_id["msg_02"].usage == _usage(CUT_START)
    assert _abandoned(by_id["msg_02"]), "the cut response is not marked abandoned"
    # The binary's own error message is no model's answer and spent nothing.
    assert answered == frozenset({MODEL, "<synthetic>"})
    assert not any(_abandoned(u) for k, u in by_id.items() if k != "msg_02")


def test_an_api_error_end_holds_the_completed_responses_to_the_totals_and_does_not_refuse() -> None:
    result, usages, _ = decompose.read_stream(cut_stream())
    assert _refusal(result, usages) is None
    # And the session's end is the API error, which every session's end is read as.
    end = classify_session_end(result, exit_code=1, stopped_at_wall_clock=False)
    assert (end.outcome, end.cause) == ("infrastructure", "api_error")


def test_a_completed_response_the_totals_do_not_bear_out_is_still_refused_at_an_api_error() -> None:
    short = _result({**CHARGED, "outputTokens": 179})
    result, usages, _ = decompose.read_stream(cut_stream(result=short))
    refused = _refusal(result, usages)
    assert isinstance(refused, AccountingError)
    assert refused.context == {"field": "output_tokens", "account": "180", "result": "179"}


def test_totals_that_charge_the_cut_response_too_are_refused() -> None:
    # Exact equality, one way only: totals that count the cut response as charged are not
    # what the binary was measured to write, and are no account the cut line explains.
    both = _result(
        {
            "inputTokens": 4,
            "outputTokens": 181,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 102225,
        }
    )
    result, usages, _ = decompose.read_stream(cut_stream(result=both))
    assert isinstance(_refusal(result, usages), AccountingError)


@pytest.mark.parametrize(
    ("terminal", "is_error"),
    [("completed", False), ("max_turns", True), ("prompt_too_long", True), ("api_error", False)],
)
def test_a_cut_response_in_a_session_that_did_not_end_in_an_api_error_is_refused(
    terminal: str, is_error: bool
) -> None:
    ended = _result(CHARGED, is_error=is_error, terminal=terminal)
    result, usages, _ = decompose.read_stream(cut_stream(result=ended))
    assert any(_abandoned(u) for u in usages), "the cut response is not marked abandoned"
    refused = _refusal(result, usages)
    assert isinstance(refused, AccountingError), "a cut response outside an API error passed"
    assert refused.context.get("message_id") == "msg_02"


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param({"cut_delta": True}, id="a response with its delta"),
        pytest.param({"cut_assistant": True}, id="a response with an assistant message"),
        pytest.param({"marker": "msg_99"}, id="a marker naming another response"),
        pytest.param({"marker": None}, id="a marker naming no response"),
        pytest.param({"with_marker": False}, id="no marker at all"),
    ],
)
def test_a_response_the_binary_did_not_close_as_cut_is_never_abandoned(
    shape: dict[str, Any],
) -> None:
    result, usages, _ = decompose.read_stream(cut_stream(**shape))
    (cut,) = [u for u in usages if u.message_id == "msg_02"]
    assert not _abandoned(cut)
    # So it is counted, and the totals that do not charge it refuse the account.
    refused = _refusal(result, usages)
    assert isinstance(refused, AccountingError)
    assert refused.context["field"] == "input_tokens"


def test_a_stream_with_no_result_is_unchecked_and_keeps_the_cut_line_marked() -> None:
    text = cut_stream().rsplit("\n", 2)[0] + "\n"  # the result event gone
    result, usages, _ = decompose.read_stream(text)
    assert result is None
    assert [u.message_id for u in usages if _abandoned(u)] == ["msg_02"]
    assert _refusal(result, usages) is None


# --- the compaction line, the reviewer's reading of the totals --------------------------------


def test_the_compaction_line_reads_no_compaction_from_an_api_error_with_a_cut_response() -> None:
    result, usages, _ = decompose.read_stream(cut_stream())
    try:
        line = compaction_line(result, usages, compactions=0, message_id="compaction-1")
    except AccountingError as exc:
        pytest.fail(f"the compaction line refused the API error's account: {exc.context}")
    assert line is None


def test_a_compaction_s_call_is_the_totals_less_the_charged_responses_not_the_cut_one() -> None:
    summary = {
        "inputTokens": 3,
        "outputTokens": 500,
        "cacheReadInputTokens": 1000,
        "cacheCreationInputTokens": 0,
    }
    totals = {k: CHARGED[k] + summary[k] for k in CHARGED}
    result, usages, _ = decompose.read_stream(cut_stream(result=_result(totals)))
    try:
        line = compaction_line(result, usages, compactions=1, message_id="compaction-1")
    except AccountingError as exc:
        pytest.fail(f"the compaction line refused the API error's account: {exc.context}")
    assert line is not None and line.compaction and not _abandoned(line)
    assert line.usage == Usage(
        input_tokens=3,
        output_tokens=500,
        cache_read_input_tokens=1000,
        cache_creation_input_tokens=0,
    )


def test_a_compacted_session_with_a_cut_response_that_did_not_end_in_an_api_error_is_refused() -> (
    None
):
    ended = _result(CHARGED, is_error=False, terminal="completed")
    result, usages, _ = decompose.read_stream(cut_stream(result=ended))
    assert any(_abandoned(u) for u in usages), "the cut response is not marked abandoned"
    with pytest.raises(AccountingError) as caught:
        compaction_line(result, usages, compactions=1, message_id="compaction-1")
    assert caught.value.context.get("message_id") == "msg_02"


# --- the token account: recorded, visible, not charged ----------------------------------------


def _require_the_mark() -> None:
    assert "abandoned" in MessageUsage.model_fields, "a usage line cannot be marked abandoned"
    assert "abandoned" in TokensUsed.model_fields, "a token line cannot be marked abandoned"


def test_the_account_charges_no_cut_line_and_shows_it_apart_from_a_fresh_read_of_the_log(
    tmp_path: Path,
) -> None:
    _require_the_mark()
    _, usages, _ = decompose.read_stream(cut_stream())
    path = tmp_path / "events.jsonl"
    log = EventLog(path, run_id="run-1", gate_mode="on")
    log.emit(RunStarted, config_sha256="c" * 64)
    for line in usages:
        log.emit(
            TokensUsed,
            attribution="reviewer:rev-1",
            message_id=line.message_id,
            usage=line.usage,
            abandoned=line.abandoned,
        )
    log.close()
    raw = [json.loads(x) for x in path.read_text().splitlines() if '"tokens_used"' in x]
    # The cut line says so in its own words; every other line keeps its bytes.
    assert [r["message_id"] for r in raw if r.get("abandoned") is True] == ["msg_02"]
    assert all("abandoned" not in r for r in raw if r["message_id"] != "msg_02")
    account = TokenAccount.from_events(read_events(path))
    charged = account.by_attribution()["reviewer:rev-1"]
    assert charged == _usage(FIRST_FINAL), "the cut response was charged"
    assert account.total() == charged
    assert account.abandoned() == {"reviewer:rev-1": _usage(CUT_START)}
    # Every charged token is in exactly one kind, the cut one in none.
    assert sum(u.total() for u in account.by_kind().values()) == charged.total()


def test_one_message_recorded_once_cut_and_once_charged_is_an_error_not_a_choice() -> None:
    _require_the_mark()
    account = TokenAccount()
    account.add("session:a", "m1", _usage(CUT_START), abandoned=True)
    with pytest.raises(AccountingError):
        account.add("session:a", "m1", _usage(CUT_START))


def test_a_line_cannot_be_both_a_compaction_s_call_and_a_cut_response() -> None:
    _require_the_mark()
    with pytest.raises(ValueError, match="compaction"):
        MessageUsage(message_id="m", usage=_usage(CUT_START), compaction=True, abandoned=True)


# --- every caller: the plan call, a role session, a leftover, a review -----------------------


def test_the_plan_call_ends_as_its_api_error_with_the_cut_line_on_its_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = cut_stream()

    def ran(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        return subprocess.CompletedProcess(argv, 1, stdout=stream, stderr="")

    monkeypatch.setattr(decompose, "claude_binary", lambda: "/nonexistent/claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.272")
    monkeypatch.setattr(subprocess, "run", ran)
    # No binary ran, so no debug log or managed tier says anything; only the stream's end is read.
    monkeypatch.setattr(decompose, "traffic_refusal", lambda *a, **k: None)
    monkeypatch.setattr(decompose, "drift", lambda *a, **k: None)
    try:
        outcome = decompose.call(
            "Build a robot.\n",
            config=make_config(),
            workdir=tmp_path / "decomposition",
            base_url=None,
            credential=Credential(mode="api_key", secret="sk-ant-test-dummy-not-a-credential"),
        )
    except AccountingError as exc:
        pytest.fail(f"the plan call's API error was refused as an account: {exc.context}")
    assert (outcome.ok, outcome.cause) == (False, "api_error")
    assert [u.message_id for u in outcome.usage if _abandoned(u)] == ["msg_02"]


def test_a_role_session_s_end_is_read_as_its_api_error_after_its_account_holds() -> None:
    # The dispatcher's own steps after a session ends, in its order, on the session's bytes.
    data = cut_stream().encode()
    captured = captured_from(data)
    assert captured.tampered is None
    assert _refusal(captured.result, captured.usage) is None
    end, limit = session_end(
        data,
        captured.result,
        exit_code=1,
        stopped_at_wall_clock=False,
        lost=captured.lost,
        claude_version="2.1.301",
    )
    assert (end.outcome, end.cause, limit) == ("infrastructure", "api_error", None)
    assert [u.message_id for u in captured.usage if _abandoned(u)] == ["msg_02"]


@pytest.mark.parametrize("ending", ["api_error", "completed"])
def test_a_leftover_cut_at_an_api_error_is_whole_and_one_cut_otherwise_is_reported(
    tmp_path: Path, ending: str
) -> None:
    from left_session import INSTALL_BIN, sentinel_installed, spawn_logged

    run_dir = tmp_path / "run"
    sdir = run_dir / "sessions" / "cut"
    sdir.mkdir(parents=True)
    started = "Mon Jan  1 00:00:00 2001"
    record = {"pid": 999_999, "started": started, "session_id": "cut"}
    (sdir / "process.json").write_text(json.dumps(record))
    spawn_logged(run_dir, [("cut", 999_999, started)])
    sentinel_installed(sdir, run_dir / "guarded")
    ended = (
        None if ending == "api_error" else _result(CHARGED, is_error=False, terminal="completed")
    )
    (sdir / "stdout.jsonl").write_text(cut_stream(result=ended))
    dispatcher = ClaudeDispatcher(
        config=make_config(),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=INSTALL_BIN,
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=Path("/nonexistent/review-scratch"),
    )
    (left,) = dispatcher.stop_leftovers()
    assert left.complete is True
    assert [u.message_id for u in left.usage if _abandoned(u)] == ["msg_02"]
    if ending == "api_error":
        assert left.tampered is None, left.tampered
    else:
        assert left.tampered is not None and "msg_02" in left.tampered


def _review_setup(tmp_path: Path) -> ReviewerSetup:
    return ReviewerSetup(
        run_id="run-1",
        models={"control": MODEL},
        claude_version="2.1.301",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "rs",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
        held_out_canaries=(),
    )


def _reviewed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stream: str) -> object:
    """A review whose session wrote ``stream``, read by the reviewer's own conclusion."""
    read = tmp_path / "rs" / "review" / "read"
    read.mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), indicators=(), sha256=lambda: "0" * 64)
    stdout = tmp_path / "stdout.jsonl"
    stdout.write_text(stream)
    monkeypatch.setattr(claude, "binary_version", lambda binary: "2.1.301")
    monkeypatch.setattr(claude, "review_dir", lambda root, sid: tmp_path / "rs" / "review")
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda self, review, a, sid: packet)
    monkeypatch.setattr(
        ClaudeReviewer,
        "_install",
        lambda *_a: Installed(settings="s", config="c", spawn_args=(), spawn_env={}),
    )
    monkeypatch.setattr(ClaudeReviewer, "_spawn", lambda self, *a, **k: (stdout, 1, False))
    monkeypatch.setattr(claude, "review_prompt", lambda *a, **k: "p")
    monkeypatch.setattr(claude, "remove_secrets", lambda *a: None)
    monkeypatch.setattr(claude, "redact", lambda *a: None)
    monkeypatch.setattr(claude, "verdict_schema", lambda *a, **k: {})
    monkeypatch.setattr(claude, "contract_text", lambda *a, **k: "c")
    rubric = Rubric(role="control", text="r", sha256="0" * 64)
    reviewer = ClaudeReviewer(role="control", setup=_review_setup(tmp_path), rubric=rubric)
    try:
        return reviewer.review(SimpleNamespace())  # type: ignore[arg-type]
    except (ReviewUnavailableError, AccountingError) as exc:
        return exc


def test_a_review_cut_by_a_network_break_is_an_infrastructure_end_with_its_cut_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised = _reviewed(tmp_path, monkeypatch, cut_stream())
    assert isinstance(raised, ReviewUnavailableError), f"not the review's own end: {raised!r}"
    assert raised.cause == "infrastructure"
    assert "api_error" in str(raised)
    assert [u.message_id for u in raised.usage if _abandoned(u)] == ["msg_02"]


def test_a_review_whose_completed_response_the_totals_do_not_bear_out_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    short = _result({**CHARGED, "inputTokens": 1})
    raised = _reviewed(tmp_path, monkeypatch, cut_stream(result=short))
    assert isinstance(raised, AccountingError)
    assert raised.context["field"] == "input_tokens"


# --- the loop: the existing retry, and the line in the record ---------------------------------


def _cut_lines() -> tuple[MessageUsage, ...]:
    _, usages, _ = decompose.read_stream(cut_stream())
    return usages


@pytest.fixture
def cut_lines() -> tuple[MessageUsage, ...]:
    return _cut_lines()


def test_a_role_session_s_api_error_is_retried_and_its_cut_line_is_recorded_not_charged(
    tmp_path: Path, cut_lines: tuple[MessageUsage, ...]
) -> None:
    _require_the_mark()

    class _Cut(FakeDispatcher):
        def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401
            report = super().run(request, on_spawn)
            if len(self.requests) == 1:
                return report.model_copy(update={"usage": cut_lines})
            return report

    rig = Rig(tmp_path, dispatcher=_Cut(infra={1: "api_error"}), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    ends = [e for e in events if isinstance(e, SessionEnded)]
    assert [(e.outcome, e.cause) for e in ends][:1] == [("infrastructure", "api_error")]
    assert len(rig.dispatcher.requests) == 2  # the existing retry, after the API error
    cut = [e for e in events if isinstance(e, TokensUsed) and e.abandoned]
    assert [(e.attribution, e.message_id) for e in cut] == [("session:sess-1", "msg_02")]
    account = TokenAccount.from_events(events)
    assert account.by_attribution()["session:sess-1"] == _usage(FIRST_FINAL)
    assert account.abandoned() == {"session:sess-1": _usage(CUT_START)}


def test_a_role_review_s_api_error_is_retried_and_its_cut_line_is_recorded_not_charged(
    tmp_path: Path, cut_lines: tuple[MessageUsage, ...]
) -> None:
    _require_the_mark()
    cut = ReviewUnavailableError(
        "the session ended with api_error",
        cause="infrastructure",
        session_id="rev-cut",
        reviewer_model="claude-opus-5-5",
        usage=cut_lines,
    )
    rig = Rig(tmp_path, reviewer=FakeReviewer(unavailable={1: cut}), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    unavailable = [e for e in events if isinstance(e, ReviewUnavailable)]
    assert [(e.cause, e.retry) for e in unavailable] == [("infrastructure", True)]
    marked = [e for e in events if isinstance(e, TokensUsed) and e.abandoned]
    assert [(e.attribution, e.message_id) for e in marked] == [("reviewer:rev-cut", "msg_02")]
    account = TokenAccount.from_events(events)
    assert account.by_attribution()["reviewer:rev-cut"] == _usage(FIRST_FINAL)
    assert account.abandoned() == {"reviewer:rev-cut": _usage(CUT_START)}


# --- the run record: the plan call's and the plan review's lines ------------------------------


def _envelope() -> Any:  # noqa: ANN401 - an envelope as the log fills one in
    return {"seq": 1, "ts": "2026-11-18T00:00:00.000000Z", "run_id": "run-1", "gate_mode": "on"}


def test_the_plan_call_s_cut_line_is_recorded_marked(
    cut_lines: tuple[MessageUsage, ...],
) -> None:
    _require_the_mark()
    from physgate.orchestrator.record import DecompositionCall, RunRecord

    call = DecompositionCall(session_id="dec-1", usage=cut_lines)
    lines = [e for e in RunRecord._spent(call, _envelope, ()) if isinstance(e, TokensUsed)]
    marked = [(e.attribution, e.message_id) for e in lines if e.abandoned]
    assert marked == [("decomposition:dec-1", "msg_02")]
    account = TokenAccount.from_events(lines)
    assert account.by_attribution()["decomposition:dec-1"] == _usage(FIRST_FINAL)
    assert account.decomposition_invocations() == 1


def test_the_plan_review_s_cut_line_is_recorded_marked_beside_its_infrastructure_end(
    cut_lines: tuple[MessageUsage, ...],
) -> None:
    _require_the_mark()
    from physgate.orchestrator.events import DesignReviewRan, DesignUnavailable
    from physgate.orchestrator.record import RoundReview, RunRecord
    from physgate.orchestrator.trajectory import seal

    reviewed = RoundReview(
        stream_seal=seal(b"the plan call's stream\n"),
        session_id="rev-plan",
        usage=cut_lines,
        unavailable=DesignUnavailable(
            cause="infrastructure",
            detail="the session ended with api_error",
            session_id="rev-plan",
            reviewer_model="claude-opus-5-5",
        ),
    )
    owner = SimpleNamespace(config=SimpleNamespace(design_review="observe"))
    lines = list(RunRecord._reviewing(owner, reviewed, "0" * 64, _envelope, None))  # type: ignore[arg-type]
    marked = [
        (e.attribution, e.message_id) for e in lines if isinstance(e, TokensUsed) and e.abandoned
    ]
    assert marked == [("reviewer:rev-plan", "msg_02")]
    (ran,) = [e for e in lines if isinstance(e, DesignReviewRan)]
    assert ran.unavailable is not None and ran.unavailable.cause == "infrastructure"
