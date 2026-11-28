"""An ablation trial's record says what it is, and no reader of a measured arm takes it.

The assembler marks an ablation run's trial record with what the run took away
(``ablation: "reviewers=off"``), read from the run's own configuration, so whoever assembles it
(the round, the record audit) writes the same mark; a measured trial's record has none, and keeps
its bytes. Fed in by hand, an arm's records are refused by every reader of a measured arm by name
(``ablation_record``): the per-role report, the counting rule (and the gap readers, which count
through it), and the baseline command, from the sheet beside a run set. The arm's own reader
takes only records that carry the mark, and the record audit holds the mark to the run.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from round_rig import PRICES, SCORED, Rig, make_rig
from test_an_ablation_arm_runs_beside_its_reference_and_is_never_read_as_the_harness import (
    ARM,
    _whole,
)

from physgate.evaluation.baseline.audit import HarnessCell, audit_harness
from physgate.evaluation.baseline.cli import replaced_run
from physgate.evaluation.baseline.runner import BaselineError, RunSet
from physgate.evaluation.observe.cost import load_price_sheet
from physgate.evaluation.per_role.assemble import read_arm_records
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.report import (
    ReportError,
    TrialRecord,
    complete,
    parse_design,
    parse_trials,
)
from physgate.evaluation.tiers.measure import census


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.fixture(scope="module")
def ran(tmp_path_factory: pytest.TempPathFactory) -> Rig:
    """One whole round with a reviewers-off arm, every place taken one at a time."""
    rig = make_rig(tmp_path_factory.mktemp("arm"))
    status, _ = _whole(rig)
    assert status == "done"
    return rig


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _arm_trials(rig: Rig) -> Path:
    return rig.root / "out" / f"ablation.{ARM}.trials.jsonl"


def test_an_arm_s_record_carries_the_mark_and_a_measured_record_none(ran: Rig) -> None:
    arm = [json.loads(x) for x in _lines(_arm_trials(ran))]
    harness = [json.loads(x) for x in _lines(ran.root / "out" / "visible.trials.jsonl")]
    assert [r["ablation"] for r in arm] == ["reviewers=off"] * 4
    assert all("ablation" not in r for r in harness), "a measured record keeps its bytes"
    # A record without the mark is written as it always was: the field is left out.
    record = TrialRecord.model_validate_json(_lines(ran.root / "out" / "visible.trials.jsonl")[0])
    assert "ablation" not in record.model_dump_json()


def test_the_per_role_report_refuses_an_arm_s_record_fed_in_by_hand(ran: Rig) -> None:
    records = parse_trials(_lines(_arm_trials(ran)))
    tasks = sorted({r.task for r in records})
    design = parse_design(
        json.dumps(
            {
                "experiment": "by hand",
                "seed": 1,
                "suites": [
                    {
                        "name": "control_visible",
                        "label": "the visible cell",
                        "role": "control",
                        "tier": "visible",
                        "tasks": tasks,
                        "arms": ["harness", "raw"],
                        "trials": 2,
                    }
                ],
            }
        ).encode()
    )
    with pytest.raises(ReportError) as refused:
        complete(design, records)
    assert refused.value.context["refused_because"] == "ablation_record"


def test_the_counting_rule_refuses_an_arm_s_records_beside_the_harness_s_run_set(
    ran: Rig,
) -> None:
    with pytest.raises(PerRoleError) as refused:
        census(
            ran.made.store,
            "control",
            ran.made.version,
            "visible",
            ran.root / "out" / "visible.runs.json",
            _arm_trials(ran),
        )
    assert refused.value.context["refused_because"] == "ablation_record"


def test_the_baseline_command_refuses_an_arm_s_sheet_beside_a_run_set(
    ran: Rig, tmp_path: Path
) -> None:
    out = ran.root / "out"
    harness = sorted((out / "trials").glob("*.runs.json"))[0]
    sheet = sorted((out / f"ablation.{ARM}" / "trials").glob("*.trial.json"))[0]
    shutil.copyfile(harness, tmp_path / "0009.runs.json")
    shutil.copyfile(sheet, tmp_path / "0009.trial.json")
    with pytest.raises(BaselineError) as refused:
        replaced_run(tmp_path / "0009.runs.json")
    assert refused.value.context["refused_because"] == "ablation_record"
    # The harness's own sheet beside its own set is read as before.
    assert replaced_run(harness) is None


def test_the_arm_s_reader_takes_only_records_that_carry_the_mark(ran: Rig) -> None:
    assert len(read_arm_records(_lines(_arm_trials(ran)))) == 4
    with pytest.raises(ReportError) as refused:
        read_arm_records(_lines(ran.root / "out" / "visible.trials.jsonl"))
    assert refused.value.context["refused_because"] == "not_an_ablation_record"


def test_the_record_audit_holds_the_mark_to_the_run(ran: Rig, tmp_path: Path) -> None:
    out = ran.root / "out"
    runs = RunSet.model_validate_json((out / f"ablation.{ARM}.runs.json").read_bytes())

    def audit(trials: Path) -> list[tuple[str, str, int | None]]:
        found = audit_harness(
            store=ran.made.store,
            role="control",
            version=ran.made.version,
            cells=[HarnessCell("visible", runs, trials)],
            prices=load_price_sheet(PRICES),
            score=_score,
            scratch=tmp_path / "scratch",
        )
        return [(d.tier, d.kind, d.index) for d in found]

    assert audit(_arm_trials(ran)) == []
    stripped = tmp_path / "stripped.trials.jsonl"
    lines = [json.loads(x) for x in _lines(_arm_trials(ran))]
    del lines[0]["ablation"]
    stripped.write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert audit(stripped) == [("visible", "ablation", 0)]


def test_a_record_that_does_not_carry_its_place_s_mark_stops_the_round_record_not_the_arm_s(
    ran: Rig,
) -> None:
    from physgate.evaluation import harness_round  # noqa: PLC0415 - the driver's own writer
    from physgate.evaluation.harness_round import HARNESS_ROUNDS, RoundError  # noqa: PLC0415
    from physgate.evaluation.tiers.store import withheld_root  # noqa: PLC0415

    place = next((withheld_root(ran.made.store, "control") / HARNESS_ROUNDS).iterdir())
    lines = [json.loads(x) for x in _lines(place / "ledger.jsonl")]
    assembled = [x for x in lines if x["kind"] == "assembled"]
    arm_places = {p["index"] for p in lines[0]["order"] if p.get("arm") is not None}
    arm_line = next(x for x in assembled if x["index"] in arm_places)
    harness_line = next(x for x in assembled if x["index"] not in arm_places)
    # Each as written: its own place's mark, or none.
    assert harness_round._record_line(harness_line)
    assert harness_round._record_line(arm_line, arm=ARM)
    unmarked = {
        **arm_line,
        "record": {k: v for k, v in arm_line["record"].items() if k != "ablation"},
    }
    for line, arm in ((unmarked, ARM), (harness_line, ARM), (arm_line, None)):
        with pytest.raises(RoundError) as refused:
            harness_round._record_line(line, arm=arm)
        assert refused.value.context["refused_because"] == "record_not_the_arm_s"
