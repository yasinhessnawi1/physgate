"""The catalogue's relations, instantiated over the graph's ``constrains`` edges.

A relation instance names its terms by node and quantity. The unit check
evaluates every instance's two sides for unit consistency; the check named in
the relation's ``judged_by`` decides whether it holds. Both read the same
instances from here, so the unit check and the judging check can never disagree
about what the relation is.

An instance with a term missing (a component that gives its thermal resistance
but not its temperature limit) is kept, with the missing names: the checks
record it as unchecked rather than dropping it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from physgate.gate.catalogue import RELATIONS, Relation, kind_of
from physgate.gate.graph import GraphView
from physgate.gate.units import Measured, add, measure, multiply
from physgate.orchestrator.protocols import NumericOutput, Term


@dataclass(frozen=True)
class TermRef:
    """One quantity of one node."""

    node: str
    name: str

    def spelled(self) -> str:
        """The term as an expression writes it."""
        return f"{self.name}({self.node})"


@dataclass(frozen=True)
class Product:
    """Two quantities multiplied, where the catalogue names the product's kind."""

    left: TermRef
    right: TermRef

    def spelled(self) -> str:
        """The product as an expression writes it."""
        return f"{self.left.spelled()} * {self.right.spelled()}"

    def refs(self) -> tuple[TermRef, TermRef]:
        """Both factors."""
        return (self.left, self.right)


Factor = TermRef | Product


@dataclass(frozen=True)
class Instance:
    """One relation at one place in the graph: ``sum(left) op sum(right)``."""

    relation: Relation
    #: The node the relation is about: the supply, the module, the component.
    subject: str
    left: tuple[Factor, ...]
    op: Literal["<=", "=="]
    right: tuple[Factor, ...]
    #: Quantity names the relation needs here and the graph does not give.
    missing: tuple[str, ...] = ()

    def expression(self) -> str:
        """The instance as one line: which quantities of which nodes, and how."""
        left = " + ".join(t.spelled() for t in self.left) or "0"
        right = " + ".join(t.spelled() for t in self.right) or "0"
        return f"{left} {self.op} {right}"

    def refs(self) -> tuple[TermRef, ...]:
        """Every quantity the instance reads."""
        found: list[TermRef] = []
        for term in (*self.left, *self.right):
            found.extend(term.refs() if isinstance(term, Product) else (term,))
        return tuple(found)

    def nodes(self) -> frozenset[str]:
        """Every node the instance reads, its subject included."""
        return frozenset({self.subject, *(r.node for r in self.refs())})


def _has(view: GraphView, node_id: str, name: str) -> bool:
    return name in view.nodes[node_id].quantities


def _members(view: GraphView, target: str, name: str) -> tuple[TermRef, ...]:
    return tuple(TermRef(n, name) for n in view.constrained_by(target) if _has(view, n, name))


def instances(view: GraphView) -> list[Instance]:
    """Every relation instance in the graph, in a stable order."""
    found: list[Instance] = []
    for node_id, node in view.nodes.items():
        q = node.quantities
        consumers = _members(view, node_id, "power_draw")
        if "power_supply" in q or (node.kind == "module" and consumers):
            found.append(
                Instance(
                    relation=RELATIONS["power_budget"],
                    subject=node_id,
                    left=consumers,
                    op="<=",
                    right=(TermRef(node_id, "power_supply"),) if "power_supply" in q else (),
                    missing=() if "power_supply" in q else ("power_supply",),
                )
            )
        upstream = [t for t in node.constrains if t in view.nodes and _has(view, t, "power_supply")]
        if "power_supply" in q and ("power_draw" in q or upstream):
            found.append(
                Instance(
                    relation=RELATIONS["supply_covered"],
                    subject=node_id,
                    left=(TermRef(node_id, "power_supply"),),
                    op="<=",
                    right=(TermRef(node_id, "power_draw"),) if "power_draw" in q else (),
                    missing=() if "power_draw" in q else ("power_draw",),
                )
            )
        if "current_limit" in q:
            found.extend(
                Instance(
                    relation=RELATIONS["current_limit"],
                    subject=node_id,
                    left=(consumer,),
                    op="<=",
                    right=(TermRef(node_id, "current_limit"),),
                )
                for consumer in _members(view, node_id, "stall_current")
            )
        members = _members(view, node_id, "mass")
        if node.kind == "module" and members:
            found.append(
                Instance(
                    relation=RELATIONS["mass_sum"],
                    subject=node_id,
                    left=(TermRef(node_id, "mass"),) if "mass" in q else (),
                    op="==",
                    right=members,
                    missing=() if "mass" in q else ("mass",),
                )
            )
        if "input_power" in q or "output_power" in q:
            needed = [n for n in ("input_power", "output_power") if n not in q]
            right = [TermRef(node_id, "output_power")] if "output_power" in q else []
            if "heat_dissipation" in q:
                right.append(TermRef(node_id, "heat_dissipation"))
            found.append(
                Instance(
                    relation=RELATIONS["energy_balance"],
                    subject=node_id,
                    left=(TermRef(node_id, "input_power"),) if "input_power" in q else (),
                    op="==",
                    right=tuple(right),
                    missing=tuple(needed),
                )
            )
        if "heat_rejection_capacity" in q:
            found.append(
                Instance(
                    relation=RELATIONS["heat_budget"],
                    subject=node_id,
                    left=_members(view, node_id, "heat_dissipation"),
                    op="<=",
                    right=(TermRef(node_id, "heat_rejection_capacity"),),
                )
            )
        junction = (
            "ambient_temperature",
            "thermal_resistance",
            "heat_dissipation",
            "max_temperature",
        )
        if "thermal_resistance" in q or "max_temperature" in q:
            absent = tuple(n for n in junction if n not in q)
            complete = not absent
            found.append(
                Instance(
                    relation=RELATIONS["junction_limit"],
                    subject=node_id,
                    left=(
                        TermRef(node_id, "ambient_temperature"),
                        Product(
                            TermRef(node_id, "thermal_resistance"),
                            TermRef(node_id, "heat_dissipation"),
                        ),
                    )
                    if complete
                    else (),
                    op="<=",
                    right=(TermRef(node_id, "max_temperature"),) if complete else (),
                    missing=absent,
                )
            )
    return found


def touching(found: Iterable[Instance], nodes: Iterable[str]) -> list[Instance]:
    """The instances that read any of ``nodes``."""
    wanted = set(nodes)
    return [i for i in found if i.nodes() & wanted]


def measured(view: GraphView, ref: TermRef) -> Measured:
    """One term measured against its kind.

    Raises:
        UnitRefusedError, pint errors: see :func:`physgate.gate.units.measure`.
    """
    quantity = view.nodes[ref.node].quantities[ref.name]
    kind = kind_of(ref.name)
    if kind is None:  # relations are built from catalogue names only
        msg = f"relation term {ref.name!r} is not in the catalogue"
        raise ValueError(msg)
    return measure(kind, quantity.value, quantity.unit)


def side(view: GraphView, factors: tuple[Factor, ...]) -> Measured | None:
    """The sum of one side's factors, under the kind algebra; ``None`` for an empty side.

    Raises:
        UnitRefusedError, pint errors: a term is refused, or the kinds do not combine.
    """
    total: Measured | None = None
    for factor in factors:
        value = (
            multiply(measured(view, factor.left), measured(view, factor.right))
            if isinstance(factor, Product)
            else measured(view, factor)
        )
        total = value if total is None else add(total, value)
    return total


def terms_of(view: GraphView, instance: Instance) -> tuple[Term, ...]:
    """The instance's quantities as they are declared, for a finding's details."""
    return tuple(
        Term(
            node_id=ref.node,
            name=ref.name,
            value=NumericOutput(
                value=view.nodes[ref.node].quantities[ref.name].value,
                unit=view.nodes[ref.node].quantities[ref.name].unit,
            ),
        )
        for ref in instance.refs()
    )


def output(value: Fraction, unit: str) -> NumericOutput:
    """An exact number as a record's output: an integer where it is one."""
    number: float | int = int(value) if value.denominator == 1 else float(value)
    return NumericOutput(value=number, unit=unit)
