"""An id is one id however it is spelt, in the split and in the scan.

Two tasks whose ids differ only in case, in a compatibility form (a full-width letter) or in
their separators (``.``, ``_``, ``-``) are one task to anyone reading the tier, so a split
that takes both, or a scan that lets one be visible and the other held out, would let a
held-out task be read under another spelling.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.tiers.authoring import AuthoringError, sha256sums, split
from physgate.evaluation.tiers.heldout import scan

CANARY_A = "a" * 32
CANARY_B = "b" * 32


def _fold() -> Any:
    """The fold, or the row fails: ids are not folded yet."""
    found = getattr(importlib.import_module("physgate.evaluation.tiers.task"), "fold_id", None)
    assert found is not None, "no fold of ids is built"
    return found


@pytest.mark.parametrize(
    ("one", "other"),
    [
        ("ctl.1", "ctl_1"),
        ("ctl.1", "ctl-1"),
        ("ctl_1", "ctl-1"),
        ("ctl..1", "ctl-1"),
        ("CTL.1", "ctl.1"),
        ("\uff43\uff54\uff4c.1", "ctl.1"),  # full-width "ctl"
    ],
    ids=["dot-underscore", "dot-hyphen", "underscore-hyphen", "a run", "case", "nfkc"],
)
def test_two_spellings_of_one_id_fold_alike(one: str, other: str) -> None:
    fold = _fold()
    assert fold(one) == fold(other)


def test_ids_that_differ_otherwise_stay_apart() -> None:
    fold = _fold()
    assert fold("ctl.1") != fold("ctl.2") != fold("ctl1")


def _stage(root: Path, ids: list[str]) -> Path:
    staging = root / "staging"
    for task_id in ids:
        write_task_dir(
            staging / task_id,
            own_task(id=task_id),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    return staging


def test_a_split_refuses_two_staged_ids_that_fold_alike(tmp_path: Path) -> None:
    ids = [f"control.t{i:02d}" for i in range(23)] + ["control_t00"]
    staging = _stage(tmp_path, ids)
    with pytest.raises(AuthoringError, match="repeat an id") as refused:
        split(
            staging,
            tmp_path / "visible",
            tmp_path / "held_out",
            validation=tmp_path / "validation",
            seed=1,
        )
    assert refused.value.context.get("refused_because") == "id_fold_collision"
    assert not (tmp_path / "visible").exists() and not (tmp_path / "held_out").exists()


def _held(base: Path, ids: tuple[str, ...]) -> Path:
    root = base / "private" / "heldout"
    for task_id, canary in zip(ids, (CANARY_A, CANARY_B), strict=False):
        write_task_dir(
            root / task_id,
            own_task(id=task_id, tier="held_out", canary=canary),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    (root / "SHA256SUMS").write_text(sha256sums(root))
    return root


def _scan(base: Path, root: Path, **kw: Any) -> list[str]:
    import hashlib

    (base / "runs").mkdir(exist_ok=True)
    found: list[str] = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): hashlib.sha256(sha256sums(root).encode()).hexdigest()},
        run_canaries=(CANARY_A, CANARY_B)[: len(list(root.glob("*/task.json")))],
        places={"run directory": base / "runs"},
        scratch=base / "scan",
        **kw,
    )
    return found


def test_two_held_out_tasks_whose_ids_fold_alike_refuse_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _held(base, ("control.h-0", "control.h_0"))
    assert any("one id, however spelt" in p for p in _scan(base, root))


def test_a_visible_id_that_folds_to_a_held_out_one_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _held(base, ("control.h-0",))
    visible = base / "repo" / "visible"
    write_task_dir(
        visible / "control.h_0",
        own_task(id="control.h_0"),
        {"good": (controller(), None), "bad_slow": (controller(), "settling")},
    )
    problems = _scan(base, root, visible_tier=visible)
    assert any("both visible and held out" in p for p in problems)
