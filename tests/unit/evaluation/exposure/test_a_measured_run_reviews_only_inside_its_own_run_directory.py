"""A measured run reviews only inside its own run directory, where the run roots withhold it whole.

A harness trial's review root holds each review's packet (the brief, the specification, the
answer), each reviewer's session directory and the place apart with the key for labels. A later
trial's role session and a raw baseline session of the same round run afterwards as the same
user. A measured run withholds whole exactly the registered run roots of its stores, and its
directory lies strictly inside one of them. So its review root, if strictly inside its directory,
is withheld whole from every later session. That makes the run roots and the review roots of its
stores the same places: nothing else is withheld whole, and no register of review roots is
needed, since every earlier measured run's review root lies in its own run directory too.

The command shows a requirement the review root the run names:
- at decompose, when one is given;
- at every run and resume, where one is always given.

A measured run asked at run or resume and shown none is refused. The refusals say a reason and
what the root is, never a path. A run that is not measured is not held to it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from exposure_fixtures import LAYER, StandInStore, config, stand_in_store, with_run_root

from physgate.evaluation import requirements
from physgate.evaluation.tiers.exposure import run_roots
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import RunConfig


@pytest.fixture
def made(tmp_path: Path) -> StandInStore:
    return stand_in_store(tmp_path.resolve() / "s")


def _measured(made: StandInStore, **changes: object) -> RunConfig:
    roots = [str(root) for root in run_roots(made.store, "control")]
    return config(made.tasks["held_out"][0], made, withheld_whole=roots, **changes)


def _ask(run: RunConfig, run_dir: Path, review_root: Path | None, *, new_run: bool) -> str | None:
    try:
        facts = RunFacts(
            config=run,
            os_layer=LAYER,
            shell_sessions=True,
            new_run=new_run,
            run_dir=run_dir,
            review_root=review_root,  # type: ignore[call-arg]
        )
    except TypeError:
        pytest.fail("a requirement is not shown the run's review root (RunFacts.review_root)")
    found: str | None = requirements.a_measured_run_withholds_every_run_root_whole(facts)
    return found


@pytest.mark.parametrize("new_run", [True, False], ids=["at decompose", "at run or resume"])
@pytest.mark.parametrize("beneath", ["review", "reviews/round-1"])
def test_a_measured_run_reviewing_inside_its_own_directory_goes_on(
    made: StandInStore, tmp_path: Path, new_run: bool, beneath: str
) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    run_dir = runs / "round" / "0000-1"
    assert _ask(_measured(made), run_dir, run_dir / beneath, new_run=new_run) is None


@pytest.mark.parametrize(
    "where",
    ["the standing root", "the run root", "another run's directory", "the run's own directory"],
)
@pytest.mark.parametrize("new_run", [True, False], ids=["at decompose", "at run or resume"])
def test_a_measured_run_reviewing_anywhere_else_is_refused_and_no_path_is_said(
    made: StandInStore, tmp_path: Path, where: str, new_run: bool
) -> None:
    base = tmp_path.resolve()
    runs = with_run_root(made, base / "runs")
    run_dir = runs / "round" / "0000-1"
    review = {
        "the standing root": base / "review-scratch",
        "the run root": runs,
        "another run's directory": runs / "round" / "0000-2" / "review",
        "the run's own directory": run_dir,
    }[where]
    why = _ask(_measured(made), run_dir, review, new_run=new_run)
    assert why is not None and "(review_root_outside_the_run)" in why, why
    assert str(base) not in why, why


def test_a_review_root_reached_through_a_link_is_judged_where_it_really_is(
    made: StandInStore, tmp_path: Path
) -> None:
    base = tmp_path.resolve()
    runs = with_run_root(made, base / "runs")
    run_dir = runs / "round" / "0000-1"
    run_dir.mkdir(parents=True)
    (base / "elsewhere").mkdir()
    os.symlink(base / "elsewhere", run_dir / "review")
    why = _ask(_measured(made), run_dir, run_dir / "review", new_run=False)
    assert why is not None and "(review_root_outside_the_run)" in why, why


def test_a_measured_run_shown_no_review_root_at_run_or_resume_is_refused(
    made: StandInStore, tmp_path: Path
) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    why = _ask(_measured(made), runs / "run-1", None, new_run=False)
    assert why is not None and "(review_root_not_shown)" in why, why


def test_a_measured_run_whose_plan_is_not_reviewed_decomposes_with_no_review_root(
    made: StandInStore, tmp_path: Path
) -> None:
    runs = with_run_root(made, tmp_path.resolve() / "runs")
    assert _ask(_measured(made), runs / "run-1", None, new_run=True) is None


def test_a_run_that_is_not_measured_may_review_anywhere(made: StandInStore, tmp_path: Path) -> None:
    base = tmp_path.resolve()
    runs = with_run_root(made, base / "runs")
    run = _measured(made, reportable=False)
    assert _ask(run, runs / "run-1", base / "review-scratch", new_run=False) is None
    assert _ask(run, runs / "run-1", None, new_run=False) is None
