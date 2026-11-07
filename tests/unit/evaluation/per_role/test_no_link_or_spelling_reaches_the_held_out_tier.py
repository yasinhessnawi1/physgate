"""One matrix for every way a path could reach the held-out tier around the scan's checks.

Links at any component (the tier itself, its parent, a grandparent, a file or directory
inside it), hard links, spellings (``..``, case, a prefix sibling) and nesting with the
visible tier: each must be a problem, and the one look-alike that is not (a sibling whose
name starts with the tier's) must not be. And the scan reads the tier only through the
descriptors it opened, never by path again, so nothing swapped in between is read.
"""

from __future__ import annotations

import builtins
import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from task_fixtures import controller, own_task, write_task_dir

from physgate.evaluation.per_role.authoring import sha256sums
from physgate.evaluation.per_role.heldout import scan

CANARY = "c" * 32


def _tier(root: Path) -> Path:
    write_task_dir(
        root / "control.h0",
        own_task(id="control.h0", tier="held_out", canary=CANARY),
        {"good": (controller(), None), "bad_slow": (controller(), "settling")},
    )
    (root / "SHA256SUMS").write_text(sha256sums(root))
    return root


def _problems(
    base: Path, root: Path, *, places: dict[str, Path] | None = None, visible: Path | None = None
) -> list[str]:
    real = Path(os.path.realpath(root))
    digest = hashlib.sha256(sha256sums(real).encode()).hexdigest() if real.is_dir() else "0" * 64
    (base / "runs").mkdir(exist_ok=True)
    return scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): digest},
        run_canaries=(CANARY,),
        places=places if places is not None else {"run directory": base / "runs"},
        scratch=base / "scan",
        visible_tier=visible,
    )


def _layout(base: Path) -> Path:
    return _tier(base / "a" / "b" / "heldout")


LINKS: dict[str, Callable[[Path], Path]] = {}


def _link_at_tier(base: Path) -> Path:
    real = _tier(base / "real-tier")
    (base / "a").mkdir()
    (base / "a" / "heldout").symlink_to(real)
    return base / "a" / "heldout"


def _link_at_parent(base: Path) -> Path:
    _tier(base / "real-parent" / "heldout")
    (base / "a").symlink_to(base / "real-parent")
    return base / "a" / "heldout"


def _link_at_grandparent(base: Path) -> Path:
    _tier(base / "real-gp" / "b" / "heldout")
    (base / "a").symlink_to(base / "real-gp")
    return base / "a" / "b" / "heldout"


def _file_link_inside(base: Path) -> Path:
    root = _layout(base)
    (base / "elsewhere.json").write_text("{}")
    (root / "control.h0" / "references" / "good" / "extra.json").symlink_to(base / "elsewhere.json")
    return root


def _dir_link_inside(base: Path) -> Path:
    root = _layout(base)
    (base / "outdir").mkdir()
    (root / "control.h0" / "references" / "bad_more").symlink_to(base / "outdir")
    return root


def _hard_link_inside(base: Path) -> Path:
    root = _layout(base)
    os.link(root / "control.h0" / "task.json", base / "a-second-name.json")
    return root


@pytest.mark.parametrize(
    "make",
    [
        _link_at_tier,
        _link_at_parent,
        _link_at_grandparent,
        _file_link_inside,
        _dir_link_inside,
        _hard_link_inside,
    ],
    ids=["tier", "parent", "grandparent", "file inside", "directory inside", "hard link"],
)
def test_a_link_at_any_component_or_a_second_name_refuses_the_run(
    tmp_path: Path, make: Callable[[Path], Path]
) -> None:
    base = tmp_path.resolve()
    assert _problems(base, make(base)) != []


@pytest.mark.parametrize(
    ("place", "flagged"),
    [
        ("a/b/heldout", True),
        ("a/b/heldout/work", True),
        ("a/b", True),
        ("a/b/heldout-other", False),
        ("a/b/heldout-other/../heldout/work", True),
        ("A/B/HELDOUT", True),
    ],
    ids=["the root", "inside", "around", "a prefix sibling", "dot-dot into it", "another case"],
)
def test_places_are_judged_by_whole_resolved_components(
    tmp_path: Path, place: str, flagged: bool
) -> None:
    base = tmp_path.resolve()
    root = _layout(base)
    (base / "a" / "b" / "heldout-other").mkdir()
    target = base / place
    if place.startswith("A/") and not target.exists():
        pytest.skip("a case-sensitive volume: the variant is another place")
    problems = _problems(base, root, places={"review root": target})
    assert any(p.startswith("the review root") for p in problems) is flagged


def test_a_place_that_is_a_link_to_the_tier_refuses_the_run(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    root = _layout(base)
    (base / "innocent").symlink_to(root)
    assert "the review root is the held-out root" in _problems(
        base, root, places={"review root": base / "innocent"}
    )


@pytest.mark.parametrize("where", ["a/b/heldout/visible", "a"], ids=["inside", "around"])
def test_a_visible_tier_inside_or_around_refuses_the_run(tmp_path: Path, where: str) -> None:
    base = tmp_path.resolve()
    root = _layout(base)
    (base / where).mkdir(exist_ok=True)
    assert any("visible tier" in p for p in _problems(base, root, visible=base / where))


def test_the_tier_is_read_only_through_the_descriptors_the_scan_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path.resolve()
    root = _layout(base)
    digest = hashlib.sha256(sha256sums(root).encode()).hexdigest()
    (base / "runs").mkdir()
    real_open, real_read = builtins.open, Path.read_bytes

    def no_path_open(file: object, *a: object, **k: object) -> object:
        if isinstance(file, (str, Path)) and Path(file).is_relative_to(root):
            raise AssertionError(f"re-opened by path: {file}")
        return real_open(file, *a, **k)  # type: ignore[call-overload]

    def no_path_read(self: Path) -> bytes:
        if self.is_relative_to(root):
            raise AssertionError(f"re-read by path: {self}")
        return real_read(self)

    monkeypatch.setattr(builtins, "open", no_path_open)
    monkeypatch.setattr(Path, "read_bytes", no_path_read)
    problems = scan(
        root,
        run_held_out=(str(root),),
        run_digests={str(root): digest},
        run_canaries=(CANARY,),
        places={"run directory": base / "runs"},
        scratch=base / "scan",
    )
    assert problems == []
