"""The installation check is a line of the run's log, and it changes nothing the log decides.

``physgate run`` and ``resume`` hold the hooks' installation to its build before
anything is spawned, and record how long that took. The line is a record of the
machine's work, like the environment record: it is not a transition, so the task
ledger projected from the log and the position a resume rebuilds are exactly
what they would be without it, and it may be written at any point, a halted
run's resume included.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from loop_fakes import FakeDispatcher, Rig, plan
from pydantic import ValidationError

from physgate.orchestrator.events import InstallChecked, read_events
from physgate.orchestrator.loop import Loop


def _checked(loop: Loop) -> None:
    loop.record.emit(
        InstallChecked(
            **loop.record.envelope(), path="/i", action="checked", seconds=0.35, entries=2114
        )
    )


def _run(root: Path, with_checks: bool) -> tuple[bytes, dict[str, str]]:
    # One infrastructure failure with no retries halts the run; a resume continues it.
    rig = Rig(root, dispatcher=FakeDispatcher(infra={1: "api_error"}))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    if with_checks:
        _checked(loop)
    assert loop.run().kind == "halted"
    loop.close()
    loop = rig.open()
    if with_checks:
        _checked(loop)  # after the halt, before the resume: allowed
    assert loop.resume().kind == "done"
    statuses: dict[str, str] = {k: v.status for k, v in loop.state.subtasks.items()}
    loop.close()
    return (root / "ledger.jsonl").read_bytes(), statuses


def test_the_ledger_and_the_resume_are_the_same_with_and_without_the_line(
    tmp_path: Path,
) -> None:
    plain = _run(tmp_path / "plain", with_checks=False)
    checked = _run(tmp_path / "checked", with_checks=True)
    assert checked == plain
    assert plain[1] == {"s1": "done", "s2": "done"}
    lines = read_events(tmp_path / "checked" / "events.jsonl")
    found = [e for e in lines if isinstance(e, InstallChecked)]
    assert [(e.action, e.entries) for e in found] == [("checked", 2114)] * 2  # read back whole


def test_a_negative_time_or_count_or_another_action_is_refused() -> None:
    envelope = {"seq": 0, "ts": "2026-09-27T12:00:00.000000Z", "run_id": "r", "gate_mode": "on"}
    fields = {"path": "/i", "action": "checked", "seconds": 0.1, "entries": 1}
    for bad in ({"seconds": -0.1}, {"entries": -1}, {"action": "skipped"}, {"path": ""}):
        with pytest.raises(ValidationError):
            InstallChecked(**envelope, **{**fields, **bad})  # type: ignore[arg-type]
