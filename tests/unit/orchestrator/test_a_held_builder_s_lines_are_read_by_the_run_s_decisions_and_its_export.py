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
from test_a_builder_is_held_until_the_design_it_implements_merges import (
    LAW,
    chain_run,
    chained,
    drive_item,
    first_run,
    resumed,
    rigged,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import lines
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    DRIVE,
    FW,
)
from test_a_queue_decision_acts_at_a_boundary import decide

from physgate.evaluation.observe.sequence import decisions
from physgate.evaluation.whole.export import export_whole_run
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


def exported(run_dir: Path, tmp_path: Path) -> str:
    """The export's status over ``run_dir``'s event log, beside an empty store."""
    run = Path(os.path.realpath(tmp_path)) / "copy"
    (run / "store").mkdir(parents=True)
    Store(run / "store").close()
    (run / "events.jsonl").write_bytes((run_dir / "events.jsonl").read_bytes())
    out = Path(os.path.realpath(tmp_path)) / "answers" / "whole_run.json"
    return export_whole_run(run, out).status


def test_the_export_reads_a_builder_held_for_good_as_a_run_not_every_module_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path / "rig")
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "reject", "no attempt is left", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch) == "done"
    assert exported(rig.run_dir, tmp_path) == "unfinished"


def test_the_export_reads_a_builder_let_go_and_merged_as_a_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rigged(tmp_path / "rig")
    assert first_run(rig, monkeypatch) == "wait"
    decide(rig.run_dir, "approve", item_id=drive_item(lines(rig)))
    assert resumed(rig, monkeypatch) == "done"
    # Finished, its empty graph then holding no structure: the log is read, not refused.
    assert exported(rig.run_dir, tmp_path) == "contract_lost"
