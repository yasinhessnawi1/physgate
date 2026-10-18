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

from left_session import INSTALL_BIN, sentinel_installed, spawn_logged
from loop_fakes import FakeDispatcher, Rig, plan

from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import Halted, Incident, LeftoverRead, read_events
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


def _dispatcher(run_dir: Path, **overrides: Any) -> ClaudeDispatcher:
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
