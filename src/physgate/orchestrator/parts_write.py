"""What the parts decisions of a run become: the nodes that hold them, and the record.

ARCH-122. When every part of a plan is decided, code writes what a person stated of each part
they have or make onto the part's node, and nowhere else (the plan, not the person or a
session, says where each value goes). A component's own names go to its node; the names the
plan marks as shared go to the node the role that writes the cross nodes holds for it
(:func:`physgate.orchestrator.decompose.shared_node_id`), joined to the component's by a
``constrains`` edge. Each quantity carries the record of the decision that made it
(:class:`physgate.state.schema.Declared`), and the node's ``updated`` stamp is the time of
the decision, so the payload is a function of the plan and the decisions alone: the replay
derives the same bytes from the log.

The record (``parts.json``) is the decisions as a role reads them: each component, its choice,
the values and the texts. It is a function of the plan and the released decisions too.

What landed is held to the journal (:func:`unlanded_declared`): every declared quantity at the
journal's head is one a landed parts write wrote, so a declared value that reached the journal
any other way, or a landed line changed afterwards, is found and never taken as the person's.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from physgate.orchestrator.plan import Component, shared_node_id
from physgate.orchestrator.queue import PartsBody, parts_sha256
from physgate.state.schema import DECLARED_SOURCE
from physgate.state.store import JournalLine, payload_digest

Payload = dict[str, Any]
Choice = Literal["have", "make", "find"]

#: The node's geometry digest: a part's node says nothing of geometry, as the constant says.
PARTS_GEOMETRY_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True)
class TakenPart:
    """One part's decision as the run recorded it: the choice, what it stated, who and when."""

    item_id: str
    choice: Choice
    body: PartsBody | None
    operator: str
    decided_ts: str


@dataclass(frozen=True)
class PartsWrite:
    """One node write the parts decisions owe: where, by whom, from which decision, what."""

    node_id: str
    owner_role: str
    component: str
    shared: bool
    item_id: str
    body: PartsBody
    payload: Payload
    payload_sha256: str


def names_of(component: Component, body: PartsBody, *, shared: bool) -> tuple[str, ...]:
    """The names of ``body`` the node of ``component`` holds, in the order the body states them.

    Shared names go to the cross node. Every other name, those the plan lists as the
    component's own and those a person added, goes to the component's node.
    """
    kept = set(component.shared)
    return tuple(n for n in body.declared if (n in kept) == shared)


def parts_payload(
    component: Component,
    *,
    shared: bool,
    owner_role: str,
    item_id: str,
    body: PartsBody,
    operator: str,
    decided_ts: str,
) -> Payload | None:
    """The node ``component`` holds the stated values on, or ``None`` where it holds none."""
    names = names_of(component, body, shared=shared)
    if not names:
        return None
    digest = parts_sha256(body)
    quantities = {
        name: {
            "value": body.declared[name].value,
            "unit": body.declared[name].unit,
            "source": DECLARED_SOURCE,
            "written_by": owner_role,
            "declared": {"item_id": item_id, "decision_sha256": digest, "operator": operator},
        }
        for name in names
    }
    return {
        "id": shared_node_id(owner_role, component.node) if shared else component.node,
        "kind": "component",
        "domain": "cross" if shared else component.domain,
        "owner_role": owner_role,
        "quantities": quantities,
        "requirements": [],
        "constrains": [component.node] if shared else [],
        "model": None,
        "geometry_hash": PARTS_GEOMETRY_HASH,
        "updated": decided_ts,
    }


def parts_writes(
    components: Sequence[Component],
    item_ids: Sequence[str],
    taken: Mapping[str, TakenPart],
    cross_owner: str | None,
) -> tuple[PartsWrite, ...]:
    """Every write the decisions owe, in the plan's order: a component's node, then its cross node.

    A component the person will find, and one whose body states nothing a node holds, owes none.

    Raises:
        ValueError: a decision states a shared name and the run has no role for the cross nodes.
    """
    owed: list[PartsWrite] = []
    for component, item_id in zip(components, item_ids, strict=True):
        part = taken[item_id]
        if part.choice == "find" or part.body is None:
            continue
        for shared in (False, True):
            owner = cross_owner if shared else component.role
            if shared and owner is None:
                if names_of(component, part.body, shared=True):
                    msg = f"{component.node} states shared names and the run has no sizing role"
                    raise ValueError(msg)
                continue
            payload = parts_payload(
                component,
                shared=shared,
                owner_role=owner or component.role,
                item_id=item_id,
                body=part.body,
                operator=part.operator,
                decided_ts=part.decided_ts,
            )
            if payload is not None:
                owed.append(
                    PartsWrite(
                        node_id=str(payload["id"]),
                        owner_role=str(payload["owner_role"]),
                        component=component.node,
                        shared=shared,
                        item_id=item_id,
                        body=part.body,
                        payload=payload,
                        payload_sha256=payload_digest(payload),
                    )
                )
    return tuple(owed)


def parts_record(components: Sequence[Component], taken: Sequence[TakenPart]) -> bytes:
    """The record of the decisions, as canonical JSON: each component, its choice and what it says.

    A part the person will find states nothing. The bytes are what the dispatcher writes for a
    role to read, and their digest and length are what the release line names.
    """
    entries = []
    for component, part in zip(components, taken, strict=True):
        body = part.body
        entries.append(
            {
                "node": component.node,
                "label": component.label,
                "choice": part.choice,
                "declared": body.model_dump(mode="json")["declared"] if body else {},
                "texts": list(body.texts) if body else [],
            }
        )
    return json.dumps({"components": entries}, sort_keys=True, separators=(",", ":")).encode()


def _declared_of(payload: object) -> dict[str, object]:
    """The quantities of ``payload`` that carry a decision's record, by name."""
    quantities = payload.get("quantities") if isinstance(payload, dict) else None
    if not isinstance(quantities, dict):
        return {}
    return {
        str(name): entry
        for name, entry in quantities.items()
        if isinstance(entry, dict) and entry.get("declared") is not None
    }


def unlanded_declared(
    lines: Iterable[JournalLine], landed: Sequence[tuple[str, str, int]]
) -> str | None:
    """Why the journal's declared quantities are not what the landed parts writes wrote, or None.

    ``lines`` is the whole canonical journal; ``landed`` is each parts write the record says
    landed, as ``(node, payload digest, revision)`` in the order it landed. Each landed line is
    held to its digest, whole. Then every declared quantity at the head, node by node, must be
    one the node's latest landed write holds, field for field (value, unit, source, record and
    the rest), and each of those must still stand at the head.
    """
    journal = sorted(lines, key=lambda line: line.rev)
    by_rev = {line.rev: line for line in journal}
    owed: dict[str, dict[str, object]] = {}
    for node_id, digest, revision in landed:
        line = by_rev.get(revision)
        holds = (
            line is not None
            and line.node_id == node_id
            and isinstance(line.payload, dict)
            and payload_digest(line.payload) == digest
        )
        if not holds:
            return (
                f"the parts write of {node_id} that landed at journal revision {revision} is not "
                "in the journal as it landed"
            )
        owed[node_id] = _declared_of(line.payload if line is not None else None)
    head = {line.node_id: line.payload for line in journal}
    for node_id in sorted(set(head) | set(owed)):
        held, wanted = _declared_of(head.get(node_id)), owed.get(node_id, {})
        for name in sorted(set(held) | set(wanted)):
            if held.get(name) != wanted.get(name):
                return (
                    f"the declared quantity {name} of {node_id} at the journal's head is not what "
                    "a landed parts write wrote; only a person's recorded decision declares a value"
                )
    return None
