"""A quantity may name the simulation record it was read from; one that names none is unchanged.

The reference holds names only: the record's id, the extractor, and for a time record the
trace. It is optional and omitted from every dump when absent, so no existing node, journal
line or digest changes; the seeded workload's journals were shown byte-identical across the
change, and the tests below hold every dump the harness makes of a quantity.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from physgate.state.exceptions import MissingUnitError
from physgate.state.schema import Node, Quantity, SeriesRef, validate_node

PLAIN = {"value": 0.62, "unit": "rad", "source": "the margin script", "written_by": "control"}


def _node(quantity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "control.loop_gain",
        "kind": "component",
        "domain": "control",
        "owner_role": "control",
        "quantities": {"phase_margin": quantity},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-16T00:00:00Z",
    }


def test_a_quantity_naming_no_record_dumps_exactly_as_before() -> None:
    quantity = Quantity.model_validate(PLAIN)
    assert quantity.model_dump() == PLAIN
    assert quantity.model_dump(mode="json") == PLAIN
    assert json.loads(quantity.model_dump_json()) == PLAIN
    assert "series" not in quantity.model_dump_json()


def test_a_node_naming_no_record_dumps_exactly_as_before() -> None:
    payload = _node(PLAIN)
    # A node's own default, which predates the reference, is the only key a dump adds.
    assert validate_node(payload).model_dump() == {**payload, "no_change_justified": {}}


def test_a_quantity_names_its_record_and_how_it_was_read() -> None:
    reference = {"record": "loop_nominal", "extract": "phase_margin"}
    quantity = Quantity.model_validate({**PLAIN, "series": reference})
    assert quantity.series == SeriesRef(record="loop_nominal", extract="phase_margin")
    assert quantity.model_dump()["series"] == reference
    timed = {"record": "step_nominal", "extract": "max_abs", "trace": "tilt"}
    assert Quantity.model_validate({**PLAIN, "series": timed}).model_dump()["series"] == timed


@pytest.mark.parametrize(
    "reference",
    [
        {"record": "step_nominal", "extract": "max"},
        {"record": "loop_nominal", "extract": "phase_margin", "trace": "loop_phase"},
        {"record": "Loop", "extract": "phase_margin"},
        {"record": "../loop", "extract": "phase_margin"},
        {"record": "loop_nominal", "extract": "settling_time"},
        {"record": "loop_nominal", "extract": "phase_margin", "value": 0.62},
        {"record": "loop_nominal"},
        "loop_nominal",
    ],
    ids=[
        "time_without_trace",
        "frequency_with_trace",
        "upper_case_id",
        "parent_step",
        "unknown_extractor",
        "a_number_in_the_reference",
        "no_extractor",
        "a_bare_string",
    ],
)
def test_a_malformed_reference_is_refused(reference: object) -> None:
    with pytest.raises(ValidationError):
        Quantity.model_validate({**PLAIN, "series": reference})


def test_a_bare_number_is_still_refused_with_a_reference_beside_it() -> None:
    bare = {"value": 0.62, "series": {"record": "loop_nominal", "extract": "phase_margin"}}
    with pytest.raises(MissingUnitError):
        validate_node(_node(bare))


def test_a_node_carrying_a_reference_round_trips() -> None:
    payload = _node({**PLAIN, "series": {"record": "loop_nominal", "extract": "phase_margin"}})
    node = Node.model_validate(payload)
    assert node.model_dump() == {**payload, "no_change_justified": {}}
