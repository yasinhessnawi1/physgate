"""A trial's answer is read from the module directory its own recorded plan names, and nowhere else.

The planner chooses where each module lies; the run records it in its plan's lines. So the answer
is the one file of the task's answer name directly inside the module directory the trial's plan
names for its role, wherever the plan put that directory: ``modules/<name>``, as most plans do, or
any other place the plan check let through. A file of that name anywhere else on the run branch is
not the answer, even when it is the only one; and a planned directory without it is no answer, the
harness's own fail.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.harness_round import HARNESS_ROUNDS, LEDGER, ROUND_RECORD, run_round
from physgate.evaluation.tiers.store import withheld_root


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _assembled(rig: Rig, **how: Any) -> dict[str, Any]:  # noqa: ANN401
    status, summary = run_round(
        rig.inputs(trials=1), driver=rig.driver(**how), scorer=_score, sleep=lambda _: None
    )
    assert status in ("done", "done_without_caps")
    place = withheld_root(rig.made.store, "control") / HARNESS_ROUNDS / summary["round"]
    lines = [json.loads(x) for x in (place / LEDGER).read_bytes().splitlines()]
    (line,) = [x for x in lines if x["kind"] == "assembled"]
    return dict(line)


def test_the_answer_in_a_planned_modules_directory_is_found_as_before(tmp_path: Path) -> None:
    line = _assembled(make_rig(tmp_path))
    assert (line["answer"], line["outcome"]) == ("found", "pass")


def test_the_answer_in_a_planned_directory_outside_modules_is_found(tmp_path: Path) -> None:
    line = _assembled(make_rig(tmp_path), module_dir=lambda minted: f"control/{minted}")
    assert (line["answer"], line["outcome"]) == ("found", "pass")


def test_the_answer_in_a_planned_directory_deeper_under_modules_is_found(tmp_path: Path) -> None:
    line = _assembled(make_rig(tmp_path), module_dir=lambda minted: f"modules/ctl/{minted}")
    assert (line["answer"], line["outcome"]) == ("found", "pass")


def _elsewhere(tmp_path: Path) -> Rig:
    """A rig whose target already holds a file of the answer's name in a directory no plan names."""
    rig = make_rig(tmp_path)
    old = rig.target / "modules" / "old" / rig.task().answer.path
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({"x": 1}))
    for args in (["add", "-A"], ["commit", "-q", "-m", "an older module"]):
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
            cwd=rig.target,
            check=True,
            capture_output=True,
        )
    return rig


def test_an_answer_file_outside_the_planned_directory_is_not_taken_beside_the_answer(
    tmp_path: Path,
) -> None:
    line = _assembled(_elsewhere(tmp_path))
    assert (line["answer"], line["outcome"]) == ("found", "pass")


def test_an_answer_file_outside_the_planned_directory_is_not_taken_alone(tmp_path: Path) -> None:
    line = _assembled(_elsewhere(tmp_path), silent={1})
    assert (line["answer"], line["outcome"]) == ("contract_lost", "fail")


def test_a_planned_directory_without_the_answer_is_the_harness_s_own_fail(tmp_path: Path) -> None:
    line = _assembled(make_rig(tmp_path), silent={1})
    assert (line["answer"], line["outcome"]) == ("contract_lost", "fail")
    assert line["harness_total"] is not None
    summary = json.loads((tmp_path.resolve() / "out" / ROUND_RECORD).read_bytes())
    assert summary["done"] is True
