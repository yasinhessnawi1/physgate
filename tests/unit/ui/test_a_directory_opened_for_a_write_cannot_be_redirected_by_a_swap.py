"""A directory opened by the walk is the one that was judged, whatever is swapped afterwards.

The resolver judges a path and returns it; whatever opens it afterwards by name can be sent
elsewhere by a same-user swap in between. The walk closes that for anything that writes: it
opens the directory from the root down, never through a link, and holds what it reached to
what was judged. These tests make each swap happen at a fixed point, through the module's
own seams, rather than hoping a race lands there:

- right after the path is judged (the run directory, a directory above it inside the root,
  the root itself);
- just before the root is opened (the run directory replaced by another real directory);
- during the walk, between one component and the next.

Each swap aims at a copy of the run directory outside every root, holding a marker. A
refusal is required, and so is "nothing was handed back", since the caller can only reach a
file through the descriptor the walk returns. The race test at the end swaps continuously
and reports how many attempts the swap actually reached between the judgement and the walk.
"""

from __future__ import annotations

import os
import shutil
import threading
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from physgate.ui import guard
from physgate.ui import paths as paths_module
from physgate.ui.exceptions import GuardRefusedError, PathRefusedError
from physgate.ui.paths import Allowlist

MARKER = "decisions"


def _tree(base: Path, label: str) -> Path:
    """``base/group/run-1`` holding a marker file that names where it is."""
    run = base / "group" / "run-1"
    run.mkdir(parents=True)
    (run / MARKER).write_text(f"{label}\n")
    return run


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """A root holding ``group/run-1``; the same shape outside every root; a held-out tier."""
    root = tmp_path / "root"
    inside = _tree(root, "inside")
    elsewhere = tmp_path / "elsewhere"
    outside = _tree(elsewhere, "outside")
    held = tmp_path / "held"
    held.mkdir()
    return {"tmp": tmp_path, "root": root, "inside": inside, "elsewhere": elsewhere,
            "outside": outside, "held": held}  # fmt: skip


def _allow(world: dict[str, Path]) -> Allowlist:
    return Allowlist.build(
        [str(world["root"])], held_out=[str(world["held"])], answer_keys=[], harness=None
    )


def _ids(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_dev, st.st_ino


def _open_descriptors() -> int:
    return len(os.listdir("/dev/fd"))


def _marker_via(fd: int) -> str:
    handle = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        return os.read(handle, 64).decode()
    finally:
        os.close(handle)


def _after_judging(monkeypatch: pytest.MonkeyPatch, swap: Callable[[], None]) -> None:
    """Run ``swap`` once, right after the resolver has judged the path."""
    judged = Allowlist.resolve

    def resolve_then_swap(self: Allowlist, path: Path | str) -> Path:
        real = judged(self, path)
        swap()
        return real

    monkeypatch.setattr(Allowlist, "resolve", resolve_then_swap)


def _refused_handing_back_nothing(allow: Allowlist, path: Path, reason: str) -> None:
    before = _open_descriptors()
    with pytest.raises(PathRefusedError, match=reason):
        allow.open_directory(path)
    assert _open_descriptors() == before, "a refused walk left a descriptor open"


# -- what the walk does when nothing is swapped --------------------------------------


def test_the_walk_reaches_the_judged_directory_and_reads_beneath_it(
    world: dict[str, Path],
) -> None:
    allow = _allow(world)
    with allow.opened_directory(world["inside"]) as fd:
        assert (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == _ids(world["inside"])
        assert _marker_via(fd) == "inside\n"
    with pytest.raises(OSError):
        os.fstat(fd)


def test_a_root_that_is_itself_the_directory_is_reached_with_no_step_below_it(
    world: dict[str, Path],
) -> None:
    allow = Allowlist.build([str(world["inside"])], held_out=[], answer_keys=[], harness=None)
    with allow.opened_directory(world["inside"]) as fd:
        assert _marker_via(fd) == "inside\n"


def test_a_link_inside_the_root_is_judged_where_it_lands_and_the_walk_takes_the_real_path(
    world: dict[str, Path],
) -> None:
    alias = world["root"] / "alias"
    alias.symlink_to(world["inside"], target_is_directory=True)
    with _allow(world).opened_directory(alias) as fd:
        assert (os.fstat(fd).st_dev, os.fstat(fd).st_ino) == _ids(world["inside"])


def test_a_path_that_is_not_a_directory_or_is_gone_is_refused(world: dict[str, Path]) -> None:
    allow = _allow(world)
    _refused_handing_back_nothing(allow, world["inside"] / MARKER, "not a real directory")
    _refused_handing_back_nothing(allow, world["root"] / "missing", "not a real directory")


def test_a_path_outside_every_root_is_refused_before_anything_is_opened(
    world: dict[str, Path],
) -> None:
    _refused_handing_back_nothing(_allow(world), world["outside"], "outside every root")


# -- swaps at a fixed point --------------------------------------------------------


def test_the_directory_swapped_for_a_link_after_judging_is_refused_at_approval(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approval reads the judged path without following it: a link is not a directory."""

    def swap() -> None:
        world["inside"].rename(world["inside"].with_name("run-1.moved"))
        world["inside"].symlink_to(world["outside"], target_is_directory=True)

    _after_judging(monkeypatch, swap)
    _refused_handing_back_nothing(_allow(world), world["inside"], "not a real directory")


def test_a_directory_above_it_swapped_for_a_link_after_judging_is_refused_on_the_walk(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case only the no-follow walk catches.

    With ``group`` a link to the outside copy, approving the judged path follows it and approves
    the outside directory; a walk that followed links would reach that same directory and pass
    the identity check. Only refusing the link at its own step stops it.
    """
    group = world["root"] / "group"

    def swap() -> None:
        group.rename(group.with_name("group.moved"))
        group.symlink_to(world["outside"].parent, target_is_directory=True)

    _after_judging(monkeypatch, swap)
    _refused_handing_back_nothing(_allow(world), world["inside"], "now a link, or is gone")


def _root_away(world: dict[str, Path]) -> None:
    world["root"].rename(world["root"].with_name("root.moved"))
    world["root"].symlink_to(world["elsewhere"], target_is_directory=True)


def _root_back(world: dict[str, Path]) -> None:
    world["root"].unlink()
    world["root"].with_name("root.moved").rename(world["root"])


def test_the_root_replaced_after_judging_is_no_longer_found_above_the_path(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root swapped after judging is no longer found above the path.

    Its name now leads to a same-shaped directory outside it: approval follows it, and no
    directory above the path has the root's (device, inode) any more.
    """
    _after_judging(monkeypatch, lambda: _root_away(world))
    _refused_handing_back_nothing(_allow(world), world["inside"], "outside every root")


def test_the_root_swapped_away_back_and_away_again_is_refused_at_the_root(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case only the root's own identity catches.

    Away before approval, so the outside copy is approved; back while the root is looked up, so
    it is found; away again before it is opened. Every step below is a real directory and the
    end matches the (wrong) approval: only the opened root's (device, inode), recorded at
    start, differs.
    """
    _after_judging(monkeypatch, lambda: _root_away(world))
    looked_up = Allowlist._beneath

    def back_while_looked_up(
        self: Allowlist, real: Path
    ) -> tuple[paths_module.Root, tuple[str, ...]]:
        _root_back(world)
        found = looked_up(self, real)
        _root_away(world)
        return found

    monkeypatch.setattr(Allowlist, "_beneath", back_while_looked_up)
    _refused_handing_back_nothing(_allow(world), world["inside"], "no longer the directory")


def test_the_directory_replaced_by_another_real_one_before_the_walk_is_refused_at_the_end(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case only the final identity catches.

    The outside copy is moved into the run directory's place: no link anywhere, so every step
    of the walk succeeds, and only the comparison with what was approved refuses it.
    """
    opened: Callable[[Path], int] = paths_module._open_root

    def swap_then_open_root(path: Path) -> int:
        world["inside"].rename(world["inside"].with_name("run-1.moved"))
        world["outside"].rename(world["inside"])
        return opened(path)

    monkeypatch.setattr(paths_module, "_open_root", swap_then_open_root)
    _refused_handing_back_nothing(_allow(world), world["inside"], "different directory")


def test_the_next_component_swapped_for_a_link_during_the_walk_is_refused_at_its_step(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    opened_child: Callable[[int, str], int] = paths_module._open_child
    swapped: list[str] = []

    def swap_before_last(parent: int, name: str) -> int:
        if name == "run-1" and not swapped:
            world["inside"].rename(world["inside"].with_name("run-1.moved"))
            world["inside"].symlink_to(world["outside"], target_is_directory=True)
            swapped.append(name)
        return opened_child(parent, name)

    monkeypatch.setattr(paths_module, "_open_child", swap_before_last)
    _refused_handing_back_nothing(_allow(world), world["inside"], "now a link, or is gone")
    assert swapped == ["run-1"], "the swap never happened, so this test proved nothing"


def test_the_held_out_tier_moved_by_a_link_into_the_directory_s_place_is_refused(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def swap() -> None:
        shutil.rmtree(world["inside"])
        world["inside"].symlink_to(world["held"], target_is_directory=True)

    _after_judging(monkeypatch, swap)
    _refused_handing_back_nothing(_allow(world), world["inside"], "not a real directory")


# -- a path that changes while it is judged ------------------------------------------


def _vanishing(path: str, root: str) -> bool:
    raise FileNotFoundError(2, "No such file or directory", path)


def test_a_path_that_vanishes_while_it_is_judged_is_refused_never_a_raw_error(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path that vanishes mid-judgement is refused, never passed on as a raw error.

    Found by the continuous swap below: resolving a path whose component is removed between two
    of the standard library's own steps raises ``FileNotFoundError`` from inside the held-out
    test. Planted here deterministically at that call.
    """
    allow = _allow(world)  # built before the plant: start-up uses the same held-out test
    monkeypatch.setattr(paths_module, "reaches", _vanishing)
    with pytest.raises(PathRefusedError, match="changed while it was being judged"):
        allow.resolve(world["inside"])
    _refused_handing_back_nothing(allow, world["inside"], "changed while it was being judged")


def test_the_guard_s_read_rule_refuses_a_path_that_vanishes_while_it_is_judged(
    world: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    allow = _allow(world)
    monkeypatch.setattr(paths_module, "reaches", _vanishing)
    assert allow.readable(str(world["inside"] / MARKER)) is False


# -- the read kind does not walk ----------------------------------------------------


def test_the_read_kind_refuses_the_walk_so_no_read_route_can_use_it(
    world: dict[str, Path],
) -> None:
    """The read kind refuses the walk.

    The walk's steps name only a component, relative to a descriptor the audit event does not
    carry, and the read rule refuses a relative path. A later action kind may admit the walk
    from this function alone; until then nothing a route runs can use it.
    """
    allow = _allow(world)
    guard.install()
    with pytest.raises(GuardRefusedError), guard.scope("read", readable=allow.readable):
        allow.open_directory(world["inside"])


# -- a continuous swap, reporting what it reached ------------------------------------


@pytest.fixture
def flipping(world: dict[str, Path]) -> Iterator[threading.Event]:
    """A thread that keeps swapping the run directory with a link to the outside copy."""
    stop = threading.Event()
    real = world["inside"].with_name("run-1.real")

    def flip() -> None:
        while not stop.is_set():
            world["inside"].rename(real)
            world["inside"].symlink_to(world["outside"], target_is_directory=True)
            world["inside"].unlink()
            real.rename(world["inside"])

    thread = threading.Thread(target=flip, daemon=True)
    thread.start()
    yield stop
    stop.set()
    thread.join(timeout=10)


def test_a_continuous_swap_never_hands_back_the_outside_directory(
    world: dict[str, Path], flipping: threading.Event
) -> None:
    """A continuous swap never hands back the outside directory, and reports what it reached.

    Each outcome is counted; the escapes must be zero, and the count of attempts the swap
    reached between the judgement and the walk is reported, never assumed. Zero reached means
    the run was vacuous for the window, and it says so; the deterministic tests carry the branch.
    """
    allow = _allow(world)
    outside = _ids(world["outside"])
    counts = {"reached": 0, "escaped": 0, "judging": 0, "judged_away": 0, "approval": 0, "walk": 0}
    for _ in range(3000):
        try:
            fd = allow.open_directory(world["inside"])
        except PathRefusedError as exc:
            text = str(exc)
            if "changed while it was being judged" in text:
                counts["judging"] += 1
            elif "not a real directory" in text:
                counts["approval"] += 1
            elif "outside every root" in text:
                counts["judged_away"] += 1
            else:
                counts["walk"] += 1
            continue
        try:
            st = os.fstat(fd)
            if (st.st_dev, st.st_ino) == outside or _marker_via(fd) != "inside\n":
                counts["escaped"] += 1
            else:
                counts["reached"] += 1
        finally:
            os.close(fd)
    flipping.set()
    assert sum(counts.values()) == 3000
    assert counts["escaped"] == 0, counts
    print(f"continuous swap outcomes: {counts}")
    if counts["walk"] == 0:
        warnings.warn(
            f"no swap landed between the judgement and the walk in this run: {counts}",
            stacklevel=1,
        )
