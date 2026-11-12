"""A write that breaks a cross-cutting duty halts the run under a cause of its own.

The check after a step names two kinds of write. One is a node changed by a role that does
not own it: the store's own guard refuses that write, so one in the record got past the
store, and the run halts as a ``cross_role_write``, as it always has. The other is a write
the store accepts and a cross-cutting duty forbids: a cross node from a role that does not
own the cross nodes, a domain node from the role that does, an interface node made during
a step, a node from the role that owns completion. That run halts as a ``duty_breach``, so
the record, the halt and the evaluation's decision sequence tell the two apart.

A step with both is a ``cross_role_write``: a write past the store's own guard is the
graver of the two, and it is the cause such a step was always recorded under. A run
recorded before the new cause existed keeps the cause it was recorded with, and replays.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeGraph, Rig, plan

from physgate.evaluation.observe.sequence import decisions
from physgate.orchestrator.events import DiffChecked, Halted, Incident, read_events
from physgate.orchestrator.exceptions import RunStateError
from physgate.state.divergence import COMPLETION_OWNER_NODE, CROSS_NODE, Divergence

FOREIGN = Divergence(
    node_id="electrical.motor", revision=7, owner_role="electrical", acting_role="control"
)
CROSS = Divergence(
    node_id="control.motor_current",
    revision=8,
    owner_role="control",
    acting_role="control",
    reason=CROSS_NODE,
    detail="control.motor_current is of the cross domain; only the sizing role writes them",
)
COMPLETION = Divergence(
    node_id="integration.check",
    revision=9,
    owner_role="integration",
    acting_role="integration",
    reason=COMPLETION_OWNER_NODE,
    detail="the integration role owns the completion declaration; it writes no node",
)


def _halted_after(tmp_path: Path, *found: Divergence) -> list[Any]:
    rig = Rig(tmp_path, diff=FakeGraph(divergent={1: found}))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    assert loop.run().kind == "halted"
    loop.close()
    return read_events(tmp_path / "events.jsonl")


def _sequence(tmp_path: Path) -> list[dict[str, Any]]:
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    return decisions([json.loads(line) for line in lines])


@pytest.mark.parametrize("breach", [CROSS, COMPLETION], ids=["cross node", "completion owner"])
def test_a_duty_breach_is_recorded_halted_and_sequenced_as_one(
    tmp_path: Path, breach: Divergence
) -> None:
    events = _halted_after(tmp_path, breach)
    (checked,) = [e for e in events if isinstance(e, DiffChecked)]
    assert checked.divergences == (str(breach),)
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "duty_breach" and incident.detail == str(breach)
    (halt,) = [e for e in events if isinstance(e, Halted)]
    assert halt.reason == "incident" and halt.detail == "duty_breach in s1"
    steps = [s for s in _sequence(tmp_path) if s["step"] == "incident"]
    assert [(s["subtask_id"], s["cause"]) for s in steps] == [("s1", "duty_breach")]


def test_a_write_past_the_store_s_guard_is_still_a_cross_role_write(tmp_path: Path) -> None:
    events = _halted_after(tmp_path, FOREIGN)
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "cross_role_write"
    (halt,) = [e for e in events if isinstance(e, Halted)]
    assert halt.detail == "cross_role_write in s1"
    steps = [s for s in _sequence(tmp_path) if s["step"] == "incident"]
    assert [s["cause"] for s in steps] == ["cross_role_write"]


@pytest.mark.parametrize(
    "found", [(CROSS, FOREIGN), (FOREIGN, CROSS)], ids=["breach first", "foreign write first"]
)
def test_a_step_with_both_is_a_cross_role_write_whatever_their_order(
    tmp_path: Path, found: tuple[Divergence, ...]
) -> None:
    events = _halted_after(tmp_path, *found)
    (incident,) = [e for e in events if isinstance(e, Incident)]
    assert incident.cause == "cross_role_write"
    assert incident.detail == "; ".join(str(d) for d in found)


def test_a_run_recorded_with_the_old_cause_keeps_it_and_replays(tmp_path: Path) -> None:
    # A log written before the new cause existed: its incident line is left as it was, is
    # read back as it was written, and a resume replays the log to the same halt.
    rig = Rig(tmp_path, diff=FakeGraph(divergent={1: (FOREIGN,)}))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    loop.run()
    loop.close()
    log = tmp_path / "events.jsonl"
    (line,) = [r for r in map(json.loads, log.read_text().splitlines()) if r["kind"] == "incident"]
    assert line["cause"] == "cross_role_write"
    (incident,) = [e for e in read_events(log) if isinstance(e, Incident)]
    assert incident.cause == "cross_role_write"
    with pytest.raises(RunStateError, match="halted for incident"):
        rig.open().resume()
