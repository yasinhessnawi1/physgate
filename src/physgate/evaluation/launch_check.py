"""The machine's state a measured round may be launched on, as one check a launch script calls.

A measured session reads every place no rule names (the OS layer allows each read it is not told
to deny; an allow-list for reads is not built, and that is a stated limit, the same in every arm).
So what lies in those places is a launch condition, checked here and printed by name:

- **no other run's material is readable** where a measured session may read: a directory that
  holds a run's, a raw trial's, a decomposition's, a round's or a review's own record, beneath
  the operator's home, the store outside its roles' roots or the machine's other places a session
  reads, and not beneath a place every measured session is refused (each role's root in the
  store, its registered run roots, the standing review root, the harness's and the sessions'
  temporary directories, the shared temporary ones); a folder the walk cannot list is named as
  not established;
- **the repository the trials are cloned from holds only what a trial may see**: one branch,
  no other reference (no tag, remote branch, stash or note), no linked worktree, and no object
  that branch does not reach, where an earlier run's work could lie; and, since every session
  reads the source's own directory too, not only what a clone of it holds, no file there that git
  does not track or ignores, and no tracked file changed from what the branch holds (counted by
  kind, never named);
- **no run that does not withhold the run roots is left beneath them**: a run's own sessions
  read whatever its run withholds not, and a run beneath the roots that withholds them not
  reads every measured run's material there.

Each finding is one line naming its kind and its place; the check never reads a record's content
but the run configuration's ``withheld_whole`` field, and never follows a link while it walks.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

#: The record files whose directory is a run's material: a harness run's configuration, a raw
#: trial's record, a decomposition's parameters, a harness round's and a baseline round's
#: records, and a review root's own record.
MATERIAL_NAMES = frozenset(
    {
        "run.json",
        "raw.json",
        "params_source.json",
        "round.json",
        "baseline.json",
        "review_root.json",
    }
)
#: How many entries the walk reads in all: past it the places are not established, which is a
#: finding of its own. A walk goes as deep as a place does.
MAX_ENTRIES = 2_000_000
#: Directories a walk does not enter: a package tree or a repository's object store holds no
#: run's records, and each holds more entries than everything else together.
NOT_ENTERED = frozenset({"node_modules", ".git", "__pycache__", ".venv", "site-packages"})
#: The machine's places beside the operator's home that every session reads and that hold what
#: other processes leave: ``/var/tmp`` (the shared temporary directories are refused to sessions).
MACHINE_PLACES: tuple[Path, ...] = (Path("/var/tmp"),)


@dataclass(frozen=True)
class Finding:
    """One thing the check found, by kind and place."""

    kind: str
    place: str
    detail: str = ""

    def line(self) -> str:
        """The finding as the check prints it."""
        tail = f": {self.detail}" if self.detail else ""
        return f"finding: {self.kind}: {self.place}{tail}"


def _under(path: str, roots: Iterable[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def _walk(
    top: str, refused: Sequence[str], budget: list[int]
) -> Iterator[tuple[str, tuple[str, ...] | None]]:
    """Each directory beneath ``top`` holding a material record, with every such record's name.

    Yields ``(top, None)`` once where the walk was cut short (its entries), and ``(directory,
    ())`` for each directory it cannot list: what lies there is not established. Never follows a
    link; never enters a refused place, nor a directory that holds a record (a run's own tree).
    """
    stack = [top]
    while stack:
        directory = stack.pop()
        if _under(os.path.realpath(directory), refused):
            continue
        try:
            entries = list(os.scandir(directory))
        except OSError:
            yield directory, ()
            continue
        budget[0] -= len(entries)
        if budget[0] < 0:
            yield top, None
            return
        names = {e.name for e in entries}
        held = tuple(sorted(names & MATERIAL_NAMES))
        if held:
            yield directory, held
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode) or entry.name in NOT_ENTERED:
                continue
            stack.append(entry.path)


def material_findings(places: Sequence[Path], refused: Sequence[Path]) -> list[Finding]:
    """Run material found beneath ``places``, outside every ``refused`` place."""
    real_refused = [os.path.realpath(p) for p in refused]
    found: list[Finding] = []
    budget = [MAX_ENTRIES]
    for place in places:
        if not place.is_dir():
            continue
        for directory, names in _walk(str(place), real_refused, budget):
            if names is None:
                found.append(
                    Finding("not_established", str(place), "the walk was cut short, too large")
                )
            elif not names:
                found.append(
                    Finding("not_established", directory, "it cannot be listed by this user")
                )
            else:
                held = ", ".join(names)
                found.append(Finding("run_material_readable", directory, f"it holds {held}"))
    return found


#: How many entries of the source's own directory the check reads before it stops, said.
MAX_SOURCE_ENTRIES = 200_000
_HEX = frozenset("0123456789abcdef")


class _UnreadableError(Exception):
    """The source's git directory holds something the check does not read as git writes it."""


def _oid(text: str) -> str | None:
    word = text.strip()
    return word if len(word) in (40, 64) and set(word) <= _HEX else None


def _refs(git_dir: Path) -> dict[str, str]:
    """Every reference of the source, by name: its loose ones and its packed ones, read as data.

    Read without git, so nothing of the repository's configuration is ever applied: each loose
    reference a plain file beneath ``refs`` (no link followed) holding an object id or naming
    another reference, and ``packed-refs`` line by line. A symbolic reference is resolved to the
    id it names, or left out where it names none.

    Raises:
        _UnreadableError: a reference git could write cannot be read as one (a reference table, a
            link, a file that holds neither an id nor a name).
    """
    if os.path.lexists(git_dir / "reftable"):
        msg = "its references are kept in a table"
        raise _UnreadableError(msg)
    loose: dict[str, str] = {}
    stack = [git_dir / "refs"]
    while stack:
        here = stack.pop()
        try:
            entries = list(os.scandir(here))
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _UnreadableError(str(exc.strerror)) from None
        for entry in entries:
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                stack.append(Path(entry.path))
            elif stat.S_ISREG(st.st_mode):
                loose[Path(entry.path).relative_to(git_dir).as_posix()] = (
                    Path(entry.path).read_text(errors="replace").strip()
                )
            else:
                msg = "a reference is a link or no file"
                raise _UnreadableError(msg)
    refs: dict[str, str] = {}
    packed = git_dir / "packed-refs"
    if packed.is_symlink():
        msg = "packed-refs is a link"
        raise _UnreadableError(msg)
    if packed.is_file():
        for line in packed.read_text(errors="replace").splitlines():
            if not line or line.startswith(("#", "^")):
                continue
            oid, _, name = line.partition(" ")
            if _oid(oid) is None or not name:
                msg = "packed-refs holds a line that is no reference"
                raise _UnreadableError(msg)
            refs[name] = oid
    for name, text in loose.items():
        if _oid(text) is not None or text.startswith("ref: "):
            refs[name] = text
        else:
            msg = "a reference holds neither an id nor a name"
            raise _UnreadableError(msg)
    for name, text in list(refs.items()):
        if text.startswith("ref: "):
            target = refs.get(text[5:].strip())
            if target is None or _oid(target) is None:
                del refs[name]
            else:
                refs[name] = target
    return refs


def _head(git_dir: Path, refs: dict[str, str]) -> str | None:
    """The commit the source's own directory was checked out from, read as data; ``None``."""
    try:
        text = (git_dir / "HEAD").read_text(errors="replace").strip()
    except OSError:
        return None
    if text.startswith("ref: "):
        return refs.get(text[5:].strip())
    return _oid(text)


def _blob_id(data: bytes, width: int) -> str:
    """The id git gives a blob of ``data``, in the object format whose ids are ``width`` long."""
    digest = hashlib.sha1 if width == 40 else hashlib.sha256  # noqa: S324 - git's own object id
    return digest(b"blob %d\0" % len(data) + data).hexdigest()


def _as_written(path: str, st: os.stat_result) -> tuple[str, bytes] | None:
    """A working file as git would store it: its mode and its bytes; ``None`` for anything else."""
    if stat.S_ISLNK(st.st_mode):
        return "120000", os.fsencode(os.readlink(path))
    if not stat.S_ISREG(st.st_mode):
        return None
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read()
    return ("100755" if st.st_mode & stat.S_IXUSR else "100644"), data


def _working_files(source: Path, head: str) -> list[Finding]:
    """The source's own directory beside what its branch holds: counted by kind, never named.

    No git command runs on the source for it, so nothing the repository names (a file-system
    monitor, a filter or diff driver its attributes or configuration select, a hook, a
    submodule's configuration) can run: the branch's tree is listed in a clean store that holds
    the source's objects and none of its configuration (``objects_only``), and every file of the
    directory is read and hashed here, as git hashes a blob, its mode compared too. What the
    tree does not hold, ignored or not, is counted; so is each tracked file changed or gone. A
    submodule's directory is not entered.
    """
    from physgate.orchestrator.exceptions import GitError
    from physgate.orchestrator.git import git

    try:
        listed = git(
            source, "ls-tree", "-r", "-z", "--full-tree", head, objects_only=True,
            errors="surrogateescape",
        )  # fmt: skip
    except GitError:
        return [Finding("source_unreadable", str(source), "its branch's tree cannot be read")]
    tracked: dict[str, tuple[str, str]] = {}
    gitlinks: set[str] = set()
    for line in filter(None, listed.split("\0")):
        meta, _, name = line.partition("\t")
        mode, _kind, oid = meta.split(" ")
        if mode == "160000":
            gitlinks.add(name)
        else:
            tracked[name] = (mode, oid)
    untracked = changed = seen = 0
    present: set[str] = set()
    stack = [""]
    while stack:
        rel = stack.pop()
        here = os.path.join(str(source), rel) if rel else str(source)
        try:
            entries = list(os.scandir(here))
        except OSError:
            return [Finding("not_established", here, "it cannot be listed by this user")]
        seen += len(entries)
        if seen > MAX_SOURCE_ENTRIES:
            return [Finding("not_established", str(source), "its directory holds too many files")]
        for entry in entries:
            name = f"{rel}/{entry.name}" if rel else entry.name
            if name == ".git" or name in gitlinks:
                continue
            st = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                stack.append(name)
                continue
            present.add(name)
            if name not in tracked:
                untracked += 1
                continue
            written = _as_written(entry.path, st)
            mode, oid = tracked[name]
            if written is None or written[0] != mode or _blob_id(written[1], len(oid)) != oid:
                changed += 1
    changed += len(set(tracked) - present)
    said = [
        _counted(untracked, NOT_HELD) if untracked else "",
        _counted(changed, CHANGED) if changed else "",
        # Its own repository, with its own configuration: never read here, so said.
        f"{len(gitlinks)} {SUBMODULES}" if gitlinks else "",
    ]
    if not any(said):
        return []
    detail = ", ".join(w for w in said if w) + " (a session reads the source's directory itself)"
    return [Finding("source_files", str(source), detail)]


#: How a ``source_files`` finding says each kind of thing the source's directory holds beside
#: its branch's commit: files the branch does not hold (ignored ones among them), files it holds
#: that changed or are gone (a change a clean filter would normalise among them), submodules.
NOT_HELD = "the branch does not hold"
CHANGED = "the branch holds, changed or gone"
SUBMODULES = "submodule(s), whose directories are not looked at"


#: What in a git directory makes git read references or objects from somewhere else, which the
#: check does not follow: a source that holds one is refused as unread, by its kind.
INDIRECTIONS = ("commondir", "objects/info/alternates", "objects/info/http-alternates")


def _own_git_dir(source: Path) -> tuple[Path | None, list[Finding]]:
    """The source's git directory, where it holds its references and objects itself; or why not.

    Read as git would read it only where git reads nothing from elsewhere: a ``.git`` that is a
    directory of its own (no pointer file, no link), with no file sending git to a common
    directory or to another object store, no reference table, and ``refs`` and ``packed-refs``
    no link. Anywhere else the check and git could disagree about what the source holds, so it
    is refused (``source_indirect``): in doubt the check says it could not read the source.
    """
    git_dir = source / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        why = "its .git is no directory of its own (a pointer file or a link)"
        return None, [Finding("source_indirect", str(source), why)]
    for name in (*INDIRECTIONS, "reftable"):
        if os.path.lexists(git_dir / name):
            why = f"its git directory holds {name}, which sends git elsewhere"
            return None, [Finding("source_indirect", str(source), why)]
    for name in ("refs", "packed-refs", "HEAD", "objects"):
        if (git_dir / name).is_symlink():
            return None, [Finding("source_indirect", str(source), f"its {name} is a link")]
    return git_dir, []


def source_state(source: Path) -> tuple[str | None, list[Finding]]:
    """The commit the source is checked out at, and what its own directory holds beside it.

    Read as :func:`source_findings` reads them, with no git command run in the source: the
    commit from its references as data (``None`` where it has none to read), its directory hashed
    here (:func:`_working_files`). For a caller that needs the source as one commit, as it is.
    """
    git_dir, refused = _own_git_dir(source)
    if git_dir is None:
        return None, refused
    try:
        head = _head(git_dir, _refs(git_dir))
    except (_UnreadableError, OSError) as exc:
        return None, [Finding("source_unreadable", str(source), f"its references: {exc}")]
    if head is None:
        return None, [Finding("source_unreadable", str(source), "it is checked out at nothing")]
    return head, _working_files(source, head)


def source_findings(source: Path) -> list[Finding]:
    """What the repository the trials are cloned from holds beyond one branch's own work.

    No git command runs in the source itself: its configuration, attributes and hooks are files a
    session may have written. Its references and linked worktrees are read as data from its git
    directory; its objects are walked in a clean store that holds none of its configuration
    (:func:`~physgate.orchestrator.git.unreachable_from`); its own directory is hashed here
    (:func:`_working_files`).
    """
    from physgate.orchestrator.exceptions import GitError
    from physgate.orchestrator.git import unreachable_from

    git_dir, refused = _own_git_dir(source)
    if git_dir is None:
        return refused
    try:
        refs = _refs(git_dir)
    except (_UnreadableError, OSError) as exc:
        return [Finding("source_unreadable", str(source), f"its references cannot be read: {exc}")]
    found: list[Finding] = []
    branches = [(name, oid) for name, oid in sorted(refs.items()) if name.startswith("refs/heads/")]
    if len(branches) != 1:
        found.append(
            Finding("source_branches", str(source), f"{len(branches)} branches, where one is all")
        )
    for name in sorted(refs):
        if not name.startswith("refs/heads/"):
            found.append(Finding("source_reference", str(source), f"it holds {name}"))
    try:
        linked = [e for e in os.scandir(git_dir / "worktrees") if e.is_dir(follow_symlinks=False)]
    except FileNotFoundError:
        linked = []
    except OSError:
        found.append(Finding("source_unreadable", str(source), "its worktrees cannot be listed"))
        linked = []
    if linked:
        found.append(Finding("source_worktrees", str(source), f"{len(linked)} linked worktrees"))
    head = _head(git_dir, refs)
    if head is None:
        found.append(
            Finding("source_unreadable", str(source), "what it is checked out at is unread")
        )
    else:
        found += _working_files(source, head)
    if branches:
        try:
            loose = unreachable_from(source, [oid for _, oid in sorted(refs.items())])
        except GitError:
            found.append(Finding("source_unreadable", str(source), "its objects cannot be walked"))
        else:
            if loose:
                found.append(
                    Finding(
                        "source_objects",
                        str(source),
                        f"{len(loose)} objects no reference reaches (an earlier run's work can be "
                        "among them)",
                    )
                )
    return found


def _counted(n: int, what: str) -> str:
    return f"{n} {'file' if n == 1 else 'files'} {what}"


def withholding_findings(run_roots: Sequence[Path], registered: set[str]) -> list[Finding]:
    """Each run beneath the run roots whose configuration does not withhold every one of them."""
    from physgate.orchestrator.exceptions import OrchestratorError
    from physgate.orchestrator.run_config import load_run_config

    found: list[Finding] = []
    budget = [MAX_ENTRIES]
    for root in run_roots:
        if not root.is_dir():
            continue
        for directory, names in _walk(str(root), (), budget):
            if names is None:
                found.append(Finding("not_established", str(root), "the walk was cut short"))
                continue
            if not names:
                found.append(Finding("not_established", directory, "it cannot be listed"))
                continue
            if "run.json" not in names:
                continue
            try:
                config = load_run_config(Path(directory) / "run.json")
            except (OrchestratorError, OSError, ValueError):
                found.append(Finding("run_unreadable", directory, "its run.json cannot be read"))
                continue
            named = {os.path.realpath(p) for p in config.withheld_whole}
            if not registered <= named:
                found.append(
                    Finding(
                        "run_not_withholding",
                        directory,
                        "a run beneath the run roots that does not withhold them all",
                    )
                )
    return found


def launch_findings(
    *, store: Path, source: Path, home: Path, also: Sequence[Path] = ()
) -> list[Finding]:
    """Every finding of the launch check, in the order the module's docstring names them."""
    from physgate.evaluation.tiers.exposure import ExposureError, run_roots
    from physgate.evaluation.tiers.store import role_root
    from physgate.evaluation.tiers.task import Role
    from physgate.oslayer.harness_temp import harness_temps_root
    from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs
    from physgate.oslayer.session_temp import session_temps_root
    from physgate.reviewers.places import standing_root

    found: list[Finding] = []
    roots: list[Path] = []
    for role in get_args(Role):
        try:
            roots += run_roots(store, role)
        except ExposureError as exc:
            found.append(Finding("run_roots_unreadable", str(store), f"{role}: {exc}"))
    # The store is walked but for its roles' roots: a measured session is refused those, not the
    # store, so a folder at the store's top that no role's root holds is read like any other.
    refused = [
        *(role_root(store, role) for role in get_args(Role)),
        *roots,
        standing_root(home),
        Path(harness_temps_root()),
        Path(session_temps_root()),
        *map(Path, shared_temp_dirs()),
        *map(Path, claude_temp_dirs()),
    ]
    places = [home, *MACHINE_PLACES, *also]
    if not _under(os.path.realpath(store), [os.path.realpath(p) for p in places]):
        places.append(store)
    found += material_findings(places, refused)
    found += source_findings(source)
    found += withholding_findings(roots, {os.path.realpath(r) for r in roots})
    return found
