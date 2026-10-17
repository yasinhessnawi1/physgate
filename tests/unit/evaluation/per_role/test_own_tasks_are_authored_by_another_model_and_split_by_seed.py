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
from physgate.evaluation.per_role.task import load_task


def test_an_author_on_the_implementers_model_is_refused() -> None:
    with pytest.raises(AuthoringError, match="implementers' own model"):
        require_author_model("claude-opus-5-5", "claude-opus-5-5")
    require_author_model("claude-sonnet-5", "claude-opus-5-5")


def test_the_author_is_told_the_format_and_the_metrics_and_nothing_of_the_harness() -> None:
    brief = author_brief("control")
    for told in ("phase_margin: deg", "settling_time: s", "composes", "expect.json", "16 tasks"):
        assert told in brief.replace("exactly 16", "16")
    for withheld in ("knowledge", "rubric", "reviewer", "gate", "physgate", "harness"):
        assert withheld not in brief.lower()


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
