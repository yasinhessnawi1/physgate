"""A module in a run withheld whole reads what was merged before it, in its own worktree.

In a run naming a tier, a role session reaches only its own worktree of its own run, what it is
given to read in its session directory, and its interpreter's directory. It does not reach the
run's store, its repository, the orchestrator's integration worktree or other modules' worktrees,
all of which a run naming no tier leaves open to it.

A module that builds on another's merged work still has that work: each subtask's worktree is made
from the run branch's head, which holds every module merged before it. The session then reads the
earlier module's files where they are in its own worktree, by the file tools and the shell. It
reads what the harness issues to it in its session directory too. The same files, in the places
outside its worktree where they also lie, stay refused.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.orchestrator.merge import RunGit

MERGED = "modules/m1/driver.py"
ENV = {
    "PATH": "/usr/bin:/bin",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=cwd, env={**ENV, "HOME": str(cwd)}, check=True)


def _layout(base: Path) -> tuple[RunGit, Path, Path]:
    """A run in a run root, its first module merged into the run branch, the second's worktree."""
    run_dir = base / "runs" / "run-b"
    repo = run_dir / "target"
    repo.mkdir(parents=True)
    (repo / "README.md").write_text("a target\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "target")
    run = RunGit(repo=repo, run_dir=run_dir, run_id="r")
    run.open_run_branch("main")
    # The first module's accepted work, as its merge leaves it on the run branch.
    merged = run.integration / MERGED
    merged.parent.mkdir(parents=True)
    merged.write_text("def drive(): return 1\n")
    _git(run.integration, "add", "-A")
    _git(run.integration, "commit", "-q", "-m", "merge m1")
    worktree = run.open_subtask("m2")
    sdir = run_dir / "sessions" / "s2"
    for d in ("state", "session", "config", "home"):
        (sdir / d).mkdir(parents=True)
    (sdir / "issued.json").write_text("what the harness issues to it\n")
    (run_dir / "store").mkdir()
    return run, worktree, sdir


def _config(base: Path, worktree: Path, sdir: Path) -> SessionConfig:
    run_dir = base / "runs" / "run-b"
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch=None,
        store_root=str(run_dir / "store"),
        state_dir=str(sdir / "state"),
        target_dir=str(sdir / "session"),
        claude_config_dir=str(sdir / "config"),
        user_home=str(sdir / "home"),
        token_ceiling=1000,
        sessions_root=str(run_dir / "sessions"),
        required_reading=(str(sdir / "issued.json"),),
        withheld_whole=(str(base / "runs"),),
        own_place=str(run_dir),
    )
    return build_config(request, current_installation())


def _reads(config: SessionConfig, target: Path) -> bool:
    by_tool = paths.protection(str(target), config.worktree, config, writing=False) is None
    by_shell = not shell_paths.check(parse(f"cat {target}")[0], config.worktree, config)
    return by_tool and by_shell


def test_the_next_module_reads_the_merged_module_in_its_own_worktree(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    _run, worktree, sdir = _layout(base)
    config = _config(base, worktree, sdir)
    assert (worktree / MERGED).is_file(), "the worktree was not made from the run branch's head"
    assert _reads(config, worktree / MERGED)
    # And what the harness issues to it, in its session directory, by its file tools.
    assert (
        paths.protection(str(sdir / "issued.json"), config.worktree, config, writing=False) is None
    )


def test_the_run_s_other_places_stay_refused_to_it(tmp_path: Path) -> None:
    base = tmp_path.resolve()
    run, worktree, sdir = _layout(base)
    config = _config(base, worktree, sdir)
    for elsewhere in (
        run.integration / MERGED,
        run.repo / "README.md",
        run.run_dir / "store",
    ):
        assert not _reads(config, elsewhere), f"the session reads {elsewhere.relative_to(base)}"
