"""A measured run withholds whole every run root of the stores it names, and nothing else so.

The earlier runs on a store lie under its roles' run roots, each with every canary of the store,
the plan written from its brief and its answer. A measured run names, among the roots its
sessions withhold whole (``withheld_whole``), exactly the run roots the run-roots log holds for
every role whose root it names, spelt as the log holds them: one left out refuses it, and so
does any root that is not one of them. Its directory lies inside a run root, never at one, so
its sessions have a place of their own inside the root they withhold. The command asks it at
the start and at every run and resume, so a root registered while a run was halted refuses its
resume until it names it. A run that is not measured is not held to it. Each refusal says counts
and a reason, never a path. A baseline round holds every harness run to the same rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exposure_fixtures import StandInStore, api, config, facts, stand_in_store, with_run_root

from physgate.evaluation import requirements
from physgate.evaluation.tiers.exposure import run_roots

REQUIREMENT = "a_measured_run_withholds_every_run_root_whole"


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path.resolve() / "s")


def _ask(run: object, run_dir: Path | None, *, new_run: bool = True) -> str | None:
    requirement = getattr(requirements, REQUIREMENT, None)
    assert requirement is not None, "no requirement holds a measured run to the run roots"
    assert requirement in requirements.REQUIREMENTS, "the command does not hold runs to it"
    found: str | None = requirement(facts(run, run_dir, new_run=new_run))  # type: ignore[arg-type]
    return found


def _roots(made: StandInStore) -> list[str]:
    return [str(r) for r in run_roots(made.store, "control")]


def _two_roots(made: StandInStore, base: Path) -> tuple[Path, Path]:
    return with_run_root(made, base / "runs"), with_run_root(made, base / "older")


def test_a_run_withholding_every_run_root_whole_goes_on(made: StandInStore, tmp_path: Path) -> None:
    runs, _ = _two_roots(made, tmp_path.resolve())
    task = made.tasks["held_out"][0]
    run = config(task, made, withheld_whole=_roots(made))
    assert _ask(run, runs / "run-1") is None


def test_a_run_root_left_out_refuses_it_and_says_no_path(
    made: StandInStore, tmp_path: Path
) -> None:
    runs, older = _two_roots(made, tmp_path.resolve())
    task = made.tasks["held_out"][0]
    run = config(task, made, withheld_whole=[str(runs)])
    why = _ask(run, runs / "run-1")
    assert why is not None and "(run_root_not_withheld)" in why, why
    assert str(older) not in why and str(runs) not in why, why


def test_a_run_withholding_no_run_root_is_refused(made: StandInStore, tmp_path: Path) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    task = made.tasks["held_out"][0]
    why = _ask(config(task, made), runs / "run-1")
    assert why is not None and "(run_root_not_withheld)" in why, why


@pytest.mark.parametrize("other", ["elsewhere", "runs/run-0", "runs/"])
def test_a_root_withheld_whole_that_is_no_run_root_as_recorded_refuses_it(
    made: StandInStore, tmp_path: Path, other: str
) -> None:
    base = tmp_path.resolve()
    runs = with_run_root(made, base / "runs")
    (base / "elsewhere").mkdir()
    task = made.tasks["held_out"][0]
    # A place of no store, a run inside the root, and the root spelt otherwise than recorded.
    named = str(base / other) if other != "runs/" else str(runs) + "/"
    run = config(task, made, withheld_whole=[*_roots(made), named])
    why = _ask(run, runs / "run-1")
    assert why is not None and "(withheld_whole_not_a_run_root)" in why, why
    assert str(base) not in why, why


def test_a_run_whose_directory_is_a_run_root_is_refused(made: StandInStore, tmp_path: Path) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    task = made.tasks["held_out"][0]
    why = _ask(config(task, made, withheld_whole=_roots(made)), runs)
    assert why is not None and "(run_dir_is_a_run_root)" in why, why


def test_a_root_registered_while_a_run_was_halted_refuses_its_resume(
    made: StandInStore, tmp_path: Path
) -> None:
    base = tmp_path.resolve()
    runs = with_run_root(made, base / "runs")
    task = made.tasks["held_out"][0]
    run = config(task, made, withheld_whole=_roots(made))
    assert _ask(run, runs / "run-1", new_run=False) is None
    with_run_root(made, base / "later")
    why = _ask(run, runs / "run-1", new_run=False)
    assert why is not None and "(run_root_not_withheld)" in why, why


def test_a_run_that_is_not_measured_is_not_held_to_it(made: StandInStore, tmp_path: Path) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    task = made.tasks["held_out"][0]
    run = config(task, made, reportable=False)
    assert _ask(run, runs / "run-1") is None


def test_a_measured_run_naming_no_store_withholds_no_root_whole(tmp_path: Path) -> None:
    made = stand_in_store(tmp_path.resolve() / "s")
    task = made.tasks["visible"][0]
    plain = config(task, made, held_out=[], held_out_sha256=[], held_out_canaries=[])
    assert _ask(plain, tmp_path / "run") is None
    (tmp_path / "elsewhere").mkdir()
    named = config(
        task,
        made,
        held_out=[],
        held_out_sha256=[],
        held_out_canaries=[],
        withheld_whole=[str(tmp_path.resolve() / "elsewhere")],
    )
    why = _ask(named, tmp_path / "run")
    assert why is not None and "(withheld_whole_not_a_run_root)" in why, why


def test_a_baseline_round_refuses_a_harness_run_that_left_a_run_root_open(
    made: StandInStore, tmp_path: Path
) -> None:
    runner = api("physgate.evaluation.baseline.runner")
    error = api("physgate.evaluation.baseline.runner.BaselineError")
    with_run_root(made, tmp_path.resolve() / "runs")
    task = made.tasks["held_out"][0]
    canaries = set(made.canaries)
    with pytest.raises(error) as raised:
        runner._require_withheld(made.store, "control", config(task, made), canaries, {})
    assert raised.value.context.get("refused_because") == "run_root_not_withheld"
    # Withholding every one, the same run is not refused for it.
    whole = config(task, made, withheld_whole=_roots(made))
    runner._require_withheld(made.store, "control", whole, canaries, {})


def test_the_field_is_left_out_of_the_record_of_a_run_that_names_none(made: StandInStore) -> None:
    task = made.tasks["held_out"][0]
    plain = config(task, made)
    assert "withheld_whole" not in json.loads(plain.canonical_bytes())
    named = config(task, made, withheld_whole=["/elsewhere/runs"])
    assert json.loads(named.canonical_bytes())["withheld_whole"] == ["/elsewhere/runs"]
    assert named.sha256() != plain.sha256()
