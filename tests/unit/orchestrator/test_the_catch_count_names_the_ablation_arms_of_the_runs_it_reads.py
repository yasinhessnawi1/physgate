"""The catch count keeps each run's ablation arms apart, and names them on its rows.

A catch is a blocking gate failure on work a reviewer had passed (ARCH-083). Under
``reviewers: off`` no reviewer passed anything, under ``generalist`` the reviewer is not the
paired one, and under ``skills: off`` or ``hooks: off`` the work was made by a smaller harness:
a row that summed such a run with a full harness's would read as one number about both. So every
gate event carries the arms its run recorded on its opening line, the count is taken per gate
mode and per set of arms, and a row names the arms that differ from the full harness. A row of
full-harness runs reads as it always did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from loop_fakes import FakeGate, FakeReviewer, Rig, plan
from orch_helpers import CLEAN_HARNESS
from test_reviewers_generalist_reviews_with_the_paired_rubric_less_its_domain_sections import (
    _verdict,
)

from physgate.cli import main
from physgate.orchestrator.catches import catches
from physgate.orchestrator.gate_events import recorded_gate_events

ALWAYS_FAILS = ["fail"] * 10


def _run(tmp: Path, **arms: Any) -> Path:  # noqa: ANN401
    overrides = {**arms, "ablation": bool(arms), "harness": CLEAN_HARNESS}
    # A generalist arm's reviewer judges with the generalist rubric, as the arm's reviewers do.
    kind = "generalist" if arms.get("reviewers") == "generalist" else None
    rig = Rig(
        tmp,
        gate_mode="observe",
        gate=FakeGate(verdicts=ALWAYS_FAILS),
        reviewer=FakeReviewer(results={1: _verdict(kind)}),
        config_overrides=overrides,
    )
    loop = outcome_of(rig.open)
    assert not isinstance(loop, Exception), f"the run is refused at its configuration: {loop}"
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    return tmp


def _events(run_dir: Path) -> Any:  # noqa: ANN401
    return recorded_gate_events(run_dir / "events.jsonl", run_dir / "run.json")


@pytest.mark.parametrize(
    "arms",
    [
        {"reviewers": "off"},
        {"reviewers": "generalist"},
        {"hooks": "off"},
        {"reviewers": "off", "hooks": "off"},
    ],
    ids=lambda a: "+".join(f"{k}={v}" for k, v in a.items()),
)
def test_each_gate_event_carries_its_run_s_arms(tmp_path: Path, arms: dict[str, str]) -> None:
    found = _events(_run(tmp_path, **arms))
    assert found
    for event in found:
        carried = {name: getattr(event, name, None) for name in arms}
        assert carried == arms, f"a gate event of the run does not name its arms: {carried}"


def test_a_full_harness_run_s_gate_events_name_no_arm(tmp_path: Path) -> None:
    found = _events(_run(tmp_path))
    for event in found:
        assert getattr(event, "reviewers", None) is None
        assert "reviewers" not in event.model_dump_json()


def test_the_count_keeps_an_arm_s_runs_apart_from_the_full_harness(tmp_path: Path) -> None:
    full = _events(_run(tmp_path / "full"))
    off = _events(_run(tmp_path / "off", reviewers="off"))
    rows = catches([*full, *off])
    alls = [row for row in rows if row.name == "all"]
    assert len(alls) == 2, f"the count summed an ablation run with a full harness run: {alls}"
    named = sorted(getattr(row, "reviewers", None) or "paired" for row in alls)
    assert named == ["off", "paired"]
    by_arm = {getattr(row, "reviewers", None): row for row in alls}
    assert by_arm[None].checks_run == catches(full)[-1].checks_run
    assert by_arm["off"].reviewer_had_passed == 0
    assert "reviewers" not in by_arm[None].model_dump_json()


def test_the_command_prints_the_arm_on_its_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    full = _run(tmp_path / "full")
    off = _run(tmp_path / "off", reviewers="off")
    assert main(["catches", "--run-dir", str(full), "--run-dir", str(off)]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    alls = [row for row in rows if row["name"] == "all"]
    assert sorted(row.get("reviewers", "paired") for row in alls) == ["off", "paired"]
