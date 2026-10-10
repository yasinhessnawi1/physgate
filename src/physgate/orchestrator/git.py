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

import atexit
import functools
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from physgate.orchestrator.exceptions import GitError

AUTHOR = ("physgate orchestrator", "orchestrator@physgate.invalid")

#: Git's empty tree. Attribute lookup reads ``.gitattributes`` from it, so no committed
#: attribute selects a diff driver or a merge driver, two ways a role-written repository would
#: otherwise run a program when the harness diffs or merges it. (This does not govern the
#: clean/smudge filter ``git add`` applies; that is why content reads run against a clean store
#: rather than relying on it, and why a write in a role worktree is a separate concern.)
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_ATTR_SOURCE": _EMPTY_TREE,
    "GIT_AUTHOR_NAME": AUTHOR[0],
    "GIT_AUTHOR_EMAIL": AUTHOR[1],
    "GIT_COMMITTER_NAME": AUTHOR[0],
    "GIT_COMMITTER_EMAIL": AUTHOR[1],
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}
#: Overrides on every command: hooks off, no signing, the file-system monitor off (it is a
#: program a repository can name), a repository's own attributes file off, the ``ext``
#: transport off, and every signature path neutralised — a signed commit, merge or log would
#: otherwise run ``gpg.program``, a program a repository can name, to make or verify a
#: signature. A repository's local config is still read for keys that only change git's
#: output; the exec vectors above are forced off, and content reads run against a clean store
#: (:func:`_object_store`) so even those keys cannot be read.
_FLAGS = (
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "commit.gpgsign=false",
    "-c", "core.fsmonitor=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "protocol.ext.allow=never",
    "-c", "log.showSignature=false",
    "-c", "merge.verifySignatures=false",
    "-c", f"gpg.program={os.devnull}",
)  # fmt: skip
#: Added to a diff: no external diff program, no textconv program, and a submodule shown as
#: its gitlink rather than recursed into (recursion re-runs git in the submodule, where the
#: parent's ``--no-ext-diff``/``--no-textconv`` do not reach).
_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv", "--no-color", "--submodule=short")


def _git_dir(repo: Path) -> Path:
    """The repository's git directory, read from the filesystem without running git."""
    dot = Path(repo) / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        pointer = dot.read_text().strip()
        if pointer.startswith("gitdir:"):
            named = Path(pointer.removeprefix("gitdir:").strip())
            return named if named.is_absolute() else (Path(repo) / named).resolve()
    msg = "the path is not a git repository"
    raise GitError(msg, cwd=str(repo))


def _object_dirs(repo: Path) -> tuple[str, ...]:
    """Every object directory a repository's commits are read from, from the filesystem.

    A worktree's objects live in the repository's common directory; a repository may name
    more in ``objects/info/alternates``. Each is a store of content-addressed objects: naming
    one grants read access to objects a commit already pins, never a way to change them.
    """
    git_dir = _git_dir(repo)
    roots = [git_dir]
    commondir = git_dir / "commondir"
    if commondir.is_file():
        named = Path(commondir.read_text().strip())
        roots.append(named if named.is_absolute() else (git_dir / named).resolve())
    found: list[str] = []
    seen: set[str] = set()
    pending = [root / "objects" for root in roots]
    while pending:
        objects = pending.pop(0)
        resolved = str(objects.resolve())
        if resolved in seen or not objects.is_dir():
            continue
        seen.add(resolved)
        found.append(resolved)
        alternates = objects / "info" / "alternates"
        if alternates.is_file():
            for line in alternates.read_text().splitlines():
                entry = line.strip()
                if entry and not entry.startswith("#"):
                    pending.append(Path(entry))
    if not found:
        msg = "the repository holds no object store"
        raise GitError(msg, cwd=str(repo))
    return tuple(found)


_STORES: list[str] = []


@atexit.register
def _remove_stores() -> None:
    for store in _STORES:
        shutil.rmtree(store, ignore_errors=True)


@functools.cache
def _object_store(object_dirs: tuple[str, ...]) -> str:
    """A throwaway bare git directory reaching ``object_dirs`` through alternates, nothing else.

    A content read (a diff of two commits) runs against this instead of inside the repository,
    so the repository's own config, its ``.gitattributes``, its ``include`` paths and any
    submodule's config are never read and can run nothing, and a committed submodule is shown
    as its gitlink rather than recursed into.
    """
    store = tempfile.mkdtemp(prefix="physgate-git-store-")
    _STORES.append(store)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    done = subprocess.run(
        ["git", *_FLAGS, "init", "-q", "--bare", store],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        msg = "git could not prepare a clean object store"
        raise GitError(msg, stderr=done.stderr.strip()[-400:])
    (Path(store) / "objects" / "info" / "alternates").write_text("\n".join(object_dirs) + "\n")
    return store


def git(
    cwd: Path, *args: str, check: bool = True, stdin: str | None = None, objects_only: bool = False
) -> str:
    """Run one git command in ``cwd`` and return its standard output.

    With ``objects_only`` the command runs against a clean object store that reaches ``cwd``'s
    objects but holds none of its config, attributes or submodules: used for content reads (a
    diff of two commits), so a role-written repository cannot make the read run a program.

    Raises:
        GitError: it exited non-zero and ``check`` is true.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    if objects_only:
        store = _object_store(_object_dirs(Path(cwd)))
        argv = ["git", "--git-dir", store, *_FLAGS, *args]
        run_in: Path | str = store
    else:
        verify_worktree_pointer(Path(cwd))
        argv = ["git", *_FLAGS, *args]
        run_in = cwd
    done = subprocess.run(
        argv,
        cwd=run_in,
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


def git_timed(cwd: Path, *args: str, timeout: float) -> tuple[int | None, str, float]:
    """Run one git command with a time limit: (exit code or None on timeout, stderr, seconds).

    Never raises for a failure or a timeout: the caller records what happened.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    started = time.monotonic()
    try:
        done = subprocess.run(
            ["git", *_FLAGS, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "", time.monotonic() - started
    return done.returncode, done.stderr.strip()[-400:], time.monotonic() - started


def verify_worktree_pointer(cwd: Path) -> None:
    """Fail closed unless a linked worktree's ``.git`` names a real git admin directory.

    A role session owns its worktree. If it rewrote the worktree's ``.git`` pointer file to
    name a directory it controls, the orchestrator's next commit, run with its working
    directory here, would take that directory's config — a filter, a hook — as git's own and
    run a program. The pointer file is a protected root, so a tool write to it is refused and a
    shell write is put back; this is the second check, before every in-repo git command: the
    pointer must name an admin directory that is a git worktree's (it has ``commondir`` and a
    ``gitdir`` back-pointer resolving to this very ``.git``), or the command does not run.

    A repository whose ``.git`` is an ordinary directory (not a linked worktree) is left alone.
    """
    dot = Path(cwd) / ".git"
    if not dot.is_file():
        return
    pointer = dot.read_text().strip()
    if not pointer.startswith("gitdir:"):
        msg = "a worktree's .git is not a gitdir pointer"
        raise GitError(msg, cwd=str(cwd))
    named = Path(pointer.removeprefix("gitdir:").strip())
    admin = named if named.is_absolute() else (Path(cwd) / named).resolve()
    back = admin / "gitdir"
    if not (admin / "commondir").is_file() or not back.is_file():
        msg = "a worktree's .git points at no git worktree admin directory"
        raise GitError(msg, cwd=str(cwd), admin=str(admin))
    if Path(back.read_text().strip()).resolve() != dot.resolve():
        msg = "a worktree's .git and its admin directory disagree"
        raise GitError(msg, cwd=str(cwd), admin=str(admin))


def head_of(repo: Path, ref: str) -> str:
    """The commit ``ref`` points at, as a full SHA."""
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def common_dir(repo: Path) -> Path:
    """The git directory a repository's refs live in, whatever its layout.

    A repository that is itself a worktree, or keeps its git directory elsewhere
    behind a ``.git`` file, has no ``<repo>/.git/refs``; git says where they are.
    """
    found = Path(git(repo, "rev-parse", "--git-common-dir").strip())
    return found if found.is_absolute() else (Path(repo) / found).resolve()


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
    raw = git(
        repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, commit, objects_only=True
    )
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
    return git(repo, "diff", *_DIFF_FLAGS, base, commit, objects_only=True)


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
