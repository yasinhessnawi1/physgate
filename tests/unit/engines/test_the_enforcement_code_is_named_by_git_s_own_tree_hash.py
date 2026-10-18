"""The enforcement code a run has is named by git's own tree hash of its hook package.

A reader holds a recorded hash to the repository with ``git rev-parse <commit>:<path>``, so
the hash is git's: the same files give the same id git gives them, an uncommitted change
gives another, and what git ignores here (byte-compiled files, folder metadata) is left out.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from physgate.engines.enforcement import ENFORCEMENT_PACKAGE, enforcement_tree, tree_hash

REPO = Path(__file__).resolve().parents[3]
#: The commit R-HK-03 froze, and the tree of its hook package the evidence register names.
MEASURED_COMMIT = "1c5e988"


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env
    )
    return done.stdout.strip()


def _fixture(root: Path) -> Path:
    tree = root / "pkg"
    (tree / "sub" / "deeper").mkdir(parents=True)
    (tree / "a.py").write_text("x = 1\n")
    (tree / "sub" / "b.txt").write_bytes(b"\x00binary\xff")
    (tree / "sub" / "deeper" / "c.py").write_text("")  # empty file
    run = tree / "run.sh"
    run.write_text("#!/bin/sh\necho hi\n")
    run.chmod(0o755)
    # A name that sorts differently as a directory than as a file: "sub" vs "sub.py".
    (tree / "sub.py").write_text("y = 2\n")
    (tree / "link").symlink_to("a.py")
    # What git ignores here, and what it never holds.
    (tree / "__pycache__").mkdir()
    (tree / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"compiled")
    (tree / "sub" / "x.pyc").write_bytes(b"compiled")
    (tree / ".DS_Store").write_bytes(b"meta")
    (tree / "empty").mkdir()
    return tree


def test_the_hash_is_git_s_tree_id_for_the_same_files(tmp_path: Path) -> None:
    tree = _fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n.DS_Store\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid"}
    env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"}
    _git(tmp_path, "commit", "-qm", "fixture", env=env)
    assert tree_hash(tree) == _git(tmp_path, "rev-parse", "HEAD:pkg")
    # A change to one byte, or to one mode, is another tree.
    (tree / "sub" / "deeper" / "c.py").write_text(" ")
    changed = tree_hash(tree)
    assert changed != _git(tmp_path, "rev-parse", "HEAD:pkg")
    (tree / "sub" / "deeper" / "c.py").write_text("")
    (tree / "run.sh").chmod(0o644)
    assert tree_hash(tree) not in (changed, _git(tmp_path, "rev-parse", "HEAD:pkg"))


def test_this_process_s_hook_package_is_named_as_git_would_name_it_now(tmp_path: Path) -> None:
    # The working files as they stand, through a scratch index, so an uncommitted change counts.
    index = tmp_path / "index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    _git(REPO, "read-tree", "HEAD", env=env)
    relative = str(ENFORCEMENT_PACKAGE.relative_to(REPO))
    _git(REPO, "add", "-A", "--", relative, env=env)
    expected = _git(REPO, "write-tree", f"--prefix={relative}/", env=env)
    assert enforcement_tree() == expected


def test_the_register_names_the_hook_tree_of_the_measured_commit() -> None:
    from physgate.engines.claude_code.layers import HOOK_EVIDENCE

    known = subprocess.run(
        ["git", "cat-file", "-e", f"{MEASURED_COMMIT}^{{commit}}"], cwd=REPO, check=False
    )
    if known.returncode != 0:
        pytest.skip(f"this clone does not hold {MEASURED_COMMIT}: the register is not checked here")
    measured = _git(REPO, "rev-parse", f"{MEASURED_COMMIT}:src/physgate/hooks")
    assert HOOK_EVIDENCE["2.1.301"].enforcement_tree == measured
