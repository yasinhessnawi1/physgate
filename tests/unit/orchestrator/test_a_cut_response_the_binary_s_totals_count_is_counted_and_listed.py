"""A response cut short that the binary's totals count is counted, listed, and refuses nothing.

A session's network broke mid-response. The binary closed the response itself (a
``message_stop`` whose ``abandoned_blocks`` names it) and then either retried and completed,
or ended in an API error. At the scripted endpoint, on both pinned binaries (2.1.301 and
2.1.322), the binary's per-model totals (``modelUsage``) then count the cut response's starting
usage, in both ends, and its top-level ``usage`` does too (the integration rows measure it on
each pin). A real run's review on 2.1.301 showed the other shape: an API error whose totals
leave the cut response out. The stream does not say which shape a session had; the totals do.

So a session whose totals equal every line, the cut responses included, is counted as they
count it: each cut response is still its own line, marked as cut short and as counted, listed
apart, and the cost is a lower bound (its streamed output is in nobody's figure). Totals that
leave the cut response out are read as before: only at an API-error end. Any other figure is
refused, as is a session whose totals count some of its cut responses and not others.

The streams here are built by hand in the event shapes the binaries wrote at the scripted
endpoint; none is a copy of a run's transcript.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import make_config
from test_a_response_cut_short_by_an_api_error_is_kept_apart_from_the_binary_s_totals import (
    CHARGED,
    CUT_START,
    FIRST_FINAL,
    MODEL,
    _abandoned,
    _line,
    _result,
    _reviewed,
    _stream_event,
    _usage,
    cut_stream,
)

import physgate.orchestrator.decompose as decompose
from physgate.orchestrator.accounting import TokenAccount, require_matching_totals
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher, captured_from
from physgate.orchestrator.events import EventLog, RunStarted, TokensUsed, read_events
from physgate.orchestrator.exceptions import AccountingError
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.usage_limit import session_end

#: The retry's usage: what the request that completed after the cut one started and ended with.
RETRY_START = {
    "input_tokens": 3,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 55515,
    "output_tokens": 1,
}
RETRY_FINAL = {**RETRY_START, "output_tokens": 240}


def _totals(*parts: dict[str, int]) -> dict[str, int]:
    return {
        "inputTokens": sum(p["input_tokens"] for p in parts),
        "outputTokens": sum(p["output_tokens"] for p in parts),
        "cacheReadInputTokens": sum(p["cache_read_input_tokens"] for p in parts),
        "cacheCreationInputTokens": sum(p["cache_creation_input_tokens"] for p in parts),
    }


#: What both pins' totals counted at the scripted endpoint: every response, the cut one too.
COUNTING_THE_CUT = _totals(FIRST_FINAL, CUT_START, RETRY_FINAL)
#: Totals that leave the cut response out, as the real run's API-error end had them.
LEAVING_IT_OUT = _totals(FIRST_FINAL, RETRY_FINAL)


def retried_stream(
    totals: dict[str, int] = COUNTING_THE_CUT,
    *,
    terminal: str = "completed",
    is_error: bool = False,
) -> str:
    """One complete response, one cut short, the binary's retry, and the retry completed."""
    lines = cut_stream(result="").splitlines()
    # Everything up to the cut response's closing line, which the binary marks; then the retry.
    at = next(i for i, x in enumerate(lines) if '"abandoned_blocks"' in x)
    retry = [
        _line(type="system", subtype="api_retry", attempt=1, error="unknown", session_id="s"),
        _stream_event(
            {"type": "message_start", "message": {"id": "msg_03", "usage": RETRY_START}},
            api_message_id="msg_03",
        ),
        _stream_event(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
            api_message_id="msg_03",
        ),
        _line(
            type="assistant",
            message={
                "id": "msg_03",
                "model": MODEL,
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
                "usage": RETRY_START,
            },
            parent_tool_use_id=None,
        ),
        _stream_event({"type": "content_block_stop", "index": 0}, api_message_id="msg_03"),
        _stream_event({"type": "message_delta", "usage": RETRY_FINAL}, api_message_id="msg_03"),
        _stream_event({"type": "message_stop"}, api_message_id="msg_03"),
    ]
    end = _result(totals, is_error=is_error, terminal=terminal)
    return "\n".join([*lines[: at + 1], *retry, end]) + "\n"


def _refusal(result: dict[str, Any] | None, usages: tuple[MessageUsage, ...]) -> object:
    try:
        require_matching_totals(result, usages)
    except AccountingError as exc:
        return exc
    return None


def _counted(line: MessageUsage | TokensUsed) -> bool:
    """Whether the line is marked as one the binary's totals count, cut short or not."""
    return bool(getattr(line, "in_binary_totals", False))


RULE = "a cut response the binary's totals count is counted and listed, and refuses nothing"


# --- the totals check -------------------------------------------------------------------------


def test_a_retry_that_completed_after_a_cut_response_is_not_refused() -> None:
    result, usages, _ = decompose.read_stream(retried_stream())
    assert [u.message_id for u in usages if _abandoned(u)] == ["msg_02"]
    refused = _refusal(result, usages)
    assert refused is None, f"{RULE}: refused with {refused!r}"


def test_the_check_returns_the_cut_response_marked_as_the_totals_count_it() -> None:
    result, usages, _ = decompose.read_stream(retried_stream())
    try:
        settled = require_matching_totals(result, usages)
    except AccountingError as exc:
        pytest.fail(f"{RULE}: refused with {exc.context}")
    assert settled is not None, f"{RULE}: the check returns no lines to record"
    by_id = {u.message_id: u for u in settled}
    assert _abandoned(by_id["msg_02"]) and _counted(by_id["msg_02"]), RULE
    # Every other line keeps its bytes.
    assert by_id["msg_01"] == next(u for u in usages if u.message_id == "msg_01")
    assert not any(_counted(u) for k, u in by_id.items() if k != "msg_02")


def test_an_api_error_end_whose_totals_count_the_cut_response_is_not_refused() -> None:
    # The other end measured at the scripted endpoint: the network stayed down, the binary
    # gave up, and its totals still counted what the cut response started with.
    ended = _result(_totals(FIRST_FINAL, CUT_START))
    result, usages, _ = decompose.read_stream(cut_stream(result=ended))
    try:
        settled = require_matching_totals(result, usages)
    except AccountingError as exc:
        pytest.fail(f"{RULE}: an API error's end was refused with {exc.context}")
    (cut,) = [u for u in settled if u.message_id == "msg_02"]
    assert _abandoned(cut) and _counted(cut), RULE


def test_totals_that_leave_the_cut_response_out_are_still_read_only_at_an_api_error() -> None:
    result, usages, _ = decompose.read_stream(retried_stream(LEAVING_IT_OUT))
    refused = _refusal(result, usages)
    assert isinstance(refused, AccountingError), "a completed end left the cut response out"
    assert refused.context.get("message_id") == "msg_02"
    at_an_api_error = _result(CHARGED)
    result, usages, _ = decompose.read_stream(cut_stream(result=at_an_api_error))
    settled = require_matching_totals(result, usages)
    (cut,) = [u for u in settled if u.message_id == "msg_02"]
    assert _abandoned(cut) and not _counted(cut)


def test_a_completed_response_the_totals_do_not_bear_out_is_still_refused() -> None:
    short = {**COUNTING_THE_CUT, "outputTokens": COUNTING_THE_CUT["outputTokens"] - 1}
    result, usages, _ = decompose.read_stream(retried_stream(short))
    assert isinstance(_refusal(result, usages), AccountingError)


def test_totals_that_count_one_cut_response_and_not_another_are_refused() -> None:
    # A second cut response, closed the same way: the totals count the first and not it.
    lines = retried_stream(COUNTING_THE_CUT).splitlines()
    second = [
        _stream_event(
            {"type": "message_start", "message": {"id": "msg_04", "usage": CUT_START}},
            api_message_id="msg_04",
        ),
        _stream_event(
            {"type": "message_stop"},
            api_message_id="msg_04",
            abandoned_blocks={"api_message_id": "msg_04", "from_block_index": 0},
        ),
    ]
    text = "\n".join([*lines[:-1], *second, lines[-1]]) + "\n"
    result, usages, _ = decompose.read_stream(text)
    assert sorted(u.message_id for u in usages if _abandoned(u)) == ["msg_02", "msg_04"]
    assert isinstance(_refusal(result, usages), AccountingError)


def test_a_line_counted_by_the_totals_is_a_cut_response_and_no_compaction() -> None:
    with pytest.raises(ValueError, match="cut short"):
        MessageUsage(message_id="m", usage=_usage(CUT_START), in_binary_totals=True)
    with pytest.raises(ValueError, match="cut short"):
        TokensUsed(
            seq=1,
            ts="2026-11-19T00:00:00.000000Z",
            run_id="run-1",
            gate_mode="on",
            attribution="session:a",
            message_id="m",
            usage=_usage(CUT_START),
            in_binary_totals=True,
        )


def test_a_result_with_no_totals_leaves_every_line_as_it_was_settled() -> None:
    # A resumed invocation killed before its result: the lines an earlier result settled keep
    # their marks, and a cut response read from a stream with no result is not counted.
    settled = _settled()
    assert require_matching_totals(None, settled) == settled
    text = retried_stream().rsplit("\n", 2)[0] + "\n"  # the result event gone
    result, usages, _ = decompose.read_stream(text)
    assert result is None
    (cut,) = [u for u in require_matching_totals(result, usages) if u.abandoned]
    assert not _counted(cut)


# --- the account -----------------------------------------------------------------


def _logged(tmp_path: Path, lines: tuple[MessageUsage, ...]) -> Path:
    path = tmp_path / "events.jsonl"
    log = EventLog(path, run_id="run-1", gate_mode="on")
    log.emit(RunStarted, config_sha256="c" * 64)
    for line in lines:
        log.emit(
            TokensUsed,
            attribution="reviewer:rev-1",
            message_id=line.message_id,
            usage=line.usage,
            abandoned=line.abandoned,
            in_binary_totals=getattr(line, "in_binary_totals", False),
        )
    log.close()
    return path


def _settled() -> tuple[MessageUsage, ...]:
    result, usages, _ = decompose.read_stream(retried_stream())
    settled = require_matching_totals(result, usages)
    assert settled is not None, f"{RULE}: the check returns no lines to record"
    return settled


def test_the_account_counts_the_cut_response_the_totals_count_and_lists_it(tmp_path: Path) -> None:
    assert "in_binary_totals" in TokensUsed.model_fields, f"{RULE}: no line can say so"
    path = _logged(tmp_path, _settled())
    raw = [json.loads(x) for x in path.read_text().splitlines() if '"tokens_used"' in x]
    marked = [r["message_id"] for r in raw if r.get("in_binary_totals") is True]
    assert marked == ["msg_02"]
    assert all("in_binary_totals" not in r for r in raw if r["message_id"] != "msg_02")
    account = TokenAccount.from_events(read_events(path))
    every = Usage(
        input_tokens=COUNTING_THE_CUT["inputTokens"],
        output_tokens=COUNTING_THE_CUT["outputTokens"],
        cache_read_input_tokens=COUNTING_THE_CUT["cacheReadInputTokens"],
        cache_creation_input_tokens=COUNTING_THE_CUT["cacheCreationInputTokens"],
    )
    assert account.by_attribution() == {"reviewer:rev-1": every}, RULE
    assert account.total() == every
    assert account.cut_in_binary_totals() == {"reviewer:rev-1": _usage(CUT_START)}, RULE
    # Not among the responses the totals leave out, whose billing is unknown.
    assert account.abandoned() == {}


def test_the_operator_s_token_reader_lists_the_counted_cut_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.ui.readers as readers

    path = _logged(tmp_path, _settled())
    monkeypatch.setattr(readers, "run_dir_of", lambda context, params: path.parent)
    monkeypatch.setattr(readers, "_file", lambda context, run_dir, *parts: run_dir.joinpath(*parts))
    served = json.loads(readers.tokens(None, {}).body)  # type: ignore[arg-type]
    assert served.get("cut_short_in_binary_totals") == {
        "reviewer:rev-1": _usage(CUT_START).model_dump(mode="json")
    }, RULE
    assert served["not_in_binary_totals_billing_unknown"] == {}


# --- every caller: a role session, a leftover, the plan call, a review, the loop -------------


def test_a_role_session_that_retried_after_a_cut_response_ends_as_it_ended() -> None:
    data = retried_stream().encode()
    captured = captured_from(data)
    assert captured.tampered is None
    refused = _refusal(captured.result, captured.usage)
    assert refused is None, f"{RULE}: refused with {refused!r}"
    end, limit = session_end(
        data,
        captured.result,
        exit_code=0,
        stopped_at_wall_clock=False,
        lost=captured.lost,
        claude_version="2.1.301",
    )
    assert (end.outcome, limit) == ("completed", None)


def test_a_leftover_that_retried_after_a_cut_response_is_whole_and_counted(
    tmp_path: Path,
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
    (sdir / "stdout.jsonl").write_text(retried_stream())
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
    assert left.tampered is None, f"{RULE}: {left.tampered}"
    assert [u.message_id for u in left.usage if _counted(u)] == ["msg_02"], RULE


def test_the_plan_call_that_retried_after_a_cut_response_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stream = retried_stream()

    def ran(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        return subprocess.CompletedProcess(argv, 0, stdout=stream, stderr="")

    monkeypatch.setattr(decompose, "claude_binary", lambda: "/nonexistent/claude")
    monkeypatch.setattr(decompose, "binary_version", lambda binary=None: "2.1.272")
    monkeypatch.setattr(subprocess, "run", ran)
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
        pytest.fail(f"{RULE}: the plan call was refused with {exc.context}")
    assert [u.message_id for u in outcome.usage if _counted(u)] == ["msg_02"], RULE


def test_a_review_that_retried_after_a_cut_response_is_no_refused_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raised = _reviewed(tmp_path, monkeypatch, retried_stream())
    assert not isinstance(raised, AccountingError), f"{RULE}: refused with {raised!r}"
    usage = getattr(raised, "usage", ())
    assert [u.message_id for u in usage if _counted(u)] == ["msg_02"], RULE


def test_the_loop_records_the_counted_cut_line_and_counts_it(tmp_path: Path) -> None:
    lines = _settled()

    class _Retried(FakeDispatcher):
        def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401
            report = super().run(request, on_spawn)
            return report.model_copy(update={"usage": lines})

    rig = Rig(tmp_path, dispatcher=_Retried())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    marked = [e for e in events if isinstance(e, TokensUsed) and _counted(e)]
    assert [(e.attribution, e.message_id) for e in marked] == [("session:sess-1", "msg_02")], RULE
    account = TokenAccount.from_events(events)
    assert account.cut_in_binary_totals() == {"session:sess-1": _usage(CUT_START)}
    assert account.by_attribution()["session:sess-1"].total() == sum(u.usage.total() for u in lines)


#: A stand-in role session: its hooks run, and it writes the retried stream as its own, answered
#: by the run's model. The stand-in module's prelude is prepended.
PRINTS_THE_STREAM = r"""
import json, os, shlex, subprocess, sys

argv = sys.argv[1:]
if argv == ["--version"]:
    print("2.1.272 (Claude Code)")
    sys.exit(0)
settings = json.load(open(argv[argv.index("--settings") + 1]))
session_id = argv[argv.index("--session-id") + 1]


def hook(event):
    command = settings["hooks"][event][0]["hooks"][0]["command"]
    body = json.dumps({"session_id": session_id, "cwd": os.getcwd(), "hook_event_name": event})
    subprocess.run(shlex.split(command), input=body.encode(), capture_output=True, check=False)


hook("SessionStart")
hook("SessionEnd")
sys.stdout.write(STREAM.replace(ANSWERING, MODEL_NAME))
sys.stdout.flush()
sys.exit(0)
"""


def test_the_dispatcher_reports_a_role_session_s_counted_cut_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_a_role_session_leaves_nothing_running_before_the_orchestrator_s_git import (
        SESSION,
        Session,
    )

    session = Session(tmp_path, "plain", pause=0.0, wall_clock_s=60.0)
    written = session.binary.read_text()
    stand_in = f"STREAM = {retried_stream()!r}\nANSWERING = {MODEL!r}\n" + PRINTS_THE_STREAM
    session.binary.write_text(written[: written.index(SESSION)] + stand_in)
    dispatcher = session.dispatcher(monkeypatch)
    try:
        report = dispatcher.run(session.request(), session.spawned)
    except AccountingError as exc:
        pytest.fail(f"{RULE}: the role session was refused with {exc.context}")
    assert report.end.outcome == "completed"
    assert [u.message_id for u in report.usage if _counted(u)] == ["msg_02"], RULE
