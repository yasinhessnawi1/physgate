"""The orchestrator's git reads a repository's objects, not its configuration or attributes.

A role session owns its worktree, so it can write the repository's local configuration, its
`.gitattributes`, and commit a submodule. git honours all of those when it runs inside that
repository, and some of them run a program. The hardening closes that class: a content read runs
against a clean object store, and every command runs with attributes, the file-system monitor,
hooks and submodule recursion off.

These tests use only inert markers: a repository-local setting or attribute whose sole effect is
visible in git's own output (an abbreviation length, a diff prefix, a diff driver that only
changes how a path is listed, a gitlink that must stay a gitlink). None runs a program. The test
asserts the harness's read does not change, so the repository's configuration was not consulted.
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
