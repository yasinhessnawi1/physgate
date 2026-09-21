"""The shape of a graph node, validated at every boundary.

The architecture's node shape is the authority here, and it is stricter than the
guard the store comparison measured: that guard checked only that a unit string
was present, while the architecture's node carries a value, a unit, a source and
the role that wrote it. All four are mandatory, extras are refused, and the value
must be a number. Verified against the frozen workload before this was written:
across its five seeds there are exactly two quantity shapes, the full four on
every legal quantity and those minus the unit on every deliberately faulty one,
so the stricter model accepts every legal write and refuses every faulty one
exactly as the looser guard did.

Validation is strict rather than coercing, which was a deliberate choice and is
measured in the tests: in the coercing mode the string ``"2.4"``, the boolean
``True``, ``NaN`` and infinity are all accepted as the value of a quantity. Every
one of those would reach the physics gate as a number it could do arithmetic on,
and two of them are not numbers at all. An integer is still accepted, because
JSON has no way to say that ``2`` is a float.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.state.exceptions import MalformedNodeIdError, MissingUnitError

#: A node id is a dotted identifier. The graph stores one file per node and
#: names that file after the id, so anything carrying a separator, a parent
#: reference or an absolute path would write outside the graph directory. Ids
#: come from agents, so this is untrusted input and the pattern is a whitelist
#: rather than a list of things to reject.
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
NODE_ID_MAX_LENGTH = 128

NodeKind = Literal["component", "module", "requirement", "interface"]

#: The architecture enumerates the domain in exactly the notation it uses for
#: the kind, and the physics gate routes on it, so it is closed the same way.
DomainKind = Literal["mechanical", "electrical", "control", "firmware", "cross"]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


class Quantity(BaseModel):
    """One physical quantity: a number, its unit, where it came from, who wrote it.

    A bare number is not a quantity. Neither is a number with an empty unit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)

    value: float | int
    unit: NonEmptyStr
    source: NonEmptyStr
    written_by: NonEmptyStr


class Node(BaseModel):
    """One node of the design-state graph."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: Annotated[str, Field(max_length=NODE_ID_MAX_LENGTH)]
    kind: NodeKind
    domain: DomainKind
    owner_role: NonEmptyStr
    quantities: dict[str, Quantity] = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list)
    constrains: list[str] = Field(default_factory=list)
    model: str | None = None
    geometry_hash: NonEmptyStr
    updated: NonEmptyStr


def validate_node_id(node_id: object) -> str:
    """Return ``node_id`` if it is a legal identifier, else raise.

    Raises:
        MalformedNodeIdError: the id is not a string, is too long, or does not
            match the dotted-identifier pattern.
    """
    if not isinstance(node_id, str):
        msg = "node id is not a string"
        raise MalformedNodeIdError(msg, node_id=repr(node_id))
    if len(node_id) > NODE_ID_MAX_LENGTH:
        msg = "node id is too long"
        raise MalformedNodeIdError(msg, node_id=node_id[:64], length=str(len(node_id)))
    if not NODE_ID_PATTERN.match(node_id):
        msg = "node id is not a dotted identifier"
        raise MalformedNodeIdError(msg, node_id=node_id)
    return node_id


def quantities_are_valid(payload: dict[str, Any]) -> bool:
    """True if every quantity in ``payload`` is a well-formed quantity.

    Separate from :class:`Node` because the store reports a quantity fault as a
    rejection with the frozen reason string, not as a raise.
    """
    quantities = payload.get("quantities") or {}
    if not isinstance(quantities, dict):
        return False
    for entry in quantities.values():
        try:
            Quantity.model_validate(entry)
        except Exception:  # noqa: BLE001 - any validation failure is the answer
            return False
    return True


def validate_node(payload: dict[str, Any]) -> Node:
    """Validate a whole node payload.

    Raises:
        MalformedNodeIdError: the id is not a legal identifier.
        MissingUnitError: a quantity is not a well-formed quantity.
    """
    validate_node_id(payload.get("id"))
    if not quantities_are_valid(payload):
        msg = "a quantity is missing its unit, its number, or carries an unknown field"
        raise MissingUnitError(msg, node_id=str(payload.get("id")))
    return Node.model_validate(payload)
