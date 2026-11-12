"""The node proposals directory is write-denied to every shell command, and made before it starts.

A node reaches the graph as a proposal the Write or Edit tool writes, which the
hooks check before it exists. A command can reach the directory without naming it
(a path it builds as it runs, a directory it copies or moves into place), so the
OS layer denies it to the shell, while the file tools, which it does not wrap,
still write there. A denied path that does not exist is named only where its
parent exists, so the installer makes the directory first, never through a link.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_the_deny_list_is_the_registry import _config, _fs, _layout

from physgate.hooks import graph
from physgate.hooks.settings import _make_file_tool_dirs
from physgate.oslayer.policy import FIELD_RULES, proposals_dir, sandbox_policy


def _deny(paths: dict[str, Path]) -> tuple[set[str], tuple[str, ...]]:
    policy = sandbox_policy(
        _config(paths), home=str(paths["sdir"] / "home"), temp_dir=str(paths["temp"])
    )
    return set(_fs(policy)["denyWrite"]), policy.absent_named


def test_the_proposals_directory_is_where_the_hooks_look(tmp_path: Path) -> None:
    assert proposals_dir(str(tmp_path)) == str(tmp_path / graph.PROPOSALS_DIR)


def test_an_existing_proposals_directory_is_write_denied(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    proposals = paths["worktree"] / graph.PROPOSALS_DIR
    proposals.mkdir(parents=True)
    deny, absent = _deny(paths)
    assert str(proposals) in deny and str(proposals) not in absent
    # The outbox beside it stays the scripts' to write.
    assert str(paths["worktree"] / ".physgate" / "series") not in deny


def test_an_absent_one_beside_existing_harness_files_is_named_and_swept(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    (paths["worktree"] / ".physgate").mkdir()
    proposals = str(paths["worktree"] / graph.PROPOSALS_DIR)
    deny, absent = _deny(paths)
    assert proposals in deny and proposals in absent


def test_the_worktree_s_rule_says_so() -> None:
    assert "proposals" in FIELD_RULES["worktree"]


def test_the_installer_makes_the_directory(tmp_path: Path) -> None:
    _make_file_tool_dirs(str(tmp_path))
    assert (tmp_path / graph.PROPOSALS_DIR).is_dir()
    _make_file_tool_dirs(str(tmp_path))  # and again, as a resumed session's installer does
    assert (tmp_path / graph.PROPOSALS_DIR).is_dir()


def test_the_installer_makes_nothing_for_a_worktree_that_is_not_there(tmp_path: Path) -> None:
    _make_file_tool_dirs(str(tmp_path / "missing"))
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("step", [".physgate", ".physgate/proposals"])
def test_the_installer_never_follows_a_link_a_session_left(tmp_path: Path, step: str) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    worktree = tmp_path / "worktree"
    (worktree / step).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(elsewhere, worktree / step)
    with pytest.raises(ValueError, match="not a directory"):
        _make_file_tool_dirs(str(worktree))
    assert list(elsewhere.iterdir()) == []


def test_the_installer_refuses_a_file_where_the_directory_goes(tmp_path: Path) -> None:
    (tmp_path / ".physgate").mkdir()
    (tmp_path / graph.PROPOSALS_DIR).write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        _make_file_tool_dirs(str(tmp_path))


# --- the completion declaration's directory, held as the proposals' is -------------------------


def test_the_completion_directory_is_write_denied_as_the_proposals_are(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    completion = paths["worktree"] / graph.COMPLETION_DIR
    completion.mkdir(parents=True)
    deny, absent = _deny(paths)
    assert str(completion) in deny and str(completion) not in absent
    assert "declaration" in FIELD_RULES["worktree"]


def test_the_installer_makes_the_completion_directory_too(tmp_path: Path) -> None:
    _make_file_tool_dirs(str(tmp_path))
    assert (tmp_path / graph.COMPLETION_DIR).is_dir()
    _make_file_tool_dirs(str(tmp_path))
    assert (tmp_path / graph.COMPLETION_DIR).is_dir()


# --- the disputes' directory, held as the proposals' is -----------------------------------------


def test_the_disputes_directory_is_write_denied_as_the_proposals_are(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    disputes = paths["worktree"] / graph.DISPUTES_DIR
    disputes.mkdir(parents=True)
    deny, absent = _deny(paths)
    assert str(disputes) in deny and str(disputes) not in absent
    assert "disputes" in FIELD_RULES["worktree"]


def test_the_installer_makes_the_disputes_directory_too(tmp_path: Path) -> None:
    _make_file_tool_dirs(str(tmp_path))
    assert (tmp_path / graph.DISPUTES_DIR).is_dir()
