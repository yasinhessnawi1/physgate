"""Only what the split would take enters the pool, and a check that cannot run refuses.

The pool feeds the split, so a task enters it only through the split's own entry check: a
task written as anything but a visible one, or carrying a canary, is refused at the pool as
the split would refuse it, under a counted reason, never pooled to stop a later split. A task
whose brief cannot be checked for giving its answer away (the check itself fails) is refused
too, and counted, rather than ending the count or passing unchecked.

One round pools twenty-four tasks and cuts three tiers of eight from them by one seed:
visible, validation and held out, the two protected ones inside the protected root, each with
its canaries and its own list.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    _plan,
    _run,
    _tasks,
    _write_task,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role import validate as validate_module
from physgate.evaluation.per_role.author_session import pool_dir
from physgate.evaluation.per_role.validate import refusal_reasons, sound, validate
from physgate.evaluation.tiers.task import load_task

#: Fields that make a well-formed task one the split refuses, and the reason it is counted as.
REFUSED = [
    ({"tier": "held_out", "canary": "a" * 32}, "tier_not_visible"),
    ({"tier": "validation", "canary": "b" * 32}, "tier_not_visible"),
    ({"canary": "c" * 32}, "carries_canary"),
]


def _changed(directory: Path, change: dict[str, Any]) -> None:
    task = directory / "task.json"
    task.write_text(json.dumps({**json.loads(task.read_text()), **change}))


@pytest.mark.parametrize(("change", "reason"), REFUSED, ids=["held out", "validation", "canary"])
def test_a_task_the_split_would_refuse_is_not_sound_and_is_counted(
    tmp_path: Path, change: dict[str, Any], reason: str
) -> None:
    tier = tmp_path / "staging"
    for n in range(2):
        _write_task(tier / f"control.t{n:02d}", n)
    _changed(tier / "control.t01", change)
    assert sound(tier) == ["control.t00"], f"a task the split refuses ({reason}) was sound"
    assert refusal_reasons(tier).get(reason) == 1, refusal_reasons(tier)


@pytest.mark.parametrize(("change", "reason"), REFUSED, ids=["held out", "validation", "canary"])
def test_a_session_s_task_the_split_would_refuse_is_never_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any], reason: str
) -> None:
    def write(worktree: Path) -> None:
        _tasks(2)(worktree)
        _changed(worktree / "control.t01", change)

    plan, _, out = _run(tmp_path, monkeypatch, write)
    assert out["pooled"] == 1 and out["refused_because"].get(reason) == 1, out
    pooled = [load_task(p).task for p in sorted(pool_dir(plan.held_out_root, "control").iterdir())]
    assert [(t.tier, t.canary) for t in pooled] == [("visible", None)]


def _leak_check_fails_for(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = validate_module.brief_leaks

    def failing(loaded: Any) -> bool:  # noqa: ANN401
        if loaded.task.id == name:
            raise ValueError("the good reference's answer cannot be read")
        return real(loaded)

    monkeypatch.setattr(validate_module, "brief_leaks", failing)


def test_a_brief_that_cannot_be_checked_refuses_its_task_and_is_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tier = tmp_path / "staging"
    for n in range(3):
        _write_task(tier / f"control.t{n:02d}", n)
    _leak_check_fails_for(monkeypatch, "control.t01")
    try:
        held = sound(tier)
        reasons = refusal_reasons(tier)
        shown = validate(tier)
    except ValueError as exc:
        pytest.fail(f"a leak check that failed ended the count: {exc}")
    assert held == ["control.t00", "control.t02"]
    assert reasons.get("brief_unchecked") == 1, reasons
    assert len(shown["brief_gives_the_answer"]) == 1 and shown["tasks"] == 3


def test_a_session_s_task_whose_brief_cannot_be_checked_is_not_pooled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _leak_check_fails_for(monkeypatch, "control.t01")
    try:
        _, _, out = _run(tmp_path, monkeypatch, _tasks(3))
    except ValueError as exc:
        pytest.fail(f"a leak check that failed ended the session's staging: {exc}")
    assert out["pooled"] == 2 and out["refused_because"].get("brief_unchecked") == 1, out


# --------------------------------------------- twenty-four, cut into three tiers


def test_twenty_four_pooled_tasks_are_cut_into_three_tiers_of_eight_by_the_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, fake, out = _run(tmp_path, monkeypatch, _tasks(24))
    assert "up to 24 tasks" in fake.calls[0]["prompt"]
    assert out["status"] == "split", f"twenty-four sound tasks were not split: {out['status']}"
    root = plan.held_out_root
    where = getattr(author_session, "validation_tier", None)
    assert where is not None, "there is no place for a role's validation tier"
    tiers = {
        "visible": sorted(p.name for p in plan.visible.iterdir()),
        "validation": sorted(p.name for p in where(root, "control").iterdir() if p.is_dir()),
        "held_out": sorted(p.name for p in (root / "control").iterdir() if p.is_dir()),
    }
    order = [f"control.t{n:02d}" for n in range(24)]
    random.Random(plan.seed).shuffle(order)
    drawn = sorted(order[:24])
    random.Random(plan.seed).shuffle(drawn)
    assert tiers == {
        "visible": sorted(drawn[:8]),
        "validation": sorted(drawn[8:16]),
        "held_out": sorted(drawn[16:]),
    }
    assert out["held_out_count"] == 8 and out.get("validation_count") == 8
    assert out["visible"] == tiers["visible"]
    printed = json.dumps(out)
    for name in tiers["validation"] + tiers["held_out"]:
        assert name not in printed, "a protected task's id was printed"
    assert out["validation_check"]["references_held"] == 8
    assert out["held_out_check"]["references_held"] == 8
    assert not pool_dir(root, "control").exists() or not list(pool_dir(root, "control").iterdir())


def test_fewer_than_twenty_four_are_pooled_and_no_tier_is_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, out = _run(tmp_path, monkeypatch, _tasks(16))
    assert out["status"] == "pooled" and out["pool"] == 16, (
        f"sixteen tasks cut tiers that need twenty-four: {out['status']}"
    )
    assert not plan.visible.exists() and not (plan.held_out_root / "control").exists()
    assert _plan(tmp_path).count == 24
