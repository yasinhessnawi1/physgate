"""A decision written while a session ran is marked by the queue listing, not refused.

A person may decide while a session runs; a session's hidden write could add a
decision too, which would close an escalation and hide it from the listing. The
loop records the decisions file's length at each session's start and end, and
the listing marks a decision whose bytes fall in such a window for a person to
confirm.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, FakeGate, Rig, plan

from physgate.cli import main
from physgate.orchestrator.queue import ApprovalQueue


def test_a_decision_inside_a_session_window_is_marked_and_one_outside_is_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def decide(item: str) -> None:
        ApprovalQueue(tmp_path / "queue.jsonl").resolve(item, decision="split", resolved_by="yasin")

    # s1 and s2 fail the gate three times each and are escalated; during s3's
    # session a decision on s1 is written.
    dispatcher = FakeDispatcher(during={7: lambda: decide("run-1-s1")})
    rig = Rig(tmp_path, dispatcher=dispatcher)
    rig.gate = FakeGate(verdicts=["fail"] * 6 + ["pass"])
    loop = rig.open()
    loop.start(plan("s1", "s2", "s3"))
    assert loop.run().kind == "done"
    loop.close()
    decide("run-1-s2")  # after every session: outside any window

    assert main(["queue", "list", "--run-dir", str(tmp_path)]) == 0
    decided = {d["item_id"]: d["flag"] for d in json.loads(capsys.readouterr().out)["decided"]}
    assert decided["run-1-s2"] is None
    assert decided["run-1-s1"] == "made while session sess-7 ran; confirm"
