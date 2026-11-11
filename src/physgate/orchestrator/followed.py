"""The record of one followed interface revision, apart from its derivation.

Kept apart from :mod:`physgate.orchestrator.follow`, which derives it through the contract clause
and so loads pint: the run's records and the reviewer's artefact carry this shape, and a hook that
reads them may not load pint.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.state.store import payload_digest
from physgate.state.store import written as written

_Id = Annotated[str, StringConstraints(min_length=1)]
_Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FollowedInterface(BaseModel):
    """One interface revision derived at a change check, with everything it was derived from.

    ``before`` is the interface as the store held it, ``joined_payloads`` each joined node's
    payload as the attempt proposed it, in id order, and ``after`` the derived revision, whose
    digest is ``payload_sha256``: what replay derives again and binds to the write intents.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    interface: _Id
    attempt: Annotated[int, Field(ge=1)]
    joined: Annotated[tuple[_Id, ...], Field(min_length=1)]
    before: dict[str, Any]
    joined_payloads: Annotated[tuple[dict[str, Any], ...], Field(min_length=1)]
    after: dict[str, Any]
    payload_sha256: _Sha256

    @model_validator(mode="after")
    def _the_parts_name_each_other(self) -> FollowedInterface:
        ids = tuple(str(p.get("id")) for p in self.joined_payloads)
        if (
            self.joined != ids
            or self.before.get("id") != self.interface
            or self.after.get("id") != self.interface
            or payload_digest(self.after) != self.payload_sha256
        ):
            msg = (
                "a followed interface names its joined nodes as their payloads do, the interface "
                "it revises on both sides, and the digest of its revision"
            )
            raise ValueError(msg)
        return self

    def changed(self) -> tuple[tuple[str, dict[str, Any], dict[str, Any]], ...]:
        """Each quantity whose value or unit differs: its name, then before and after."""
        old, new = self.before.get("quantities", {}), self.after.get("quantities", {})
        return tuple(
            (name, old[name], new[name])
            for name in sorted(new)
            if name in old and written(old[name]) != written(new[name])
        )
