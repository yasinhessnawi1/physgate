from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role.metrics import CONTROL_METRIC_UNITS
from physgate.evaluation.tiers.authoring import (
    AuthoringError,
    author_brief,
    require_author_model,
    split,
)
from physgate.evaluation.tiers.task import Task, load_task


def test_an_author_on_the_implementers_model_is_refused() -> None:
    with pytest.raises(AuthoringError, match="implementers' own model"):
        require_author_model("claude-opus-5-5", "claude-opus-5-5")
    require_author_model("claude-sonnet-5", "claude-opus-5-5")


def test_the_author_is_told_the_format_and_the_metrics_and_nothing_of_the_harness() -> None:
    brief = author_brief("control")
    for told in ("phase_margin, in deg", "settling_time, in s", "composes", "expect.json"):
        assert told in brief
    for withheld in ("knowledge", "rubric", "reviewer", "gate", "physgate", "harness"):
        assert withheld not in brief.lower()
    # Sessions pooled together are told what their ids begin with, and nothing more.
    assert "beginning with" not in brief
    told_prefix = author_brief("control", count=8, id_prefix="b2.")
    assert 'dots allowed, beginning with "b2."' in told_prefix and "up to 8 tasks" in told_prefix
    assert "session" not in told_prefix.replace("Your session", "")


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
    # The budget, and what it means: one complete task at a time, no tool for every task,
    # and never a refused call repeated (the loop that spent 80 M tokens on nothing).
    assert "fixed token budget" in brief and "stopped when it is spent" in brief
    flat = " ".join(brief.split())
    assert "write each task completely" in flat and "before you begin the next" in flat
    assert "a tool for every task\nis not worth building" in brief
    assert "If a tool call is refused, do not repeat it" in brief


def _stage(root: Path, count: int = 24) -> Path:
    staging = root / "staging"
    for i in range(count):
        write_task_dir(
            staging / f"control.t{i:02d}",
            own_task(id=f"control.t{i:02d}"),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return staging


def _split(
    staging: Path, visible: Path, held: Path, *, validation: Path | None = None, **kw: Any
) -> dict[str, Any]:
    """The three-way split, with the validation tier beside the held-out one unless named."""
    beside = held.parent / f"{held.name}.validation" if validation is None else validation
    try:
        return split(staging, visible, held, validation=beside, **kw)
    except TypeError as exc:
        pytest.fail(f"the split takes no validation tier: {exc}")


def _tier(path: Path) -> list[Task]:
    return [load_task(p).task for p in sorted(path.iterdir()) if p.is_dir()]


def test_a_split_sends_eight_to_each_of_three_tiers_and_the_same_seed_splits_alike(
    tmp_path: Path,
) -> None:
    first = _split(_stage(tmp_path / "a"), tmp_path / "a/visible", tmp_path / "a/heldout", seed=7)
    second = _split(_stage(tmp_path / "b"), tmp_path / "b/visible", tmp_path / "b/heldout", seed=7)
    assert first["visible"] == second["visible"] and len(first["visible"]) == 8
    assert first.get("validation_count") == 8 and first["held_out_count"] == 8
    for name in ("validation", "heldout"):
        assert [
            t.id
            for t in _tier(tmp_path / f"a/{'heldout.validation' if name == 'validation' else name}")
        ] == [
            t.id
            for t in _tier(tmp_path / f"b/{'heldout.validation' if name == 'validation' else name}")
        ]
    other = _split(_stage(tmp_path / "c"), tmp_path / "c/visible", tmp_path / "c/heldout", seed=8)
    assert other["visible"] != first["visible"]


def test_the_three_tiers_are_cut_in_the_order_of_one_seeded_shuffle(tmp_path: Path) -> None:
    _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=11)
    order = [f"control.t{i:02d}" for i in range(24)]
    random.Random(11).shuffle(order)
    assert sorted(p.name for p in (tmp_path / "visible").iterdir()) == sorted(order[:8])
    assert sorted(t.id for t in _tier(tmp_path / "heldout.validation")) == sorted(order[8:16])
    assert sorted(t.id for t in _tier(tmp_path / "heldout")) == sorted(order[16:])


@pytest.mark.parametrize(
    ("name", "label"), [("heldout", "held_out"), ("heldout.validation", "validation")]
)
def test_protected_tasks_carry_canaries_kept_inside_their_tier_and_the_staging_is_gone(
    tmp_path: Path, name: str, label: str
) -> None:
    staging = _stage(tmp_path)
    out = _split(staging, tmp_path / "visible", tmp_path / "heldout", seed=1)
    tier = tmp_path / name
    assert tier.is_dir(), f"the split wrote no {label} tier"
    held = _tier(tier)
    listed = tier / "canaries.json"
    assert listed.is_file(), f"the {label} tier holds no canary list of its own"
    assert sorted(str(t.canary) for t in held) == sorted(json.loads(listed.read_text()))
    assert {t.tier for t in held} == {label} and len(held) == 8
    assert (tier / "SHA256SUMS").is_file()
    prefix = "held_out" if label == "held_out" else "validation"
    assert (
        out.get(f"{prefix}_sha256")
        == hashlib.sha256((tier / "SHA256SUMS").read_bytes()).hexdigest()
    )
    assert out.get(f"{prefix}_canaries_sha256") == hashlib.sha256(listed.read_bytes()).hexdigest()
    assert not staging.exists()
    visible = _tier(tmp_path / "visible")
    assert {t.tier for t in visible} == {"visible"} and {t.canary for t in visible} == {None}


def test_no_canary_is_given_twice_across_the_protected_tiers(tmp_path: Path) -> None:
    _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=2)
    carried = [
        t.canary for t in _tier(tmp_path / "heldout") + _tier(tmp_path / "heldout.validation")
    ]
    assert len(carried) == 16 and len(set(carried)) == 16


@pytest.mark.parametrize("count", [16, 23, 25])
def test_a_staging_directory_without_exactly_twenty_four_tasks_is_refused(
    tmp_path: Path, count: int
) -> None:
    with pytest.raises(AuthoringError, match="not 24"):
        _split(_stage(tmp_path, count), tmp_path / "visible", tmp_path / "heldout", seed=1)


def test_the_author_is_asked_for_the_three_tiers_worth() -> None:
    assert "up to 24 tasks, one at a time" in author_brief("control")


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"tier": "held_out", "canary": "a" * 32}, "tier_not_visible"),
        ({"tier": "validation", "canary": "b" * 32}, "tier_not_visible"),
        ({"canary": "c" * 32}, "carries_canary"),
    ],
    ids=["held out", "validation", "visible with a canary"],
)
def test_the_split_takes_only_what_its_entry_check_admits(
    tmp_path: Path, change: dict[str, Any], reason: str
) -> None:
    staging = _stage(tmp_path)
    task = staging / "control.t03" / "task.json"
    task.write_text(json.dumps({**json.loads(task.read_text()), **change}))
    try:
        _split(staging, tmp_path / "visible", tmp_path / "heldout", seed=1)
    except AuthoringError as exc:
        assert exc.context.get("refused_because") == reason, f"refused for another reason: {exc}"
    else:
        pytest.fail(f"the split took a staged task its entry check refuses ({reason})")
    assert not (tmp_path / "visible").exists() and not (tmp_path / "heldout").exists()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({}, None),
        ({"tier": "held_out", "canary": "a" * 32}, "tier_not_visible"),
        ({"tier": "validation", "canary": "a" * 32}, "tier_not_visible"),
        ({"canary": "a" * 32}, "carries_canary"),
    ],
)
def test_the_entry_check_names_why_a_task_may_not_be_split(
    change: dict[str, Any], reason: str | None
) -> None:
    from physgate.evaluation.tiers import authoring

    check = getattr(authoring, "entry_refusal", None)
    assert check is not None, "there is no entry check shared by the split and the pool"
    assert check(Task.model_validate_json(json.dumps(own_task(**change)))) == reason


def test_a_split_never_writes_over_a_tier(tmp_path: Path) -> None:
    (tmp_path / "heldout").mkdir()
    with pytest.raises(AuthoringError, match="already exists"):
        _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)


def test_a_split_never_writes_over_a_validation_tier(tmp_path: Path) -> None:
    (tmp_path / "heldout.validation").mkdir()
    with pytest.raises(AuthoringError, match="already exists"):
        _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)
    assert not (tmp_path / "heldout").exists() and not (tmp_path / "visible").exists()


def test_a_link_planted_at_the_held_out_tier_s_place_refuses_the_split(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "heldout").symlink_to(elsewhere)  # inert: points at an empty directory
    with pytest.raises(AuthoringError, match="link"):
        _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)
    assert list(elsewhere.iterdir()) == []


def test_a_link_planted_above_the_held_out_tier_refuses_the_split(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "area").symlink_to(real)
    with pytest.raises(AuthoringError, match="link"):
        _split(
            _stage(tmp_path),
            tmp_path / "visible",
            tmp_path / "area" / "heldout",
            validation=tmp_path / "validation",
            seed=1,
        )
    assert list(real.iterdir()) == []


def test_a_link_inside_a_staged_task_is_never_copied_into_a_tier(tmp_path: Path) -> None:
    staging = _stage(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("not a task")
    (staging / "control.t00" / "references" / "good" / "extra.json").symlink_to(secret)
    with pytest.raises(AuthoringError, match="link"):
        _split(staging, tmp_path / "visible", tmp_path / "heldout", seed=1)
    assert not (tmp_path / "heldout").exists() and not (tmp_path / "visible").exists()


@pytest.mark.parametrize(
    ("visible", "held", "validation"),
    [
        ("tiers", "tiers/heldout", "validation"),
        ("tiers/visible", "tiers", "validation"),
        ("same", "same", "validation"),
        ("visible", "heldout", "heldout/validation"),
        ("visible", "heldout", "visible"),
        ("visible", "tiers/heldout", "tiers"),
    ],
    ids=[
        "held-out inside visible",
        "visible inside held-out",
        "one place",
        "validation inside held-out",
        "validation where visible is",
        "held-out inside validation",
    ],
)
def test_the_three_tiers_never_share_a_place(
    tmp_path: Path, visible: str, held: str, validation: str
) -> None:
    with pytest.raises(AuthoringError, match="apart"):
        _split(
            _stage(tmp_path),
            tmp_path / visible,
            tmp_path / held,
            validation=tmp_path / validation,
            seed=1,
        )


def test_a_held_out_task_written_without_its_canary_is_caught_when_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from physgate.evaluation.tiers import authoring
    from physgate.evaluation.tiers.task import task_bytes

    def losing_the_canary(task: Task) -> bytes:
        return task_bytes(task.model_copy(update={"canary": None, "tier": "visible"}))

    monkeypatch.setattr(authoring, "task_bytes", losing_the_canary)
    with pytest.raises(AuthoringError, match="its own canary"):
        _split(_stage(tmp_path), tmp_path / "visible", tmp_path / "heldout", seed=1)
