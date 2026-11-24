"""The run and review directories a round names pass the core's rule for a measured run.

Every measured run withholds its stores' run roots whole and reviews inside its own run directory
(the core asks it at decomposition, at every run and at every resume). A trial's run directory
lies strictly inside the registered run root, spelt as on disk, and is no run root itself; its
review root lies strictly inside it, and not in its worktrees or its sessions' directories, where
a module's work is committed from and a session's own files lie. Asked of every directory the
round named to the command, at decomposition and at the drive, as the core's own requirement.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, Rig, StandInDriver, make_rig

from physgate.evaluation.harness_round import REVIEW, Decompose, Drive, run_round
from physgate.evaluation.requirements import a_measured_run_withholds_every_run_root_whole
from physgate.evaluation.tiers.exposure import review_root_refusal, run_roots_refusal
from physgate.evaluation.tiers.store import spelt_as_on_disk
from physgate.orchestrator.requirements import RunFacts
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.oslayer.probe import Present

TIERS = ("visible", "held_out")
#: The OS layer present where the sessions run, as the rig's parameters record it.
LAYER = Present(mechanism="bubblewrap", claude_version="2.1.301")


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.fixture(scope="module")
def round_of_two(tmp_path_factory: pytest.TempPathFactory) -> tuple[Rig, StandInDriver]:
    """A round of a visible and a held-out task, two trials of each."""
    rig = make_rig(tmp_path_factory.mktemp("named"))
    driver = rig.driver()
    status, _ = run_round(
        rig.inputs(tiers=TIERS, trials=2, tasks=1),
        driver=driver,
        scorer=_score,
        sleep=lambda _: None,
    )
    assert status == "done"
    return rig, driver


def _facts(config: RunConfig, run_dir: Path, review_root: Path, *, new_run: bool) -> RunFacts:
    return RunFacts(
        config=config,
        os_layer=LAYER,
        shell_sessions=True,
        new_run=new_run,
        run_dir=run_dir,
        review_root=review_root,
    )


def test_every_directory_the_round_decomposed_in_passes_the_core_s_rule(
    round_of_two: tuple[Rig, StandInDriver],
) -> None:
    _, driver = round_of_two
    assert len(driver.decomposed) == 4
    for call in driver.decomposed:
        config = load_run_config(call.run_dir / "run.json")
        assert config.withheld_whole, "the run withheld no root whole"
        assert call.review_root == call.run_dir / REVIEW
        assert (
            a_measured_run_withholds_every_run_root_whole(
                _facts(config, call.run_dir, call.review_root, new_run=True)
            )
            is None
        )
        assert run_roots_refusal(config, call.run_dir) is None
        assert review_root_refusal(call.run_dir, call.review_root, reviewing=True) is None


def test_every_directory_the_round_drove_passes_the_core_s_rule(
    round_of_two: tuple[Rig, StandInDriver],
) -> None:
    _, driver = round_of_two
    assert len(driver.drives) >= 4
    for call in driver.drives:
        config = load_run_config(call.run_dir / "run.json")
        assert (
            a_measured_run_withholds_every_run_root_whole(
                _facts(config, call.run_dir, call.review_root, new_run=False)
            )
            is None
        )


def test_a_trial_s_run_directory_is_spelt_as_on_disk_strictly_inside_its_run_root(
    round_of_two: tuple[Rig, StandInDriver],
) -> None:
    rig, driver = round_of_two
    root = str(rig.run_root)
    calls: list[Decompose | Drive] = [*driver.decomposed, *driver.drives]
    for call in calls:
        run_dir = str(call.run_dir)
        assert run_dir == os.path.realpath(run_dir) and spelt_as_on_disk(call.run_dir)
        assert run_dir.startswith(root + "/") and run_dir != root
        review = os.path.realpath(call.review_root)
        assert review.startswith(run_dir + "/")
        for place in ("worktrees", "sessions"):
            assert not review.startswith(f"{run_dir}/{place}")
