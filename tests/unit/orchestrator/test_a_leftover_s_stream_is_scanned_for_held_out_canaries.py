"""At a resume, a leftover session's stream is scanned for held-out canaries.

A session left without an end by a previous orchestrator is read at the resume as a
finished session's stream is (see the leftover read's own tests). Its stream is also
scanned for the run's held-out canaries, as at a normal session end: a hit records a
``held_out_read`` incident and halts the run, whatever else the resume finds. The
canary itself is never written into the record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from left_session import INSTALL_BIN, sentinel_installed, spawn_logged
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Halted, Incident, LeftoverRead, read_events
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import Leftover
from physgate.orchestrator.trajectory import seal

CANARY = "c" * 32


def _left(run_dir: Path, session: str, text: str) -> None:
    sdir = run_dir / "sessions" / session
    sdir.mkdir(parents=True)
    # Not running: the session finished while its orchestrator was down.
    started = "Mon Jan  1 00:00:00 2001"
    record = {"pid": 999_999, "started": started, "session_id": session}
    (sdir / "process.json").write_text(json.dumps(record))
    spawn_logged(run_dir, [(session, 999_999, started)])
    sentinel_installed(sdir, run_dir / "guarded")
    tool_output = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": text}]},
    }
    (sdir / "stdout.jsonl").write_text(json.dumps(tool_output) + "\n")


def _dispatcher(
    run_dir: Path, *, quarantine: tuple[str, str, str] | None = None, **overrides: Any
) -> ClaudeDispatcher:
    from orch_helpers import make_config

    return ClaudeDispatcher(
        config=make_config(**overrides),
        run=RunGit(repo=run_dir, run_dir=run_dir, run_id="run-1"),
        store_root=run_dir / "store",
        install_bin=INSTALL_BIN,
        binary="/nonexistent/claude",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy-not-a-credential"),
        review_root=Path("/nonexistent/review-scratch"),
        quarantine=quarantine,
    )


def test_a_leftover_that_displayed_a_held_out_canary_is_found(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "exposed", f"the task reads: <!-- {CANARY} -->")
    _left(run_dir, "clean", "nothing held out here")
    found = _dispatcher(run_dir, held_out_canaries=(CANARY,)).stop_leftovers()
    assert {left.session_id: left.held_out_seen for left in found} == {
        "exposed": CANARY,
        "clean": None,
    }


def test_a_leftover_is_not_scanned_for_canaries_the_run_does_not_hold(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "exposed", f"the task reads: <!-- {CANARY} -->")
    (left,) = _dispatcher(run_dir).stop_leftovers()
    assert left.held_out_seen is None


def _exposed(**fields: Any) -> Leftover:
    return Leftover(
        session_id="sess-old",
        pid=4242,
        killed=0,
        stopped=False,
        complete=True,
        seal=seal(b"the stream as read\n"),
        held_out_seen=CANARY,
        **fields,
    )


class _ExposedLeftover(FakeDispatcher):
    tampered_leftover: str | None = None

    def stop_leftovers(self) -> list[Leftover]:
        return [_exposed(tampered=self.tampered_leftover)]


def test_an_exposed_leftover_is_a_held_out_read_incident_and_the_run_halts(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=_ExposedLeftover())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    assert rig.dispatcher.requests == []
    events = read_events(tmp_path / "events.jsonl")
    assert [e for e in events if isinstance(e, LeftoverRead)]
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "held_out_read"
    assert "sess-old" in incident.detail
    assert CANARY[:8] not in incident.detail
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert halted.reason == "incident" and "held_out_read" in (halted.detail or "")
    assert events.index(halted) > events.index(incident)


def test_an_exposed_leftover_is_recorded_when_its_stream_was_also_tampered(
    tmp_path: Path,
) -> None:
    dispatcher = _ExposedLeftover()
    dispatcher.tampered_leftover = "the stream goes on after its result event"
    rig = Rig(tmp_path, dispatcher=dispatcher)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    incidents = [e for e in events if isinstance(e, Incident)]
    assert sorted(i.cause for i in incidents) == ["held_out_read", "trajectory_tampered"]
    assert all(CANARY[:8] not in i.detail for i in incidents)
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert events.index(halted) > max(events.index(i) for i in incidents)


RUBRIC_CANARY = "0123456789abcdef0011223344556677"


def test_a_leftover_role_session_that_displayed_a_rubric_canary_is_found(tmp_path: Path) -> None:
    # Reviewer material is scanned at a resume as at a normal session end.
    run_dir = tmp_path / "run"
    _left(run_dir, "read-the-rubric", f"rubric text <!-- {RUBRIC_CANARY} -->")
    _left(run_dir, "clean", "nothing here")
    dispatcher = _dispatcher(run_dir)
    dispatcher._canaries = frozenset({RUBRIC_CANARY})
    found = {left.session_id: left.review_material_seen for left in dispatcher.stop_leftovers()}
    assert found == {"read-the-rubric": RUBRIC_CANARY, "clean": None}


class _RubricLeftover(FakeDispatcher):
    def stop_leftovers(self) -> list[Leftover]:
        return [
            Leftover(
                session_id="sess-old",
                pid=4242,
                killed=0,
                stopped=False,
                complete=True,
                seal=seal(b"the stream as read\n"),
                review_material_seen=RUBRIC_CANARY,
            )
        ]


def test_a_leftover_that_read_reviewer_material_is_an_incident_and_the_run_halts(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=_RubricLeftover())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    assert rig.dispatcher.requests == []
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "review_material_read" and "sess-old" in incident.detail
    assert RUBRIC_CANARY[:8] not in incident.detail
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert events.index(halted) > events.index(incident)


def test_a_leftover_whose_stream_is_gone_halts_and_is_never_scanned_as_clean(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "gone", "nothing held out here")
    (run_dir / "sessions" / "gone" / "stdout.jsonl").unlink()
    with pytest.raises(InvocationError, match="gone"):
        _dispatcher(run_dir, held_out_canaries=(CANARY,)).stop_leftovers()


def test_a_halt_on_a_gone_stream_leaves_the_session_unended_and_the_next_resume_halts_again(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "gone", "nothing held out here")
    sdir = run_dir / "sessions" / "gone"
    (sdir / "stdout.jsonl").unlink()
    for _ in range(2):
        with pytest.raises(InvocationError, match="gone"):
            _dispatcher(run_dir, held_out_canaries=(CANARY,)).stop_leftovers()
        assert not (sdir / "ended.json").exists()


def _q(session: str, why: str = "the stream was removed by a cleanup job") -> tuple[str, str, str]:
    return session, "yasin", why


def test_one_gone_stream_ends_no_session_and_every_gone_stream_is_named(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "fine", "nothing held out here")
    _left(run_dir, "gone-b", "x")
    _left(run_dir, "gone-c", "x")
    for name in ("gone-b", "gone-c"):
        (run_dir / "sessions" / name / "stdout.jsonl").unlink()
    for _ in range(2):
        with pytest.raises(InvocationError) as raised:
            _dispatcher(run_dir, held_out_canaries=(CANARY,)).stop_leftovers()
        message = f"{raised.value} {raised.value.context}"
        assert "gone-b" in message and "gone-c" in message and "fine" not in message
        assert "--quarantine" in message
        # Nothing is ended, so the next resume reports the fine session too.
        assert not list((run_dir / "sessions").glob("*/ended.json"))
    # Setting one aside leaves the other halting, and still ends nothing.
    with pytest.raises(InvocationError, match="gone-c"):
        _dispatcher(run_dir, held_out_canaries=(CANARY,), quarantine=_q("gone-b")).stop_leftovers()
    assert not list((run_dir / "sessions").glob("*/ended.json"))


def test_a_marker_file_in_a_session_directory_quarantines_nothing(tmp_path: Path) -> None:
    """A session can write its own directory: only the operator's command-line flag counts."""
    run_dir = tmp_path / "run"
    _left(run_dir, "gone", "x")
    sdir = run_dir / "sessions" / "gone"
    (sdir / "stdout.jsonl").unlink()
    (sdir / "quarantine.json").write_text(json.dumps({"by": "yasin", "why": "forged"}))
    with pytest.raises(InvocationError, match="gone"):
        _dispatcher(run_dir).stop_leftovers()


def test_a_quarantined_gone_stream_is_recorded_as_unscanned_never_as_clean(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "fine", "nothing held out here")
    _left(run_dir, "gone", "x")
    (run_dir / "sessions" / "gone" / "stdout.jsonl").unlink()
    found = {
        left.session_id: left
        for left in _dispatcher(
            run_dir, held_out_canaries=(CANARY,), quarantine=_q("gone")
        ).stop_leftovers()
    }
    assert set(found) == {"fine", "gone"}
    assert found["fine"].quarantine is None and found["fine"].scan == "scanned"
    gone = found["gone"]
    assert gone.quarantine == "yasin: the stream was removed by a cleanup job"
    assert gone.scan == "unscanned (stream gone)"
    assert gone.seal is None and gone.usage == () and not gone.complete
    assert all((run_dir / "sessions" / n / "ended.json").exists() for n in found)


def test_a_quarantine_of_a_stream_that_is_there_or_a_stranger_is_refused(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "present", f"the task reads: <!-- {CANARY} -->")
    for target in ("present", "nobody"):
        with pytest.raises(InvocationError, match="never set aside|not a leftover"):
            _dispatcher(
                run_dir, held_out_canaries=(CANARY,), quarantine=_q(target)
            ).stop_leftovers()
        assert not list((run_dir / "sessions").glob("*/ended.json"))


def test_a_quarantine_is_an_incident_that_halts_and_never_counts_as_clean(
    tmp_path: Path,
) -> None:
    class _Quarantined(FakeDispatcher):
        def stop_leftovers(self) -> list[Leftover]:
            return [
                Leftover(
                    session_id="sess-old",
                    pid=4242,
                    killed=0,
                    stopped=False,
                    quarantine="yasin: the stream was removed by a cleanup job",
                    scan="unscanned (stream gone)",
                )
            ]

    rig = Rig(tmp_path, dispatcher=_Quarantined())
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    assert rig.dispatcher.requests == []
    events = read_events(tmp_path / "events.jsonl")
    (read,) = [e for e in events if isinstance(e, LeftoverRead)]
    assert read.scan == "unscanned (stream gone)" and "yasin" in (read.quarantine or "")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "stream_quarantined"
    assert "sess-old" in incident.detail and "yasin" in incident.detail
    assert "unscanned (stream gone)" in incident.detail and incident.ts
    (halted,) = [e for e in events if isinstance(e, Halted)]
    assert halted.reason == "incident" and "stream_quarantined" in halted.detail
    # A non-resumable halt: a later resume refuses until a person resolves it.


def test_the_resume_command_takes_the_quarantine_flag_and_the_run_command_does_not() -> None:
    import argparse

    from physgate.orchestrator.cli import _quarantine_request, add_parsers

    top = argparse.ArgumentParser()
    add_parsers(top.add_subparsers(dest="cmd"))
    base = ["--run-dir", "r", "--target", "t", "--install", "i", "--review-root", "x"]
    args = top.parse_args(["resume", *base, "--quarantine", "s9", "--quarantine-why", "removed"])
    request = _quarantine_request(args)
    assert request is not None and request[0] == "s9" and request[2] == "removed" and request[1]
    with pytest.raises(SystemExit):
        top.parse_args(["run", *base, "--quarantine", "s9"])
    from physgate.orchestrator.exceptions import RunStateError

    with pytest.raises(RunStateError):
        _quarantine_request(top.parse_args(["resume", *base, "--quarantine", "s9"]))


def test_a_leftover_whose_stream_is_present_and_empty_is_still_read(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _left(run_dir, "empty", "")
    (run_dir / "sessions" / "empty" / "stdout.jsonl").write_text("")
    (left,) = _dispatcher(run_dir, held_out_canaries=(CANARY,)).stop_leftovers()
    assert left.held_out_seen is None
    assert not left.complete
