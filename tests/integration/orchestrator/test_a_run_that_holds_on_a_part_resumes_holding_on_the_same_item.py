"""A run that holds on a part, killed and resumed, holds on the same item and asks nothing twice.

ARCH-122. Each process here is a real one, killed by the signal no handler sees. A process
killed after the run's opening and before it listed a part loses none: the next lists them,
under the ids the record gives. A process killed after it took a person's decision into the log
leaves that decision taken once; the next does not take it again, holds on the parts still
open under their own ids, and dispatches nothing until the last is decided.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.events import Position
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)

pytestmark = pytest.mark.integration

CHILD = Path(__file__).resolve().parent / "parts_child.py"
IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]


def _child(run_dir: Path, mode: str) -> tuple[int, dict[str, Any] | None]:
    done = subprocess.run(
        [sys.executable, str(CHILD), str(run_dir), mode],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    lines = [line for line in done.stdout.splitlines() if line.startswith("{")]
    return done.returncode, json.loads(lines[-1]) if lines else None


def _decide(run_dir: Path, item_id: str, position: Position, parts: Any = None) -> None:
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(verb="choose", note=None, position=position, parts=parts),
        resolved_by="yasin",
        shown=ShownItem(
            item_sha256=read_queue(run_dir).digests[item_id],
            trajectories=statuses_now(run_dir, item_id),
        ),
    )


def test_a_killed_run_resumes_on_the_same_items_and_asks_nothing_twice(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    # Killed after its opening, before it listed a part.
    code, _ = _child(run_dir, "open")
    assert code == -signal.SIGKILL, "the first process did not die by the kill"
    assert read_queue(run_dir).items == ()

    # The next lists every part, under the ids the record gives, and holds.
    code, found = _child(run_dir, "drive")
    assert code == 0 and found is not None, found
    assert (found["step"], found["items"], found["taken"]) == ("wait", IDS, [])
    assert found["dispatched"] is False

    # A person decides the first part; the process that takes it into the log is killed at once.
    body = getattr(queue_module, "PartsBody", None)
    assert body is not None, "the queue has no parts body"
    mass = body.model_validate({"declared": {"mass": {"value": 0.4, "unit": "kg"}}, "texts": ()})
    _decide(run_dir, IDS[0], "have", mass)
    code, _ = _child(run_dir, "drive-kill")
    assert code == -signal.SIGKILL, "the process did not die after taking the decision"

    # The next holds on the same items, lists none twice, and takes the decision no second time.
    code, found = _child(run_dir, "drive")
    assert code == 0 and found is not None, found
    assert (found["step"], found["items"], found["taken"]) == ("wait", IDS, [IDS[0]])
    assert found["dispatched"] is False
    assert [one.item_id for one in read_queue(run_dir).open_items()] == IDS[1:]

    # The last decision releases it, and nothing was asked again on the way.
    for one in IDS[1:]:
        _decide(run_dir, one, "find")
    code, found = _child(run_dir, "drive")
    assert code == 0 and found is not None, found
    assert (found["step"], found["taken"]) == ("done", IDS)
    assert found["dispatched"] is True


def _decided_run(run_dir: Path) -> None:
    code, _ = _child(run_dir, "open")
    assert code == -signal.SIGKILL
    body = getattr(queue_module, "PartsBody")  # noqa: B009
    stated = body.model_validate(
        {
            "declared": {
                "mass": {"value": 0.4, "unit": "kg"},
                "stall_current": {"value": 2.4, "unit": "A"},
            },
            "texts": (),
        }
    )
    _child(run_dir, "drive")
    _decide(run_dir, IDS[0], "have", stated)
    for one in IDS[1:]:
        _decide(run_dir, one, "find")


@pytest.mark.parametrize("mode", ["drive-kill-intent", "drive-kill-done"])
def test_a_run_killed_while_it_writes_what_was_decided_writes_each_node_once(
    tmp_path: Path, mode: str
) -> None:
    run_dir = tmp_path / "run"
    _decided_run(run_dir)

    # Killed by the signal no handler sees, after the first intent or the first landed write.
    code, _ = _child(run_dir, mode)
    assert code == -signal.SIGKILL, "the process did not die in the writing"
    ledger = run_dir / "graph_ledger.jsonl"
    written = len(ledger.read_text().splitlines()) if ledger.exists() else 0
    assert written == (0 if mode == "drive-kill-intent" else 1)

    # The next process accounts for what landed, writes what did not, and releases once.
    code, found = _child(run_dir, "drive")
    assert code == 0 and found is not None, found
    assert found["step"] == "done" and found["dispatched"] is True
    assert found["released"] == 1
    assert sorted(set(found["intended"])) == ["control.motor_left", "sizing.control_motor_left"]
    assert found["done"] == [2, 3]
    assert len(ledger.read_text().splitlines()) == 2
