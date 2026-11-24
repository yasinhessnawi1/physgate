"""Each role's current tier version, published for the Evidence page as ``tiers status`` read it.

**Why a publication.** What the page shows of a version comes from places no folder of the
operator UI may reach: the check record lies in the role's root, and the exposure register and
its measurement lines beneath the role's withheld root. So the UI's server reads none of them.
A person runs the tiers command's own reader at a terminal (``physgate tiers status --store S
--publish DIR``), which holds every version's manifest to the tiers' bytes as it does today, and
the server serves what that wrote. Nothing here opens a tier or a task: it reads the command's
own answer (:func:`physgate.evaluation.tierset_cli.status`) and the register's measurement
lines (:func:`physgate.evaluation.tiers.exposure.measurements`), and keeps a few fields of them.

**The current version** of a role is its one ``fresh`` version: written to today's question and
not marked exposed. None fresh, more than one, or a version the reader refuses, and the role is
published as a refusal and no version is shown: which one is current cannot be told, and it is
never guessed. Since an exposure makes a version stale, the version shown is ``fresh`` and its
exposure ``none`` for as long as that is the rule; both are published all the same, so a page
says them rather than leaves them to be inferred.

**The record is closed.** One file per role, :func:`published_name`, holding exactly one of two
shapes, each with an exact key set and every value of a fixed type:

- read: ``role``, ``read_at``, ``version`` (the manifest's own id), ``counts`` (the three tiers'
  task counts), ``check`` (``null`` when the version has no blind check and so is not scored,
  the check's counts and where its answer came from, or a closed word saying why its record is
  refused), ``exposure`` (a closed word), ``version_state`` (``fresh`` or ``stale``) and
  ``measured`` (whether a measurement whose results anyone sees names the version; a probe is
  not one);
- refused: ``role``, ``read_at`` and ``refused``, a closed word (:data:`SENTENCES`).

No string is free: every one is a closed word, the version id or the time it was read. No task
id, brief, canary, path, tier or canary-list digest, check digest, register line or number from
a run is published, and no sentence of an error is: a refusal is published as its word alone,
and the page is given the sentence for that word from :data:`SENTENCES`. The blind check's
counts are a property of the tier fixed before any result exists; ``measured`` is one bit.

**Where it is written.** Into a folder of its own, judged exactly as the gap trend's
publication judges one (:func:`physgate.evaluation.gaps.published.folder_refusal`), and never
into the gap trend's own folder: a folder holding a published gap trend is refused. It is
written by a person, never inside a harness session. A publish that fails once the folder is
judged publishes the failure in place of the copy before it, so no older copy reads as current.

**Its parser** (:func:`read_published_status`) refuses anything its writer could not have
written: a file over :data:`MOST_STATUS_BYTES`, a cut file, a key it does not know at any
depth, a value of another kind, a broken count, another role's file. Its refusals are its own
fixed sentences and never repeat what the file holds.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast, get_args

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from physgate.evaluation import tierset_cli
from physgate.evaluation.gaps import published as gap_publication
from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers import exposure
from physgate.evaluation.tiers.task import Sha256

__all__ = [
    "MOST_STATUS_BYTES",
    "ROLES",
    "SENTENCES",
    "TierStatusError",
    "TierStatusRead",
    "TierStatusRefused",
    "publish_status",
    "published_name",
    "read_for_publication",
    "read_published_status",
    "refusal_sentence",
]

#: The roles a tier status is published for, in the order a page shows them.
StatusRole = Literal["control", "firmware"]
ROLES: tuple[StatusRole, ...] = get_args(StatusRole)
#: The most bytes a publication is read to: a record of a role is a few hundred.
MOST_STATUS_BYTES = 4 * 1024

#: Why a role's status is published as a refusal, and the one sentence a page says for each.
Reason = Literal[
    "store_unreadable",
    "register_unreadable",
    "version_refused",
    "no_fresh_version",
    "fresh_versions_several",
    "publish_failed",
]
SENTENCES: Mapping[str, str] = {
    "store_unreadable": (
        "The tier store could not be read when the status was published, so no version is "
        "shown. Read the status at a terminal to see why, then publish it again."
    ),
    "register_unreadable": (
        "The role's exposure register could not be read whole when the status was published, "
        "so whether a version was seen cannot be told, and none is shown."
    ),
    "version_refused": (
        "A version of this role is not what its manifest says, so which version is current "
        "cannot be told, and none is shown."
    ),
    "no_fresh_version": (
        "No version of this role is fresh (written to today's question and not seen), so none "
        "is shown."
    ),
    "fresh_versions_several": (
        "More than one version of this role is fresh, so which one is current cannot be told, "
        "and none is shown."
    ),
    "publish_failed": (
        "The status could not be read for publishing, so nothing of it is shown. Read it at a "
        "terminal to see why, then publish it again."
    ),
}
#: Why a version's check record is refused, as the check records name it; any other word is
#: published as ``check_record_unreadable``.
CheckReason = Literal[
    "check_record_changed",
    "check_record_invalid",
    "check_record_not_the_version",
    "check_record_unreadable",
    "check_record_unsynced",
    "check_record_unwritten",
]
Exposure = Literal["none", "exposed", "exposed_unchecked"]
VersionState = Literal["fresh", "stale"]
Count = Annotated[int, Field(ge=0)]

#: What the register's measurement of a version is that does not make it measured: the
#: isolation probe scores answers built for one requirement alone, and is no run.
NOT_A_RUN = frozenset({"probe"})
#: The words ``tiers status`` refuses a version with when the role's register is not read whole.
REGISTER_REFUSALS = frozenset({"register_unreadable", "register_missing", "version_unknown"})
#: The gap trend's own publications, which a folder holding the tier status may not hold.
GAP_TREND_NAMES = frozenset(gap_publication.published_name(role) for role in ROLES)


class TierStatusError(PerRoleError):
    """The status cannot be published as asked, or a publication is not one its writer wrote."""


def _refuse(reason: str, msg: str) -> TierStatusError:
    return TierStatusError(msg, refused_because=reason)


class _Closed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Counts(_Closed):
    """The three tiers' task counts, as the version's manifest records them."""

    visible: Count
    validation: Count
    held_out: Count


class Check(_Closed):
    """The version's blind check, by its counts alone, and where its answer came from."""

    tasks: Annotated[int, Field(ge=1)]
    all_yes: Count
    left_out: Count
    source: Literal["check", "imported"]


class CheckRefused(_Closed):
    """The version's check record is refused as read: why, in a closed word."""

    refused: CheckReason


class TierStatusRead(_Closed):
    """A role's current version as ``tiers status`` read it at ``read_at``."""

    role: StatusRole
    read_at: AwareDatetime
    version: Sha256
    counts: Counts
    check: Check | CheckRefused | None
    exposure: Exposure
    version_state: VersionState
    measured: bool

    @model_validator(mode="after")
    def _holds_its_counts(self) -> TierStatusRead:
        check = self.check
        if isinstance(check, Check) and not (
            check.all_yes + check.left_out == check.tasks == self.counts.held_out
        ):
            msg = "the check's counts are not every task of the held-out tier"
            raise ValueError(msg)
        if self.exposure != "none" and self.version_state != "stale":
            msg = "an exposed version is stale"
            raise ValueError(msg)
        return self


class TierStatusRefused(_Closed):
    """A role whose current version cannot be told, or read: why, in a closed word."""

    role: StatusRole
    read_at: AwareDatetime
    refused: Reason


TierStatus = TierStatusRead | TierStatusRefused
_PUBLICATION: TypeAdapter[TierStatus] = TypeAdapter(TierStatus)


def published_name(role: str) -> str:
    """The name a role's publication is written under, and found under at the top of a root."""
    return f"tier-status-{role}.json"


def refusal_sentence(reason: str) -> str:
    """The sentence a page says for a role published as refused for ``reason``."""
    return SENTENCES.get(reason, SENTENCES["publish_failed"])


def _closed_check_reason(reason: object) -> CheckReason:
    if reason in get_args(CheckReason):
        return cast("CheckReason", reason)
    return "check_record_unreadable"


def _check(found: Mapping[str, Any] | None) -> Check | CheckRefused | None:
    """The check as ``tiers status`` gives it, cut to what is published."""
    if found is None:
        return None
    if "refused_because" in found:
        return CheckRefused(refused=_closed_check_reason(found["refused_because"]))
    return Check(
        tasks=found["tasks"],
        all_yes=found["all_yes"],
        left_out=found["flagged"],
        source=found["source"],
    )


def _exposure(because: Sequence[str]) -> Exposure:
    """The exposure word ``tiers status`` gives a version, by the reasons it is stale."""
    if "exposed" in because:
        return "exposed"
    if "exposed_unchecked" in because:
        return "exposed_unchecked"
    return "none"


def _role_status(
    store: Path, role: StatusRole, versions: Sequence[Mapping[str, Any]], read_at: datetime
) -> TierStatus:
    """The role's one fresh version as read, or why there is not exactly one."""
    mine = [v for v in versions if v["role"] == role]

    def refused(reason: Reason) -> TierStatusRefused:
        return TierStatusRefused(role=role, read_at=read_at, refused=reason)

    unread = [reason for v in mine if v["state"] == "refused" for reason in v["because"]]
    if unread:
        # ``tiers status`` refuses every version of a role whose register it cannot read.
        if any(reason in REGISTER_REFUSALS for reason in unread):
            return refused("register_unreadable")
        return refused("version_refused")
    fresh = [v for v in mine if v["state"] == "fresh"]
    if not fresh:
        return refused("no_fresh_version")
    if len(fresh) > 1:
        return refused("fresh_versions_several")
    (found,) = fresh
    version = str(found["version"])
    measured = any(
        line.version == version and line.measured not in NOT_A_RUN
        for line in exposure.measurements(store, role)
    )
    tiers = found["tiers"]
    return TierStatusRead(
        role=role,
        read_at=read_at,
        version=version,
        counts=Counts(
            visible=tiers["visible"]["count"],
            validation=tiers["validation"]["count"],
            held_out=tiers["held_out"]["count"],
        ),
        check=_check(found["check"]),
        exposure=_exposure(found["because"]),
        version_state=found["state"],
        measured=measured,
    )


def read_for_publication(store: Path, *, now: datetime | None = None) -> tuple[TierStatus, ...]:
    """Each role's status in ``store`` as ``tiers status`` reads it now, or why it is refused.

    Never raises for what the store holds: any failure of the read is published as a refusal.
    """
    read_at = now or datetime.now(UTC)
    whole: Reason
    try:
        versions = tierset_cli.status(store)["versions"]
    except OSError:
        whole = "store_unreadable"
    except exposure.ExposureError:
        whole = "register_unreadable"
    except Exception:  # noqa: BLE001 - any failure is published, never its words
        whole = "publish_failed"
    else:
        found: list[TierStatus] = []
        for role in ROLES:
            reason: Reason
            try:
                found.append(_role_status(store, role, versions, read_at))
                continue
            except exposure.ExposureError:
                reason = "register_unreadable"
            except Exception:  # noqa: BLE001 - any failure is published, never its words
                reason = "publish_failed"
            found.append(TierStatusRefused(role=role, read_at=read_at, refused=reason))
        return tuple(found)
    return tuple(TierStatusRefused(role=role, read_at=read_at, refused=whole) for role in ROLES)


def _inside_a_session() -> None:
    found = sorted(name for name in gap_publication.SESSION_MARKERS if name in os.environ)
    if found:
        msg = f"the tier status is published by a person, never from a session ({', '.join(found)})"
        raise _refuse("inside_a_session", msg)


def _beside_the_gap_trend(out: Path) -> str | None:
    """Why ``out`` is the gap trend's folder, or ``None``.

    Raises:
        OSError: ``out`` cannot be listed.
    """
    with os.scandir(out) as entries:
        held = sorted(entry.name for entry in entries if entry.name in GAP_TREND_NAMES)
    if held:
        return (
            "the folder to publish into holds the published gap trend; the tier status is "
            "published into a folder of its own"
        )
    return None


def publish_status(
    store: Path, *, out: Path, now: datetime | None = None
) -> tuple[TierStatus, ...]:
    """Publish each role's status, as ``tiers status`` reads ``store`` now, into ``out``.

    Every role's file is written, whole; a role whose status is refused is published as that
    refusal, in place of whatever was there.

    Raises:
        TierStatusError: asked for inside a harness session; ``out`` is not a folder of its own
            (judged as the gap trend's publication judges one) or holds the gap trend; or a
            file cannot be written, and the copy before it is then removed.
    """
    _inside_a_session()
    folder, home = Path(out), Path(store)
    refusal = gap_publication.folder_refusal(folder, home, gap_publication.known_places())
    if refusal is None:
        try:
            refusal = _beside_the_gap_trend(folder)
        except OSError:
            refusal = "the folder to publish into cannot be listed"
    if refusal is not None:
        msg = f"{refusal}. {gap_publication.WHERE_TO_PUBLISH}"
        raise _refuse("publish_refused", msg)
    records = read_for_publication(home, now=now)
    for record in records:
        data = record.model_dump_json().encode() + b"\n"
        try:
            gap_publication.write_whole(
                folder, published_name(record.role), data, what="the tier status"
            )
        except gap_publication.GapsError as exc:
            raise _refuse("publish_failed", str(exc)) from None
    return records


def read_published_status(data: bytes, role: str) -> TierStatus:
    """The publication ``data`` of ``role``, as its writer wrote it.

    Raises:
        TierStatusError: it is over its size bound, cut, holds a key or a value its writer could
            not have written, or is another role's. The sentence is fixed, and repeats nothing
            the file holds.
    """
    if len(data) > MOST_STATUS_BYTES:
        msg = (
            f"the published tier status is over {MOST_STATUS_BYTES} bytes, which no status its "
            "writer publishes reaches; publish it again"
        )
        raise _refuse("publication_unreadable", msg)
    try:
        published = _PUBLICATION.validate_json(data)
    except ValidationError:
        msg = (
            "the published tier status is not a file the publish command wrote: it was cut, "
            "edited or written by something else; publish it again"
        )
        raise _refuse("publication_unreadable", msg) from None
    if published.role != role:
        msg = f"the published tier status under the {role} role's name is another role's"
        raise _refuse("publication_unreadable", msg)
    return published
