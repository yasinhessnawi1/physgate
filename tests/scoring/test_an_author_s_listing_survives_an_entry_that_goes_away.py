"""The author's checkpoint lists the session's task directories while the session writes them.

An entry the session removes between the listing and the look at it is no longer a task: it
is left out. It never ends the listing, which would end the checkpoint, and with it the watch
that holds the session to its cap. The same holds one level down, for an entry inside a task
that goes away while the task is copied.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.evaluation.per_role import author_session


def test_an_entry_that_goes_away_while_the_tasks_are_listed_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("control.t01", "control.t02"):
        (tmp_path / name).mkdir()
    real = author_session._classify

    def vanishing(name: str, dir_fd: int) -> os.stat_result:
        if name == "control.t01":
            raise FileNotFoundError(name)
        return real(name, dir_fd)

    monkeypatch.setattr(author_session, "_classify", vanishing)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            names: list[str] | None = author_session._task_names(fd)
        except FileNotFoundError:
            names = None
    finally:
        os.close(fd)
    assert names == ["control.t02"], "an entry that went away ended the listing"


def test_an_entry_inside_a_task_that_goes_away_while_it_is_copied_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = tmp_path / "worktree"
    task = worktree / "control.t01"
    task.mkdir(parents=True)
    (task / "task.json").write_text("{}")
    (task / "draft.json").write_text("{}")  # the author removes it as the copy looks at it
    real = author_session._classify

    def vanishing(name: str, dir_fd: int) -> os.stat_result:
        if name == "draft.json":
            raise FileNotFoundError(name)
        return real(name, dir_fd)

    monkeypatch.setattr(author_session, "_classify", vanishing)
    try:
        refused: int | None = author_session.stage(worktree, tmp_path / "staging")
    except FileNotFoundError:
        refused = None
    assert refused == 0, "an entry that went away inside a task ended the copy"
    assert sorted(p.name for p in (tmp_path / "staging" / "control.t01").iterdir()) == ["task.json"]
    # The checkpoint copies the same way; were it to raise, the watch would stop the session.
    progress = author_session.AuthorProgress(
        worktree, tmp_path / "checks", cap=8_000_000, per_task=1_000_000
    )
    try:
        reason: str | None = progress.check(0)
    except FileNotFoundError:
        reason = "raised"
    assert reason is None, "an entry that went away inside a task ended the checkpoint"
