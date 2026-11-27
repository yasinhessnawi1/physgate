"""What a baseline round was bound to and what it found: counts and digests, never a task.

Two records, each written once, as a new file:

- ``<out>/evaluation/tiers.json``: the tier version the round ran on and each tier's digest,
  as the version's manifest names them (:class:`TiersRecord`). The record a comparison of two
  runs reads beside each to refuse runs on different tiers.
  A round on a version leaves out the held-out tasks its blind check flagged (it runs none of
  them), and the record says which (``held_out_left_out``), beside the held-out count.
- ``<out>/baseline.json``: the round's record (:class:`BaselineRecord`): the tier version and
  digests, the pin set every raw session ran under with its digest, and per tier the trials,
  their outcomes and excluded trials counted, the caps and tokens spent summed, and how many of
  the tier's tasks it covered, of how many, and whether that is the whole tier: a round on part
  of a tier is run and recorded so, and is no figure of the tier (:func:`tier_figure`). A
  baseline is bound to the version id and the pin-set digest: a comparison against a harness
  run set on another version, or under another pin, is no comparison with this baseline.

A round on an external task set (a published benchmark's tasks, ARCH-143) writes
``<out>/evaluation/external.json`` (:class:`ExternalSetRecord`: the benchmark, the task count
and the set's digest) in place of ``tiers.json``, and counts its trials under ``external``
alone: the set is a source of its own, never a fourth tier of a version.

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

from pydantic import Field, StringConstraints, model_validator

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.base import Identifier, _Frozen
from physgate.evaluation.tiers.checks import LeftOutSaid
from physgate.evaluation.tiers.manifest import TierSet
from physgate.evaluation.tiers.task import Role, Sha256, canonical_json

#: The pins that name the task a session ran on, not the conditions it ran under.
PER_TASK_PINS = frozenset({"brief_sha256", "answer"})
#: The pins that name the trial's own places, new for each trial or round: the trial's place in
#: the store's work root, and the round's own directory withheld besides.
PER_TRIAL_PINS = frozenset({"held_out_carved", "held_out_also"})
TIERS_RECORD = Path("evaluation") / "tiers.json"
EXTERNAL_RECORD = Path("evaluation") / "external.json"
BASELINE_RECORD = "baseline.json"
Count = Annotated[int, Field(ge=0)]
#: What a round counts its trials under: a tier version's three tiers, or an external set.
SourceTier = Literal["visible", "validation", "held_out", "external"]
VERSION_TIERS: tuple[SourceTier, ...] = ("visible", "validation", "held_out")
EXTERNAL_TIERS: tuple[SourceTier, ...] = ("external",)


class BaselineRecordError(PerRoleError):
    """A baseline's record could not be written as a new file, or its trials disagree."""


class TiersRecord(_Frozen):
    """The tier version a run ran on, and each tier's digest as its manifest names it.

    And how many held-out tasks its version's blind check flagged, which the round left out of
    its held-out count and did not run, with the check record's digest and its source; never
    which, since a run's directory may be published. Two records on one version that name
    different check records are no comparison. Left out of the bytes of a record written before
    there was any.
    """

    format: Literal[1]
    version: Sha256
    role: Role
    visible: Sha256
    validation: Sha256
    held_out: Sha256
    held_out_left_out: LeftOutSaid | None = Field(default=None, exclude_if=lambda v: v is None)


class ExternalSetRecord(_Frozen):
    """The external task set a round ran on: one benchmark's published tasks, apart from the tiers.

    ``sha256`` is the set's directory's digest, as a tier's is taken, so a changed set is
    another set; a round on it is no baseline for runs on this one.
    """

    format: Literal[1]
    benchmark: Identifier
    role: Role
    tasks: Annotated[int, Field(ge=1)]
    sha256: Sha256


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
    #: The tokens the sessions' records count, as the run's account counts them.
    spent: Count
    #: The tokens of responses the binary cut short that its totals left out: in no session's
    #: count, their billing unknown. Where it is above 0, ``spent`` is a lower bound by up to
    #: that much. Left out of a tier with none, so such a tier keeps its bytes.
    spent_not_in_binary_totals: Count = Field(default=0, exclude_if=lambda v: not v)
    #: How many of the tier's tasks the round ran, those its version's check left out not
    #: among them; of how many such tasks the tier holds; and whether that is all of them. A
    #: round is held to the harness runs it is given, which may be of part of a tier: it runs
    #: them, and says so here. Left out of a record written before records said it, which is
    #: then no tier's figure (:func:`tier_figure`).
    covered: Count | None = Field(default=None, exclude_if=lambda v: v is None)
    of: Count | None = Field(default=None, exclude_if=lambda v: v is None)
    whole: bool | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def _coverage_holds_together(self) -> TierCounts:
        said = (self.covered, self.of, self.whole)
        if said == (None, None, None):
            return self
        if (
            self.covered is None
            or self.of is None
            or self.covered > self.of
            or self.whole != (self.covered == self.of)
        ):
            msg = (
                "a tier's coverage does not hold together: it says how many tasks were covered, "
                "of how many, and is whole exactly when those are equal"
            )
            raise ValueError(msg)
        return self


class BaselineRecord(_Frozen):
    """One baseline round: what it was bound to, and what it found, counted."""

    format: Literal[1]
    #: The round's own id: names its place beneath the withheld root, and nothing else.
    id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    created: Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    #: The tier version the round ran on; ``None`` for a round on an external set.
    tiers: TiersRecord | None
    #: The external set the round ran on; ``None`` for a round on a tier version.
    external: ExternalSetRecord | None
    pins: dict[str, Any]
    pin_set_sha256: Sha256
    #: Whether the round was a development one: held to harness runs that need not be
    #: reportable or from a clean checkout. Such a round is no baseline for a reported
    #: comparison, whatever runs it happened to be held to.
    development: bool
    harness_runs: Count
    counts: dict[SourceTier, TierCounts]
    #: Set where the round ran on a practice version, which it did only when told it was a
    #: shakedown: such a round is no baseline of any measurement. Left out otherwise, so every
    #: record keeps its bytes.
    practice: Literal[True] | None = Field(default=None, exclude_if=lambda v: v is None)
    #: Where the round is the once-more of an earlier round's entry: that round's id and
    #: directory, the entry's place in its run set, its last session, and why it is run again.
    #: The earlier record is kept and never counted. Left out otherwise.
    rerun_of: dict[str, Any] | None = Field(default=None, exclude_if=lambda v: v is None)
    #: Per tier, how many of the round's entries gave no figure of their own and ran under a
    #: cap the cell's rule took from other trials (:mod:`.caps`), and of how many entries. Left
    #: out of a round where every entry had its own figure.
    no_figure: dict[SourceTier, dict[str, int]] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def _one_source_and_its_tiers(self) -> BaselineRecord:
        if (self.tiers is None) == (self.external is None):
            msg = "a baseline record names one source: a tier version or an external task set"
            raise ValueError(msg)
        wanted = VERSION_TIERS if self.external is None else EXTERNAL_TIERS
        if set(self.counts) != set(wanted):
            msg = "a baseline record counts exactly its source's tiers"
            raise ValueError(msg)
        return self


def tier_figure(record: BaselineRecord, tier: SourceTier) -> TierCounts:
    """A round's counts of ``tier``, as a figure of the tier: only of all of it.

    The one door through which a round's record becomes a figure of a tier (a pass rate, a gap,
    a comparison): a tier's figure is of every task of it but those its version's check left
    out, never of a part chosen by which runs were made, as the harness side's counting rule
    holds (:func:`physgate.evaluation.tiers.measure.census`).

    Raises:
        BaselineRecordError: the round did not cover the whole tier, or its record does not say
            (``tier_not_covered``); or the record counts no such tier.
    """
    counts = record.counts.get(tier)
    if counts is None:
        msg = f"the round counts no {tier} tier"
        raise BaselineRecordError(msg, refused_because="tier_not_in_round")
    if counts.whole is not True:
        known = (
            "does not say how much of it it covered"
            if counts.whole is None
            else f"covered {counts.covered} of its {counts.of} tasks that are not left out"
        )
        msg = (
            f"the round {known} of the {tier} tier: a tier's figure covers every task of it but "
            "those its check left out"
        )
        raise BaselineRecordError(msg, refused_because="tier_not_covered")
    return counts


def tiers_record(manifest: TierSet, left: LeftOutSaid | None = None) -> TiersRecord:
    """The tiers record of the version ``manifest`` names, from the manifest's own digests.

    ``left``: how many held-out tasks its check flagged, which the round left out.
    """
    return TiersRecord(
        format=1,
        version=manifest.version,
        role=manifest.role,
        visible=manifest.visible.sha256,
        validation=manifest.validation.sha256,
        held_out=manifest.held_out.sha256,
        held_out_left_out=left,
    )


def pin_set(pins: Mapping[str, Any]) -> dict[str, Any]:
    """The pins a raw session ran under, without those that name its task or its place."""
    return {
        name: value for name, value in pins.items() if name not in PER_TASK_PINS | PER_TRIAL_PINS
    }


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


def record_bytes(record: TiersRecord | ExternalSetRecord | BaselineRecord) -> bytes:
    """A record's bytes as written: its canonical JSON, one line."""
    return canonical_json(record.model_dump(mode="json"))
