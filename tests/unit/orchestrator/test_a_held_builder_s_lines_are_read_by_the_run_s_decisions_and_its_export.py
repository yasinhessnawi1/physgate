"""A run's design pairs, a builder's hold and its release are read by every reader of its record.

Over runs the real loop made: the decisions a rerun compares name the planned pairs, each hold
with why, the item a person can act on and the chain, and each release, in log order; the
whole-design export reads the record of a run whose builder stayed held for good as a run that
did not record every module complete, and that of a run whose builder was let go and merged as
finished, never as a log no run could have written.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from sign_off_rig import (
    before_the_sign_off_rule,  # noqa: F401 - the fixture, by name
    sign_every_open_item,
)
from test_a_builder_is_held_until_the_design_it_implements_merges import (
    LAW,
    chain_run,
    chained,
    drive_item,
    first_run,
    resumed,
    rigged,
)
from test_a_choice_on_a_failed_contract_reopens_the_other_module import of
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import lines
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    DRIVE,
    FW,
)
from test_a_queue_decision_acts_at_a_boundary import decide

from physgate.evaluation.observe.sequence import decisions
from physgate.evaluation.whole.export import Export, export_whole_run
from physgate.orchestrator import record
from physgate.state.store import Store

THIRD = "third-7a8b9c"
FW_LAW = "fw.law"


def held_steps(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    kinds = {"design_pairs", "builder_held", "builder_released"}
    return [
        {k: v for k, v in step.items() if k != "seq"}
        for step in decisions(rows)
        if step["step"] in kinds
    ]


#: A row about what the lines of the hold say, not about the sign-off the designer's merge owes:
#: its run starts as one recorded before the rule table, which owes none.
BEFORE_THE_RULE = pytest.mark.usefixtures("before_the_sign_off_rule")


@BEFORE_THE_RULE
def test_the_decisions_name_the_pairs_each_hold_and_the_release_in_log_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path)
    assert first_run(rig, monkeypatch) == "wait"
    item = drive_item(lines(rig))
    decide(rig.run_dir, "approve", item_id=item)
    assert resumed(rig, monkeypatch) == "done"
    assert held_steps(lines(rig)) == [
        {
            "step": "design_pairs",
            "pairs": [{"designer": DRIVE, "builder": FW, "nodes": [LAW]}],
            "mutual": [],
        },
        {
            "step": "builder_held",
            "subtask_id": FW,
            "designer": DRIVE,
            "nodes": [LAW],
            "why": "escalated",
            "item_id": item,
            "chain": None,
        },
        {"step": "builder_released", "subtask_id": FW, "designer": DRIVE, "nodes": [LAW]},
    ]


def test_the_decisions_name_a_hold_for_good_and_its_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chained(tmp_path, acts=False)
    chain_run(rig, monkeypatch)
    item = drive_item(lines(rig))
    holds = [s for s in held_steps(lines(rig)) if s["step"] == "builder_held"]
    assert [(s["subtask_id"], s["why"], s["item_id"], s["chain"]) for s in holds] == [
        (FW, "escalated", item, None),
        (THIRD, "designer_held", None, [FW, DRIVE]),
    ]
    assert (holds[1]["designer"], holds[1]["nodes"]) == (FW, [FW_LAW])


def export_of(run_dir: Path, tmp_path: Path) -> Export:
    """The export over ``run_dir``'s event log, beside an empty store."""
    run = Path(os.path.realpath(tmp_path)) / "copy"
    (run / "store").mkdir(parents=True)
    Store(run / "store").close()
    (run / "events.jsonl").write_bytes((run_dir / "events.jsonl").read_bytes())
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    return export_whole_run(run, out)


def exported(run_dir: Path, tmp_path: Path) -> str:
    """The export's status over ``run_dir``'s event log, beside an empty store."""
    return export_of(run_dir, tmp_path).status


@pytest.mark.parametrize(("mark", "end"), [("release_2", "unrun"), ("release", "done")])
def test_the_export_reads_a_builder_held_for_good_as_a_run_not_every_module_complete(
    mark: str, end: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record, "WAIT_CYCLE", mark)
    rig = rigged(tmp_path / "rig")
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "reject", "no attempt is left", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch) == end
    assert exported(rig.run_dir, tmp_path) == "unfinished"


@BEFORE_THE_RULE
def test_the_export_reads_a_builder_let_go_and_merged_as_a_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path / "rig")
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch) == "done"
    # Finished, its empty graph then holding no structure: the log is read, not refused.
    done = export_of(rig.run_dir, tmp_path)
    assert (done.status, done.sign_offs_owed) == ("contract_lost", ())


def test_the_export_reads_a_builder_let_go_and_merged_as_unfinished_until_the_sign_off_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path / "rig")
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    # The designer merged and the builder ran on its merge; the control module's sign-off is owed.
    assert resumed(rig, monkeypatch) == "wait"
    assert len(of(lines(rig), "builder_released")) == 1
    assert exported(rig.run_dir, tmp_path / "before") == "unfinished"
    assert sign_every_open_item(rig.run_dir)
    assert resumed(rig, monkeypatch) == "done"
    done = export_of(rig.run_dir, tmp_path / "after")
    assert (done.status, done.sign_offs_owed) == ("contract_lost", ())
