"""The tier-set store: every version of every role's tiers, outside the repository.

::

    <store>/
      <role>/                    the role's protected root, withheld from its authoring sessions
        withheld/                withheld from every run that names a tier of the store
          pool/                  the round's tasks that hold, and its sessions' provenance
          author/, check/        the authoring and blind-check sessions' streams
        <version>/               one round's three tiers, named by its manifest's id
          tierset.json           the manifest: counts and digests only
          provenance.json        the round's sessions: ids, ends, spend and stream digests
          visible/<task>/…       read by implementers
          validation/<task>/…    protected, as held out is; SHA256SUMS and canaries.json
          held_out/<task>/…      protected; SHA256SUMS and canaries.json

**A run that names anything under a role's root withholds all of it that is protected.** The
authoring sessions' streams hold every task they wrote, the blind check's hold the held-out
tasks it was given, and the pool holds tasks that become held-out ones; none carries a canary.
So they lie under one root per role, ``withheld/``. A run that names anything under
``<store>/<role>``, the role's root itself or the store, must name among the roots its sessions
withhold (the run's ``held_out``), where every layer of the protection refuses them: that
withheld root (:func:`withheld_refusal`), and the validation and held-out tiers of every
version under the role's root, older ones too (:func:`protected_tier_refusal`). A tier the run
does not withhold is read by its sessions with no canary of the run's to show it. Each such
entry is spelt as the filesystem spells it (:func:`spelling_refusal`), so the spelling every
layer is given is the one on disk, whatever case the volume ignores.

**Work out of the role's root is a leftover too.** An author's tasks before they are pooled,
and the blind check's copy of the held-out tasks, lie outside every protected root while their
session runs; a record ``<name>.working`` in the role's root says so until the work is kept
inside it and removed. While such a record stands, nothing starts on the store
(:func:`leftovers`).

**A version is written once.** The split writes it into a fresh temporary directory beside
it (``.version-<random>``) and renames that into place last, once its tiers, its provenance
record and its manifest are whole: a look at the role's root finds a version whole, or not
at all. A version already there is never written again (:func:`write_version`).

**The pool never outlives the split.** It holds tasks that will be held out and validation
ones, without their canaries, which are given at the split, so a session that read it would
see future held-out work and nothing would detect it. The split marks it spent
(``pool.spent``) before the version's rename and removes it after; the tasks the draw did
not take go with it. While a pool or a temporary version is in a store, no run that names
the store starts, and no authoring or blind-check session either, except an author adding to
its own role's pool, which its session withholds (:func:`leftovers`).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from physgate.evaluation.tiers.authoring import (
    TIERS,
    AuthoringError,
    _open_chain,
    _write_whole,
    split,
)
from physgate.evaluation.tiers.manifest import (
    MANIFEST_NAME,
    PROVENANCE_NAME,
    VERSION_NAME,
    TierSet,
    brief_digest,
    make_tierset,
    manifest_bytes,
    requirements_digest,
    tier_record,
)
from physgate.evaluation.tiers.task import Role

#: The one root per role that holds what sessions wrote: the pool and the sessions' streams.
WITHHELD = "withheld"
POOL = "pool"
#: What the pool is called once the split has drawn from it, until it is removed.
SPENT_POOL = "pool.spent"
#: What a version is called while it is written, before it is whole and has its name.
TEMPORARY = ".version-"
AUTHOR_EVIDENCE = "author"
CHECK_EVIDENCE = "check"
#: What a record of a session's work out of the role's root ends with: ``author.working``,
#: ``check.working``.
WORKING = ".working"
#: The folders directly under a role's root that hold what sessions wrote. No canary list
#: the harness writes lies in one.
SESSION_FOLDERS = frozenset({WITHHELD})
#: Why a store refuses a run or a session, counted: what only a split in progress holds, and
#: work a session has out of the role's root.
LEFT = ("pool_left", "temporary_version_left", "work_left")
#: The tiers of every version a run withholds once it names anything under the role's root.
PROTECTED = ("validation", "held_out")


def role_root(store: Path, role: Role) -> Path:
    """A role's protected root: its pool, its sessions' streams and its versions."""
    return store / role


def withheld_root(store: Path, role: Role) -> Path:
    """The root under which a role's pool and sessions' streams lie, withheld from every run."""
    return role_root(store, role) / WITHHELD


def pool_dir(store: Path, role: Role) -> Path:
    """Where a role's tasks that hold wait until the tiers are cut."""
    return withheld_root(store, role) / POOL


def author_evidence(store: Path, role: Role) -> Path:
    """Where the role's authoring sessions' streams are kept."""
    return withheld_root(store, role) / AUTHOR_EVIDENCE


def check_evidence(store: Path, role: Role) -> Path:
    """Where the role's blind-check sessions' streams are kept."""
    return withheld_root(store, role) / CHECK_EVIDENCE


def version_dir(store: Path, role: Role, version: str) -> Path:
    """Where one version of a role's tiers lies."""
    return role_root(store, role) / version


def is_visible_tier(path: Path) -> bool:
    """Whether ``path`` is a version's visible tier, judged by its place alone."""
    return (
        path.name == "visible"
        and VERSION_NAME.fullmatch(path.parent.name) is not None
        and path.parent.parent.name in get_args(Role)
    )


def _resolved(entry: str) -> Path:
    """A held-out entry as every check here judges it: absolute, normalised, links followed."""
    return Path(entry).resolve(strict=False)


def _role(name: str) -> Role | None:
    """The role a directory's name names, in any case; ``None`` if none."""
    return {role.casefold(): role for role in get_args(Role)}.get(name.casefold())


def _of_a_role_root(name: str) -> bool:
    """Whether an entry called ``name`` lies only in a role's root: by its name alone."""
    folded = name.casefold()
    return (
        VERSION_NAME.fullmatch(folded) is not None
        or folded == WITHHELD
        or folded.startswith(TEMPORARY)
        or folded.endswith(WORKING)
    )


def _holds_a_role_root_s(path: Path) -> bool:
    """Whether the directory ``path`` holds what only a role's root holds, by names on disk.

    A directory that cannot be listed is taken to hold it: what it holds cannot be ruled out.
    """
    if not os.path.isdir(path):
        return False
    try:
        return any(_of_a_role_root(name) for name in os.listdir(path))
    except OSError:
        return True


def _named_role_roots(path: Path) -> list[tuple[Path, Role]]:
    """The store and role of every role's root ``path`` lies in, is, or (as a store) holds.

    ``path`` is resolved. It lies in a role's root when a part of it is named as a role, in
    any case, and the part after it is one only a role's root holds (a version, the withheld
    root, a version being written, a record of work), or that part holds one on disk; the
    right-most such part is taken, so a store whose own path happens to hold such a pair is
    still found. ``path`` names a store when a directory under it, named as a role, holds one.
    """
    parts = path.parts
    for at in range(len(parts) - 1, 0, -1):
        role = _role(parts[at])
        if role is None:
            continue
        here = Path(*parts[: at + 1])
        below = parts[at + 1] if at + 1 < len(parts) else None
        if (below is not None and _of_a_role_root(below)) or _holds_a_role_root_s(here):
            return [(Path(*parts[:at]), role)]
    found: list[tuple[Path, Role]] = []
    if os.path.isdir(path):
        try:
            names = sorted(os.listdir(path))
        except OSError:
            # What it holds cannot be ruled out, so it is taken as a store of every role:
            # the leftover check then refuses it as unreadable.
            return [(path, role) for role in get_args(Role)]
        for name in names:
            role = _role(name)
            if role is not None and _holds_a_role_root_s(path / name):
                found.append((path, role))
    return found


def role_roots(held_out: tuple[str, ...]) -> list[tuple[Path, Role]]:
    """The store and role of every role's root an entry names: lies in, is, or holds.

    Each entry is resolved once (:func:`_resolved`) and only its resolved form is judged: a
    run naming ``<store>/<role>/<version>``, a tier of it or anything beneath, the withheld
    root, the role's root itself or the store, however spelt (``.``, ``..``, a trailing slash,
    a link, another case of the role's name), names that role's root
    (:func:`_named_role_roots`). Fail closed: such an entry is never read as naming nothing.
    """
    found: dict[tuple[str, str], tuple[Path, Role]] = {}
    for entry in held_out:
        for store, role in _named_role_roots(_resolved(entry)):
            found[(str(store), role)] = (store, role)
    return [found[key] for key in sorted(found)]


def _withholds(named: Path, place: Path) -> bool:
    """Whether a run withholding ``named`` withholds ``place``: the same or beneath it.

    Compared as spelt: an entry spelt otherwise than on disk is refused before this counts
    for anything (:func:`spelling_refusal`), so no case is taken for another.
    """
    one, other = str(place), str(named).rstrip("/")
    return one == other or one.startswith(other + "/")


def _judged(
    held_out: tuple[str, ...], also: Sequence[tuple[Path, Role]]
) -> tuple[list[Path], list[tuple[Path, Role]]]:
    """Every entry resolved, and every role's root to judge: those named, and ``also``."""
    roots = {(str(store), role): (store, role) for store, role in role_roots(held_out)}
    for given, role in also:
        store = _resolved(str(given))
        roots[(str(store), role)] = (store, role)
    return [_resolved(entry) for entry in held_out], [roots[key] for key in sorted(roots)]


def _missing(named: Sequence[Path], places: Sequence[Path]) -> list[str]:
    """Every place in ``places`` that no root in ``named`` withholds, as text, sorted."""
    return sorted(str(p) for p in places if not any(_withholds(root, p) for root in named))


def withheld_refusal(
    held_out: tuple[str, ...], *, also: Sequence[tuple[Path, Role]] = ()
) -> tuple[str, str] | None:
    """Why a run withholding ``held_out`` may not start: a counted reason and its words.

    Every role's root the run names (:func:`role_roots`), and each of ``also``, asks for that
    role's withheld root among the run's roots: one of them, resolved, is that root or holds
    it; ``None`` if each is there.
    """
    named, roots = _judged(held_out, also)
    missing = _missing(named, [withheld_root(store, role) for store, role in roots])
    if not missing:
        return None
    return "withheld_root_not_named", (
        f"the run names a tier of a store but not {len(missing)} withheld root(s) of it "
        f"({', '.join(missing)}), which hold the sessions' streams and the pool: tasks that are "
        "held-out ones, with no canary; a run withholds them with the tier"
    )


def protected_tier_refusal(
    held_out: tuple[str, ...], *, also: Sequence[tuple[Path, Role]] = ()
) -> tuple[str, str] | None:
    """Why a run withholding ``held_out`` may not start: a counted reason and its words.

    Every role's root the run names (:func:`role_roots`), and each of ``also``, asks for the
    validation and held-out tiers of every version under it, as the role's root lists them
    on disk, among the run's roots; ``None`` if each is there. A role's root that cannot be
    listed refuses (``store_unreadable``): a version under it cannot be ruled out.
    """
    named, roots = _judged(held_out, also)
    places: list[Path] = []
    for store, role in roots:
        root = role_root(store, role)
        try:
            names = os.listdir(root) if os.path.lexists(root) else []
        except OSError as exc:
            return "store_unreadable", (
                f"the role's root {root} cannot be listed ({exc}), so a version under it, "
                "whose tiers the run would have to withhold, cannot be ruled out"
            )
        places += [
            root / name / tier
            for name in names
            if VERSION_NAME.fullmatch(name.casefold())
            for tier in PROTECTED
        ]
    missing = _missing(named, places)
    if not missing:
        return None
    return "protected_tier_not_named", (
        f"the run names a store's role but not {len(missing)} protected tier(s) under it "
        f"({', '.join(missing)}): every version's validation and held-out tiers there, older "
        "ones too, are withheld with what the run names, or its sessions read them with no "
        "canary of the run's to show it"
    )


def _spelt_as_on_disk(path: Path) -> bool:
    """Whether every part of ``path`` that exists is spelt as its directory lists it.

    Raises:
        OSError: a directory on the way cannot be listed, so the spelling cannot be judged.
    """
    here = Path(path.anchor)
    for part in path.parts[1:]:
        if not os.path.lexists(here / part):
            return True
        if part not in os.listdir(here):
            return False
        here = here / part
    return True


def spelling_refusal(
    held_out: tuple[str, ...], *, also: Sequence[tuple[Path, Role]] = ()
) -> tuple[str, str] | None:
    """Why a run withholding ``held_out`` may not start: a counted reason and its words.

    Once the run names a role's root (:func:`role_roots`), or ``also`` gives one, every entry
    is spelt, resolved, as the filesystem spells each part of it that exists; ``None`` if so.
    On a volume that ignores case another case reaches the same files, but whether every
    layer of the protection refuses a root named so is not shown, so it is refused here.
    """
    named, roots = _judged(held_out, also)
    if not roots:
        return None
    wrong: list[str] = []
    for path in named:
        try:
            if not _spelt_as_on_disk(path):
                wrong.append(str(path))
        except OSError as exc:
            wrong.append(f"{path} (cannot be judged: {exc})")
    if not wrong:
        return None
    return "held_out_not_spelt_as_on_disk", (
        f"{len(wrong)} root(s) the run withholds are not spelt as the filesystem spells them "
        f"({', '.join(sorted(wrong))}); name each as it is on disk, so every layer of the "
        "protection is given the spelling that is there"
    )


def leftovers(store: Path, *, continuing: Path | None = None) -> dict[str, int]:
    """What only a split in progress holds, and work out of a role's root, counted by reason.

    ``pool_left`` counts every pool, drawn from or not, but ``continuing``: the one pool an
    author may add to, its own role's, which its session withholds. ``temporary_version_left``
    counts every version still being written. ``work_left`` counts every record of a session's
    work out of the role's root (``<name>.working``), its own role's too: that work (tasks
    before they are pooled, the check's copy of the held-out tasks, with no canary) lies where
    a session could read it. Only names are looked at, in any case.

    Raises:
        OSError: the store or a role's root cannot be listed, or a role's root or withheld
            root is a link (the harness makes them with ``mkdir``), so nothing can be ruled
            out.
    """
    counts = dict.fromkeys(LEFT, 0)
    if not os.path.lexists(store):
        return counts
    for role in sorted(os.listdir(store)):
        here = store / role
        if here.is_symlink():
            raise OSError(f"{here} is a link; a role's root is a directory the harness made")
        if not here.is_dir():
            continue
        for name in os.listdir(here):
            folded = name.casefold()
            if folded.startswith(TEMPORARY):
                counts["temporary_version_left"] += 1
            elif folded.endswith(WORKING):
                counts["work_left"] += 1
        withheld = here / WITHHELD
        if withheld.is_symlink():
            raise OSError(f"{withheld} is a link; a withheld root is a directory the harness made")
        if not withheld.is_dir():
            continue
        for name in os.listdir(withheld):
            folded = name.casefold()
            if folded in (POOL, SPENT_POOL) and withheld / name != continuing:
                counts["pool_left"] += 1
            elif folded.endswith(WORKING):
                counts["work_left"] += 1
    return counts


def leftover_refusal(store: Path, *, continuing: Path | None = None) -> tuple[str, str] | None:
    """Why nothing may start on ``store``: a counted reason and its words; ``None`` if nothing.

    Nothing starts while a split's leftovers, or a record of work out of a role's root, are in
    the store (:func:`leftovers`), or while the store cannot be listed (``store_unreadable``).
    """
    try:
        counts = leftovers(store, continuing=continuing)
    except OSError as exc:
        return "store_unreadable", (
            f"the tier-set store {store} cannot be listed ({exc}), so a pool or a version "
            "being written cannot be ruled out"
        )
    left = [reason for reason in LEFT if counts[reason]]
    if not left:
        return None
    return left[0], (
        f"the tier-set store {store} holds {counts['pool_left']} pool(s), "
        f"{counts['temporary_version_left']} version(s) being written and "
        f"{counts['work_left']} record(s) of a session's work out of a role's root, whose tasks "
        "are or become held-out and validation ones and carry no canary; nothing starts on it "
        "until a person has looked at them and removed them"
    )


def _removed(path: Path) -> str | None:
    """Remove ``path`` if it is there; the reason if it could not be, never silently."""
    if not os.path.lexists(path):
        return None
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"{path}: {exc}"
    return f"{path}: still there" if os.path.lexists(path) else None


def _loudly(problems: Sequence[str | None], what: str) -> None:
    left = [p for p in problems if p is not None]
    if left:
        msg = f"{what}; remove these by hand before anything else runs: " + "; ".join(left)
        raise AuthoringError(msg, left=" | ".join(left))


def write_version(
    root: Path,
    chosen: Sequence[Path],
    *,
    role: Role,
    seed: int,
    model: str,
    runtime: str,
    provenance: bytes,
    retire: Path | None = None,
    generated: str | None = None,
) -> tuple[TierSet, dict[str, Any]]:
    """Split ``chosen`` into a new version under the role's ``root``; its manifest and the split.

    The tasks are copied into a fresh temporary directory beside the versions, split there by
    ``seed`` (:func:`.authoring.split`), and the provenance record and the manifest written
    whole beside the tiers; then ``retire`` (the pool drawn from) is marked spent, the
    temporary directory is renamed to the version's id, and the spent pool is removed. A
    version that exists is never written again.

    Returns:
        The manifest, and what the split may show (visible ids, protected counts and digests).

    Raises:
        AuthoringError: the split refuses, the version exists (``version_exists``), a spent
            pool is left (``pool_left``), or what was written cannot be removed or renamed
            (loudly, naming what to remove by hand).
    """
    temporary = root / f"{TEMPORARY}{secrets.token_hex(8)}"
    os.mkdir(temporary, 0o700)
    try:
        draw = temporary / "draw"
        draw.mkdir(mode=0o700)
        for task in chosen:
            shutil.copytree(task, draw / task.name, symlinks=True)
        placed = split(
            draw,
            temporary / "visible",
            temporary / "held_out",
            validation=temporary / "validation",
            seed=seed,
        )
        fd = _open_chain(temporary, make=False)
        try:
            _write_whole(fd, PROVENANCE_NAME, provenance)
            records = {
                name: tier_record(temporary / name, protected=name != "visible") for name in TIERS
            }
            manifest = make_tierset(
                role=role,
                **{name: record.model_dump(mode="json") for name, record in records.items()},
                model=model,
                seed=seed,
                brief_sha256=brief_digest(role),
                requirements_sha256=requirements_digest(role),
                generated=generated or datetime.now(UTC).date().isoformat(),
                runtime=runtime,
                provenance_sha256=hashlib.sha256(provenance).hexdigest(),
            )
            _write_whole(fd, MANIFEST_NAME, manifest_bytes(manifest))
        finally:
            os.close(fd)
    except BaseException:
        _loudly([_removed(temporary)], "a version that did not finish could not be removed")
        raise
    _publish(temporary, root / manifest.version, retire)
    return manifest, placed


def _publish(temporary: Path, target: Path, retire: Path | None) -> None:
    """Rename the whole version ``temporary`` to ``target``; then remove the pool ``retire``.

    The pool is marked spent before the rename, so a runner stopped between the two leaves
    a spent pool and a temporary version, which refuse everything after it, rather than a
    pool that looks like one still filling (and whose tasks would be drawn again).
    """
    # Beside the pool, under the withheld root: a spent pool is still what sessions wrote.
    spent = (retire or target.parent / WITHHELD / POOL).parent / SPENT_POOL
    refusal: tuple[str, str] | None = None
    if os.path.lexists(target):
        refusal = ("version_exists", f"{target} exists; a version is never written again")
    elif retire is not None and os.path.lexists(spent):
        refusal = ("pool_left", f"{spent} is left from a split that did not finish")
    if refusal is not None:
        _loudly([_removed(temporary)], "a version that was not placed could not be removed")
        raise AuthoringError(refusal[1], refused_because=refusal[0], path=str(target))
    try:
        if retire is not None:
            os.rename(retire, spent)
        os.rename(temporary, target)
    except OSError as exc:
        msg = (
            f"the version could not be put in place ({exc}); {temporary} and any {spent} are "
            "left for a person to look at, and refuse every run and session until then"
        )
        raise AuthoringError(msg, refused_because="version_not_placed") from exc
    if retire is not None:
        _loudly([_removed(spent)], "the pool the version was drawn from could not be removed")
