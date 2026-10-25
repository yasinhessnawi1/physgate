"""The clause an interface contract is held to, on every node of a pair joined to the interface.

The interface node is the contract: written at decomposition, immutable after, and read by both
modules of a pair. A clause is one quantity of one interface node, checked on every node of the
pair's two roles that is joined to it: a node, other than an interface node, that lists the
interface among the nodes it constrains, or that the interface lists. Interface nodes are the
decomposition's contracts, which no session writes, so none is a module's node.

A joined node holds a clause when it carries the quantity's name, its unit has the interface's
root units (pint's dimension and the power of the radian, which unit arithmetic alone cannot
see: otherwise 1 Hz would read as 1 rad/s), and its value, converted to the interface's unit
through the gate's own parser and registry, agrees with the interface's under ``math.isclose``
at a relative tolerance of 1e-9 with no absolute term. That is a representation tolerance, not
an engineering margin, and zero agrees only with zero. The catalogue's sign and shape rules are
not applied here: they are the gate's.

A side with no joined node fails as not joined, whether or not the interface has quantities. A
pair passes only when every interface is joined on both sides and every clause passes, and every
result counts the clauses it checked, so a pass with none can be told apart from one with some.

Every result carries the digest of the definition that judged it (:func:`definition_sha256`):
the tolerances, the bytes of the code that decides a clause, pint's version, and any unit
definition file loaded beyond pint's defaults. A change to any of them is a new definition: a
contract test changed after a result was read cannot pass for the one that produced it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate import unit_spelling
from physgate.contracts.pairs import ContractError, ContractPair
from physgate.gate import units
from physgate.gate.units import PINT, PINT_ERRORS, UnitRefusedError, parse
from physgate.orchestrator.common import NonEmptyStr
from physgate.state.schema import Node, Quantity

#: The relative tolerance of a clause, a representation tolerance and no engineering margin.
REL_TOL = 1e-9
#: The absolute term: none, so zero agrees only with zero.
ABS_TOL = 0.0
#: The code that decides a clause, whose bytes the definition's digest covers.
SOURCES: dict[str, Path] = {
    "clause": Path(__file__),
    "units": Path(units.__file__),
    "unit_spelling": Path(unit_spelling.__file__),
}
#: Unit definition files the conversion's registry loads beyond pint's defaults, whose bytes the
#: digest covers. None: the gate's registry is pint's own, built with no file.
REGISTRY_FILES: tuple[Path, ...] = ()

SideName = Literal["producer", "consumer"]
Outcome = Literal["pass", "fail"]
#: How one joined node stands against one clause: held, its name ``missing``, its ``unit``
#: refused or not the interface's, or its ``value`` not close.
NodeOutcome = Literal["pass", "missing", "unit", "value"]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class NodeCheck(_Frozen):
    """One joined node against one clause."""

    node: NonEmptyStr
    side: SideName
    outcome: NodeOutcome
    #: Why the unit failed, in the gate's words; ``None`` for any other outcome.
    reason: str | None = None


class ClauseResult(_Frozen):
    """One quantity of the interface on every joined node; it passes when both sides hold it."""

    quantity: NonEmptyStr
    outcome: Outcome
    nodes: tuple[NodeCheck, ...]

    @model_validator(mode="after")
    def _the_outcome_is_the_nodes(self) -> ClauseResult:
        held = {n.side for n in self.nodes} == {"producer", "consumer"} and all(
            n.outcome == "pass" for n in self.nodes
        )
        if (self.outcome == "pass") != held:
            msg = "a clause passes exactly when both sides hold it on every joined node"
            raise ValueError(msg)
        return self


class InterfaceCheck(_Frozen):
    """One interface of a pair: the nodes joined on each side, and one clause per quantity."""

    interface: NonEmptyStr
    producer_nodes: tuple[NonEmptyStr, ...]
    consumer_nodes: tuple[NonEmptyStr, ...]
    not_joined: tuple[SideName, ...]
    clauses: tuple[ClauseResult, ...]
    clauses_checked: Annotated[int, Field(ge=0)]
    outcome: Outcome

    @model_validator(mode="after")
    def _the_count_and_outcome_are_the_checks(self) -> InterfaceCheck:
        sides = (("producer", self.producer_nodes), ("consumer", self.consumer_nodes))
        unjoined = tuple(side for side, found in sides if not found)
        passed = not unjoined and all(c.outcome == "pass" for c in self.clauses)
        if (
            self.not_joined != unjoined
            or self.clauses_checked != len(self.clauses)
            or (self.outcome == "pass") != passed
        ):
            msg = "an interface's sides, count and outcome are those of its nodes and clauses"
            raise ValueError(msg)
        return self


class ContractResult(_Frozen):
    """A pair held to the clause on every interface it shares, under one definition."""

    pair: ContractPair
    interfaces: tuple[InterfaceCheck, ...]
    clauses_checked: Annotated[int, Field(ge=0)]
    outcome: Outcome
    definition_sha256: Sha256

    @model_validator(mode="after")
    def _the_total_and_outcome_are_the_interfaces(self) -> ContractResult:
        if (
            tuple(c.interface for c in self.interfaces) != self.pair.interfaces
            or self.clauses_checked != sum(c.clauses_checked for c in self.interfaces)
            or (self.outcome == "pass") != all(c.outcome == "pass" for c in self.interfaces)
        ):
            msg = "a result checks its pair's interfaces, and its count and outcome are theirs"
            raise ValueError(msg)
        return self


def agrees(held: Quantity | None, wanted: Quantity) -> tuple[NodeOutcome, str | None]:
    """Whether a node's quantity holds the interface's: the outcome, and why a unit failed."""
    if held is None:
        return "missing", None
    try:
        have, want = parse(held.value, held.unit), parse(wanted.value, wanted.unit)
    except UnitRefusedError as exc:
        return "unit", str(exc)
    if have.to_root_units().units != want.to_root_units().units:
        return "unit", f"{held.unit!r} is not in the root units of the interface's {wanted.unit!r}"
    try:
        converted = float(have.to(want.units).magnitude)
    except PINT_ERRORS as exc:
        # Not pint's own text: in exact fractions it cannot always print its refusal.
        return (
            "unit",
            f"pint cannot convert {held.unit!r} to {wanted.unit!r} ({type(exc).__name__})",
        )
    except OverflowError:
        return "value", None
    close = math.isclose(converted, float(want.magnitude), rel_tol=REL_TOL, abs_tol=ABS_TOL)
    return ("pass" if close else "value"), None


def joined(contract: Node, role: str, nodes: Mapping[str, Node]) -> tuple[str, ...]:
    """The nodes of ``role``, interface nodes aside, joined to ``contract``, in id order."""
    return tuple(
        sorted(
            node_id
            for node_id, node in nodes.items()
            if node.owner_role == role
            and node.kind != "interface"
            and (contract.id in node.constrains or node_id in contract.constrains)
        )
    )


def check_pair(pair: ContractPair, nodes: Mapping[str, Node]) -> ContractResult:
    """Hold ``pair`` to the clause on every interface it shares, over the graph's ``nodes``.

    Raises:
        ContractError: an interface of the pair is missing from ``nodes``, is not an interface
            node, or is owned by another role than the pair's producer. The pairs were read
            from the plan, so such a graph is not the plan's.
    """
    checks = tuple(_interface(pair, interface, nodes) for interface in pair.interfaces)
    return ContractResult(
        pair=pair,
        interfaces=checks,
        clauses_checked=sum(c.clauses_checked for c in checks),
        outcome="pass" if all(c.outcome == "pass" for c in checks) else "fail",
        definition_sha256=definition_sha256(),
    )


def _interface(pair: ContractPair, interface: str, nodes: Mapping[str, Node]) -> InterfaceCheck:
    contract = nodes.get(interface)
    if (
        contract is None
        or contract.kind != "interface"
        or contract.owner_role != pair.producer.role
    ):
        msg = "an interface node of the pair is missing, is no interface, or is another role's"
        raise ContractError(msg, interface=interface, producer=pair.producer.role)
    sides: dict[SideName, tuple[str, ...]] = {
        "producer": joined(contract, pair.producer.role, nodes),
        "consumer": joined(contract, pair.consumer.role, nodes),
    }
    clauses = []
    for name, wanted in sorted(contract.quantities.items()):
        checked = []
        for side, found in sides.items():
            for node_id in found:
                outcome, reason = agrees(nodes[node_id].quantities.get(name), wanted)
                checked.append(NodeCheck(node=node_id, side=side, outcome=outcome, reason=reason))
        held = all(sides.values()) and all(c.outcome == "pass" for c in checked)
        clauses.append(
            ClauseResult(quantity=name, outcome="pass" if held else "fail", nodes=tuple(checked))
        )
    unjoined = tuple(side for side, found in sides.items() if not found)
    return InterfaceCheck(
        interface=interface,
        producer_nodes=sides["producer"],
        consumer_nodes=sides["consumer"],
        not_joined=unjoined,
        clauses=tuple(clauses),
        clauses_checked=len(clauses),
        outcome="pass" if not unjoined and all(c.outcome == "pass" for c in clauses) else "fail",
    )


def definition() -> dict[str, object]:
    """What the definition's digest is taken over, read now from the code that decides a clause."""
    return {
        "rel_tol": repr(REL_TOL),
        "abs_tol": repr(ABS_TOL),
        "sources": {name: _sha256(path) for name, path in sorted(SOURCES.items())},
        "pint": PINT,
        "registry_files": {path.name: _sha256(path) for path in REGISTRY_FILES},
    }


def definition_sha256() -> str:
    """The sha256 of the definition's canonical JSON: what every contract result carries."""
    canonical = json.dumps(definition(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
