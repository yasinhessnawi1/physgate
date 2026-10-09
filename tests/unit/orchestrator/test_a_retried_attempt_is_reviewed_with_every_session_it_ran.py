"""A retried attempt is reviewed with every session it ran, in order.

A session that ended for infrastructure (its turn limit here) is followed by a fresh
session on the same attempt, which spends no repair attempt and keeps the worktree, as
designed. Both sessions are the attempt's trajectory, so the reviewer is handed both:
the earlier one with its seal, then the one that completed it. A session that left no
stream has nothing to show and is not listed.
"""

from __future__ import annotations

from pathlib import Path

from loop_fakes import FakeDispatcher, FakeReviewer, Rig, plan

from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.trajectory import seal


def test_the_reviewer_is_handed_the_earlier_session_then_the_completing_one(
    tmp_path: Path,
) -> None:
    streams = tmp_path / "streams"
    dispatcher = FakeDispatcher(infra={1: "turn_limit"}, trajectories=streams)
    rig = Rig(tmp_path, dispatcher=dispatcher, reviewer=FakeReviewer(), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    (artefact,) = rig.reviewer.seen
    assert [r.attempt for r in dispatcher.requests] == [1, 1]  # no attempt spent
    (earlier,) = artefact.earlier_sessions
    assert earlier.session_id == "sess-1"
    assert Path(earlier.trajectory) == streams / "sess-1" / "stdout.jsonl"
    assert earlier.trajectory_sha256 == seal(Path(earlier.trajectory).read_bytes()).sha256
    assert Path(artefact.trajectory) == streams / "sess-2" / "stdout.jsonl"
    ended = [e for e in read_events(tmp_path / "events.jsonl") if isinstance(e, SessionEnded)]
    assert [(e.outcome, e.trajectory is not None) for e in ended] == [
        ("infrastructure", True),
        ("completed", True),
    ]


def test_a_session_that_left_no_stream_is_not_listed(tmp_path: Path) -> None:
    dispatcher = FakeDispatcher(infra={1: "api_error"})  # no stream written at all
    rig = Rig(tmp_path, dispatcher=dispatcher, reviewer=FakeReviewer(), delays=(0.0,))
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    (artefact,) = rig.reviewer.seen
    assert artefact.earlier_sessions == ()


def test_one_session_has_no_earlier_ones(tmp_path: Path) -> None:
    rig = Rig(tmp_path, reviewer=FakeReviewer())
    loop = rig.open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    (artefact,) = rig.reviewer.seen
    assert artefact.earlier_sessions == ()
