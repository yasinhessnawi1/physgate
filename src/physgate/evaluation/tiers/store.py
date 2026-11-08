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

**What sessions wrote is withheld from every run.** The authoring sessions' streams hold every
task they wrote, the blind check's hold the held-out tasks it was given, and the pool holds
tasks that become held-out ones; none carries a canary. So they lie under one root per role,
``withheld/``, and a run that names any tier of the store must name that root too, for each
role it names, among the roots its sessions withhold (the run's ``held_out``), where every
layer of the protection refuses it as it refuses a tier (:func:`withheld_refusal`).

**A version is written once.** The split writes it into a fresh temporary directory beside
it (``.version-<random>``) and renames that into place last, once its tiers, its provenance
record and its manifest are whole: a look at the role's root finds a version whole, or not
at all. A version already there is never written again (:func:`write_version`).

**The pool never outlives the split.** It holds tasks that will be held out and validation
ones, without their canaries, which are given at the split, so a session that read it would
see future held-out work and nothing would detect it. The split marks it spent
(``pool.spent``) before the version's rename and removes it after; the tasks the draw did
not take go with it. While a pool or a temporary version is in a store, no run that names a
version of that store starts, and no authoring or blind-check session either, except an
author adding to its own role's pool, which its session withholds (:func:`leftovers`).
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
#: The folders directly under a role's root that hold what sessions wrote. No canary list
#: the harness writes lies in one.
SESSION_FOLDERS = frozenset({WITHHELD})
#: Why a store refuses a run or a session, counted: what only a split in progress holds.
LEFT = ("pool_left", "temporary_version_left")


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


def tier_role(root: Path) -> tuple[Path, Role] | None:
    """The store and role a protected tier root lies in, by its place alone; ``None`` outside."""
    store = store_of(root)
    if store is None:
        return None
    role: Role = root.parent.parent.name  # type: ignore[assignment]
    return store, role


def withheld_refusal(held_out: tuple[str, ...]) -> tuple[str, str] | None:
    """Why a run withholding ``held_out`` may not start: a counted reason and its words.

    Every tier of a store the run names asks for that store's withheld root of the same role
    among the run's roots, compared as absolute, normalised paths; ``None`` if each is there.
    """
    named = {os.path.normpath(os.path.abspath(r)) for r in held_out}
    missing = sorted(
        {
            str(withheld_root(*found))
            for r in held_out
            if (found := tier_role(Path(r))) is not None
            and os.path.normpath(os.path.abspath(withheld_root(*found))) not in named
        }
    )
    if not missing:
        return None
    return "withheld_root_not_named", (
        f"the run names a tier of a store but not {len(missing)} withheld root(s) of it "
        f"({', '.join(missing)}), which hold the sessions' streams and the pool: tasks that are "
        "held-out ones, with no canary; a run withholds them with the tier"
    )


def store_of(root: Path) -> Path | None:
    """The store a protected root lies in, judged by its place alone; ``None`` outside one.

    A version's protected tier is ``<store>/<role>/<version>/<tier>``. Nothing beneath the
    root is opened.
    """
    if (
        root.name in TIERS[1:]
        and VERSION_NAME.fullmatch(root.parent.name) is not None
        and root.parent.parent.name in get_args(Role)
    ):
        return root.parents[2]
    return None


def leftovers(store: Path, *, continuing: Path | None = None) -> dict[str, int]:
    """What only a split in progress holds, found in ``store``, counted by reason.

    ``pool_left`` counts every pool, drawn from or not, but ``continuing``: the one pool an
    author may add to, its own role's, which its session withholds. ``temporary_version_left``
    counts every version still being written. Only names are looked at, in any case.

    Raises:
        OSError: the store or a role's root cannot be listed, so nothing can be ruled out.
    """
    counts = dict.fromkeys(LEFT, 0)
    if not os.path.lexists(store):
        return counts
    for role in sorted(os.listdir(store)):
        here = store / role
        if not here.is_dir() or here.is_symlink():
            continue
        for name in os.listdir(here):
            if name.casefold().startswith(TEMPORARY):
                counts["temporary_version_left"] += 1
        withheld = here / WITHHELD
        if not withheld.is_dir() or withheld.is_symlink():
            continue
        for name in os.listdir(withheld):
            folded = name.casefold()
            if folded in (POOL, SPENT_POOL) and withheld / name != continuing:
                counts["pool_left"] += 1
    return counts


def leftover_refusal(store: Path, *, continuing: Path | None = None) -> tuple[str, str] | None:
    """Why nothing may start on ``store``: a counted reason and its words; ``None`` if nothing.

    Nothing starts while a split's leftovers are in the store (:func:`leftovers`), or while
    the store cannot be listed (``store_unreadable``).
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
        f"the tier-set store {store} holds {counts['pool_left']} pool(s) and "
        f"{counts['temporary_version_left']} version(s) being written, whose tasks become "
        "held-out and validation ones and carry no canary yet; nothing starts on it until a "
        "person has looked at them and removed them"
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
