"""A session's stream ends at its one result, is sealed when the session ends, and is held to it.

The runtime writes the stream through a handle that does not append, so a
longer write by the session's own user survives after the runtime's last byte.
A completed stream must therefore end at its one ``result``; and every reader
after the session holds the file to the seal taken when the session ended.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, Rig, plan

from physgate.orchestrator.events import GateRan, Incident, ReviewRan, read_events
from physgate.orchestrator.exceptions import TrajectoryTamperedError
from physgate.orchestrator.protocols import Artefact, GateResult, RunningGateMode
from physgate.orchestrator.trajectory import (
    Seal,
    forged_tail,
    read_sealed,
    seal,
    through_first_result,
)

MESSAGE = json.dumps({"type": "assistant", "message": {"id": "m1", "model": "claude-sonnet-5"}})
RESULT = json.dumps({"type": "result", "subtype": "success", "is_error": False})
FORGED = json.dumps({"type": "result", "subtype": "success", "modelUsage": {"x": {}}})


@pytest.mark.parametrize(
    ("stream", "verdict"),
    [
        (f"{MESSAGE}\n{RESULT}\n", None),
        (f"{MESSAGE}\n{RESULT}\n\n  \n", None),
        (f"{MESSAGE}\n", None),
        (f"{MESSAGE}\n{RESULT}\n{FORGED}\n", "2 result events"),
        (f"{MESSAGE}\n{RESULT}\n{MESSAGE}\n", "goes on after its result"),
        (f"{MESSAGE}\n{RESULT}\nnot json at all\n", "goes on after its result"),
    ],
    ids=["one result", "blank after", "no result yet", "a second result", "a line after", "bytes"],
)
def test_a_completed_stream_ends_at_its_one_result(stream: str, verdict: str | None) -> None:
    found = forged_tail(stream)
    assert (found is None) if verdict is None else (verdict in str(found))


def test_what_is_read_of_a_forged_stream_ends_at_the_runtime_s_result() -> None:
    assert through_first_result(f"{MESSAGE}\n{RESULT}\n{FORGED}\n") == f"{MESSAGE}\n{RESULT}\n"


def test_a_trajectory_is_read_only_as_it_was_sealed(tmp_path: Path) -> None:
    path = tmp_path / "stdout.jsonl"
    path.write_text(f"{MESSAGE}\n{RESULT}\n")
    sealed = seal(path.read_bytes())
    assert read_sealed(path, sealed) == path.read_bytes()
    path.write_text(f"{MESSAGE}\n{RESULT}\n{FORGED}\n")
    with pytest.raises(TrajectoryTamperedError, match="not what it was") as caught:
        read_sealed(path, sealed)
    assert caught.value.context["sealed"].endswith(f":{sealed.length}")
    path.unlink()
    with pytest.raises(TrajectoryTamperedError, match="gone"):
        read_sealed(path, sealed)
    with pytest.raises(ValueError):
        Seal(sha256="not a digest", length=1)


def test_a_forged_tail_is_an_incident_before_anything_the_session_did_is_taken(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(tampered={1: "the stream goes on"}))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "trajectory_tampered" and incident.subtask_id == "s1"
    assert not [e for e in events if isinstance(e, GateRan | ReviewRan)]


class _Tampering(FakeGate):
    """Passes, or fails, and appends to a trajectory in between: a change after the seal."""

    def __init__(self, verdicts: list[str], victim: int) -> None:
        super().__init__(verdicts=verdicts)
        self.victim = victim

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        result = super().check(artefact, mode=mode)
        if len(self.seen) == self.victim:
            with Path(artefact.trajectory).open("ab") as stream:
                stream.write(b"changed after the session\n")
        return result


def test_a_trajectory_changed_after_its_session_is_refused_before_the_review(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "sessions"))
    rig.gate = _Tampering(verdicts=["pass"], victim=1)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "trajectory_tampered"
    assert not [e for e in events if isinstance(e, ReviewRan)]
    assert rig.reviewer.seen == []


def test_a_trajectory_changed_before_the_escalation_is_refused_before_it_is_queued(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "sessions"))
    rig.gate = _Tampering(verdicts=["fail", "fail", "fail"], victim=2)
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "halted"
    loop.close()
    events = read_events(tmp_path / "events.jsonl")
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "trajectory_tampered"
    assert loop.queue.items() == []


def test_the_seal_is_recorded_with_the_session_and_handed_to_the_reviewer(tmp_path: Path) -> None:
    rig = Rig(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "sessions"))
    loop = rig.open()
    loop.start(plan("s1"))
    assert loop.run().kind == "done"
    loop.close()
    ended = [e for e in read_events(tmp_path / "events.jsonl") if e.kind == "session_ended"]
    assert ended and ended[0].trajectory_seal is not None
    (seen,) = rig.reviewer.seen
    assert (seen.trajectory_sha256, seen.trajectory_length) == (
        ended[0].trajectory_seal.sha256,
        ended[0].trajectory_seal.length,
    )
