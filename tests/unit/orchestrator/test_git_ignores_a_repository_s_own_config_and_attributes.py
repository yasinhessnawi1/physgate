"""The orchestrator's git reads a repository's objects, not its configuration or attributes.

A role session owns its worktree, so it can write the repository's local configuration, its
`.gitattributes`, and commit a submodule. git honours all of those when it runs inside that
repository, and some of them run a program. The hardening closes that class: a content read runs
against a clean object store, and every command runs with attributes, the file-system monitor,
hooks and submodule recursion off.

These tests use only inert markers: a repository-local setting or attribute whose sole effect is
visible in git's own output (an abbreviation length, a diff prefix, a diff order file, a diff
driver that only changes how a path is listed, a gitlink that must stay a gitlink). None runs a
program. The test asserts the harness's read does not change, so the repository's configuration
was not consulted. A linked worktree, whose git directory holds no objects of its own, is read
through the same store.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from physgate.orchestrator.git import changes_between, diff_text

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _two_commit_repo(root: Path) -> tuple[Path, str, str]:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "m.py").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "m.py").write_text("two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    commit = _git(repo, "rev-parse", "HEAD")
    return repo, base, commit


def test_a_local_abbrev_and_diff_prefix_do_not_change_what_the_harness_reads(
    tmp_path: Path,
) -> None:
    repo, base, commit = _two_commit_repo(tmp_path)
    clean_diff = diff_text(repo, base, commit)
    clean_changes = changes_between(repo, base, commit)
    # Inert local settings: short hashes and mnemonic (i/w) diff prefixes, visible only in output.
    _git(repo, "config", "core.abbrev", "4")
    _git(repo, "config", "diff.mnemonicPrefix", "true")
    _git(repo, "config", "diff.noprefix", "true")
    assert diff_text(repo, base, commit) == clean_diff
    assert changes_between(repo, base, commit) == clean_changes
    # The reader shows full hashes and the a/ b/ prefixes, not the local settings' output.
    assert "a/m.py" in clean_diff and "b/m.py" in clean_diff


def test_a_local_diff_order_file_does_not_change_the_listed_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    for content in ("one\n", "two\n"):
        (repo / "a.txt").write_text(content)
        (repo / "b.txt").write_text(content)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", content.strip())
    base, commit = _git(repo, "rev-parse", "HEAD~1"), _git(repo, "rev-parse", "HEAD")
    assert [c.path for c in changes_between(repo, base, commit)] == ["a.txt", "b.txt"]
    # An inert local setting: a file of path patterns that reorders git diff's output and does
    # nothing else. ``changes_between`` lists in git's order, so a read inside the repository
    # would list b.txt first.
    order = tmp_path / "order"
    order.write_text("b.txt\na.txt\n")
    _git(repo, "config", "diff.orderFile", str(order))
    raw = _git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, commit)
    assert raw.split("\0")[1] == "b.txt"  # the control: git honours it inside the repository
    assert [c.path for c in changes_between(repo, base, commit)] == ["a.txt", "b.txt"]


def test_a_linked_worktree_s_change_is_read_through_the_common_object_store(
    tmp_path: Path,
) -> None:
    repo, base, _ = _two_commit_repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "attempt", str(linked), base)
    # A linked worktree's git directory holds no objects: its ``commondir`` names the
    # repository's, which the clean store must reach.
    assert (linked / ".git").is_file()
    (linked / "m.py").write_text("three\n")
    _git(linked, "add", "-A")
    _git(linked, "commit", "-q", "-m", "attempt")
    commit = _git(linked, "rev-parse", "HEAD")
    diff = diff_text(linked, base, commit)
    assert "-one" in diff and "+three" in diff
    assert [(c.status, c.path) for c in changes_between(linked, base, commit)] == [("M", "m.py")]


def test_a_committed_gitattributes_driver_does_not_change_what_the_harness_reads(
    tmp_path: Path,
) -> None:
    repo, base, commit = _two_commit_repo(tmp_path)
    # An attribute mapping the file to a diff driver whose "binary" marking would change the
    # listing (a binary file shows "Binary files differ"), committed in the tree.
    (repo / ".gitattributes").write_text("*.py diff=marked\n")
    _git(repo, "config", "diff.marked.binary", "true")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "attr")
    marked = _git(repo, "rev-parse", "HEAD")
    diff = diff_text(repo, base, marked)
    # The attribute is not read: the change to m.py is still shown as text, not "Binary differ".
    assert "-one" in diff and "+two" in diff
    assert "Binary files" not in diff


def test_a_committed_submodule_stays_a_gitlink_and_is_not_recursed(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    _git(sub, "init", "-q", "-b", "m")
    (sub / "f").write_text("x\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "s1")
    s1 = _git(sub, "rev-parse", "HEAD")
    (sub / "f").write_text("y\n")
    _git(sub, "add", "-A")
    _git(sub, "commit", "-q", "-m", "s2")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "run")
    (repo / "a").write_text("1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "submodule", "-q", "add", str(sub), "sub")
    _git(repo / "sub", "checkout", "-q", s1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "p-s1")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo / "sub", "checkout", "-q", "m")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "p-s2")
    commit = _git(repo, "rev-parse", "HEAD")
    # A local setting asking git to recurse into the submodule: the read must still show only
    # the gitlink move, never the submodule's own file diff.
    _git(repo, "config", "diff.submodule", "diff")
    diff = diff_text(repo, base, commit)
    assert "Subproject commit" in diff or "160000" in diff
    assert "-x" not in diff and "+y" not in diff
    changes = changes_between(repo, base, commit)
    assert [c.path for c in changes] == ["sub"] and changes[0].new_mode == "160000"
