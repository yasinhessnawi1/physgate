"""A sizing-produced interface follows sizing's joined node at the opening pass (D-A2-37).

The decomposition writes each interface node's values as its forecast of the work. For an
interface the cross-nodes owner produces, the forecast is replaced once, by code, with what that
owner's opening pass computed: at the change check of an attempt of its opening subtask, and only
while no subtask of any other module has spawned, each quantity of the interface takes the value
and unit of the attempt's nodes joined to it (a ``constrains`` edge either way, the contract
clause's join, :func:`physgate.contracts.clause.joined`). Nothing else of the interface changes:
its id, kind, owner, domain, edges, requirements and set of names stay. Each quantity's source
names the node and the attempt, its writer is the owner role, and a series reference is not
carried (the joined node's own reference is checked against its record before this runs).

The attempt is refused before the gate when none of its nodes is joined to the interface, when a
joined node lacks one of its names, when two joined nodes disagree on one in the contract's own
sense (:func:`physgate.contracts.clause.agrees`), or when a unit is not of the interface's root
units. Where every value and unit is already the joined node's as written, nothing is derived.

The same derivation is used by the change check (into its scratch graph, so the gate judges the
revision as the attempt's own), by the loop before it writes the revision, by the reviewer's
packet, and by replay, which derives it again from the recorded payloads. The store writes the
revision only through :meth:`physgate.state.store.Store.follow_interface`, which holds it to the
copy :func:`physgate.state.store.followed_payload` makes; ``write_node`` still refuses every
interface write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.contracts.clause import agrees, joined
from physgate.state.schema import Node, Quantity
from physgate.state.store import followed_payload, payload_digest

Payload = dict[str, Any]
#: The finding source a follow refusal is recorded under.
INTERFACE_NOT_FOLLOWED = "interface"

_Id = Annotated[str, StringConstraints(min_length=1)]
_Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FollowRefusedError(Exception):
    """An interface the attempt cannot follow; the message is the reason the session reads."""

    def __init__(self, message: str, subject: str) -> None:
        """Say why, and name the interface."""
        super().__init__(message)
        self.subject = subject


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
            if name in old and _written(old[name]) != _written(new[name])
        )


def _written(quantity: Mapping[str, Any]) -> str:
    """A quantity's value and unit exactly as written: 2 and 2.0 are not the same writing."""
    return json.dumps([quantity.get("value"), quantity.get("unit")])


def _quantity(payload: Mapping[str, Any], name: str) -> Quantity:
    raw = dict(payload["quantities"][name])
    raw.pop("series", None)
    return Quantity.model_validate(raw)


def derive(
    interface: Payload, nodes: Mapping[str, Payload], role: str, attempt: int
) -> Payload | None:
    """The interface's next revision from the nodes of ``role`` joined to it, or ``None``.

    ``nodes`` is the attempt's own nodes, by id. ``None`` when every value and unit is already
    the first joined node's as written.

    Raises:
        FollowRefusedError: no node is joined to the interface; a joined node lacks one of its
            names; two joined nodes disagree on one; or a unit is not of the interface's root
            units.
    """
    contract = Node.model_validate(interface)
    found = joined(contract, role, {k: Node.model_validate(v) for k, v in nodes.items()})
    iid = contract.id
    if not found:
        msg = (
            f"no node of this attempt is joined to the interface {iid}, which the {role} role "
            f"produces: a node of its own that holds every quantity of {iid} under the same name "
            f"names {iid} in its constrains edges, and the interface takes its values"
        )
        raise FollowRefusedError(msg, iid)
    first = nodes[found[0]]
    for name, wanted in contract.quantities.items():
        for node_id in found:
            if name not in nodes[node_id].get("quantities", {}):
                msg = (
                    f"{node_id} is joined to the interface {iid} and holds no quantity {name}; "
                    f"a node joined to {iid} holds every one of its quantities under its name"
                )
                raise FollowRefusedError(msg, iid)
        outcome, why = agrees(_quantity(first, name), wanted)
        if outcome == "unit":
            msg = (
                f"{found[0]}'s {name} cannot revise the interface {iid}'s {name}: {why}; the "
                "interface keeps its quantities' kinds"
            )
            raise FollowRefusedError(msg, iid)
        for other in found[1:]:
            held, _ = agrees(_quantity(nodes[other], name), _quantity(first, name))
            if held != "pass":
                msg = (
                    f"{found[0]} and {other} are both joined to the interface {iid} and disagree "
                    f"on {name}; the interface follows one value"
                )
                raise FollowRefusedError(msg, iid)
    after = followed_payload(interface, [first], role, attempt)
    old, new = interface.get("quantities", {}), after["quantities"]
    if all(_written(old[name]) == _written(new[name]) for name in new):
        return None
    return after


def follow(
    interface: Payload, nodes: Mapping[str, Payload], role: str, attempt: int
) -> FollowedInterface | None:
    """The followed revision with what it was derived from, or ``None`` where nothing differs.

    Raises:
        FollowRefusedError: as :func:`derive`.
    """
    after = derive(interface, nodes, role, attempt)
    if after is None:
        return None
    contract = Node.model_validate(interface)
    found = joined(contract, role, {k: Node.model_validate(v) for k, v in nodes.items()})
    return FollowedInterface(
        interface=contract.id,
        attempt=attempt,
        joined=found,
        before=interface,
        joined_payloads=tuple(nodes[n] for n in found),
        after=after,
        payload_sha256=payload_digest(after),
    )


def rederived(entry: FollowedInterface, role: str) -> str | None:
    """Why ``entry`` is not the derivation of what it records, for ``role``; ``None`` if it is."""
    if entry.before.get("kind") != "interface" or entry.before.get("owner_role") != role:
        return f"{entry.interface} is no interface the {role} role produces"
    nodes = {str(p["id"]): p for p in entry.joined_payloads}
    try:
        again = follow(entry.before, nodes, role, entry.attempt)
    except FollowRefusedError as exc:
        return f"the recorded nodes do not give {entry.interface} a revision: {exc}"
    except ValueError as exc:
        return f"a recorded payload of {entry.interface} is not a node: {exc}"
    if again is None or again.after != entry.after or again.joined != entry.joined:
        return (
            f"the followed revision of {entry.interface} is not the derivation of the interface "
            "and the joined nodes it records"
        )
    return None
