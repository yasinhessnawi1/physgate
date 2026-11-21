"""Staging and the checkpoint's look at a task are bounded, and fail as a refusal of that task.

A task is copied into staging entry by entry, every directory counted with every file against
the task's budget, and no deeper than a task goes: past either limit the task is refused before
anything further is opened. Anything that goes wrong while one task is copied (the disk, a
recursion) refuses that task, its partial copy removed, and staging goes on with the next.

The checkpoint's look at a task (which files it holds, at what size and time) walks the same
budget and depth: a task that holds more than that is seen as over, never walked whole.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import _write_task

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import stage
from physgate.evaluation.per_role.firmware import sandbox


def _worktree(tmp_path: Path, count: int = 2) -> Path:
    worktree = tmp_path / "worktree"
    for n in range(count):
        _write_task(worktree / f"control.t{n:02d}", n)
    return worktree


def _limit(name: str) -> int:
    value = getattr(author_session, name, None)
    assert isinstance(value, int), f"there is no {name}"
    return value


def _chain(top: Path, depth: int) -> Path:
    """``depth`` nested directories under ``top``, named d00, d01, …, with a file at the bottom."""
    here = top
    for level in range(depth):
        here = here / f"d{level:02d}"
    here.mkdir(parents=True)
    (here / "note.txt").write_text("deep")
    return here


def test_directories_count_against_a_task_s_budget(tmp_path: Path) -> None:
    worktree = _worktree(tmp_path)
    many = worktree / "control.t01" / "references" / "good"
    for n in range(_limit("MOST_FILES_PER_TASK") + 1):
        (many / f"empty{n:03d}").mkdir()
    refused = stage(worktree, tmp_path / "staging")
    assert refused == 1, "a task holding more directories than a task's worth was staged"
    assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == ["control.t00"]


def test_a_task_deeper_than_a_task_goes_is_refused_before_its_depth_is_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deepest = _limit("MOST_DEPTH_PER_TASK")
    worktree = _worktree(tmp_path)
    good = worktree / "control.t01" / "references" / "good"
    _chain(good, deepest + 4)
    opened: list[str] = []
    real = sandbox.open_directory

    def recording(path: str, dir_fd: int | None = None) -> int:
        opened.append(os.path.basename(path))
        return real(path, dir_fd) if dir_fd is not None else real(path)

    monkeypatch.setattr(author_session, "open_directory", recording)
    refused = stage(worktree, tmp_path / "staging")
    assert refused == 1, "a task deeper than a task goes was staged"
    # references and good are the first two levels below the task; the chain starts at 3.
    levels = [int(name[1:]) + 3 for name in opened if name.startswith("d") and name[1:].isdigit()]
    assert levels and max(levels) <= deepest, (
        f"a directory {max(levels)} levels down was opened; the limit is {deepest}"
    )


def test_a_task_as_deep_as_a_task_goes_is_staged(tmp_path: Path) -> None:
    # Control: the limit refuses what is past it, not what reaches it.
    worktree = _worktree(tmp_path)
    _chain(worktree / "control.t01" / "references" / "good", _limit("MOST_DEPTH_PER_TASK") - 2)
    assert stage(worktree, tmp_path / "staging") == 0


@pytest.mark.parametrize(
    "failure", [OSError(28, "No space left on device"), RecursionError("too deep")]
)
def test_a_copy_that_fails_refuses_that_task_and_staging_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    worktree = _worktree(tmp_path, 3)
    real = author_session._copy_into
    calls = {"n": 0}

    def failing(source: int, target: int, budget: Any) -> None:  # noqa: ANN401
        calls["n"] += 1
        if calls["n"] == 2:
            os.mkdir("half", 0o700, dir_fd=target)
            raise failure
        real(source, target, budget)

    monkeypatch.setattr(author_session, "_copy_into", failing)
    try:
        refused = stage(worktree, tmp_path / "staging")
    except (OSError, RecursionError) as exc:
        pytest.fail(f"a copy that failed ended staging: {exc!r}")
    assert refused == 1
    assert sorted(p.name for p in (tmp_path / "staging").iterdir()) == [
        "control.t00",
        "control.t02",
    ], "the failed task's partial copy was left, or staging stopped"


def test_the_checkpoint_s_look_at_a_task_is_bounded_by_its_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    most = _limit("MOST_FILES_PER_TASK")
    task = tmp_path / "control.t00"
    _write_task(task, 0)
    for n in range(most * 4):
        (task / f"x{n:04d}.txt").write_text("x")
    looked: list[str] = []
    real = os.lstat

    def counting(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:  # noqa: ANN401
        looked.append(str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", counting)
    seen = author_session._signature(task)
    monkeypatch.undo()
    assert len(seen) <= most + 1, f"the look listed {len(seen)} entries of one task"
    assert len(looked) <= most + 1, f"the look examined {len(looked)} entries of one task"


def test_the_checkpoint_s_look_at_a_task_goes_no_deeper_than_a_task(tmp_path: Path) -> None:
    deepest = _limit("MOST_DEPTH_PER_TASK")
    task = tmp_path / "control.t00"
    _write_task(task, 0)
    _chain(task / "references" / "good", deepest + 10)
    seen = author_session._signature(task)
    depths = [entry[0].count("/") for entry in seen if entry[0] != "…"]
    assert max(depths) <= deepest, f"the look went {max(depths)} levels down"


def test_a_task_past_the_look_s_bounds_is_still_seen_to_change(tmp_path: Path) -> None:
    # The bounded look must not hide a change: a task over the bounds reads as changed when
    # its contents do, so the checkpoint stages it (and staging refuses it).
    most = _limit("MOST_FILES_PER_TASK")
    task = tmp_path / "control.t00"
    _write_task(task, 0)
    for n in range(most * 2):
        (task / f"x{n:04d}.txt").write_text("x")
    before = author_session._signature(task)
    (task / "task.json").write_text((task / "task.json").read_text() + " ")
    assert author_session._signature(task) != before
