"""The author's checkpoint lists the session's task directories while the session writes them.

An entry the session removes between the listing and the look at it is no longer a task: it
is left out. It never ends the listing, which would end the checkpoint, and with it the watch
that holds the session to its cap.
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
