"""The decomposition holds every interface unit to the unit grammar, at the schema stage.

The decomposition writes the plan's interface nodes into the store, and the change check reads a
stored unit through the unit grammar for as long as the run lasts. A unit the grammar refuses
(``1/(rad*(s))``, ``10*m``) would leave its interface unrevisable: every revision is refused for
the interface's own unit, which no session can change. So the plan's answer is judged by the
grammar too: a unit it refuses is a refusal of the answer at the schema stage, ``schema_refused``,
the one cause a decomposition call is made again for, once, and the refusal names the node, the
quantity and the spelling the grammar takes where one exists. A unit the grammar takes is
written as the product it reads it as, by the very function the change check uses.

The grammar is not the whole of what a later step reads: the change check and the gate hand the
product to the gate's unit registry (:func:`physgate.gate.units.parse`), and a unit the grammar
takes but the registry cannot read (``counts/rev``, ``Nm``, ``m**0``) would leave its interface
unrevisable in the same way. So the plan's units are read by that function too, and such a unit is
the same schema-stage refusal, naming the spelling the registry reads where the grammar has one.

Each row compares what ``judge`` returns, so a row fails on an assertion before the build.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from physgate.contracts.clause import agrees
from physgate.orchestrator.decompose import judge
from physgate.orchestrator.events import RETRIED_CAUSE
from physgate.state.schema import Quantity

NODE: dict[str, Any] = {
    "id": "balance.controller",
    "kind": "interface",
    "domain": "control",
    "owner_role": "control",
    "quantities": {
        "angle_gain": {"value": 2, "unit": "1/rad/s", "source": "brief", "written_by": "control"},
        "bus_voltage": {"value": 12, "unit": "V", "source": "brief", "written_by": "control"},
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-11-11T00:00:00Z",
}
MODEL = "claude-sonnet-5"


def _judged(unit: str) -> tuple[Any, ...]:
    node = copy.deepcopy(NODE)
    node["quantities"]["angle_gain"]["unit"] = unit
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "terminal_reason": "completed",
        "num_turns": 2,
        "modelUsage": {MODEL: {}},
        "structured_output": {
            "modules": [
                {"name": "loop", "role": "control", "module_dir": "modules/loop", "spec": "do it"}
            ],
            "interface_nodes": [node],
        },
    }
    return judge(
        result,
        exit_code=0,
        timed_out=False,
        model=MODEL,
        roles=["control"],
        answered=frozenset({MODEL}),
        brief="Build a robot.",
    )


@pytest.mark.parametrize(
    ("unit", "spelling"),
    [("1/(rad*(s))", "1/rad/s"), ("(rad*s)**-1", "1/rad/s"), ("10*m", None), ("2/rad/s", None)],
)
def test_a_unit_the_grammar_refuses_is_a_schema_refusal_naming_its_spelling(
    unit: str, spelling: str | None
) -> None:
    cause, detail, plan, *_ = _judged(unit)
    assert cause == RETRIED_CAUSE, (cause, detail)
    assert plan is None
    assert "balance.controller" in detail and "angle_gain" in detail
    assert "named units with small integer powers" in detail
    if spelling is None:
        assert "write it as" not in detail
    else:
        assert detail.endswith(f"; write it as {spelling}")


@pytest.mark.parametrize(
    ("unit", "stored"),
    [("1/(rad*s)", "1/rad/s"), ("1/( rad * s )", "1/rad/s"), ("1/rad/s", "1/rad/s"),
     ("rad**-1*s**-1", "rad**-1*s**-1")],
)  # fmt: skip
def test_a_unit_the_grammar_takes_is_planned_as_its_product(unit: str, stored: str) -> None:
    cause, detail, plan, *_ = _judged(unit)
    assert cause is None and plan is not None, (cause, detail)
    (node,) = plan.interface_nodes
    assert node.quantities["angle_gain"].unit == stored
    assert node.quantities["bus_voltage"].unit == "V"


def _read_by_the_change_check(unit: str) -> tuple[str, str | None]:
    """What the change check makes of an interface held in ``unit`` against itself."""
    held = Quantity.model_validate(
        {"value": 2, "unit": unit, "source": "brief", "written_by": "control"}
    )
    return agrees(held, held)


@pytest.mark.parametrize(
    ("unit", "spelling"),
    [("counts/rev", None), ("Nm", None), ("ticks/rev", None), ("LSB", None), ("dB", None),
     ("m**0", "1"), ("1/m**0", "1"), ("m^0", "1")],
)  # fmt: skip
def test_a_unit_the_gate_s_registry_cannot_read_is_a_schema_refusal_naming_its_spelling(
    unit: str, spelling: str | None
) -> None:
    # The grammar takes each of these; the change check could never read one.
    assert _read_by_the_change_check(unit)[0] == "unit"
    cause, detail, plan, *_ = _judged(unit)
    assert cause == RETRIED_CAUSE, (cause, detail)
    assert plan is None
    assert "balance.controller" in detail and "angle_gain" in detail
    assert repr(unit) in detail
    if spelling is None:
        assert "write it as" not in detail
    else:
        assert detail.endswith(f"; write it as {spelling}")
        assert _read_by_the_change_check(spelling) == ("pass", None)


@pytest.mark.parametrize(
    "unit", ["1/(rad*s)", "1/rad/s", "rad**-1*s**-1", "V*s/rad", "N*m", "count/s", "1"]
)
def test_every_unit_the_decomposition_stores_is_one_the_change_check_reads(unit: str) -> None:
    cause, detail, plan, *_ = _judged(unit)
    assert cause is None and plan is not None, (cause, detail)
    (node,) = plan.interface_nodes
    for quantity in node.quantities.values():
        assert _read_by_the_change_check(quantity.unit) == ("pass", None), quantity.unit


@pytest.mark.parametrize("unit", ["counts/(rev/s)", "(Nm)", "N*m/(rev/s)", "(ticks)**2"])
def test_a_refusal_names_no_spelling_the_gate_s_registry_cannot_read(unit: str) -> None:
    # The grammar has a spelling for each, and the registry reads none of them: naming one
    # would have the retry write a unit that is refused again.
    cause, detail, plan, *_ = _judged(unit)
    assert cause == RETRIED_CAUSE and plan is None, (cause, detail)
    assert repr(unit) in detail and "balance.controller" in detail and "angle_gain" in detail
    assert "write it as" not in detail


def test_a_refusal_names_the_unit_as_the_plan_wrote_it() -> None:
    # A bracketed denominator the registry cannot read is named as written, not as its product.
    cause, detail, *_ = _judged("counts/(rev*s)")
    assert cause == RETRIED_CAUSE, (cause, detail)
    assert "'counts/(rev*s)'" in detail and "write it as" not in detail
