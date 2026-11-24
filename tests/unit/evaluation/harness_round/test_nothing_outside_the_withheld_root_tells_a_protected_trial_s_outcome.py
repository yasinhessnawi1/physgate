"""Nothing outside the withheld root tells how a protected trial ended, or lets it be inferred.

A protected tier's outcomes are read only through its vector, which counts the look. So the
round's output directory and what it prints are the same however a protected trial ends: passed,
its decomposition superseded and the trial unscored, or left with no cap. They count the visible
tier's outcomes, the visible tier's superseded, set-aside, refused-credential and limit ends and
its trials with no cap; of a protected tier, only how many trials it has and how many are
assembled. And an error a protected trial's step raised, which may name its task, reaches no
one outside the withheld root as raised: its tier and its kind alone are said, nothing it carried,
wherever in the round it was raised.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, StandInDriver, make_rig, protected_tiers_withheld

from physgate.evaluation import harness_round
from physgate.evaluation.harness_round import ROUND_RECORD, RoundError, run_round

TIERS = ("visible", "held_out")
#: What differs between two rigs whatever their trials did: the round's id, each rig's own
#: version, and the digests of inputs that name each rig's own paths.
PER_RIG = (
    "round",
    "version",
    "inputs_sha256",
    "check_sha256",
    "params_sha256",
    "register_before",
    "register_after",
)


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _round(rig: Rig, driver: StandInDriver) -> tuple[str, dict[str, Any]]:
    with protected_tiers_withheld():
        status, summary = run_round(
            rig.inputs(tiers=TIERS, trials=1, tasks=1),
            driver=driver,
            scorer=_score,
            sleep=lambda _: None,
        )
    return status, summary


def _visible(rig: Rig) -> dict[str, Any]:
    """The output directory, file by file, and the round's summary in it, less the rig's own."""
    out = rig.root / "out"
    files = {p.name: p.read_bytes() for p in sorted(out.iterdir())}
    summary = json.loads(files.pop(ROUND_RECORD))
    return {"files": files, "summary": {k: v for k, v in summary.items() if k not in PER_RIG}}


def _printed(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in summary.items() if k not in PER_RIG}


@pytest.mark.parametrize(
    "ended",
    [{"fails": {2: "api_error", 3: "api_error"}}, {"fails": {2: "invalid_plan"}}, {"silent": {2}}],
    ids=["superseded then unscored", "a plan of its own refused, no cap", "no answer"],
)
def test_the_output_directory_and_the_summary_are_the_same_however_a_protected_trial_ends(
    tmp_path: Path, ended: dict[str, Any]
) -> None:
    passed = make_rig(tmp_path / "passed")
    _, first = _round(passed, passed.driver())
    other = make_rig(tmp_path / "other")
    _, second = _round(other, other.driver(**ended))
    seen = _visible(other)
    # The visible tier's own records differ by their rig's paths only; the rest is the same.
    seen["files"] = {k: v for k, v in seen["files"].items() if not k.startswith("visible.")}
    shown = _visible(passed)
    shown["files"] = {k: v for k, v in shown["files"].items() if not k.startswith("visible.")}
    assert seen == shown
    assert _printed(second) == _printed(first)


def test_of_a_protected_tier_only_its_trials_and_their_assembly_are_counted_outside(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    _, summary = _round(rig, rig.driver(fails={2: "invalid_plan"}))
    written = json.loads((rig.root / "out" / ROUND_RECORD).read_bytes())
    for said in (summary, written):
        assert set(said["tiers"]["held_out"]) == {"trials", "assembled"}
        assert set(said["no_cap"]) == {"visible"}
        for count in ("superseded", "left", "credential_refused", "usage_limit"):
            assert isinstance(said[count], int)


def _brief_and_id(rig: Rig) -> tuple[str, str]:
    task = rig.task("held_out")
    return task.brief, task.id


def _caught(rig: Rig, driver: StandInDriver, **patches: Any) -> BaseException:  # noqa: ANN401
    with pytest.MonkeyPatch.context() as patch:
        for name, value in patches.items():
            patch.setattr(harness_round, name, value)
        try:
            _round(rig, driver)
        except Exception as exc:  # noqa: BLE001 - what reaches the caller is the row's subject
            return exc
    pytest.fail("the round did not stop")


def _carries_nothing(exc: BaseException, brief: str, task_id: str) -> None:
    assert isinstance(exc, RoundError), f"a protected trial's {type(exc).__name__} was relayed"
    said = " ".join([str(exc), *map(str, exc.context.values())])
    assert brief not in said and task_id not in said
    assert exc.__cause__ is None and exc.__suppress_context__


def test_an_error_a_protected_trial_s_command_raised_is_said_by_its_kind_alone(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    brief, task_id = _brief_and_id(rig)
    driver = rig.driver()
    made = driver.decompose

    def naming(call: Any) -> int:  # noqa: ANN401
        if call.brief.read_text() == brief:
            msg = f"could not plan {task_id}: {brief}"
            raise ValueError(msg)
        return made(call)

    driver.decompose = naming  # type: ignore[method-assign]
    _carries_nothing(_caught(rig, driver), brief, task_id)


def test_an_error_raised_while_a_protected_tier_s_records_are_written_is_said_by_its_kind_alone(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    brief, task_id = _brief_and_id(rig)
    whole = harness_round._write_whole  # noqa: SLF001

    def naming(path: Path, data: bytes) -> None:
        if path.name.startswith("held_out."):
            msg = f"cannot write the records of {task_id}: {brief}"
            raise OSError(msg)
        whole(path, data)

    _carries_nothing(_caught(rig, rig.driver(), _write_whole=naming), brief, task_id)
