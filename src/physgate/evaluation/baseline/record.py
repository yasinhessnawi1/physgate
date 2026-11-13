"""What a baseline round was bound to and what it found: counts and digests, never a task.

Two records, each written once, as a new file:

- ``<out>/evaluation/tiers.json``: the tier version the round ran on and each tier's digest,
  as the version's manifest names them (:class:`TiersRecord`). The record a comparison of two
  runs reads beside each to refuse runs on different tiers.
- ``<out>/baseline.json``: the round's record (:class:`BaselineRecord`): the tier version and
  digests, the pin set every raw session ran under with its digest, and per tier the trials,
  their outcomes and excluded trials counted, and the caps and tokens spent summed. A
  baseline is bound to the version id and the pin-set digest: a comparison against a harness
  run set on another version, or under another pin, is no comparison with this baseline.

The pin set is every pin the raw arm records but those that name the task (its brief's digest
and its answer contract), which differ from trial to trial by design. Every trial of a round
ran under one pin set, or the round is refused.

Nothing here names a task: a held-out or validation task's id, brief, answer or outcome lies
beneath the role's withheld root only (:mod:`.runner`).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import _Frozen
from physgate.evaluation.tiers.manifest import TierSet
from physgate.evaluation.tiers.task import Role, Sha256, canonical_json

#: The pins that name the task a session ran on, not the conditions it ran under.
PER_TASK_PINS = frozenset({"brief_sha256", "answer"})
TIERS_RECORD = Path("evaluation") / "tiers.json"
BASELINE_RECORD = "baseline.json"
Count = Annotated[int, Field(ge=0)]


class BaselineRecordError(PerRoleError):
    """A baseline's record could not be written as a new file, or its trials disagree."""


class TiersRecord(_Frozen):
    """The tier version a run ran on, and each tier's digest as its manifest names it."""

    format: Literal[1]
    version: Sha256
    role: Role
    visible: Sha256
    validation: Sha256
    held_out: Sha256


class TierCounts(_Frozen):
    """One tier's trials in a round: outcomes counted, caps and tokens spent summed."""

    trials: Count
    passed: Count
    failed: Count
    flaky: Count
    unscored: Count
    #: Trials whose own records said not to take them; never a pass or a fail.
    excluded: Count
    cap: Count
    spent: Count


class BaselineRecord(_Frozen):
    """One baseline round: what it was bound to, and what it found, counted."""

    format: Literal[1]
    #: The round's own id: names its place beneath the withheld root, and nothing else.
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    created: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    tiers: TiersRecord
    pins: dict[str, Any]
    pin_set_sha256: Sha256
    #: Whether the round was a development one: held to harness runs that need not be
    #: reportable or from a clean checkout. Such a round is no baseline for a reported
    #: comparison, whatever runs it happened to be held to.
    development: bool
    harness_runs: Count
    counts: dict[Literal["visible", "validation", "held_out"], TierCounts]


def tiers_record(manifest: TierSet) -> TiersRecord:
    """The tiers record of the version ``manifest`` names, from the manifest's own digests."""
    return TiersRecord(
        format=1,
        version=manifest.version,
        role=manifest.role,
        visible=manifest.visible.sha256,
        validation=manifest.validation.sha256,
        held_out=manifest.held_out.sha256,
    )


def pin_set(pins: Mapping[str, Any]) -> dict[str, Any]:
    """The pins a raw session ran under, without those that name its task."""
    return {name: value for name, value in pins.items() if name not in PER_TASK_PINS}


def pin_set_sha256(pins: Mapping[str, Any]) -> str:
    """The digest a baseline is bound to: of its pin set's canonical JSON."""
    return hashlib.sha256(canonical_json(dict(pins))).hexdigest()


def write_new(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` as a new file; one already there is never replaced.

    Raises:
        BaselineRecordError: ``path`` exists (an earlier record is kept, never overwritten).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        msg = "a record is there already; a baseline's records are written once and kept"
        raise BaselineRecordError(msg, path=str(path)) from None
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def record_bytes(record: TiersRecord | BaselineRecord) -> bytes:
    """A record's bytes as written: its canonical JSON, one line."""
    return canonical_json(record.model_dump(mode="json"))
