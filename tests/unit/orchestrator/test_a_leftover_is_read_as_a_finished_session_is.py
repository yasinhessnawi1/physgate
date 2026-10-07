"""At a resume, a leftover session's stream is read as a finished session's is.

A session that ended while its orchestrator was down left a stream no one read.
The resume reads it through the same path as a session that ended under the
loop: sealed as read, parsed only up to the runtime's result, and held to that
result's totals. A tail or totals the result does not bear out are an incident,
never usage; a stream with no result is partial.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.credentials import KEY_HELPER, Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Incident, LeftoverRead, TokensUsed, read_events
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import Leftover
from physgate.orchestrator.protocols import MessageUsage, Usage
from physgate.orchestrator.trajectory import seal


def _line(event: dict[str, object]) -> str:
    return json.dumps(event)


def _message(message_id: str, input_tokens: int) -> list[str]:
    usage = {"input_tokens": input_tokens, "output_tokens": 5}
    return [
        _line(
            {
                "type": "stream_event",
                "event": {"type": "message_start", "message": {"id": message_id, "usage": usage}},
            }
        ),
        _line(
            {
                "type": "assistant",
                "message": {"id": message_id, "model": "claude-sonnet-5", "usage": usage},
            }
        ),
        _line({"type": "stream_event", "event": {"type": "message_delta", "usage": usage}}),
    ]


def _result(input_tokens: int) -> str:
    totals = {"inputTokens": input_tokens, "outputTokens": 5}
    return _line({"type": "result", "modelUsage": {"claude-sonnet-5": totals}})


def _left(run_dir: Path, session: str, lines: list[str]) -> Path:
    sdir = run_dir / "sessions" / session
    sdir.mkdir(parents=True)
    # A process that is not running: the session finished while its orchestrator was down.
    record = {"pid": 999_999, "started": "Mon Jan  1 00:00:00 2001", "session_id": session}
    (sdir / "process.json").write_text(json.dumps(record))
    stream = sdir / "stdout.jsonl"
    stream.write_text("\n".join(lines) + "\n")
    return stream


def _dispatcher(run_dir: Path) -> ClaudeDispatcher:
    from orch_helpers import make_config

    return ClaudeDispatcher(
        config=make_config(),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=run_dir / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=Path("/nonexistent/review-scratch"),
    )


def test_a_tail_after_a_leftover_s_result_is_not_taken_and_is_reported(tmp_path: Path) -> None:
    # The review's fixture: a real message, the result with its totals, then a tail
    # message carrying 999 999 input tokens.
    run_dir = tmp_path / "run"
    lines = [*_message("msg_real", 10), _result(10), *_message("msg_tail", 999_999)]
    stream = _left(run_dir, "tailed", lines)
    (left,) = _dispatcher(run_dir).stop_leftovers()
    assert [u.message_id for u in left.usage] == ["msg_real"]
    assert left.complete is True and left.tampered is not None
    assert "after its result" in left.tampered
    assert left.seal == seal(stream.read_bytes())


def test_a_leftover_with_no_result_is_partial_and_not_a_forgery(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    stream = _left(run_dir, "cut", _message("msg_real", 10))
    (left,) = _dispatcher(run_dir).stop_leftovers()
    assert [u.message_id for u in left.usage] == ["msg_real"]
    assert (left.complete, left.tampered) == (False, None)
    assert left.seal is not None
    assert left.seal.sha256 == hashlib.sha256(stream.read_bytes()).hexdigest()


def test_a_leftover_whose_result_does_not_bear_out_its_messages_is_reported(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "short", [*_message("msg_real", 10), _result(999_999)])
    (left,) = _dispatcher(run_dir).stop_leftovers()
    assert left.tampered is not None and "differs from the binary's own totals" in left.tampered


def test_a_clean_finished_leftover_is_complete_and_untouched(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "clean", [*_message("msg_real", 10), _result(10)])
    (left,) = _dispatcher(run_dir).stop_leftovers()
    assert (left.complete, left.tampered) == (True, None)


SPENT = MessageUsage(
    message_id="m-real",
    usage=Usage(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0
    ),
)


class _TamperedLeftover(FakeDispatcher):
    def stop_leftovers(self) -> list[Leftover]:
        return [
            Leftover(
                session_id="sess-old",
                pid=4242,
                killed=0,
                stopped=False,
                usage=(SPENT,),
                complete=True,
                seal=seal(b"the stream as read\n"),
                tampered="the stream goes on after its result event",
            )
        ]


def test_a_tampered_leftover_is_an_incident_its_read_sealed_its_runtime_usage_kept(
    tmp_path: Path,
) -> None:
    # The run's first act, before any dispatch, is to read what a previous process
    # left: a tampered leftover halts the run there.
    rig = Rig(tmp_path, dispatcher=_TamperedLeftover())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    assert rig.dispatcher.requests == []
    events = read_events(tmp_path / "events.jsonl")
    reads = [e for e in events if isinstance(e, LeftoverRead)]
    assert reads and reads[-1].trajectory_seal == seal(b"the stream as read\n")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert [e.cause for e in incidents][-1:] == ["trajectory_tampered"]
    assert "sess-old" in incidents[-1].detail
    spent = [e for e in events if isinstance(e, TokensUsed) and e.message_id == "m-real"]
    assert spent and not spent[-1].partial
    assert TokenAccount.from_events(events).by_attribution()["session:sess-old"] == SPENT.usage


def test_a_halted_run_s_resume_records_a_leftover_s_tokens(tmp_path: Path) -> None:
    # Token lines are recorded at any time: a run halted for exhausted retries is
    # resumed, and the leftover's spend is recorded before the resume continues.
    class _Left(FakeDispatcher):
        def stop_leftovers(self) -> list[Leftover]:
            return [
                Leftover(session_id="sess-old", pid=4242, killed=0, stopped=False, usage=(SPENT,))
            ]

    rig = Rig(tmp_path, dispatcher=_Left(infra={1: "api_error"}), delays=())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    again = rig.open()
    assert again.resume().kind == "done"
    again.close()
    events = read_events(tmp_path / "events.jsonl")
    assert any(isinstance(e, TokensUsed) and e.message_id == "m-real" and e.partial for e in events)


def _left_review(root: Path, review: str, run_id: str, lines: list[str]) -> Path:
    sdir = root / review / "session"
    (sdir / "state").mkdir(parents=True)
    (sdir / "owner.json").write_text(json.dumps({"run_id": run_id}))
    (sdir / "state" / KEY_HELPER).write_text("#!/bin/sh\necho secret\n")
    record = {
        "pid": 999_999,
        "started": "Mon Jan  1 00:00:00 2001",
        "session_id": review,
        "kind": "reviewer",
    }
    (sdir / "process.json").write_text(json.dumps(record))
    (sdir / "stdout.jsonl").write_text("\n".join(lines) + "\n")
    return sdir


def test_a_review_session_of_this_run_is_found_cleaned_and_its_tokens_are_the_reviewer_s(
    tmp_path: Path,
) -> None:
    """A review's session lives beneath the review root, which the run directory does not hold.

    Its owner record names the run: this run's resume stops it, removes its
    credential and reads its spend as a reviewer's; another run's is left alone.
    """
    from orch_helpers import make_config

    run_dir, root = tmp_path / "run", tmp_path / "rs"
    (run_dir / "sessions").mkdir(parents=True)
    lines = [*_message("msg_review", 10), _result(10)]
    mine = _left_review(root, "11111111-1111-4111-8111-111111111111", "run-1", lines)
    other = _left_review(root, "22222222-2222-4222-8222-222222222222", "run-2", lines)
    dispatcher = ClaudeDispatcher(
        config=make_config(),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=run_dir / "bin" / "physgate",
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=root,
    )
    (left,) = dispatcher.stop_leftovers()
    assert (left.session_id, left.kind, left.complete) == (mine.parent.name, "reviewer", True)
    assert not (mine / "state" / KEY_HELPER).exists()
    assert (mine / "ended.json").exists()
    assert (other / "state" / KEY_HELPER).exists()
    assert not (other / "ended.json").exists()


def test_a_leftover_review_s_tokens_are_attributed_to_the_reviewer(tmp_path: Path) -> None:
    class _LeftReview(FakeDispatcher):
        def stop_leftovers(self) -> list[Leftover]:
            return [
                Leftover(
                    session_id="rev-old",
                    pid=4242,
                    killed=0,
                    stopped=False,
                    usage=(SPENT,),
                    complete=True,
                    kind="reviewer",
                )
            ]

    rig = Rig(tmp_path, dispatcher=_LeftReview())
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    again = rig.open()
    again.resume()
    again.close()
    account = TokenAccount.from_events(read_events(tmp_path / "events.jsonl"))
    assert account.by_attribution()["reviewer:rev-old"] == SPENT.usage
    assert "session:rev-old" not in account.by_attribution()
