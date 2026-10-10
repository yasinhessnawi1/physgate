"""A run protects the target repository's common git directory from the role session.

Its configuration, its ``info/`` (attributes and exclude), its hooks and the per-worktree
configuration are where a write would make a later git command run a program. A role session
has no legitimate need to touch them, so a run makes them protected roots: the path layer refuses
a file tool's write, and the sentinel puts back a shell write. Reads stay allowed, and files
outside the git directory are untouched.

Defensive only: no input here makes a program run; the git directory is a fresh one, and the
"writes" are to inert paths, checked against the hook's own decision.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from hook_helpers import write_config

from physgate.hooks import paths
from physgate.orchestrator.dispatch import GIT_CONFIG_NAMES, git_config_roots, run_protected_roots
from physgate.orchestrator.git import common_dir
from physgate.orchestrator.merge import RunGit


def _repo(tmp: Path) -> Path:
    repo = tmp / "target"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)],
        env={"PATH": "/usr/bin:/bin", "HOME": os.devnull},
        check=True,
        capture_output=True,
    )
    return repo


def test_run_protected_roots_covers_the_git_dir_exec_surface(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="run-1")
    reverted, _ = run_protected_roots(run)
    common = common_dir(repo)
    for name in GIT_CONFIG_NAMES:
        assert common / name in reverted, name
    # They are put back (reverted), not merely refuse-only, so a shell write is undone too.
    assert set(git_config_roots(common)) <= set(reverted)


@pytest.mark.parametrize("name", ["config", "config.worktree", "hooks", "info"])
def test_the_path_layer_refuses_a_role_write_under_the_git_dir(tmp_path: Path, name: str) -> None:
    common = common_dir(_repo(tmp_path))
    roots = [
        {"path": str(p), "reason": "it is git's own directory", "watch": "revert"}
        for p in git_config_roots(common)
    ]
    _, _, config = write_config(tmp_path, protected_roots=roots)
    # A file under each protected root is refused to a writing tool.
    target = str(common / name / "x") if name in ("hooks", "info") else str(common / name)
    assert paths.protection(target, str(tmp_path), config, writing=True) is not None
    # Reading it is allowed, and an ordinary source file is untouched.
    assert paths.protection(target, str(tmp_path), config, writing=False) is None
    assert paths.protection(str(tmp_path / "m.py"), str(tmp_path), config, writing=True) is None
