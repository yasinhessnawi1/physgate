"""The anonymous per-task vector: how a protected tier's results reach the gaps.

A vector holds, for each task of a protected tier that a run set measured, its passes and its
trials (and how many of those were unscored or flaky, which count as fails), in an order
shuffled afresh when it was written, with no task id, no digest of a brief, no timing and no
cost: the task-cluster bootstrap needs per-task values only. Beside them, what binds it to its
measurement: the version and the tier's digest, the digests of the run set and of the trial
records it was read from, the digest of the configuration its runs shared, and the harness
commits and accounts they ran on. Its key is the digest of its own bytes; the register's
measurement line for it carries that key.

This module holds the schema and its reader only. The vector is written on the harness side,
beneath the role's withheld root (:func:`physgate.evaluation.tiers.measure.write_vector`).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.evaluation.per_role.exceptions import PerRoleError
from physgate.evaluation.tiers.checks import LeftOut

#: The directory beneath a role's withheld root that holds the role's vectors.
VECTORS = "gaps"
#: The vector's form as written now. In form 1 the configuration digest held every held-out
#: root's digest, the role's withheld root's among them, which any register line, vector or
#: trend line changes; from form 2 it holds the protected tiers' only, and whether each role
#: root's withheld and work roots were named, as ``compare`` does. From form 3 a held-out vector
#: leaves out the tasks its version's blind check flagged, and says which (``left_out``). An
#: earlier form is still read, and refused where it would be compared.
VECTOR_FORMAT: Literal[3] = 3
#: The most bytes a vector is read to: a vector of a tier of thousands of tasks is far less.
MOST_VECTOR_BYTES = 1024 * 1024

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Sha1 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Count = Annotated[int, Field(ge=0)]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class GapsError(PerRoleError):
    """The gaps cannot be read or written as asked, for a reason it names: never a task."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class TaskOutcome(_Frozen):
    """One task's trials: how many passed, and how many were unscored or flaky (fails)."""

    passes: Count
    trials: Annotated[int, Field(ge=1)]
    unscored: Count
    flaky: Count


class GapVector(_Frozen):
    """A protected tier's per-task outcomes, with nothing that names a task."""

    #: 1, 2 or :data:`VECTOR_FORMAT`; it says what ``drift_sha256`` was made from, and whether
    #: a held-out vector left out what its blind check flagged.
    format: Literal[1, 2, 3]
    role: Literal["control", "firmware"]
    arm: Literal["harness"]
    tier: Literal["held_out", "validation"]
    version: Sha256
    tier_sha256: Sha256
    run_set_sha256: Sha256
    trials_sha256: Sha256
    #: The digest of the configuration fields every run of the role and arm shares, as the
    #: counting rule compares them: in form 1 with every held-out root's digest, from form 2 with
    #: the protected tiers' only and whether each role root's withheld and work roots were named.
    drift_sha256: Sha256
    harness_commits: tuple[Sha1, ...] = Field(min_length=1)
    accounts: tuple[Name, ...]
    tasks: tuple[TaskOutcome, ...] = Field(min_length=1)
    #: Of a held-out vector from form 3: the tasks its version's check flagged, left out of
    #: ``tasks``, by digest, with the check record's digest. ``None`` of a validation vector,
    #: which is counted whole, and of an earlier form's.
    left_out: LeftOut | None = None

    @model_validator(mode="after")
    def _says_what_it_left_out(self) -> GapVector:
        # Whatever its form: a vector that carries what it left out is a held-out vector of a
        # form that leaves out, and one of that form says it whenever it is a held-out one.
        carries = self.left_out is not None
        if carries and (self.tier != "held_out" or self.format < VECTOR_FORMAT):
            msg = "only a held-out vector of a form that leaves tasks out says what it left out"
            raise ValueError(msg)
        if self.format >= VECTOR_FORMAT and carries != (self.tier == "held_out"):
            msg = "a held-out vector says what it left out, and a validation vector leaves none"
            raise ValueError(msg)
        return self


def vector_key(raw: bytes) -> str:
    """The key of the vector whose bytes are ``raw``: their digest."""
    return hashlib.sha256(raw).hexdigest()


def read_vector(path: Path) -> tuple[GapVector, str]:
    """The vector at ``path`` and its key, held to the name it is filed under.

    Raises:
        GapsError: it cannot be read, is not a vector, or its bytes are not its name's key.
    """
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MOST_VECTOR_BYTES + 1)
    except OSError as exc:
        msg = f"the vector cannot be read: {exc.strerror}"
        raise GapsError(msg, refused_because="vector_unreadable") from None
    if len(raw) > MOST_VECTOR_BYTES:
        msg = "the vector is larger than any vector is"
        raise GapsError(msg, refused_because="vector_unreadable")
    key = vector_key(raw)
    if Path(path).name != f"{key}.json":
        msg = "the vector's bytes are not the key it is filed under"
        raise GapsError(msg, refused_because="vector_unreadable")
    try:
        return GapVector.model_validate_json(raw), key
    except ValidationError:
        msg = "the file is not a vector"
        raise GapsError(msg, refused_because="vector_unreadable") from None
