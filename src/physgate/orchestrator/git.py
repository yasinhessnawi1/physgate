"""The orchestrator's git plumbing: branches, worktrees, commits and merges.

Every command runs one git binary, resolved once per process (:func:`harness_git`): the first
``git`` on the harness's ``PATH``, then in ``/usr/bin``, whose version is 2.42 or later. git
before 2.42 silently ignores the attribute source the harness sets, so an older one is never
run, and no command looks git up on ``PATH`` itself.

Every command runs with the user's and the system's git configuration switched
off, repository hooks disabled and replacement objects ignored, so it reads and
writes the exact objects it names. The orchestrator's merges and commits must not
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
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.orchestrator.exceptions import GitError

AUTHOR = ("physgate orchestrator", "orchestrator@physgate.invalid")

#: Git's empty tree: every command takes its attributes from it (``--attr-source`` and
#: ``GIT_ATTR_SOURCE``), not from a ``.gitattributes`` in the worktree, the index or a commit.
#: So no committed attribute selects a diff driver or a merge driver, two ways a role-written
#: repository would otherwise run a program when the harness diffs or merges it, and none
#: changes what ``git add`` stages. Measured on git 2.54.0 with an inert attribute: with a
#: ``* text`` committed, a file with CRLF line endings was staged byte for byte under this
#: source, where ``git add`` without it staged the file with LF endings. git 2.39.3 ignored the
#: environment variable and staged LF, and refused the option; hence the 2.42 floor.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
#: The empty tree under each object format git can store. A clean-store read takes its attribute
#: source from the one matching the store, since git refuses an attribute source of the other hash.
#: A command inside a repository keeps the SHA-1 one, so in a SHA-256 repository it fails closed.
EMPTY_TREES = {
    "sha1": _EMPTY_TREE,
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}

#: The oldest git the harness runs: before 2.42, git ignores ``GIT_ATTR_SOURCE`` without a word
#: and refuses ``--attr-source``, so a committed ``.gitattributes`` would choose how the harness
#: diffs, merges and adds.
GIT_FLOOR = (2, 42)
#: Looked in after every directory on the harness's ``PATH``.
_LAST_DIRECTORY = "/usr/bin"
_VERSION_LINE = re.compile(r"^git version (\d+)\.(\d+)")


class GitBinary(BaseModel):
    """The git every harness git command runs, as resolved when the process first needed it."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The absolute path it was found at on the search path, as spelt (no link followed):
    #: the path every command executes.
    path: Annotated[str, StringConstraints(pattern=r"^/")]
    #: What ``git --version`` printed after ``git version``.
    version: Annotated[str, StringConstraints(min_length=1)]


def _reported_version(path: str) -> str | None:
    """What the program at ``path`` says its version is, or ``None`` if it says no git version.

    Run from the filesystem root with an empty environment, so nothing of the harness's own
    environment reaches it.
    """
    try:
        done = subprocess.run(
            [path, "--version"],
            cwd="/",
            env={"PATH": "/usr/bin:/bin", "HOME": os.devnull, "LC_ALL": "C"},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = done.stdout.strip().split("\n", 1)[0]
    if done.returncode != 0 or not _VERSION_LINE.match(line):
        return None
    return line.removeprefix("git version ").strip()


def _meets_floor(version: str) -> bool:
    found = _VERSION_LINE.match(f"git version {version}")
    return found is not None and (int(found[1]), int(found[2])) >= GIT_FLOOR


def resolve_git(search_path: str) -> GitBinary:
    """The first ``git`` at or above :data:`GIT_FLOOR`, looked for along ``search_path``.

    ``search_path`` is a ``PATH`` value; its directories are tried in order, then
    ``/usr/bin``. An empty or relative entry is skipped: it names whatever the current
    directory is when git runs, which is not a place the harness chose.

    Raises:
        GitError: no git there is 2.42 or later.
    """
    seen: set[str] = set()
    looked: list[str] = []
    for directory in [*search_path.split(os.pathsep), _LAST_DIRECTORY]:
        if not os.path.isabs(directory):
            continue
        candidate = os.path.join(os.path.normpath(directory), "git")
        if candidate in seen:
            continue
        seen.add(candidate)
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        version = _reported_version(candidate)
        looked.append(f"{candidate} ({version or 'no version'})")
        if version is not None and _meets_floor(version):
            return GitBinary(path=candidate, version=version)
    msg = (
        "no git at 2.42 or later was found on the PATH or in /usr/bin; an older git ignores "
        "the attribute source the harness sets, so the harness does not run it"
    )
    raise GitError(msg, found=", ".join(looked) or "none")


@functools.cache
def harness_git() -> GitBinary:
    """The git this process runs for every harness git command, resolved once from ``PATH``.

    Raises:
        GitError: no git at 2.42 or later is found (not cached: the next call looks again).
    """
    return resolve_git(os.environ.get("PATH", ""))


def attr_source(object_format: str = "sha1") -> str:
    """The option that makes git take attributes from the empty tree of ``object_format``."""
    return f"--attr-source={EMPTY_TREES[object_format]}"


#: The environment every command runs with. ``GIT_NO_REPLACE_OBJECTS`` turns off ``refs/replace``:
#: a replace ref makes git silently show one object in place of another, and a role can write
#: refs in a repository it works in, so a read or a merge would otherwise act on an object other
#: than the one the orchestrator named.
#:
#: ``GIT_SHALLOW_FILE`` and ``GIT_GRAFT_FILE``, set empty, name no file, so git reads neither the
#: repository's ``shallow`` file nor its ``info/grafts``. Either one makes git see a commit with
#: other parents than the commit holds (none, or any it lists), and a role session can write the
#: ``shallow`` file. A merge run in the repository computes its base through those parents, so
#: with them it could merge from another base than the write-scope check read, and keep or drop
#: a file neither saw. Measured on git 2.54: both variables, empty, restore the commit's own
#: parents in ``merge-base`` and ``merge``. An ordinary repository has neither file, so nothing
#: changes for it.
#:
#: This is the forced core of every git the harness runs: the orchestrator's, the review
#: packet's and the materialiser's. Each runner adds what is its own (an author, a ``PATH``, the
#: attribute source of the object format it reads) but none leaves any of these out.
FORCED_ENV: Mapping[str, str] = MappingProxyType(
    {
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_SHALLOW_FILE": "",
        "GIT_GRAFT_FILE": "",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
)
_ENV = {
    **FORCED_ENV,
    "GIT_ATTR_SOURCE": _EMPTY_TREE,
    "GIT_AUTHOR_NAME": AUTHOR[0],
    "GIT_AUTHOR_EMAIL": AUTHOR[1],
    "GIT_COMMITTER_NAME": AUTHOR[0],
    "GIT_COMMITTER_EMAIL": AUTHOR[1],
    "LC_ALL": "C",
}
#: Overrides on every command: hooks off, no signing, the file-system monitor off (it is a
#: program a repository can name), a repository's own attributes file off, the ``ext``
#: transport off, and every signature path neutralised — a signed commit, merge or log would
#: otherwise run ``gpg.program``, a program a repository can name, to make or verify a
#: signature. A repository's local config is still read for keys that only change git's
#: output; the exec vectors above are forced off, and content reads run against a clean store
#: (:func:`_object_store`) so even those keys cannot be read.
#:
#: The commit graph is off too. ``objects/info/commit-graph`` (and ``commit-graphs/``) is a
#: cache of every commit's parents that git trusts in place of the commits themselves, in the
#: repository and in every object directory it reaches through alternates, the clean store's
#: included. It is a file in the object directory, which a role session can write, so a graph
#: that names other parents would move a merge base, hide a merge, or change what a merge
#: merges. Read without it, git takes each commit's parents from the commit.
#:
#: Automatic maintenance is off as well. A commit or a merge otherwise starts ``git gc --auto``
#: (or ``git maintenance run --auto``) once the repository holds enough loose objects or packs,
#: and by default it detaches and keeps running after the command returns: it would repack
#: objects and pack refs in the repository's git directory while the next role session runs,
#: and that directory is protected from role sessions whole, so the session would see its
#: tool calls refused for writes the harness made. With these off, every harness write to a
#: git directory ends with the command that made it.
#:
#: Like :data:`FORCED_ENV`, these are forced on every git the harness runs, whichever module
#: runs it; a runner may add flags of its own after them.
FORCED_FLAGS: tuple[str, ...] = (
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "commit.gpgsign=false",
    "-c", "core.fsmonitor=false",
    "-c", "core.attributesFile=/dev/null",
    "-c", "protocol.ext.allow=never",
    "-c", "log.showSignature=false",
    "-c", "merge.verifySignatures=false",
    "-c", f"gpg.program={os.devnull}",
    "-c", "core.commitGraph=false",
    "-c", "gc.auto=0",
    "-c", "maintenance.auto=false",
)  # fmt: skip
_FLAGS = FORCED_FLAGS
#: Added to a diff: no external diff program, no textconv program, and a submodule shown as
#: its gitlink rather than recursed into (recursion re-runs git in the submodule, where the
#: parent's ``--no-ext-diff``/``--no-textconv`` do not reach).
_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv", "--no-color", "--submodule=short")


@dataclass(frozen=True)
class GitDir:
    """A git directory, and the common directory its objects, config and refs are read from.

    :func:`verified_git_dir` returns one whose ``common`` is the directory its check confirmed,
    so a reader given it uses that value and never reads ``commondir`` again.
    """

    path: Path
    common: Path


#: The prefix git requires of a ``.git`` file, space included: ``gitdir:`` without it is "an
#: invalid gitfile format" to git (measured on 2.54).
POINTER_PREFIX = "gitdir: "


def _git_file_path(file: Path, text: str) -> str:
    """The path in one of git's own small files, as git reads it, or a refusal.

    git removes every trailing CR and LF from a ``.git`` pointer's path and from ``commondir``,
    and nothing else: a leading or trailing blank is part of the path to git (measured on
    2.54: ``commondir`` reading ``../..`` and two spaces named the directory ``..`` and two
    spaces, not ``../..``). A path whose reading could depend on that (blank at either end, a
    line break or NUL inside, nothing at all) is refused rather than guessed at, so whatever the
    harness accepts, git reads the same way.
    """
    value = text.rstrip("\r\n")
    if not value or value != value.strip() or any(c in value for c in "\r\n\0"):
        msg = "a git file holds a path git would read differently from how it looks"
        raise GitError(msg, file=str(file), value=value[:200])
    return value


def _read_git_file(file: Path) -> str:
    """A small git file's text; bytes that are not UTF-8 are refused, never guessed at."""
    data = file.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        msg = "a git file is not text the harness can read as git does"
        raise GitError(msg, file=str(file)) from None


def _pointer_target(cwd: Path) -> Path:
    """The git directory ``cwd``'s ``.git`` file names, resolved as git resolves it.

    Relative to the directory holding the ``.git`` file.

    Raises:
        GitError: the file is not a pointer git would accept, or reads differently to git.
        OSError: it cannot be read.
    """
    dot = Path(cwd) / ".git"
    text = _read_git_file(dot)
    if not text.startswith(POINTER_PREFIX):
        msg = "a worktree's .git is not a gitdir pointer"
        raise GitError(msg, cwd=str(cwd))
    named = Path(_git_file_path(dot, text[len(POINTER_PREFIX) :]))
    return (named if named.is_absolute() else Path(cwd) / named).resolve()


def named_from(admin: Path, name: str) -> Path:
    """The path an admin directory's ``commondir`` or ``gitdir`` names, relative to that directory.

    Raises:
        GitError: it reads differently to git.
        OSError: it cannot be read.
    """
    file = admin / name
    named = Path(_git_file_path(file, _read_git_file(file)))
    return (named if named.is_absolute() else admin / named).resolve()


def _git_dir(repo: Path) -> GitDir:
    """The repository's git directory as git would find it, read from the filesystem, unchecked.

    For a read that does not verify (an observability command reading a run that may have been
    copied or moved); every write, and every read the write path makes, takes a
    :func:`verified_git_dir` instead. The files are read as git reads them, so a pointer or a
    ``commondir`` git would read another way is refused here too.
    """
    dot = Path(repo) / ".git"
    try:
        if dot.is_dir():
            git_dir = dot
        elif dot.is_file():
            git_dir = _pointer_target(Path(repo))
        else:
            msg = "the path is not a git repository"
            raise GitError(msg, cwd=str(repo))
        common = named_from(git_dir, "commondir") if (git_dir / "commondir").is_file() else git_dir
    except OSError as exc:
        msg = "the repository's git files could not be read"
        raise GitError(msg, cwd=str(repo), reason=str(exc)) from None
    return GitDir(path=git_dir, common=common)


def object_dirs(where: GitDir) -> tuple[str, ...]:
    """The object directories of the git directory ``where``: its own and its common one's.

    A worktree's objects live in the repository's common directory. A repository may name more
    in ``objects/info/alternates``, and those are not read here: the clean store that reaches
    these directories through its own alternates follows theirs as git does, with git's own
    reading of the file (comments, quoting, a relative entry taken against the object
    directory that names it, and git's depth limit). Measured on 2.54: an object present only
    in an alternate named by a relative entry is read through the store.

    Raises:
        GitError: neither directory holds an object store.
    """
    found: list[str] = []
    for objects in (where.path / "objects", where.common / "objects"):
        resolved = str(objects.resolve())
        if objects.is_dir() and resolved not in found:
            found.append(resolved)
    if not found:
        msg = "the repository holds no object store"
        raise GitError(msg, cwd=str(where.path))
    return tuple(found)


def _object_dirs(repo: Path, pinned: GitDir | None = None) -> tuple[str, ...]:
    """:func:`object_dirs` of ``pinned``, or of the repository's ``.git`` read here, unchecked."""
    return object_dirs(pinned if pinned is not None else _git_dir(repo))


_STORES: list[str] = []


@atexit.register
def _remove_stores() -> None:
    for store in _STORES:
        shutil.rmtree(store, ignore_errors=True)


def _config_get(config: Path, key: str, *, as_int: bool = False) -> str | None:
    """One key of a config file, as git's own parser reads it, or ``None`` if it is absent.

    Read as data, by git run outside the repository with ``--file`` (includes off), so nothing
    in that config is applied and no git command runs with the repository as its working or git
    directory. ``as_int`` has git read the value as the integer it would use (``1k`` is 1024).

    Raises:
        GitError: git cannot read the file or the value.
    """
    # git runs from ``/``, so it is handed the file's absolute path: the one checked here.
    # git exits 1 without a word for a file that is not there, as for a key that is not, so
    # a missing file is refused here, never read as a key that is absent.
    resolved = Path(config).resolve()
    if not resolved.is_file():
        msg = "the repository has no config file to read"
        raise GitError(msg, config=str(resolved), key=key)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    kind = ["--type=int"] if as_int else []
    done = subprocess.run(
        [harness_git().path, attr_source(), *_FLAGS, "config", "--file", str(resolved),
         "--no-includes", *kind, "--get", key],
        cwd="/",
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    if done.returncode == 1 and not done.stderr.strip():  # the key is absent
        return None
    if done.returncode != 0:
        msg = "the repository's config cannot be read"
        raise GitError(
            msg, config=str(config), key=key, exit=str(done.returncode),
            stderr=done.stderr.strip()[-400:],
        )  # fmt: skip
    return done.stdout.strip()


def object_format(where: GitDir) -> str:
    """The hash the repository names its objects with (``sha1`` or ``sha256``), as git decides it.

    The clean store must use the same one: a store of the other format cannot read a single
    object through its alternates. Read from the common directory's config by git's own config
    parser (:func:`_config_get`). git honours ``extensions.objectformat`` only in a repository
    of format version 1, refuses one of version 0 that names it, and refuses every version
    above 1 (measured on 2.54); the same holds here, so the harness never reads a repository
    git itself would refuse. A repository that names no format is SHA-1, git's default.

    Raises:
        GitError: the config cannot be read, git would refuse the repository, or it names a
            format this module does not know.
    """
    config = where.common / "config"
    version = _config_get(config, "core.repositoryformatversion", as_int=True)
    found = _config_get(config, "extensions.objectformat")
    if version not in (None, "0", "1"):
        msg = "the repository's format version is one git refuses"
        raise GitError(msg, cwd=str(where.path), version=str(version)[:40])
    if found is None:
        return "sha1"
    if version != "1":
        msg = "the repository names an object format at a format version git refuses it at"
        raise GitError(msg, cwd=str(where.path), version=str(version))
    if found not in EMPTY_TREES:
        msg = "the repository's object format cannot be read, or the clean store cannot use it"
        raise GitError(msg, cwd=str(where.path), object_format=found[:40])
    return found


def _object_format(repo: Path, pinned: GitDir | None = None) -> str:
    """:func:`object_format` of ``pinned``, or of the repository's ``.git`` read here, unchecked."""
    return object_format(pinned if pinned is not None else _git_dir(repo))


@functools.cache
def _object_store(object_dirs: tuple[str, ...], object_format: str) -> str:
    """A throwaway bare git directory reaching ``object_dirs`` through alternates, nothing else.

    A content read (a diff of two commits) runs against this instead of inside the repository,
    so the repository's own config, its ``.gitattributes``, its ``include`` paths and any
    submodule's config are never applied and can run nothing, and a committed submodule is
    shown as its gitlink rather than recursed into. The config is read only as data, for the
    ``object_format`` the store is created with, so a SHA-256 repository is read as readily as
    a SHA-1 one.
    """
    store = tempfile.mkdtemp(prefix="physgate-git-store-")
    _STORES.append(store)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.devnull,
        **_ENV,
        "GIT_ATTR_SOURCE": EMPTY_TREES[object_format],
    }
    done = subprocess.run(
        [
            harness_git().path,
            attr_source(object_format),
            *_FLAGS,
            "init",
            "-q",
            "--bare",
            f"--object-format={object_format}",
            store,
        ],
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
    cwd: Path,
    *args: str,
    check: bool = True,
    stdin: str | None = None,
    objects_only: bool = False,
    git_dir: GitDir | None = None,
    errors: str = "strict",
) -> str:
    """Run one git command in ``cwd`` and return its standard output.

    The output is decoded as UTF-8 with ``errors`` as :meth:`bytes.decode` takes it: strict by
    default, so bytes that are not UTF-8 raise where the caller did not say how to read them.

    With ``objects_only`` the command runs against a clean object store that reaches ``cwd``'s
    objects but holds none of its config, attributes or submodules: used for content reads (a
    diff of two commits), so a role-written repository cannot make the read run a program.

    With ``git_dir`` the command is pinned to that git directory (``--git-dir``) and to ``cwd``
    as its work tree (``--work-tree``), both resolved by the caller. git then never re-reads
    the worktree's ``.git`` pointer, so a pointer a role swapped between a check and here cannot
    redirect the command (the write path pins the admin directory :func:`verify_worktree_pointer`
    resolved). With both, the clean store is built from that git directory's object directories,
    and the pointer is not read again for it either.

    Raises:
        GitError: it exited non-zero and ``check`` is true.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    exe = harness_git().path
    if objects_only:
        object_format = _object_format(Path(cwd), git_dir)
        store = _object_store(_object_dirs(Path(cwd), git_dir), object_format)
        env["GIT_ATTR_SOURCE"] = EMPTY_TREES[object_format]
        argv = [exe, attr_source(object_format), "--git-dir", store, *_FLAGS, *args]
        run_in: Path | str = store
    elif git_dir is not None:
        argv = [exe, attr_source(), "--git-dir", str(git_dir.path), "--work-tree", str(cwd)]
        argv += _FLAGS
        argv += args
        run_in = cwd
    else:
        argv = [exe, attr_source(), *_FLAGS, *args]
        run_in = cwd
    done = subprocess.run(
        argv,
        cwd=run_in,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors=errors,
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


def git_timed(
    cwd: Path, *args: str, timeout: float, git_dir: GitDir | None = None
) -> tuple[int | None, str, float]:
    """Run one git command with a time limit: (exit code or None on timeout, stderr, seconds).

    Never raises for a failure or a timeout: the caller records what happened. ``git_dir``
    pins the command as it does for :func:`git`.

    Raises:
        GitError: no git at 2.42 or later is found, so there is no git to run.
    """
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.devnull, **_ENV}
    exe = harness_git().path
    pin = [] if git_dir is None else ["--git-dir", str(git_dir.path), "--work-tree", str(cwd)]
    started = time.monotonic()
    try:
        done = subprocess.run(
            [exe, attr_source(), *pin, *_FLAGS, *args],
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


def verify_worktree_pointer(
    cwd: Path, *, common: Path | None = None, repository: bool = False
) -> Path | None:
    """The verified admin directory of a linked worktree at ``cwd``, or ``None`` for a plain repo.

    Fail closed unless a linked worktree's ``.git`` names a real git admin directory of the
    repository it belongs to.

    A role session owns its worktree. If it rewrote the worktree's ``.git`` pointer file to
    name a directory it controls, the orchestrator's next commit or merge, run with its working
    directory here, would take that directory's config — a filter, a hook — as git's own and
    run a program. The pointer file is a protected root, so a tool write to it is refused and a
    shell write is put back; this is the second check, called immediately before the
    orchestrator stages, commits or merges in a live worktree (:func:`commit_all` and the
    merger): the pointer must name an admin directory that is a git worktree's, or it fails.

    An admin directory is a git worktree's when:

    - it has a ``gitdir`` back-pointer resolving to this very ``.git``;
    - it has a ``commondir`` resolving to the directory the admin directory sits in, as git
      lays it out (``<common>/worktrees/<name>``). ``commondir`` names the directory whose
      config, hooks, refs and objects git uses for the worktree, so one naming any other
      directory would hand git a configuration the harness never checked;
    - with ``common`` given, that common directory is ``common``: the repository the caller
      made the worktree in, so an admin directory laid out like git's in another repository
      is refused too.

    ``repository`` says ``cwd`` is a repository's own checkout rather than a worktree the
    harness made; only the wording of a refusal depends on it.

    It guards a write, not a read: an observability command reading a run that was copied or
    moved sees stale absolute pointers git itself follows, and must not be refused for them.
    A repository whose ``.git`` is an ordinary directory (not a linked worktree) is left alone.
    It fails closed: anything it cannot read or parse refuses the command, and it compares
    paths only after resolving them, never as raw or prefixed strings. Each file is read as git
    reads it (``gitdir: `` with its space, only trailing CR and LF removed, a relative path taken
    against the directory holding the file), and a path git could read another way is refused.
    """
    dot = Path(cwd) / ".git"
    try:
        is_pointer = dot.is_file()
    except OSError as exc:
        msg = "a worktree's .git could not be examined"
        raise GitError(msg, cwd=str(cwd), reason=str(exc)) from None
    if not is_pointer:
        # An ordinary git directory, or no .git at all: not a linked worktree to validate. A
        # directory is a git dir; its absence lets git report "not a repository" on its own.
        return None
    try:
        admin = _pointer_target(Path(cwd))
        has_admin = (admin / "commondir").is_file() and (admin / "gitdir").is_file()
        back = named_from(admin, "gitdir") if has_admin else None
        found = named_from(admin, "commondir") if has_admin else None
    except OSError as exc:
        msg = "a worktree's .git or its admin directory could not be read"
        raise GitError(msg, cwd=str(cwd), reason=str(exc)) from None
    if not has_admin or back is None or found is None:
        msg = (
            "the repository's .git is not a directory the harness made or a verified worktree "
            "pointer"
            if repository
            else "a worktree's .git points at no git worktree admin directory"
        )
        raise GitError(msg, cwd=str(cwd), admin=str(admin))
    if back != dot.resolve():
        msg = "a worktree's .git and its admin directory disagree"
        raise GitError(msg, cwd=str(cwd), admin=str(admin))
    if admin.parent.name != "worktrees" or found != admin.parent.parent:
        msg = "a worktree's admin directory names another common git directory than its own"
        raise GitError(msg, cwd=str(cwd), admin=str(admin), commondir=str(found)[:200])
    if common is not None and found != Path(common).resolve():
        msg = "a worktree's admin directory belongs to another repository than the expected one"
        raise GitError(msg, cwd=str(cwd), admin=str(admin), expected=str(common))
    return admin


def verified_git_dir(cwd: Path, *, linked: bool, common: Path | None = None) -> GitDir:
    """The git directory every command the harness runs in ``cwd`` is pinned to, or a refusal.

    :func:`verify_worktree_pointer` checks a ``.git`` pointer file and leaves anything else
    alone. Used on its own before a write, that let git choose: with no ``.git`` at all git
    looks in the parent directories and commits into whichever repository it finds there, and
    with a directory, or a link to one, it uses that directory as the repository. Here only a
    git directory confirmed now is returned, and the caller pins every command to it:

    - a ``.git`` pointer that :func:`verify_worktree_pointer` accepts: its admin directory;
    - unless ``linked``, a ``.git`` that is a real directory (no link) holding ``HEAD`` and
      ``objects`` and no ``commondir``: that directory, as for a repository's main worktree.
      git follows a ``commondir`` file in any git directory, and a main worktree's has none.

    ``linked`` is for a worktree the harness made with ``git worktree add``, whose ``.git`` is
    always a pointer file, so a directory there is refused too. Such a worktree is verified
    against ``common``, the common git directory of the repository it was made in
    (:func:`common_dir`), which the caller must give.

    Returned with the common directory the check confirmed: for a worktree, the directory its
    admin directory sits in, which its ``commondir`` was found to name; for a repository's own
    git directory, that directory. Readers take it from here and never read ``commondir`` again.

    Raises:
        GitError: nothing above was found; the command must not run.
    """
    if linked and common is None:
        msg = "a worktree the harness made is verified against its repository, and none was named"
        raise GitError(msg, cwd=str(cwd))
    dot = Path(cwd) / ".git"
    try:
        is_link = dot.is_symlink()
        is_dir = dot.is_dir()
        holds_git = is_dir and (dot / "HEAD").is_file() and (dot / "objects").is_dir()
        redirected = is_dir and os.path.lexists(dot / "commondir")
    except OSError as exc:
        msg = "a worktree's .git could not be examined"
        raise GitError(msg, cwd=str(cwd), reason=str(exc)) from None
    if is_link:
        msg = "a worktree's .git is a link, so git would use whatever it names"
        raise GitError(msg, cwd=str(cwd))
    admin = verify_worktree_pointer(cwd, common=common, repository=not linked)
    if admin is not None:
        return GitDir(path=admin, common=admin.parent.parent)
    if linked and is_dir:
        msg = "a worktree the harness made has a git directory in place of its .git pointer"
        raise GitError(msg, cwd=str(cwd))
    if not holds_git:
        msg = "the path has no .git the harness can verify, so git would look for one elsewhere"
        raise GitError(msg, cwd=str(cwd))
    if redirected:
        msg = "a repository's git directory names a common directory elsewhere (commondir)"
        raise GitError(msg, cwd=str(cwd))
    resolved = dot.resolve()
    return GitDir(path=resolved, common=resolved)


def head_of(repo: Path, ref: str, *, git_dir: GitDir | None = None) -> str:
    """The commit ``ref`` points at, as a full SHA; ``git_dir`` pins it as for :func:`git`."""
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", git_dir=git_dir).strip()


def common_dir(repo: Path) -> Path:
    """The common git directory of ``repo``: where its config, hooks, refs and objects are.

    Read from the filesystem through :func:`verified_git_dir`, the check every write runs, never
    by asking git inside the repository, which would follow whatever ``.git`` and ``commondir``
    say now. For an ordinary repository it is the repository's own ``.git`` directory; for a
    repository that is itself a linked worktree it is the directory that worktree's admin
    directory sits in, which the check has confirmed its ``commondir`` names.

    Raises:
        GitError: the repository's git directory does not verify.
    """
    return verified_git_dir(repo, linked=False).common


def branch_exists(repo: Path, branch: str, *, git_dir: GitDir | None = None) -> bool:
    """Whether ``refs/heads/<branch>`` exists; ``git_dir`` pins it as for :func:`git`."""
    return bool(git(repo, "branch", "--list", branch, git_dir=git_dir).strip())


def add_worktree(repo: Path, path: Path, branch: str, start: str) -> None:
    """Check ``branch`` out at ``path``, creating the branch at ``start`` if it is new.

    An existing worktree at ``path`` on ``branch`` is kept as it is: a repair
    attempt continues in the worktree the rejected attempt left. That worktree is one a
    session ran in, so its pointer is verified and its branch read through the verified
    admin directory, as a commit there is; the repository's own git directory likewise.
    """
    if path.exists():
        admin = verified_git_dir(path, linked=True, common=common_dir(repo))
        current = git(path, "rev-parse", "--abbrev-ref", "HEAD", git_dir=admin).strip()
        if current != branch:
            msg = "a worktree exists at the path on another branch"
            raise GitError(msg, path=str(path), branch=current, expected=branch)
        worktree_config_files(admin)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pinned = verified_git_dir(repo, linked=False)
    if branch_exists(repo, branch, git_dir=pinned):
        git(repo, "worktree", "add", "--quiet", str(path), branch, git_dir=pinned)
    else:
        git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), start, git_dir=pinned)
    worktree_config_files(verified_git_dir(path, linked=True, common=pinned.common))


#: The per-worktree configuration file git reads only with ``extensions.worktreeConfig`` set.
WORKTREE_CONFIG = "config.worktree"


def worktree_config_files(admin: GitDir) -> None:
    """Make the common directory's and this worktree's ``config.worktree``, empty, if absent.

    Claude Code's Linux sandbox makes these files itself, empty, the first time a session
    runs in a linked worktree (measured on 2.1.301), in the protected git directory a
    session must not change. Made here first, by the harness, they are part of what every
    session's record holds from its start, so the sandbox finds them and makes nothing, and
    a session that changes one is still caught. An empty file configures nothing, and git
    reads none at all while ``extensions.worktreeConfig`` is unset.
    """
    for directory in (admin.common, admin.path):
        target = directory / WORKTREE_CONFIG
        if os.path.lexists(target):
            continue
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        os.close(os.open(target, flags, 0o644))


def nested_git(worktree: Path) -> Path | None:
    """The first ``.git`` below ``worktree``'s top level, of any kind, or ``None``.

    Read from the filesystem, never following a link. ``git add --all`` opens a nested
    repository to stage it as a submodule, and reads that repository's config to do it; a
    session's worktree is the session's to write, so a nested ``.git`` there is a configuration
    the harness never checked. The worktree's own ``.git`` at its top level is not looked into.

    The question asked of each directory is the one git asks: does ``<directory>/.git`` exist.
    git asks it of every subdirectory in its parent's listing, which needs only the right to
    pass through the subdirectory, not to list it; so it is asked here the same way, from the
    parent. On a case-insensitive volume ``.GIT`` or ``.Git`` answers it as ``.git`` does (git
    opens such a directory as a repository), so no spelling is compared. A symbolic link is
    not looked through: git stages it as a link. A directory the harness cannot list refuses
    the commit: what lies below it cannot be checked, and git may still reach it.

    Raises:
        GitError: a directory in the worktree cannot be listed.
    """
    top = Path(worktree)
    own = os.lstat(top / ".git") if os.path.lexists(top / ".git") else None

    def unlistable(error: OSError) -> None:
        msg = "a directory in the worktree cannot be listed, so what it holds cannot be checked"
        raise GitError(msg, cwd=str(top), path=str(error.filename))

    for directory, names, _files in os.walk(top, onerror=unlistable):
        here = Path(directory)
        if here == top and own is not None:
            # The worktree's own .git, under whichever spelling the listing gives it.
            names[:] = [n for n in names if not os.path.samestat(os.lstat(here / n), own)]
        for name in names:
            child = here / name
            if not child.is_symlink() and os.path.lexists(child / ".git"):
                return child / ".git"
    return None


def commit_all(
    worktree: Path, message: str, *, linked: bool = False, common: Path | None = None
) -> str:
    """Stage everything in ``worktree`` and commit it, even if nothing changed.

    Empty commits are allowed on purpose: an attempt that changed nothing still
    has a commit, so it can be judged and named like any other.

    The staging and the commit are where a worktree's git directory, if a session had
    repointed the worktree's ``.git`` at one it controls, would run that directory's config,
    so the pointer is verified here, immediately before, and the commit fails closed if it
    does not name a real git worktree admin whose back-pointer resolves to this worktree.
    ``linked`` says the worktree is one the harness made, so it must have that pointer, into the
    repository whose common git directory is ``common``; a repository's own ``.git`` directory
    is accepted otherwise. Anything else refuses (:func:`verified_git_dir`): git is never left
    to find a repository of its own. A worktree holding a repository of its own below its top
    level (:func:`nested_git`) is refused before anything is staged.
    """
    admin = verified_git_dir(worktree, linked=linked, common=common)
    nested = nested_git(worktree)
    if nested is not None:
        msg = "the worktree holds a git repository of its own, which staging would open"
        raise GitError(msg, cwd=str(worktree), path=str(nested))
    git(worktree, "add", "--all", git_dir=admin)
    git(worktree, "commit", "--quiet", "--allow-empty", "--file", "-", stdin=message, git_dir=admin)
    return git(worktree, "rev-parse", "--verify", "HEAD^{commit}", git_dir=admin).strip()


@dataclass(frozen=True)
class Change:
    """One path an attempt changed, with its old and new git modes."""

    status: str
    path: str
    old_mode: str
    new_mode: str


def changes_between(
    repo: Path, base: str, commit: str, *, git_dir: GitDir | None = None
) -> list[Change]:
    """Every path changed from ``base`` to ``commit``, renames split in two.

    Read in the clean store, built from ``git_dir`` when the caller verified one. A path is
    whatever bytes the commit names, which a session can choose: one that is not UTF-8 is
    decoded with its bytes kept as lone surrogates (:func:`utf8_name` tells), so reading the
    list never raises and the write-scope check refuses the path before anything records it.
    """
    raw = git(
        repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, commit,
        objects_only=True, git_dir=git_dir, errors="surrogateescape",
    )  # fmt: skip
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


def utf8_name(path: str) -> str | None:
    """``None`` for a path that is UTF-8 as committed; otherwise the path, escaped as ASCII."""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return path.encode("utf-8", "surrogateescape").decode("ascii", "backslashreplace")
    return None


def merge_base(repo: Path, one: str, other: str, *, git_dir: GitDir | None = None) -> str:
    """The best common ancestor of two commits.

    Each name is resolved to its commit in the repository (pinned to ``git_dir``), the only
    place refs are; the ancestry is then walked in the clean store, which holds none of the
    repository's ``shallow``, graft or commit-graph files, so the base is the one the commits'
    own parents give.
    """
    ends = [head_of(repo, name, git_dir=git_dir) for name in (one, other)]
    return git(repo, "merge-base", *ends, objects_only=True, git_dir=git_dir).strip()


def diff_text(repo: Path, base: str, commit: str, *, git_dir: GitDir | None = None) -> str:
    """The patch from ``base`` to ``commit``, for a person to read.

    A file git takes as text may hold bytes that are not UTF-8: each such byte reads as the
    replacement character, the same on every read, so an item rebuilt from it compares equal.
    """
    return git(
        repo, "diff", *_DIFF_FLAGS, base, commit,
        objects_only=True, git_dir=git_dir, errors="replace",
    )  # fmt: skip


def merges_of(
    repo: Path, branch: str, since: str, *, git_dir: GitDir | None = None
) -> dict[str, str]:
    """Second parent to merge commit, for every merge on ``branch`` after ``since``.

    Both names are resolved in the repository (pinned to ``git_dir``) and the history between
    them is read in the clean store, as for :func:`merge_base`: a merge the repository's files
    made look parentless would otherwise be missed, and merged a second time.
    """
    tip = head_of(repo, branch, git_dir=git_dir)
    start = head_of(repo, since, git_dir=git_dir)
    out = git(
        repo, "log", "--merges", "--format=%H %P", f"{start}..{tip}",
        objects_only=True, git_dir=git_dir,
    )  # fmt: skip
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
