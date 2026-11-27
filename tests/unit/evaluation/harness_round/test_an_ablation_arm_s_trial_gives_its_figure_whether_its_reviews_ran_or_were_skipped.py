"""An ablation arm's trial gives its figure whether its reviews ran or were skipped.

An arm that takes away a part other than the reviewers (here the skills) is still a reviewed run:
the round's stand-in reviewers record each review's spawn on the run's log as the real reviewer
does, in the arm's runs as in the harness's, and leave its stream beneath the run's review root.
Its reviews end by their verdicts, so the arm's sheet states a figure and no reason for none. An
arm with its reviewers off spawns no review at all: its log says each review was skipped, and the
rule finds no session of its open, so its figure is stated too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from round_rig import SCORED, Rig, make_rig

from physgate.evaluation.baseline.runner import RunSet
from physgate.evaluation.harness_round import Ablation, run_round
from physgate.orchestrator.events import (
    ReviewRan,
    ReviewSkipped,
    SessionEnded,
    SessionSpawned,
    read_events,
)
from physgate.orchestrator.review_root_record import recorded_review_root
from physgate.orchestrator.session_ends import open_sessions


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _whole(rig: Rig, arm: Ablation) -> tuple[str, dict[str, Any]]:
    """Both places of a cell of one task and one trial, one call each, as a launch script does."""
    driver = rig.driver()
    status, summary = "", dict[str, Any]()
    for place in range(2):
        status, summary = run_round(
            rig.inputs(trials=1, tasks=1, seed_base=1, order_seed=1124, ablation=arm),
            driver=driver,
            scorer=_score,
            sleep=lambda _: None,
            resume=place > 0,
            only=place,
        )
    return status, summary


def _arm_runs(rig: Rig, name: str) -> list[Path]:
    path = rig.root / "out" / f"ablation.{name}.runs.json"
    runs = RunSet.model_validate_json(path.read_bytes())
    return [Path(entry.run_dir) for entry in runs.trials]


def _arm_sheets(rig: Rig, name: str) -> list[dict[str, Any]]:
    trials = rig.root / "out" / f"ablation.{name}" / "trials"
    return [json.loads(p.read_bytes()) for p in sorted(trials.glob("*.trial.json"))]


def test_an_arm_s_reviewed_trial_records_each_review_s_spawn_and_gives_its_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    arm = Ablation("skills_off", rig.arm_params(reviewers="paired", skills="off"))
    status, summary = _whole(rig, arm)
    # The arm's sheet states a figure and no reason for none.
    [sheet] = _arm_sheets(rig, "skills_off")
    assert sheet["no_figure"] is None
    assert sheet["harness_total"] is not None and sheet["harness_total"] > 0
    assert sheet["raw_pair"] == "never"
    [run_dir] = _arm_runs(rig, "skills_off")
    events = read_events(run_dir / "events.jsonl")
    reviews = [e.result.session_id for e in events if isinstance(e, ReviewRan)]
    assert reviews, "the arm's run was reviewed"
    # The stand-in reviewer recorded each review's spawn in the arm's run, as the real one does,
    # and left its stream beneath the run's review root.
    spawned = [e.session_id for e in events if isinstance(e, SessionSpawned)]
    assert set(reviews) <= set(spawned)
    root = recorded_review_root(run_dir)
    assert root is not None
    for session_id in reviews:
        assert (root / session_id / "session" / "stdout.jsonl").is_file()
    # A review its verdict ended is no session left open, in the arm's run as in the harness's.
    assert open_sessions(events, run_dir) == ()
    assert status == "done"
    assert summary["no_figure"] == {"visible": 0}


def test_an_arm_that_skips_every_review_spawns_none_and_gives_its_figure(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    status, _summary = _whole(rig, Ablation("reviewers_off", rig.arm_params()))
    [run_dir] = _arm_runs(rig, "reviewers_off")
    events = read_events(run_dir / "events.jsonl")
    assert any(isinstance(e, ReviewSkipped) for e in events)
    assert not any(isinstance(e, ReviewRan) for e in events)
    # Every spawn on its log is a role session's, each ended by its own line.
    spawned = {e.session_id for e in events if isinstance(e, SessionSpawned)}
    assert spawned
    assert spawned == {e.session_id for e in events if isinstance(e, SessionEnded)}
    assert open_sessions(events, run_dir) == ()
    [sheet] = _arm_sheets(rig, "reviewers_off")
    assert sheet["harness_total"] is not None and sheet["harness_total"] > 0
    assert sheet["no_figure"] is None
    # The round's harness trial was reviewed beside it, and gives its figure too.
    assert status == "done"
