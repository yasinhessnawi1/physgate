"""A reopen removes the old worktree itself; a decisions line that does not read halts the run once.

A reopened module works in a fresh worktree. The old one was removed at the run's stop points, and
nothing removed it when no stop came between the merge and the reopen: a follow-up after sizing's
closing pass, or a decision taken by a process that died before its stop's removal line. The step
that writes the reopen now removes the old worktree first, once, and records it.

A line in the decisions file that the queue's reader refuses (a hand edit, a torn rewrite) made
every resume raise the reader's refusal, with nothing on the record. It is one incident naming the
file and the line, under its own cause, and the run halts; a person mends the file, so no resume
continues from that halt. A process killed between the incident and its halt writes the halt
alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arbitration_runs import CLOSING, events_of
from test_a_choice_on_a_failed_contract_reopens_the_other_module import again, choose, of, opened
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    escaped,
    kinds,
    lines,
)
from test_a_follow_up_after_the_closing_pass_is_recorded_and_replayed_as_the_record_owes import (
    ended,
    slice_rig,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import FW

from physgate.orchestrator.events import Event, Halted, WorktreeRemoved
from physgate.orchestrator.queue import DECISIONS_NAME

# --- the old worktree --------------------------------------------------------------------------


def removals(rows: list[dict[str, Any]], subtask_id: str) -> list[str]:
    return [r["path"] for r in of(rows, "worktree_removed", subtask_id=subtask_id)]


def test_a_decision_s_reopen_with_no_stop_since_the_merge_removes_the_old_worktree_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The process that listed the item died at its stop, before it recorded the old worktree's
    # removal: the decision is taken, and the reopen written, with no stop between.
    def at_fw_s_removal(event: Event, _: list[Event]) -> bool:
        return isinstance(event, WorktreeRemoved) and event.subtask_id == FW

    rig = opened(tmp_path, monkeypatch, kill=at_fw_s_removal)
    assert removals(lines(rig), FW) == []
    choose(rig.run_dir, "producer")
    said = escaped(lambda: again(rig, monkeypatch))
    assert said is None, said
    rows = lines(rig)
    assert removals(rows, FW) == [f"worktrees/{FW}", f"worktrees/{FW}.reopen-1"]
    (reopen,) = of(rows, "subtask_reopened", subtask_id=FW)
    first = of(rows, "worktree_removed", subtask_id=FW)[0]
    assert first["seq"] < reopen["seq"], "the old worktree was removed after the reopen"
    assert first["reason"] == "done"


def test_a_follow_up_removes_the_old_worktree_before_its_reopen(tmp_path: Path) -> None:
    rig = slice_rig(tmp_path)
    assert ended(rig, plan=CLOSING) == "done"
    rows = [e.model_dump(mode="json") for e in events_of(rig)]
    assert removals(rows, "s1") == ["worktrees/s1", "worktrees/s1.reopen-1"]
    (reopen,) = of(rows, "subtask_reopened", subtask_id="s1")
    first = of(rows, "worktree_removed", subtask_id="s1")[0]
    assert first["seq"] < reopen["seq"], "the old worktree was removed after the reopen"


# --- an unreadable decisions line ----------------------------------------------------------------


BROKEN = b'{"kind": "decision", "item_id": "nothing like a decision"}\n'


def waiting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: ANN401 - the rig
    """The contract rig stopped on its item, with a decisions line its reader refuses."""
    rig = opened(tmp_path, monkeypatch)
    assert kinds(lines(rig))[-1] != "halted"
    (rig.run_dir / DECISIONS_NAME).write_bytes(BROKEN)
    return rig


def resumed(rig: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> str:  # noqa: ANN401
    """How a resume ended, or what escaped it, as text."""
    said: list[str] = []
    escape = escaped(lambda: said.append(again(rig, monkeypatch, **kw)))
    return escape if escape is not None else said[0]


def test_a_decisions_line_that_does_not_read_is_one_incident_and_the_run_halts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = waiting(tmp_path, monkeypatch)
    before = len(lines(rig))
    assert resumed(rig, monkeypatch) == "halted"
    later = lines(rig)[before:]
    halts = [r for r in later if r["kind"] in ("incident", "halted")]
    assert kinds(halts) == ["incident", "halted"], kinds(later)
    incident, halt = halts
    assert incident["cause"] == "decisions_unreadable"
    assert DECISIONS_NAME in incident["detail"] and "line 1" in incident["detail"]
    assert halt["detail"].startswith("decisions_unreadable")


def test_the_incident_names_the_line_the_reader_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch)
    choose(rig.run_dir, "producer")
    path = rig.run_dir / DECISIONS_NAME
    path.write_bytes(path.read_bytes() + BROKEN)
    assert resumed(rig, monkeypatch) == "halted"
    (incident,) = of(lines(rig), "incident")
    assert incident["cause"] == "decisions_unreadable"
    assert "line 2" in incident["detail"], incident["detail"]


def test_no_resume_continues_from_an_unreadable_decisions_line_s_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = waiting(tmp_path, monkeypatch)
    assert resumed(rig, monkeypatch) == "halted"
    before = lines(rig)
    said = resumed(rig, monkeypatch)
    assert "RunStateError" in said and "halted for incident" in said, said
    assert lines(rig) == before


def test_a_kill_between_that_incident_and_its_halt_writes_the_halt_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = waiting(tmp_path / "reference", monkeypatch)
    assert resumed(reference, monkeypatch) == "halted"
    rig = waiting(tmp_path / "cut", monkeypatch)
    before = len(lines(rig))
    said = resumed(rig, monkeypatch, kill=lambda e, _: isinstance(e, Halted))
    assert said == "killed", said
    assert kinds(lines(rig)[before:])[-1:] == ["incident"]
    assert resumed(rig, monkeypatch) == "halted"
    rows = lines(rig)
    assert kinds([r for r in rows if r["kind"] in ("incident", "halted")]) == ["incident", "halted"]
    tail = [r for r in rows[before:] if r["kind"] not in ("os_layer_checked", "resumed")]
    reference_tail = [
        r for r in lines(reference)[before:] if r["kind"] not in ("os_layer_checked", "resumed")
    ]
    assert kinds(tail) == kinds(reference_tail)
    assert [r.get("detail") for r in tail] == [
        r.get("detail", "").replace(str(reference.run_dir), str(rig.run_dir))
        if r.get("detail") is not None
        else None
        for r in reference_tail
    ]
