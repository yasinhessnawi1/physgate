"""The held-out scan refuses whenever it is in doubt.

A tier it cannot fully vouch for, a place it cannot fully read, a spelling the hooks would
treat as the tier: each is a problem, and any problem keeps the run from starting.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role.authoring import sha256sums
from physgate.evaluation.per_role.heldout import scan

CANARY_A = "a" * 32
CANARY_B = "b" * 32


def _tier(base: Path, canaries: tuple[str, ...] = (CANARY_A, CANARY_B)) -> Path:
    root = base / "private" / "heldout"
    for i, canary in enumerate(canaries):
        write_task_dir(
            root / f"control.h{i}",
            own_task(id=f"control.h{i}", tier="held_out", canary=canary),
            {"good": (controller(), None), "bad_slow": (controller(), "settling")},
        )
    (root / "SHA256SUMS").write_text(sha256sums(root))
    return root


def _recorded(root: Path) -> str:
    """The digest the run records for the tier, taken when the tier was written."""
    return hashlib.sha256(sha256sums(root).encode()).hexdigest() if root.is_dir() else "0" * 64


def _scan(base: Path, root: Path, **kw: object) -> list[str]:
    args: dict[str, object] = {
        "run_held_out": (str(root),),
        "run_canaries": (CANARY_A, CANARY_B),
        "places": {"run directory": base / "runs"},
        "scratch": base / "scan",
    }
    args.update(kw)
    if "run_digests" not in args:
        args["run_digests"] = {str(root): _recorded(root)}
    (base / "runs").mkdir(exist_ok=True)
    return scan(root, **args)  # type: ignore[arg-type]


def test_a_sound_tier_and_run_has_no_problem(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    assert _scan(base, _tier(base)) == []


def test_a_held_out_task_that_does_not_load_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    task = json.loads((root / "control.h0" / "task.json").read_text())
    task["inputs"] = [2.0]  # a bare number
    (root / "control.h0" / "task.json").write_text(json.dumps(task))
    (root / "SHA256SUMS").write_text(sha256sums(root))
    assert any("control.h0" in p and "does not load" in p for p in _scan(base, root))


def test_a_held_out_task_marked_visible_or_without_its_canary_refuses_the_run(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    task = json.loads((root / "control.h1" / "task.json").read_text())
    task.update(tier="visible", canary=None)
    (root / "control.h1" / "task.json").write_text(json.dumps(task))
    (root / "SHA256SUMS").write_text(sha256sums(root))
    problems = _scan(base, root)
    assert any("control.h1" in p and "not marked held out" in p for p in problems)


def test_canaries_must_be_exactly_the_run_s(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    problems = _scan(base, root, run_canaries=(CANARY_A, "c" * 32))
    assert any("canary the run does not name" in p for p in problems)
    assert any("no held-out task carries" in p for p in problems)


def test_anything_but_tasks_and_their_digest_in_the_tier_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    (root / "notes.txt").write_text("stray")
    assert any("notes.txt" in p for p in _scan(base, root))


def test_a_tier_that_is_not_its_recorded_digest_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    (root / "control.h0" / "references" / "good" / "answer.json").write_text("{}")
    assert any("not the bytes its digest records" in p for p in _scan(base, root))


def test_a_task_directory_not_named_as_its_task_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    (root / "control.h0").rename(root / "control.renamed")
    (root / "SHA256SUMS").write_text(sha256sums(root))
    assert any("control.renamed" in p and "not named as its task" in p for p in _scan(base, root))


def test_a_task_both_visible_and_held_out_by_spelling_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    visible = base / "visible"
    write_task_dir(
        visible / "Control.H0",
        own_task(id="control.h0"),
        {"good": (controller(), None), "bad_slow": (controller(), "settling")},
    )
    problems = _scan(base, root, visible_tier=visible)
    assert any("both visible and held out" in p for p in problems)


def test_a_place_the_scan_cannot_read_whole_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    locked = base / "runs" / "locked"
    locked.mkdir(parents=True)
    locked.chmod(0)
    try:
        assert any("could not be read" in p for p in _scan(base, root))
    finally:
        locked.chmod(0o700)


def test_a_place_spelt_in_another_case_is_judged_as_the_hooks_judge_it(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    variant = Path(str(root).replace("private/heldout", "PRIVATE/HELDOUT"))
    if not variant.exists():
        pytest.skip("a case-sensitive volume: the variant is another place")
    problems = _scan(base, root, places={"review root": variant})
    assert "the review root is the held-out root" in problems


def test_a_failure_inside_the_scan_refuses_rather_than_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)

    def broken(*_a: object, **_k: object) -> object:
        raise ValueError("cannot build")

    monkeypatch.setattr("physgate.evaluation.per_role.heldout.build_config", broken)
    assert any("could not be checked" in p for p in _scan(base, root))


def test_a_held_out_root_that_is_a_link_or_missing_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    assert any("not a directory" in p for p in _scan(base, base / "nowhere"))
    os.symlink(_tier(base), base / "alias")
    assert _scan(base, base / "alias") != []


def test_a_task_in_the_tier_marked_visible_refuses_the_run_even_with_its_canary(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    task = json.loads((root / "control.h1" / "task.json").read_text())
    task["tier"] = "visible"  # the canary stays
    (root / "control.h1" / "task.json").write_text(json.dumps(task))
    (root / "SHA256SUMS").write_text(sha256sums(root))
    assert any("control.h1" in p and "not marked held out" in p for p in _scan(base, root))


def test_a_visible_tier_nested_in_the_held_out_tier_or_around_it_refuses_the_run(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    inside = root / "visible"
    around = base / "private"
    for visible in (inside, around):
        visible.mkdir(exist_ok=True)
        assert any("visible tier" in p for p in _scan(base, root, visible_tier=visible)), visible


def test_containment_is_judged_by_whole_components_after_resolving_dot_dot(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    sibling = base / "private" / "heldout-other"
    sibling.mkdir()
    assert _scan(base, root, places={"review root": sibling}) == []
    dotted = base / "private" / "heldout-other" / ".." / "heldout" / "work"
    assert "the review root lies inside the held-out root" in _scan(
        base, root, places={"review root": dotted}
    )


def test_a_tier_rewritten_with_a_matching_digest_file_still_refuses_against_the_run_s_record(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    recorded = _recorded(root)
    (root / "control.h0" / "references" / "good" / "answer.json").write_text("{}")
    (root / "SHA256SUMS").write_text(sha256sums(root))  # the tier vouches for itself
    problems = _scan(base, root, run_digests={str(root): recorded})
    assert "the tier is not the bytes the run records" in problems


def test_a_tier_whose_digest_the_run_does_not_record_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    assert "the run records no digest for the held-out root" in _scan(base, root, run_digests={})


def test_a_link_anywhere_in_the_tier_refuses_the_run_and_is_never_read_through(
    tmp_path: Path,
) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    outside = base / "outside.json"
    outside.write_text("{}")
    (root / "control.h0" / "references" / "good" / "extra.json").symlink_to(outside)
    problems = _scan(base, root, run_digests={str(root): _recorded(root)})
    assert any("link or not a plain file" in p for p in problems)


def test_a_tier_file_that_cannot_be_read_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _tier(base)
    locked = root / "control.h0" / "references" / "good" / "answer.json"
    recorded = _recorded(root)
    locked.chmod(0)
    try:
        problems = _scan(base, root, run_digests={str(root): recorded})
    finally:
        locked.chmod(0o600)
    assert any("could not be read" in p or "could not be checked" in p for p in problems)
