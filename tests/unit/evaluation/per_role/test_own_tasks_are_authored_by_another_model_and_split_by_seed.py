from __future__ import annotations

import json
from pathlib import Path

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role.authoring import (
    AuthoringError,
    author_brief,
    require_author_model,
    split,
)
from physgate.evaluation.per_role.metrics import CONTROL_METRIC_UNITS
from physgate.evaluation.per_role.task import load_task


def test_an_author_on_the_implementers_model_is_refused() -> None:
    with pytest.raises(AuthoringError, match="implementers' own model"):
        require_author_model("claude-opus-5-5", "claude-opus-5-5")
    require_author_model("claude-sonnet-5", "claude-opus-5-5")


def test_the_author_is_told_the_format_and_the_metrics_and_nothing_of_the_harness() -> None:
    brief = author_brief("control")
    for told in ("phase_margin, in deg", "settling_time, in s", "composes", "expect.json"):
        assert told in brief
    assert "exactly 16 tasks" in brief
    for withheld in ("knowledge", "rubric", "reviewer", "gate", "physgate", "harness"):
        assert withheld not in brief.lower()


def test_the_author_is_told_every_name_the_scorer_reads_a_plant_and_an_answer_by() -> None:
    brief = author_brief("control")
    # The plant's inputs, each coefficient's unit, and the two optional inputs.
    for told in ("plant_num_0", "plant_den_0", '"s**k"', "plant_gain", "plant_delay"):
        assert told in brief
    # The answer's form and fields, which every task's brief must pass on to the designer.
    for told in ('"form": "lti_tf"', '"gain"', '"num"', '"den"', "proper", "at most 10"):
        assert told in brief
    # The actuator's peak, bounded in the unit the task gives its actuator's limit in.
    assert "actuator_peak, in the unit of actuator_limit" in brief
    assert "  - actuator_limit: " in brief and "  - reference_step: " in brief
    assert '"version": "1.1.0"' in brief
    # The scorer needs a settling-time bound to set its horizon.
    assert "Every task bounds settling_time" in brief
    for metric in CONTROL_METRIC_UNITS:
        assert f"  - {metric}, in {CONTROL_METRIC_UNITS[metric]}: " in brief


def test_the_author_is_not_promised_a_scoring_command_it_does_not_have() -> None:
    assert "command" not in author_brief("control")


def test_the_author_is_told_its_numerical_tools_and_to_write_each_task_as_it_goes() -> None:
    brief = author_brief("control")
    assert "python-control 0.10.1, numpy and scipy" in brief
    assert "no network" in brief
    assert "as soon as it is complete, before you begin the next" in brief


def _stage(root: Path, count: int = 16) -> Path:
    staging = root / "staging"
    for i in range(count):
        write_task_dir(
            staging / f"control.t{i:02d}",
            own_task(id=f"control.t{i:02d}"),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return staging


def test_a_split_sends_eight_to_each_tier_and_the_same_seed_splits_alike(tmp_path: Path) -> None:
    first = split(_stage(tmp_path / "a"), tmp_path / "a/visible", tmp_path / "a/heldout", seed=7)
    second = split(_stage(tmp_path / "b"), tmp_path / "b/visible", tmp_path / "b/heldout", seed=7)
    assert first["visible"] == second["visible"] and len(first["visible"]) == 8
    assert first["held_out_count"] == 8
    other = split(_stage(tmp_path / "c"), tmp_path / "c/visible", tmp_path / "c/heldout", seed=8)
    assert other["visible"] != first["visible"]


def test_held_out_tasks_carry_canaries_kept_beside_the_tier_and_the_staging_is_gone(
    tmp_path: Path,
) -> None:
    staging = _stage(tmp_path)
    split(staging, tmp_path / "visible", tmp_path / "heldout", seed=1)
    held = [load_task(p).task for p in sorted((tmp_path / "heldout").iterdir()) if p.is_dir()]
    canaries = json.loads((tmp_path / "heldout.canaries.json").read_text())
    assert sorted(t.canary for t in held) == sorted(canaries)  # type: ignore[type-var]
    assert {t.tier for t in held} == {"held_out"}
    assert (tmp_path / "heldout" / "SHA256SUMS").is_file()
    assert not staging.exists()
    visible = [load_task(p).task for p in (tmp_path / "visible").iterdir()]
    assert {t.tier for t in visible} == {"visible"} and {t.canary for t in visible} == {None}


@pytest.mark.parametrize("count", [15, 17])
def test_a_staging_directory_without_exactly_sixteen_tasks_is_refused(
    tmp_path: Path, count: int
) -> None:
    with pytest.raises(AuthoringError, match="not 16"):
        split(_stage(tmp_path, count), tmp_path / "visible", tmp_path / "heldout", seed=1)


def test_a_split_never_writes_over_a_tier(tmp_path: Path) -> None:
    (tmp_path / "heldout").mkdir()
    with pytest.raises(AuthoringError, match="already exists"):
        split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)


def test_a_link_planted_at_the_held_out_tier_s_place_refuses_the_split(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "heldout").symlink_to(elsewhere)  # inert: points at an empty directory
    with pytest.raises(AuthoringError, match="link"):
        split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)
    assert list(elsewhere.iterdir()) == []


def test_a_link_planted_above_the_held_out_tier_refuses_the_split(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "area").symlink_to(real)
    with pytest.raises(AuthoringError, match="link"):
        split(_stage(tmp_path), tmp_path / "visible", tmp_path / "area" / "heldout", seed=1)
    assert list(real.iterdir()) == []


def test_a_link_inside_a_staged_task_is_never_copied_into_a_tier(tmp_path: Path) -> None:
    staging = _stage(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("not a task")
    (staging / "control.t00" / "references" / "good" / "extra.json").symlink_to(secret)
    with pytest.raises(AuthoringError, match="link"):
        split(staging, tmp_path / "visible", tmp_path / "heldout", seed=1)
    assert not (tmp_path / "heldout").exists() and not (tmp_path / "visible").exists()


@pytest.mark.parametrize(
    ("visible", "held"),
    [("tiers", "tiers/heldout"), ("tiers/visible", "tiers"), ("same", "same")],
    ids=["held-out inside visible", "visible inside held-out", "one place"],
)
def test_the_two_tiers_never_share_a_place(tmp_path: Path, visible: str, held: str) -> None:
    with pytest.raises(AuthoringError, match="apart"):
        split(_stage(tmp_path), tmp_path / visible, tmp_path / held, seed=1)


def test_a_held_out_task_written_without_its_canary_is_caught_when_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.per_role import authoring
    from physgate.evaluation.per_role.task import Task, task_bytes

    def losing_the_canary(task: Task) -> bytes:
        return task_bytes(task.model_copy(update={"canary": None, "tier": "visible"}))

    monkeypatch.setattr(authoring, "task_bytes", losing_the_canary)
    with pytest.raises(AuthoringError, match="its own canary"):
        split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)
