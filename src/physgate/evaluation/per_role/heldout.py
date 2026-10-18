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

from physgate.evaluation.per_role.authoring import CANARIES_NAME, SUMS_NAME, sha256sums
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.task import load_task
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


_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


def tier_digest(root: Path) -> str:
    """The tier's digest, recomputed from the bytes on disk now, following no link.

    The same lines :func:`sha256sums` writes, over every file but the tier's own digest
    file, digested once more. A link, or anything but a directory or a regular file,
    anywhere in the tier is refused rather than read through or skipped.

    Raises:
        PerRoleError: the tier holds a link or something that is not a plain file, or a
            file of it cannot be read.
    """
    lines: list[str] = []
    for current, dirs, files in os.walk(root, followlinks=False, onerror=_raise):
        for name in [*dirs, *files]:
            path = Path(current) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                msg = f"the tier holds {path}, a link or not a plain file"
                raise PerRoleError(msg, path=str(path))
        for name in files:
            path = Path(current) / name
            if path.parent == root and name in (SUMS_NAME, CANARIES_NAME):
                continue
            fd = os.open(path, _READ_FLAGS)
            with os.fdopen(fd, "rb") as handle:
                data = handle.read()
            lines.append(f"{hashlib.sha256(data).hexdigest()}  {path.relative_to(root).as_posix()}")
    text = "\n".join(sorted(lines, key=lambda line: line.split("  ", 1)[1])) + "\n"
    return hashlib.sha256(text.encode()).hexdigest()


def _raise(error: OSError) -> None:
    raise error


def _root_problems(root: Path, run_held_out: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    if str(root) not in run_held_out:
        problems.append("the run's parameters do not name the held-out root")
    if not root.is_absolute() or os.path.realpath(root) != str(root):
        problems.append("the held-out root is not given as its real, absolute path")
    if root.is_symlink() or not root.is_dir():
        problems.append("the held-out root is not a directory of its own")
    return problems


def _tier_problems(
    root: Path, run_canaries: tuple[str, ...], recorded: str | None
) -> tuple[list[str], set[str]]:
    """Every problem with the tier's contents, and its task ids, case-folded.

    The tier's digest is recomputed from the bytes on disk, following no link, and held to
    the digest the run recorded, never to one the tier carries: a tier rewritten together
    with its own digest file still differs from the run's record.
    """
    problems: list[str] = []
    if recorded is None:
        problems.append("the run records no digest for the held-out root")
    else:
        try:
            if tier_digest(root) != recorded:
                problems.append("the tier is not the bytes the run records")
        except (PerRoleError, OSError) as exc:
            problems.append(f"the tier could not be read whole: {exc}")
    ids: set[str] = set()
    carried: list[str] = []
    for entry in sorted(root.iterdir()):
        if entry.name == SUMS_NAME and entry.is_file() and not entry.is_symlink():
            continue
        if entry.is_symlink() or not entry.is_dir():
            problems.append(f"the tier holds {entry.name!r}, which is not a task")
            continue
        try:
            task = load_task(entry).task
        except (PerRoleError, OSError, ValueError) as exc:
            problems.append(f"the held-out task {entry.name!r} does not load: {exc}")
            continue
        if entry.name != task.id:
            problems.append(f"the directory {entry.name!r} is not named as its task {task.id!r}")
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
    sums = root / SUMS_NAME
    if sums.is_symlink() or not sums.is_file():
        problems.append("the tier has no digest file")
    elif sums.read_bytes() != sha256sums(root).encode():
        problems.append("the tier is not the bytes its digest records")
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
