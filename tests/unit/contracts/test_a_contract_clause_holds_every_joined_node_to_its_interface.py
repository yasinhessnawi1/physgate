"""A contract clause holds every node joined to an interface to the interface node's own quantity.

The interface node is the contract. A clause is one of its quantities, checked on every node of
the pair's two roles joined to it: a node, other than an interface node, that lists the
interface among what it constrains, or that the interface lists. A node holds the clause when it
carries the quantity's name, its unit has the interface's root units (the radian's power
included, which unit arithmetic alone cannot see), and its value, converted to the interface's
unit through the gate's own parser, agrees under ``math.isclose`` at a relative 1e-9 with no
absolute term: zero agrees only with zero. A side with no joined node fails as not joined,
whether or not the interface has quantities, and every result counts the clauses it checked, so
a pass with none is told apart from a pass with some. Each result carries the digest of the
definition that judged it, which moves with any change to the code that decides a clause.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pint
import pytest
from pydantic import ValidationError

import physgate
from physgate.contracts import clause
from physgate.contracts.clause import (
    ContractResult,
    agrees,
    check_pair,
    definition,
    definition_sha256,
)
from physgate.contracts.pairs import ContractError, ContractPair, Side
from physgate.gate.units import UREG
from physgate.state.schema import Node, Quantity

#: Where a field sits in a result's JSON: keys and list indices from the top.
FieldPath = tuple[str | int, ...]

PAIR = ContractPair(
    producer=Side(module="drive", subtask_id="drive-0a1b2c", role="control"),
    consumer=Side(module="fw", subtask_id="fw-3d4e5f", role="firmware"),
    interfaces=("iface.drive",),
)


def q(value: float, unit: str, by: str = "control") -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "brief", "written_by": by}


def node(node_id: str, role: str, **fields: Any) -> Node:  # noqa: ANN401 - a node's own fields
    payload: dict[str, Any] = {
        "id": node_id,
        "kind": "component",
        "domain": role if role in ("control", "firmware") else "electrical",
        "owner_role": role,
        "quantities": {},
        "constrains": [],
        "geometry_hash": "sha256:0",
        "updated": "2026-10-25T00:00:00Z",
        **fields,
    }
    return Node.model_validate(payload)


def contract(quantities: dict[str, Any], node_id: str = "iface.drive", **fields: Any) -> Node:  # noqa: ANN401
    return node(
        node_id, "control", kind="interface", domain="cross", quantities=quantities, **fields
    )


def graph(*nodes: Node) -> dict[str, Node]:
    return {n.id: n for n in nodes}


def joined_pair(wanted: dict[str, Any], producer: dict[str, Any], consumer: dict[str, Any]) -> Any:  # noqa: ANN401
    """The pair checked over one interface and one joined node on each side."""
    return check_pair(
        PAIR,
        graph(
            contract(wanted),
            node("control.out", "control", constrains=["iface.drive"], quantities=producer),
            node("firmware.in", "firmware", constrains=["iface.drive"], quantities=consumer),
        ),
    )


# --- the tolerance -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wanted", "held", "outcome"),
    [
        (0.0, 1e-300, "value"),
        (0.0, 0.0, "pass"),
        (1.5, 1.5 * (1 + 5e-10), "pass"),
        (1.5, 1.5 * (1 + 2e-9), "value"),
        (-1.5, -1.5 * (1 + 5e-10), "pass"),
    ],
    ids=["zero against 1e-300", "zero against zero", "inside 1e-9", "outside 1e-9", "negative"],
)
def test_a_clause_uses_isclose_with_no_absolute_term(
    wanted: float, held: float, outcome: str
) -> None:
    assert (clause.REL_TOL, clause.ABS_TOL) == (1e-9, 0.0)
    got, _ = agrees(Quantity(**q(held, "V")), Quantity(**q(wanted, "V")))
    assert got == outcome
    assert (got == "pass") == math.isclose(held, wanted, rel_tol=1e-9, abs_tol=0.0)


# --- conversion, as the gate converts --------------------------------------------------------


@pytest.mark.parametrize(
    ("held", "wanted", "outcome"),
    [
        ((12000, "mV"), (12, "V"), "pass"),
        ((1500, "mm"), (1.5, "m"), "pass"),
        ((20.0, "degC"), (293.15, "K"), "pass"),
        ((60, "rpm"), (2 * math.pi, "rad/s"), "pass"),
        ((1, "Hz"), (1, "rad/s"), "unit"),
        ((12, "A"), (12, "V"), "unit"),
        ((3, "dB"), (3, "dB"), "unit"),
        ((3, "furlongs_per_glorp"), (3, "m"), "unit"),
        ((40, "delta_degC"), (40, "degC"), "unit"),
        ((2, "N*m"), (2, "J"), "pass"),
        ((-1, "kg"), (-1, "kg"), "pass"),
        ((12.5, "V"), (12, "V"), "value"),
        ((1e300, "m"), (1e300, "nm"), "value"),
    ],
    ids=[
        "millivolts to volts",
        "millimetres to metres",
        "an absolute temperature",
        "revolutions keep the radian",
        "a frequency is no angular velocity",
        "a current is no voltage",
        "a logarithmic unit is refused",
        "a unit pint cannot read",
        "a difference is no absolute temperature",
        "the shape rule stays the gate's",
        "the sign rule stays the gate's",
        "a value that differs",
        "a converted value past a float's range",
    ],
)
def test_units_are_converted_as_the_gate_converts_them(
    held: tuple[float, str], wanted: tuple[float, str], outcome: str
) -> None:
    got, reason = agrees(Quantity(**q(*held)), Quantity(**q(*wanted)))
    assert got == outcome
    assert (reason is not None) == (outcome == "unit")


def test_a_node_without_the_quantity_s_name_fails_the_clause_as_missing() -> None:
    result = joined_pair({"v": q(12, "V")}, {"v": q(12, "V")}, {"volts": q(12, "V")})
    (check,) = result.interfaces
    (only,) = check.clauses
    assert only.outcome == "fail"
    assert [(n.node, n.side, n.outcome) for n in only.nodes] == [
        ("control.out", "producer", "pass"),
        ("firmware.in", "consumer", "missing"),
    ]
    assert result.outcome == "fail"


# --- what is joined --------------------------------------------------------------------------


def test_a_side_with_no_joined_node_fails_as_not_joined() -> None:
    wanted = {"v": q(12, "V")}
    # The consumer's only node constrains another node, a third role's node constrains the
    # interface, and an interface node of the consumer's role lists it: none of them joins.
    result = check_pair(
        PAIR,
        graph(
            contract(wanted),
            node("control.out", "control", constrains=["iface.drive"], quantities=wanted),
            node("firmware.in", "firmware", constrains=["control.out"], quantities=wanted),
            node("power.rail", "electrical", constrains=["iface.drive"], quantities=wanted),
            node(
                "iface.fw_side",
                "firmware",
                kind="interface",
                domain="cross",
                constrains=["iface.drive"],
                quantities=wanted,
            ),
        ),
    )
    (check,) = result.interfaces
    assert check.not_joined == ("consumer",)
    assert (check.producer_nodes, check.consumer_nodes) == (("control.out",), ())
    assert [c.outcome for c in check.clauses] == ["fail"]
    assert (check.outcome, result.outcome) == ("fail", "fail")


def test_a_node_the_interface_lists_is_joined_as_one_that_lists_the_interface() -> None:
    wanted = {"v": q(12, "V")}
    result = check_pair(
        PAIR,
        graph(
            contract(wanted, constrains=["firmware.in"]),
            node("control.out", "control", constrains=["iface.drive"], quantities=wanted),
            node("firmware.in", "firmware", quantities={"v": q(12000, "mV", "firmware")}),
        ),
    )
    (check,) = result.interfaces
    assert (check.producer_nodes, check.consumer_nodes, check.not_joined) == (
        ("control.out",),
        ("firmware.in",),
        (),
    )
    assert result.outcome == "pass"


def test_a_producer_with_no_joined_node_fails_as_not_joined_too() -> None:
    wanted = {"v": q(12, "V")}
    result = check_pair(
        PAIR,
        graph(
            contract(wanted),
            node("firmware.in", "firmware", constrains=["iface.drive"], quantities=wanted),
        ),
    )
    (check,) = result.interfaces
    assert check.not_joined == ("producer",)
    assert result.outcome == "fail"


# --- counting --------------------------------------------------------------------------------


def test_a_zero_quantity_interface_joined_on_both_sides_records_zero_clauses() -> None:
    joined = check_pair(
        PAIR,
        graph(
            contract({}),
            node("control.out", "control", constrains=["iface.drive"]),
            node("firmware.in", "firmware", constrains=["iface.drive"]),
        ),
    )
    (check,) = joined.interfaces
    assert (check.clauses_checked, joined.clauses_checked) == (0, 0)
    assert (check.outcome, joined.outcome) == ("pass", "pass")
    # Not joined, it fails though it has no clause to fail.
    unjoined = check_pair(
        PAIR, graph(contract({}), node("control.out", "control", constrains=["iface.drive"]))
    )
    assert (unjoined.clauses_checked, unjoined.outcome) == (0, "fail")
    assert unjoined.interfaces[0].not_joined == ("consumer",)


def test_a_result_counts_the_clauses_per_interface_and_in_total() -> None:
    two = ContractPair(
        producer=PAIR.producer, consumer=PAIR.consumer, interfaces=("iface.drive", "iface.rate")
    )
    drive = {"v": q(12, "V"), "i": q(2, "A")}
    rate = {"f": q(100, "Hz")}
    result = check_pair(
        two,
        graph(
            contract(drive),
            contract(rate, node_id="iface.rate"),
            node(
                "control.out",
                "control",
                constrains=["iface.drive", "iface.rate"],
                quantities={**drive, **rate},
            ),
            node(
                "firmware.in",
                "firmware",
                constrains=["iface.drive", "iface.rate"],
                quantities={**drive, "f": q(99, "Hz")},
            ),
        ),
    )
    assert [(c.interface, c.clauses_checked, c.outcome) for c in result.interfaces] == [
        ("iface.drive", 2, "pass"),
        ("iface.rate", 1, "fail"),
    ]
    assert (result.clauses_checked, result.outcome) == (3, "fail")
    assert [c.quantity for c in result.interfaces[0].clauses] == ["i", "v"]


def test_a_result_reads_back_whole_and_one_that_contradicts_itself_is_refused() -> None:
    result = joined_pair({"v": q(12, "V")}, {"v": q(12, "V")}, {"v": q(13, "V")})
    raw = result.model_dump_json()
    assert ContractResult.model_validate_json(raw) == result
    # Each set of changes is consistent above the level it contradicts, so only the check of
    # that level can refuse it: a clause, an interface, or the result as a whole.
    clause: FieldPath = ("interfaces", 0, "clauses", 0, "outcome")
    cases: list[list[tuple[FieldPath, object]]] = [
        [(clause, "pass"), (("interfaces", 0, "outcome"), "pass"), (("outcome",), "pass")],
        [(("interfaces", 0, "not_joined"), ["producer"])],
        [(("interfaces", 0, "clauses_checked"), 0), (("clauses_checked",), 0)],
        [(("interfaces", 0, "outcome"), "pass"), (("outcome",), "pass")],
        [(("clauses_checked",), 2)],
        [(("outcome",), "pass")],
        [(("interfaces", 0, "interface"), "iface.other")],
    ]
    for changes in cases:
        data = json.loads(raw)
        for path, value in changes:
            target = data
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        with pytest.raises(ValidationError):
            ContractResult.model_validate_json(json.dumps(data))


# --- the interface the pair names ------------------------------------------------------------


@pytest.mark.parametrize(
    "interface",
    [
        None,
        node("iface.drive", "control", quantities={"v": q(12, "V")}),
        node("iface.drive", "firmware", kind="interface", domain="cross"),
    ],
    ids=["missing", "not an interface", "owned by another role than the producer"],
)
def test_an_interface_node_that_is_not_the_plan_s_is_refused(interface: Node | None) -> None:
    nodes = graph(node("control.out", "control", constrains=["iface.drive"]))
    if interface is not None:
        nodes[interface.id] = interface
    with pytest.raises(ContractError):
        check_pair(PAIR, nodes)


# --- the definition --------------------------------------------------------------------------


def test_every_contract_result_carries_the_definition_digest() -> None:
    passed = joined_pair({"v": q(12, "V")}, {"v": q(12, "V")}, {"v": q(12, "V")})
    failed = joined_pair({"v": q(12, "V")}, {"v": q(12, "V")}, {"v": q(13, "V")})
    assert (passed.outcome, failed.outcome) == ("pass", "fail")
    digest = definition_sha256()
    assert passed.definition_sha256 == failed.definition_sha256 == digest
    content = definition()
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    assert digest == hashlib.sha256(canonical.encode()).hexdigest()
    assert (content["rel_tol"], content["abs_tol"]) == (repr(1e-9), repr(0.0))
    sources = Path(physgate.__file__).parent
    assert content["sources"] == {
        name: hashlib.sha256((sources / relative).read_bytes()).hexdigest()
        for name, relative in [
            ("clause", "contracts/clause.py"),
            ("units", "gate/units.py"),
            ("unit_spelling", "unit_spelling.py"),
        ]
    }
    assert content["registry_files"] == {}
    assert content["pint"] == f"pint {pint.__version__}"


def test_the_digest_moves_with_the_tolerance_a_source_and_a_registry_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = definition_sha256()
    monkeypatch.setattr(clause, "REL_TOL", 1e-6)
    assert definition_sha256() != before
    monkeypatch.undo()
    assert definition_sha256() == before
    copy = tmp_path / "units.py"
    copy.write_bytes(clause.SOURCES["units"].read_bytes())
    monkeypatch.setitem(clause.SOURCES, "units", copy)
    assert definition_sha256() == before
    copy.write_bytes(copy.read_bytes() + b"# a comment\n")
    assert definition_sha256() != before
    monkeypatch.undo()
    extra = tmp_path / "extra_units.txt"
    extra.write_text("glorp = 3 * meter\n")
    monkeypatch.setattr(clause, "REGISTRY_FILES", (extra,))
    with_file = definition_sha256()
    assert with_file != before
    extra.write_text("glorp = 4 * meter\n")
    assert definition_sha256() not in (before, with_file)


def test_the_conversion_registry_loads_no_definition_file_beyond_pint_s_defaults() -> None:
    # pint marks a registry built from its own defaults with an empty file name.
    assert UREG._filename == ""  # noqa: SLF001 - the only record of what it was built from
    assert clause.REGISTRY_FILES == ()
    package = Path(physgate.__file__).parent
    sources = sorted(package.rglob("*.py"))
    assert sources
    loads = [
        f"{path.relative_to(package)}:{found.lineno}"
        for path in sources
        for found in ast.walk(ast.parse(path.read_text()))
        if isinstance(found, ast.Attribute) and found.attr in ("load_definitions", "define")
    ]
    assert loads == [], "a unit definition is loaded; its file belongs in REGISTRY_FILES"
