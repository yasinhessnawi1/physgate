"""One version of a role's tiers: its manifest, the id that names it, and whether it is stale.

A real model's output is not reproducible, so the version is the reproducible object: one
authoring round's three tiers, pinned by digest. Its manifest, ``tierset.json``, holds for
each tier the digest of its files (as :func:`.heldout.tier_digest` computes it), its task
count and, for the two protected tiers, its canary list's digest; and the generator's model
string, the split's seed, the author brief's digest, the requirements source's digest, the
date, the runtime's version and the provenance record's digest. It holds no task id, brief,
specification or reference of any tier: the schema has no field for one, and refuses any
field it does not name.

**The version id** is the sha256 of the manifest's canonical JSON with the id field itself
left out, so the id names exactly what the manifest says. **Every reader recomputes**: the id
from the manifest, and every digest, count and list digest from the bytes on disk
(:func:`read_version`). A manifest that states digests the disk does not give refuses the
version, so a tier is never taken to be what an edited manifest says it is.

**A version is stale** when the brief its author was given, or the requirements source that
brief draws on, differs from the current one: all three tiers were written to an old question
(:func:`staleness`). A version the register marks exposed is stale too; that is read from the
register, not from here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, ValidationError, model_validator

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.per_role.metrics import (
    ACTUATOR_LIMIT,
    ACTUATOR_PEAK,
    CONTROL_METRIC_UNITS,
    CONTROL_SCORER_VERSION,
)
from physgate.evaluation.tiers.authoring import (
    CANARIES_NAME,
    SUMS_NAME,
    TIERS,
    AuthoringError,
    _open_chain,
    author_brief,
)
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.heldout import _sums, snapshot
from physgate.evaluation.tiers.task import COMPOSES_AT_LEAST, Role, Sha256, canonical_json

MANIFEST_NAME = "tierset.json"
PROVENANCE_NAME = "provenance.json"
#: The manifest format this code writes and reads.
FORMAT = 1
#: A version's name: its id.
VERSION_NAME = re.compile(r"^[0-9a-f]{64}$")
#: Everything a version directory holds: its manifest, its provenance record, its tiers.
VERSION_HOLDS = frozenset({MANIFEST_NAME, PROVENANCE_NAME, *TIERS})
#: The largest manifest or provenance record read.
MOST_RECORD_BYTES = 1024 * 1024


class TierSetError(PerRoleError):
    """A version is not what its manifest says, or its manifest is not one."""


class TierRecord(_Frozen):
    """One tier of a version, as the manifest records it: counts and digests only."""

    sha256: Sha256
    count: int = Field(ge=0)
    canaries_sha256: Sha256 | None = None


class TierSet(_Frozen):
    """A version's manifest: what it holds and how it was made, never a task of it."""

    format: Literal[1]
    version: Sha256
    role: Role
    visible: TierRecord
    validation: TierRecord
    held_out: TierRecord
    model: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    seed: int
    brief_sha256: Sha256
    requirements_sha256: Sha256
    generated: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    runtime: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    provenance_sha256: Sha256

    @model_validator(mode="after")
    def _holds_its_rules(self) -> TierSet:
        if self.visible.canaries_sha256 is not None:
            msg = "the visible tier carries no canary list"
            raise ValueError(msg)
        for name in TIERS[1:]:
            if getattr(self, name).canaries_sha256 is None:
                msg = f"the {name} tier's canary list has no digest"
                raise ValueError(msg)
        if self.version != version_id(self.model_dump(mode="json")):
            msg = "the version id is not the digest of the manifest it names"
            raise ValueError(msg)
        return self

    def tier(self, name: str) -> TierRecord:
        """The record of the tier called ``name``."""
        record: TierRecord = getattr(self, name)
        return record


def version_id(fields: Mapping[str, Any]) -> str:
    """The id of a manifest: the sha256 of its canonical JSON, the id field left out."""
    return hashlib.sha256(
        canonical_json({key: value for key, value in fields.items() if key != "version"})
    ).hexdigest()


def make_tierset(**fields: Any) -> TierSet:
    """The manifest holding ``fields``, its format and its id.

    Raises:
        TierSetError: the fields do not make a manifest.
    """
    payload = {"format": FORMAT, **fields}
    try:
        return TierSet.model_validate_json(json.dumps({**payload, "version": version_id(payload)}))
    except ValidationError as exc:
        msg = f"not a manifest: {exc.errors()[0]['msg']}"
        raise TierSetError(msg, refused_because="manifest_invalid") from exc


def manifest_bytes(manifest: TierSet) -> bytes:
    """What ``tierset.json`` holds: the manifest's canonical JSON."""
    return canonical_json(manifest.model_dump(mode="json"))


def tier_record(path: Path, *, protected: bool) -> TierRecord:
    """The tier at ``path`` as a manifest records it, computed now from the bytes on disk.

    Read once, through descriptors (:func:`.heldout.snapshot`). A protected tier holds its
    tasks, its digest file, which must agree, and its canary list; the visible tier holds its
    tasks alone.

    Raises:
        TierSetError: the tier cannot be read whole, or holds what it must not.
    """
    try:
        files = snapshot(path)
    except (PerRoleError, OSError) as exc:
        msg = f"the {path.name} tier could not be read whole: {exc}"
        raise TierSetError(msg, refused_because="tier_unreadable") from exc
    loose = {name for name in files if "/" not in name}
    allowed = {SUMS_NAME, CANARIES_NAME} if protected else set()
    if loose - allowed or (protected and loose != allowed):
        msg = f"the {path.name} tier holds files other than its tasks, its digest and its list"
        raise TierSetError(msg, refused_because="tier_holds_other")
    sums = _sums(files)
    if protected and files[SUMS_NAME] != sums.encode():
        msg = f"the {path.name} tier is not the bytes its digest file records"
        raise TierSetError(msg, refused_because="tier_changed")
    return TierRecord(
        sha256=hashlib.sha256(sums.encode()).hexdigest(),
        count=len({name.partition("/")[0] for name in files if "/" in name}),
        canaries_sha256=hashlib.sha256(files[CANARIES_NAME]).hexdigest() if protected else None,
    )


def _read_record(dir_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        data = os.read(fd, MOST_RECORD_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MOST_RECORD_BYTES:
        msg = f"{name} is larger than any record of a version"
        raise TierSetError(msg, refused_because="manifest_unreadable")
    return data


def read_version(directory: Path) -> TierSet:
    """The manifest of the version at ``directory``, held to everything on disk.

    The directory is reached without following a link and holds exactly its manifest, its
    provenance record and its three tiers. The manifest's id is recomputed, and must be the
    directory's name; the provenance record's digest is recomputed; each tier's digest, count
    and list digest are recomputed from its bytes (:func:`tier_record`). Any difference
    refuses the version, with ``refused_because`` naming which.

    Raises:
        TierSetError: the version is not what its manifest says, or cannot be read.
    """

    def refuse(reason: str, detail: str) -> TierSetError:
        return TierSetError(f"the version {directory.name}: {detail}", refused_because=reason)

    try:
        fd = _open_chain(directory, make=False)
    except AuthoringError as exc:
        raise refuse("manifest_unreadable", "is reached through a link or is missing") from exc
    try:
        names = set(os.listdir(fd))
        if names != VERSION_HOLDS:
            raise refuse("version_holds_other", "holds other than its manifest and tiers")
        raw, provenance = _read_record(fd, MANIFEST_NAME), _read_record(fd, PROVENANCE_NAME)
    except OSError as exc:
        raise refuse("manifest_unreadable", f"cannot be read ({exc})") from exc
    finally:
        os.close(fd)
    try:
        manifest = TierSet.model_validate_json(raw)
    except ValidationError as exc:
        raise refuse("manifest_invalid", f"is no manifest: {exc.errors()[0]['msg']}") from exc
    if directory.name != manifest.version:
        raise refuse("version_misnamed", "is not named by its manifest's id")
    if hashlib.sha256(provenance).hexdigest() != manifest.provenance_sha256:
        raise refuse("provenance_changed", "its provenance record is not the one its id names")
    for name in TIERS:
        found = tier_record(directory / name, protected=name != "visible")
        stated = manifest.tier(name)
        if found.sha256 != stated.sha256:
            raise refuse("tier_changed", f"its {name} tier is not the bytes its manifest names")
        if found.count != stated.count:
            raise refuse("tier_count_changed", f"its {name} tier does not hold its count")
        if found.canaries_sha256 != stated.canaries_sha256:
            raise refuse("canary_list_changed", f"its {name} tier's list is not the one named")
    return manifest


# ------------------------------------------------------------------------ staleness


def brief_digest(role: Role) -> str:
    """The sha256 of the author brief as :func:`.authoring.author_brief` renders it today."""
    return hashlib.sha256(author_brief(role).encode()).hexdigest()


def requirements_source(role: Role) -> dict[str, Any]:
    """What the author brief draws its requirements from, as one record.

    The role's metrics and their units, the scorer's id and version, and the composition rule.

    Raises:
        AuthoringError: the role has no scorer for its own tasks yet.
    """
    if role != "control":
        msg = f"no scorer exists yet for the {role} role's own tasks"
        raise AuthoringError(msg, role=role)
    return {
        "role": role,
        "metrics": {**CONTROL_METRIC_UNITS, ACTUATOR_PEAK: f"the unit of {ACTUATOR_LIMIT}"},
        "scorer": {"id": "control", "version": CONTROL_SCORER_VERSION},
        "composes_at_least": COMPOSES_AT_LEAST,
    }


def requirements_digest(role: Role) -> str:
    """The sha256 of the canonical JSON of the role's requirements source."""
    return hashlib.sha256(canonical_json(requirements_source(role))).hexdigest()


@dataclass(frozen=True)
class Staleness:
    """Which of a version's tiers are stale, and why; nothing stale is ``()`` and ``()``."""

    tiers: tuple[str, ...]
    because: tuple[str, ...]


def staleness(manifest: TierSet) -> Staleness:
    """Whether the version ``manifest`` names was written to the question asked today.

    A changed author brief (``brief_changed``) or requirements source
    (``requirements_changed``) makes all three tiers stale: they were written, split and
    validated as one. A role whose brief cannot be rendered today is stale as well
    (``no_current_brief``): nothing says it is current.
    """
    try:
        brief, requirements = brief_digest(manifest.role), requirements_digest(manifest.role)
    except AuthoringError:
        return Staleness(tiers=TIERS, because=("no_current_brief",))
    because = tuple(
        reason
        for reason, differs in (
            ("brief_changed", manifest.brief_sha256 != brief),
            ("requirements_changed", manifest.requirements_sha256 != requirements),
        )
        if differs
    )
    return Staleness(tiers=TIERS if because else (), because=because)
