"""A law reads only names the hooks guard, and a law never restates what the checks form.

The hooks refuse, at write time, a name that misspells one a relation reads, so a writer cannot
step out of a relation by a typo. A law's inputs are read by name the same way, so every name a
loaded law reads, requires or is excused by is one of the catalogue's relation names, which the
hooks' vocabulary mirrors; a promotion that adds a name turns this red until both lists hold it.

The relations the checks already form are written down by the names each reads and its
comparator, so the loader can refuse a law that restates one. That list is held to what the
checks read: over a graph that forms every relation, each relation reads exactly its names, and
the relation names are the union of those and of the loaded laws' names, nothing else.

Widening the guarded names must not refuse a name a real plan wrote. Every name written in the
practice set and in the G11 runs that left a graph is held unrefused.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node
from law_fixtures import laws_module

from physgate.gate import relations
from physgate.gate.catalogue import RELATION_NAMES, RELATIONS, shadowing_names
from physgate.gate.graph import GraphView
from physgate.gate.relations import instances
from physgate.state.vocabulary import RELATION_QUANTITY_NAMES

ROOT = Path(__file__).resolve().parents[3]
PRACTICE = ROOT / "experiments" / "R-PG-02" / "practice" / "corpus-v1"


def relation_inputs() -> Any:
    """The names and comparator each relation reads, or a failed test: they are not written."""
    found = getattr(relations, "RELATION_INPUTS", None)
    if found is None:
        pytest.fail("the gate does not write down the names each relation reads yet")
    return found


#: One graph that forms every relation the catalogue states, each with all its names.
EVERY_RELATION = (
    node(
        "electrical.supply",
        kind="module",
        quantities={"power_supply": (20, "W"), "power_draw": (25, "W")},
    ),
    node("electrical.load", quantities={"power_draw": (5, "W")}, constrains=["electrical.supply"]),
    node(
        "electrical.battery",
        quantities={
            "power_supply": (10, "W"),
            "energy_capacity": (20, "W*h"),
            "max_discharge_power": (40, "W"),
            "power_draw": (1, "W"),
        },
    ),
    node(
        "electrical.bench",
        quantities={"power_supply": (10, "W"), "rated_output_power": (40, "W")},
    ),
    node(
        "electrical.motor",
        quantities={"stall_current": (1.6, "A")},
        constrains=["electrical.driver"],
    ),
    node("electrical.driver", quantities={"current_limit": (1.8, "A")}),
    node("mechanical.frame", kind="module", domain="mechanical", quantities={"mass": (0.3, "kg")}),
    node(
        "mechanical.part",
        domain="mechanical",
        quantities={"mass": (0.3, "kg")},
        constrains=["mechanical.frame"],
    ),
    node(
        "electrical.chip",
        quantities={
            "input_power": (2, "W"),
            "output_power": (1, "W"),
            "heat_dissipation": (1, "W"),
            "ambient_temperature": (25, "degC"),
            "thermal_resistance": (40, "K/W"),
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.box"],
    ),
    node("electrical.box", kind="module", quantities={"heat_rejection_capacity": (5, "W")}),
)


def test_the_relations_read_exactly_the_names_written_down_for_them(tmp_path: Path) -> None:
    written = relation_inputs()
    graph(tmp_path / "g", *EVERY_RELATION)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    read: dict[str, set[str]] = {}
    for instance in instances(view):
        read.setdefault(instance.relation.name, set()).update(r.name for r in instance.refs())
    assert set(read) == set(RELATIONS)
    for relation, names in read.items():
        assert names == set(written[relation].names), relation
        assert written[relation].comparator in ("<=", "==")


#: A name a relation reads that the hooks do not guard as a relation name: the source rating
#: reads a bench supply's rated output, and a misspelling of it is written, not refused. Found
#: when the relations' names were first written down; listed here, by name, so the gap is a
#: stated fact until the guard is widened or the reason it is not is written beside it.
UNGUARDED = {"rated_output_power"}


def test_the_relation_names_are_the_relations_and_the_laws_names_and_nothing_else() -> None:
    written = relation_inputs()
    table = laws_module().load_laws()
    from_relations = {name for entry in written.values() for name in entry.names}
    assert UNGUARDED <= from_relations
    assert set(RELATION_NAMES) == (from_relations - UNGUARDED) | set(table.input_names())
    assert RELATION_QUANTITY_NAMES == RELATION_NAMES


def test_every_name_a_loaded_law_reads_is_a_relation_name_the_hooks_guard() -> None:
    table = laws_module().load_laws()
    assert set(table.input_names()) <= set(RELATION_NAMES)
    assert set(table.input_names()) <= set(RELATION_QUANTITY_NAMES)


def _quantity_names(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        quantities = value.get("quantities")
        if isinstance(quantities, dict):
            yield from quantities
        for inner in value.values():
            yield from _quantity_names(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _quantity_names(inner)


def real_names() -> set[str]:
    """Every quantity name the practice set and G11 runs 2 and 4 wrote."""
    names: set[str] = set()
    for path in [PRACTICE / "base.json", *sorted((PRACTICE / "artefacts").glob("*.json"))]:
        names.update(_quantity_names(json.loads(path.read_text())))
    run4 = json.loads((Path(__file__).parent / "run4" / "values.json").read_text())
    names.update(row["name"] for row in run4)
    names.update(json.loads((Path(__file__).parent / "run2" / "names.json").read_text()))
    return names


def test_no_name_a_real_plan_wrote_is_refused_as_a_misspelling() -> None:
    names = real_names()
    assert len(names) > 200
    assert shadowing_names(names) == ()
