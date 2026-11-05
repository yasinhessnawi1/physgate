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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType
from typing import Literal

from physgate.gate.catalogue import (
    KINDS,
    MAX_DISCHARGE_PER_HOUR,
    QUANTITIES,
    RELATIONS,
    SOURCES,
    Relation,
)
from physgate.gate.graph import GraphView
from physgate.gate.units import UREG, Measured, add, measure, multiply
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


@dataclass(frozen=True)
class Scaled:
    """A quantity times a constant the catalogue sources: a discharge rate times a stored energy.

    ``unit`` is the constant's unit as pint reads it, so the unit check sees the product's
    dimension exactly as the judging check computes it.
    """

    ref: TermRef
    factor: Fraction
    unit: str
    #: The kind of the product, which the catalogue states with the constant.
    kind: str

    def spelled(self) -> str:
        """The scaled term as an expression writes it."""
        return f"{self.factor} {self.unit} * {self.ref.spelled()}"

    def refs(self) -> tuple[TermRef]:
        """The one quantity the term reads."""
        return (self.ref,)


Factor = TermRef | Product | Scaled


@dataclass(frozen=True)
class RelationInputs:
    """The quantity names one relation reads, every form of it together, and its comparator."""

    names: frozenset[str]
    comparator: Literal["<=", "=="]


#: Every relation the checks form, by the names it reads and its comparator: the catalogue's
#: relations, held to what :func:`instances` reads by a test over a graph that forms them all,
#: and the equilibrium check's readings, which the relation names below the catalogue's list.
#: A law is refused when its names and its comparator are one of these: laws add relations,
#: they never count one the checks already judge a second time.
RELATION_INPUTS: Mapping[str, RelationInputs] = MappingProxyType(
    {
        "power_budget": RelationInputs(frozenset({"power_draw", "power_supply"}), "<="),
        "supply_covered": RelationInputs(frozenset({"power_supply", "power_draw"}), "<="),
        "source_rating": RelationInputs(
            frozenset({"power_supply", "max_discharge_power", "rated_output_power", "power_draw"}),
            "<=",
        ),
        "current_limit": RelationInputs(frozenset({"stall_current", "current_limit"}), "<="),
        "discharge_rate": RelationInputs(
            frozenset({"max_discharge_power", "energy_capacity"}), "<="
        ),
        "mass_sum": RelationInputs(frozenset({"mass"}), "=="),
        "energy_balance": RelationInputs(
            frozenset({"input_power", "output_power", "heat_dissipation"}), "=="
        ),
        "heat_budget": RelationInputs(
            frozenset({"heat_dissipation", "heat_rejection_capacity"}), "<="
        ),
        "junction_limit": RelationInputs(
            frozenset(
                {"ambient_temperature", "thermal_resistance", "heat_dissipation", "max_temperature"}
            ),
            "<=",
        ),
        # The equilibrium check's readings, which no catalogue relation states.
        "torque_unit": RelationInputs(
            frozenset({"torque_peak", "reaction_moment", "gear_ratio", "external_gear_ratio"}),
            "==",
        ),
        "carrier": RelationInputs(frozenset({"supported_mass", "mass"}), "=="),
        "mount_balance": RelationInputs(
            frozenset(
                {
                    "support_position",
                    "mount_position",
                    "reaction_force",
                    "reaction_moment",
                    "load_force",
                    "mass",
                }
            ),
            "==",
        ),
    }
)


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
            found.extend(term.refs() if isinstance(term, Product | Scaled) else (term,))
        return tuple(found)

    def nodes(self) -> frozenset[str]:
        """Every node the instance reads, its subject included."""
        return frozenset({self.subject, *(r.node for r in self.refs())})


def _has(view: GraphView, node_id: str, name: str) -> bool:
    return name in view.nodes[node_id].quantities


def _members(view: GraphView, target: str, name: str) -> tuple[TermRef, ...]:
    return tuple(TermRef(n, name) for n in view.constrained_by(target) if _has(view, n, name))


def _bounded(view: GraphView, node_id: str) -> bool:
    """Whether a node its ``constrains`` edges name holds a current limit."""
    return any(
        t in view.nodes and _has(view, t, "current_limit") for t in view.nodes[node_id].constrains
    )


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
        markers = [m for m in SOURCES if m in q]
        if "power_supply" in q and markers:
            # A declared source: its supply is held to its rating, plus its draw.
            ratings = [SOURCES[m] for m in markers if SOURCES[m] in q]
            draw = (TermRef(node_id, "power_draw"),) if "power_draw" in q else ()
            found.append(
                Instance(
                    relation=RELATIONS["source_rating"],
                    subject=node_id,
                    left=(TermRef(node_id, "power_supply"),),
                    op="<=",
                    right=(TermRef(node_id, ratings[0]), *draw) if ratings else (),
                    missing=() if ratings else (SOURCES[markers[0]],),
                )
            )
        if "power_supply" in q and not markers:
            # Not a declared source, so what it supplies it must draw from upstream.
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
        if "max_discharge_power" in q and "energy_capacity" in q:
            # A store's rating is bounded by what it stores: no store class the catalogue
            # sources discharges continuously faster than its highest rate.
            found.append(
                Instance(
                    relation=RELATIONS["discharge_rate"],
                    subject=node_id,
                    left=(TermRef(node_id, "max_discharge_power"),),
                    op="<=",
                    right=(
                        Scaled(
                            TermRef(node_id, "energy_capacity"),
                            MAX_DISCHARGE_PER_HOUR,
                            "1/h",
                            "power",
                        ),
                    ),
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
        if "stall_current" in q and "current_limit" in q:
            # A node holding both is held to its own limit: a consumer aggregated with the
            # supply that carries it, which its stall must not overrun either.
            found.append(
                Instance(
                    relation=RELATIONS["current_limit"],
                    subject=node_id,
                    left=(TermRef(node_id, "stall_current"),),
                    op="<=",
                    right=(TermRef(node_id, "current_limit"),),
                )
            )
        elif "stall_current" in q and not _bounded(view, node_id):
            # A stall current no limit bounds, on its node or on a node its edges name, is
            # kept with the limit missing, so it is recorded as unchecked, never passed.
            found.append(
                Instance(
                    relation=RELATIONS["current_limit"],
                    subject=node_id,
                    left=(TermRef(node_id, "stall_current"),),
                    op="<=",
                    right=(),
                    missing=("current_limit",),
                )
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
    entry = QUANTITIES.get(ref.name)
    # Relations are built from catalogue names only: a name the gate merely reads, by a suffix
    # or by qualifier words, has a kind but is never a term.
    if entry is None:
        msg = f"relation term {ref.name!r} is not in the catalogue"
        raise ValueError(msg)
    return measure(KINDS[entry.kind], quantity.value, quantity.unit)


def scaled(view: GraphView, term: Scaled) -> Measured:
    """A scaled term measured as the kind the catalogue gives its product.

    Raises:
        UnitRefusedError, pint errors: the term is refused, or the product is not that kind.
    """
    kind = KINDS[term.kind]
    product = measured(view, term.ref).quantity * UREG.Quantity(term.factor, term.unit)
    return Measured(kind=kind, quantity=product.to(kind.canonical))


def side(view: GraphView, factors: tuple[Factor, ...]) -> Measured | None:
    """The sum of one side's factors, under the kind algebra; ``None`` for an empty side.

    Raises:
        UnitRefusedError, pint errors: a term is refused, or the kinds do not combine.
    """
    total: Measured | None = None
    for factor in factors:
        if isinstance(factor, Scaled):
            value = scaled(view, factor)
        elif isinstance(factor, Product):
            value = multiply(measured(view, factor.left), measured(view, factor.right))
        else:
            value = measured(view, factor)
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
