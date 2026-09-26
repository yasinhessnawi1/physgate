"""The orchestrator's git plumbing: branches, worktrees, commits and merges.

Every command runs with the user's and the system's git configuration switched
off and repository hooks disabled. The orchestrator's merges and commits must not
depend on one person's aliases, signing setup or hook scripts, and a hook script
in a target repository is code the orchestrator would otherwise run on every
commit. Author and committer are fixed, so the history says the orchestrator
made the commit and not an agent.

A git failure raises ``GitError`` with the command and its output. Nothing here
retries, and nothing asks a model what went wrong.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from physgate.orchestrator.exceptions import GitError

AUTHOR = ("physgate orchestrator", "orchestrator@physgate.invalid")

_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": AUTHOR[0],
    "GIT_AUTHOR_EMAIL": AUTHOR[1],
    "GIT_COMMITTER_NAME": AUTHOR[0],
    "GIT_COMMITTER_EMAIL": AUTHOR[1],
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}
_FLAGS = ("-c", f"core.hooksPath={os.devnull}", "-c", "commit.gpgsign=false")


def git(cwd: Path, *args: str, check: bool = True, stdin: str | None = None) -> str:
    """Run one git command in ``cwd`` and return its standard output.

    Raises:
        GitError: it exited non-zero and ``check`` is true.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    done = subprocess.run(
        ["git", *_FLAGS, *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and done.returncode != 0:
        msg = "a git command failed"
        raise GitError(
            msg,
            command=" ".join(args),
            cwd=str(cwd),
            exit=str(done.returncode),
            stderr=done.stderr.strip()[-800:],
        )
    return done.stdout


def head_of(repo: Path, ref: str) -> str:
    """The commit ``ref`` points at, as a full SHA."""
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def branch_exists(repo: Path, branch: str) -> bool:
    """Whether ``refs/heads/<branch>`` exists."""
    return bool(git(repo, "branch", "--list", branch).strip())


def add_worktree(repo: Path, path: Path, branch: str, start: str) -> None:
    """Check ``branch`` out at ``path``, creating the branch at ``start`` if it is new.

    An existing worktree at ``path`` on ``branch`` is kept as it is: a repair
    attempt continues in the worktree the rejected attempt left.
    """
    if path.exists():
        current = git(path, "rev-parse", "--abbrev-ref", "HEAD").strip()
        if current != branch:
            msg = "a worktree exists at the path on another branch"
            raise GitError(msg, path=str(path), branch=current, expected=branch)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(repo, branch):
        git(repo, "worktree", "add", "--quiet", str(path), branch)
    else:
        git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), start)


def commit_all(worktree: Path, message: str) -> str:
    """Stage everything in ``worktree`` and commit it, even if nothing changed.

    Empty commits are allowed on purpose: an attempt that changed nothing still
    has a commit, so it can be judged and named like any other.
    """
    git(worktree, "add", "--all")
    git(worktree, "commit", "--quiet", "--allow-empty", "--file", "-", stdin=message)
    return head_of(worktree, "HEAD")


@dataclass(frozen=True)
class Change:
    """One path an attempt changed, with its old and new git modes."""

    status: str
    path: str
    old_mode: str
    new_mode: str


def changes_between(repo: Path, base: str, commit: str) -> list[Change]:
    """Every path changed from ``base`` to ``commit``, renames split in two."""
    raw = git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, commit)
    fields = raw.split("\0")
    out: list[Change] = []
    i = 0
    while i + 1 < len(fields) and fields[i].startswith(":"):
        meta = fields[i][1:].split(" ")
        out.append(
            Change(status=meta[4][0], path=fields[i + 1], old_mode=meta[0], new_mode=meta[1])
        )
        i += 2
    return out


def merge_base(repo: Path, one: str, other: str) -> str:
    """The best common ancestor of two commits."""
    return git(repo, "merge-base", one, other).strip()


def diff_text(repo: Path, base: str, commit: str) -> str:
    """The patch from ``base`` to ``commit``, for a person to read."""
    return git(repo, "diff", "--no-color", "--no-ext-diff", base, commit)


def merges_of(repo: Path, branch: str, since: str) -> dict[str, str]:
    """Second parent to merge commit, for every merge on ``branch`` after ``since``."""
    out = git(repo, "log", "--merges", "--format=%H %P", f"{since}..{branch}")
    found: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            found[parts[2]] = parts[0]
    return found


def init_repo(path: Path) -> None:
    """Make ``path`` a git repository of its own, if it is not one already."""
    if not (path / ".git").exists():
        git(path, "init", "--quiet", "--initial-branch", "main")
