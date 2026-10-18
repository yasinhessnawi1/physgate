"""Before a run: proof that no session it starts can read the held-out tier, or the run refuses.

Anything about the held-out tier refuses when in doubt. The scan returns every problem it
finds, and a run with any problem does not start; a check that cannot be completed (a
place that cannot be read whole, a configuration that cannot be generated, any error at
all) is itself a problem, never a pass. What is checked:

- **the root:** the run names it, as its real absolute path, and it is a real directory;
- **the tier:** it is the bytes the run recorded, its digest recomputed now from what is on
  disk with no link followed (a link anywhere in it refuses the run), never taken from the
  tier's own digest file; it holds only task directories, each named as its task, and its
  digest file, which must agree too; every task loads whole (every field, unit,
  reference and the tier marker, unknown fields refused), is marked held out, and carries
  a canary; the canaries are exactly the run's, each carried once;
- **the visible tier:** it is apart from the held-out tier, neither inside it nor around it,
  and no task id is both visible and held out, however it is spelt;
- **the places:** no place a session works in or reads is the root, lies under it or
  holds it, and none holds a link that reaches it; each is judged by the hooks' own
  matcher (:func:`physgate.hooks.paths.reaches`: every spelling, case-folded, and the
  inode chain), so the scan and the hooks cannot disagree about what reaches the tier;
- **the sessions:** for each profile a session is started under (a role, a reviewer, the
  raw agent), the configuration the installer would write names the root as held out and
  the OS layer's policy denies it to the shell both ways.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

from physgate.evaluation.per_role.authoring import (
    CANARIES_NAME,
    SUMS_NAME,
    AuthoringError,
    _open_chain,
)
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.task import load_task, task_from_files
from physgate.hooks.paths import reaches
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "reviewer", "baseline")


def _relation(place: Path, root: Path) -> str | None:
    """How ``place`` stands to ``root``, judged as the hooks judge a path.

    Both are made absolute and normalised first, as the file-tool hook does before it
    judges, and then compared by the hooks' own matcher: every spelling (as given and
    resolved), case-folded, by whole components, and the inode chain.
    """
    path, top = (os.path.normpath(os.path.abspath(p)) for p in (place, root))
    if reaches(path, top):
        return "is" if reaches(top, path) else "lies inside"
    if reaches(top, path):
        return "contains"
    return None


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
#: The largest file a tier holds: a task or a reference answer.
MAX_TIER_FILE_BYTES = 1024 * 1024


def _read_fd(fd: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(fd, 65536):
        total += len(chunk)
        if total > MAX_TIER_FILE_BYTES:
            msg = "a file of the tier is larger than any task file"
            raise PerRoleError(msg)
        chunks.append(chunk)
    return b"".join(chunks)


def _walk(dir_fd: int, prefix: str, out: dict[str, bytes]) -> None:
    for name in sorted(os.listdir(dir_fd)):
        where = f"{prefix}{name}"
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            child = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
            try:
                _walk(child, f"{where}/", out)
            finally:
                os.close(child)
        elif stat.S_ISREG(st.st_mode):
            fd = os.open(name, _FILE_FLAGS, dir_fd=dir_fd)
            try:
                opened = os.fstat(fd)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    msg = f"the tier's {where} has a second name (a hard link)"
                    raise PerRoleError(msg, path=where)
                out[where] = _read_fd(fd)
            finally:
                os.close(fd)
        else:
            msg = f"the tier holds {where}, a link or not a plain file"
            raise PerRoleError(msg, path=where)


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the tier and its bytes, read once, through descriptors only.

    The tier is reached from ``/`` one component at a time without following a link, so a
    link at the tier or at any directory above it refuses; inside it, every directory and
    file is opened relative to its parent's descriptor without following a link, and read
    from that descriptor. Nothing is opened by path again, so nothing put in place between
    a check and a use is read. A link, a second name (a hard link) or anything but a plain
    file or directory refuses.

    Raises:
        PerRoleError: any of those, or the tier cannot be read whole.
    """
    try:
        fd = _open_chain(root, make=False)
    except AuthoringError as exc:
        raise PerRoleError(str(exc), path=str(root)) from exc
    out: dict[str, bytes] = {}
    try:
        _walk(fd, "", out)
    finally:
        os.close(fd)
    return out


def _sums(files: Mapping[str, bytes]) -> str:
    """The digest file's lines, as :func:`sha256sums` writes them, from bytes already read."""
    lines = [
        f"{hashlib.sha256(data).hexdigest()}  {path}"
        for path, data in sorted(files.items())
        if path not in (SUMS_NAME, CANARIES_NAME)
    ]
    return "\n".join(lines) + "\n"


def tier_digest(root: Path) -> str:
    """The tier's digest, recomputed now from the bytes on disk, through descriptors only."""
    return hashlib.sha256(_sums(snapshot(root)).encode()).hexdigest()


def _root_problems(root: Path, run_held_out: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    if str(root) not in run_held_out:
        problems.append("the run's parameters do not name the held-out root")
    if not root.is_absolute() or os.path.realpath(root) != str(root):
        problems.append("the held-out root is not given as its real, absolute path")
    if root.is_symlink() or not root.is_dir():
        problems.append("the held-out root is not a directory of its own")
    elif os.path.normcase(str(root)) != str(root) or ".." in root.parts:
        problems.append("the held-out root is not given in its plain spelling")
    return problems


def _tier_problems(
    root: Path, run_canaries: tuple[str, ...], recorded: str | None
) -> tuple[list[str], set[str]]:
    """Every problem with the tier's contents, and its task ids, case-folded.

    The tier is read once, through descriptors (:func:`snapshot`), and everything below is
    judged on those bytes: its digest, recomputed and held to the digest the run recorded,
    never to one the tier carries; its digest file; each task.
    """
    problems: list[str] = []
    try:
        files = snapshot(root)
    except (PerRoleError, OSError) as exc:
        return [f"the tier could not be read whole: {exc}"], set()
    if recorded is None:
        problems.append("the run records no digest for the held-out root")
    elif hashlib.sha256(_sums(files).encode()).hexdigest() != recorded:
        problems.append("the tier is not the bytes the run records")
    if files.get(SUMS_NAME) is None:
        problems.append("the tier has no digest file")
    elif files[SUMS_NAME] != _sums(files).encode():
        problems.append("the tier is not the bytes its digest records")
    tasks: dict[str, dict[str, bytes]] = {}
    for path, data in files.items():
        top, _, rest = path.partition("/")
        if not rest:
            if top != SUMS_NAME:
                problems.append(f"the tier holds {top!r}, which is not a task")
            continue
        tasks.setdefault(top, {})[rest] = data
    ids: set[str] = set()
    carried: list[str] = []
    for name, task_files in sorted(tasks.items()):
        try:
            task = task_from_files(task_files, where=name)
        except (PerRoleError, ValueError) as exc:
            problems.append(f"the held-out task {name!r} does not load: {exc}")
            continue
        if name != task.id:
            problems.append(f"the directory {name!r} is not named as its task {task.id!r}")
        if task.tier != "held_out" or task.canary is None:
            problems.append(f"the task {task.id!r} is not marked held out with its canary")
        else:
            carried.append(task.canary)
        ids.add(task.id.casefold())
    for canary in sorted(set(carried) - set(run_canaries)):
        problems.append(f"a held-out task carries a canary the run does not name ({canary[:4]}…)")
    for canary in sorted(set(run_canaries) - set(carried)):
        problems.append(f"no held-out task carries the run's canary {canary[:4]}…")
    if len(carried) != len(set(carried)):
        problems.append("two held-out tasks carry the same canary")
    return problems, ids


def _visible_problems(visible: Path, root: Path, held_ids: set[str]) -> list[str]:
    problems: list[str] = []
    relation = _relation(visible, root)
    if relation is not None:
        return [f"the visible tier {relation} the held-out root"]
    for entry in sorted(visible.iterdir()):
        names = {entry.name.casefold()}
        try:
            task = load_task(entry).task
            names.add(task.id.casefold())
            if task.tier == "held_out" or task.canary is not None:
                problems.append(f"the visible task {task.id!r} is marked as held out")
        except (PerRoleError, OSError, ValueError):
            pass  # a visible task that does not load is the visible tier's problem
        if names & held_ids:
            problems.append(f"the task {entry.name!r} is both visible and held out")
    return problems


def _place_problems(name: str, place: Path, root: Path) -> list[str]:
    problems: list[str] = []
    for spelling in {place, Path(os.path.realpath(place))}:
        relation = _relation(spelling, root)
        if relation is not None:
            problems.append(f"the {name} {relation} the held-out root")
    if not place.exists():
        return problems
    unread: list[str] = []
    for current, dirs, files in os.walk(
        place, followlinks=False, onerror=lambda e: unread.append(str(e.filename))
    ):
        for entry in [*dirs, *files]:
            path = Path(current) / entry
            if path.is_symlink() and reaches(str(path), str(root)):
                problems.append(f"the {name} holds a link into the tier: {path}")
    problems.extend(f"the {name} could not be read whole: {where}" for where in unread)
    return problems


def _session_problems(root: Path, scratch: Path) -> list[str]:
    problems: list[str] = []
    for profile in PROFILES:
        work = scratch / profile
        request = InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(work / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(work / "state"),
            target_dir=str(work / "session"),
            claude_config_dir=str(work / "config"),
            user_home=str(work / "home"),
            token_ceiling=1,
            held_out=(str(root),),
            read_roots=(str(work / "worktree"),) if profile == "reviewer" else (),
        )
        config = build_config(request, current_installation())
        if str(root) not in config.held_out:
            problems.append(f"a {profile} session would not be configured with the root")
        if profile == "reviewer":
            continue  # a reviewer has no shell, so no OS layer
        policy = sandbox_policy(config, home=str(work / "home"), temp_dir="/tmp/pg-scan")
        filesystem = policy.settings["sandbox"]["filesystem"]
        for direction in ("denyRead", "denyWrite"):
            if str(root) not in filesystem[direction]:
                problems.append(f"a {profile} session's OS layer would not {direction} the root")
    return problems


def _checked(what: str, check: Callable[[], list[str]]) -> list[str]:
    """``check``'s problems, or one problem saying it could not be completed."""
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - anything unchecked is a refusal, never a pass
        return [f"the {what} could not be checked: {exc!r}"]


def scan(
    held_out: Path,
    *,
    run_held_out: tuple[str, ...],
    run_digests: Mapping[str, str],
    run_canaries: tuple[str, ...],
    places: Mapping[str, Path],
    scratch: Path,
    visible_tier: Path | None = None,
) -> list[str]:
    """Every reason a run with these parameters and places could expose ``held_out``.

    ``run_held_out``, ``run_digests`` (each root's digest, as the run recorded it when the
    tier was written) and ``run_canaries`` are the run's parameters; ``places`` names every
    directory a session of the run works in or reads; ``scratch`` is an empty directory
    outside the tier where the sessions' configurations are generated to be looked at.
    An empty list is the only answer that lets the run start.
    """
    problems = _checked("root", lambda: _root_problems(held_out, run_held_out))
    held_ids: set[str] = set()
    if held_out.is_dir() and not held_out.is_symlink():

        def tier() -> list[str]:
            found, ids = _tier_problems(held_out, run_canaries, run_digests.get(str(held_out)))
            held_ids.update(ids)
            return found

        problems += _checked("tier", tier)
    if visible_tier is not None:
        problems += _checked(
            "visible tier", lambda: _visible_problems(visible_tier, held_out, held_ids)
        )
    for name, place in sorted(places.items()):
        problems += _checked(name, lambda n=name, p=place: _place_problems(n, p, held_out))  # type: ignore[misc]
    if _relation(scratch, held_out) is not None:
        problems.append("the scan's own scratch directory touches the held-out root")
    else:
        problems += _checked("sessions", lambda: _session_problems(held_out, scratch))
    return sorted(set(problems))


def digest(tier: Path) -> str:
    """The digest of a tier's digest file: what is committed in the tier's place."""
    return hashlib.sha256((tier / SUMS_NAME).read_bytes()).hexdigest()
