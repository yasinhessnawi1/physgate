"""The decision sequence carries the declaration, each completion and each contract result.

A rerun is compared with its run by this sequence, so a run that parts at a declaration, a
completion or a contract result parts there in the sequence too. The declaration step carries the
modules it names, a completion step the module and the attempt that declared it, the pairs step the
pairs in recorded order, and a contract step the pair, its verdict and whether it is the pair's
first. None carries a commit, a revision or a digest: no two reruns share them.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing as runner

from physgate import roles
from physgate.evaluation.observe.sequence import decisions

INTEG, DRIVE, FW = runner.INTEG, runner.DRIVE, runner.FW


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    rig, _ = runner.finished(tmp_path, monkeypatch, **kw)
    lines = (rig.run_dir / "events.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def steps(found: list[dict[str, Any]], *names: str) -> list[dict[str, Any]]:
    return [{k: v for k, v in s.items() if k != "seq"} for s in found if s["step"] in names]


def test_the_decision_sequence_carries_the_declaration_and_each_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = decisions(records(tmp_path, monkeypatch, declared=(DRIVE, FW)))
    assert steps(found, "declared", "completed") == [
        {"step": "declared", "subtask_id": INTEG, "attempt": 1, "modules": [DRIVE, FW]},
        {"step": "completed", "subtask_id": DRIVE, "declared_by": INTEG, "attempt": 1},
        {"step": "completed", "subtask_id": FW, "declared_by": INTEG, "attempt": 1},
    ]
    # In log order: the declaration before the gate's verdict on the attempt that made it.
    order = [s["step"] for s in found if s.get("subtask_id") == INTEG]
    assert order.index("declared") < order.index("gate")


def test_the_decision_sequence_carries_the_pairs_and_each_contract_result_and_never_its_commit_revision_or_digest(  # noqa: E501
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = records(tmp_path, monkeypatch, declared=(DRIVE, FW), fw_volts=11)
    found = decisions(lines)
    (planned,) = [r for r in lines if r["kind"] == "contract_pairs_planned"]
    tested = [r for r in lines if r["kind"] == "contract_tested"]
    assert steps(found, "contract_pairs") == [{"step": "contract_pairs", "pairs": planned["pairs"]}]
    assert steps(found, "contract") == [
        {"step": "contract", "pair": t["result"]["pair"], "verdict": v, "first": True}
        for t, v in zip(tested, ("fail", "pass"), strict=True)
    ]
    # A rerun that differs only in what no two reruns share reads the same sequence.
    again = copy.deepcopy(lines)
    for r in again:
        if r["kind"] == "contract_tested":
            r |= {"commit": "f" * 40, "revision": r["revision"] + 7}
            r["result"]["definition_sha256"] = "e" * 64
        if r["kind"] == "completion_declared":
            r["declaration_sha256"] = "e" * 64
    assert decisions(again) == found
    # One that parts at a contract result's verdict or its place parts in the sequence.
    for field, value in (("first", False), ("outcome", "pass")):
        parted = copy.deepcopy(lines)
        line = next(r for r in parted if r["kind"] == "contract_tested")
        (line if field == "first" else line["result"])[field] = value
        assert decisions(parted) != found, field
