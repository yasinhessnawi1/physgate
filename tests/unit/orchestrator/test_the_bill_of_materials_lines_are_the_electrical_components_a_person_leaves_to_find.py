"""The bill of materials' lines, and the ones a check of it will consider.

A line is the node id of every component in the electrical domain, in the order the nodes come,
read from the nodes alone: a sizing node, a mechanical component and an interface are no line,
and a node carries no mark for it. The lines a check of the bill of materials will consider are
those a person left to find; a part a person has or makes is not checked, and when the run does not
ask, every line is. Each row runs over the run in ``parts_bom_fixture``, the one the parts reader
asserts against too. No check of the bill of materials is built yet; these two functions give it
what to look at.
"""

from __future__ import annotations

import importlib
from types import MappingProxyType
from typing import Any

from parts_bom_fixture import BOM_LINES, EVENT_LOG, NODES

from physgate.orchestrator.events import parse_events
from physgate.orchestrator.replay import RunState, replay
from physgate.state.schema import Node

PARTS = "physgate.orchestrator.parts"


def named(name: str) -> Any:  # noqa: ANN401
    module = importlib.import_module(PARTS)
    assert hasattr(module, name), f"the parts module has no {name}"
    return getattr(module, name)


def nodes() -> list[Node]:
    return [Node.model_validate(n) for n in NODES]


def released() -> RunState:
    return replay(parse_events(EVENT_LOG, log="fixture"))


def test_the_lines_are_the_fixture_s_electrical_components_in_order() -> None:
    assert named("bom_lines")(nodes()) == BOM_LINES


def test_a_sizing_node_a_mechanical_component_and_an_interface_are_no_line() -> None:
    lines = named("bom_lines")(nodes())
    assert "sizing.electrical_motor_driver" not in lines
    assert "mechanical.chassis_plate" not in lines
    assert "iface.bus" not in lines


def test_an_electrical_node_that_is_not_a_component_is_no_line() -> None:
    other = [n.model_copy(update={"kind": "interface"}) for n in nodes()]
    assert named("bom_lines")(other) == ()


def test_the_lines_follow_the_order_of_the_nodes() -> None:
    assert named("bom_lines")(reversed(nodes())) == tuple(reversed(BOM_LINES))


def test_only_the_lines_a_person_left_to_find_are_to_check() -> None:
    choices = named("parts_choices")(released())
    assert named("bom_lines_to_check")(nodes(), choices) == ("electrical.wheel_encoder",)


def test_a_line_the_choices_do_not_name_is_to_check() -> None:
    assert named("bom_lines_to_check")(nodes(), MappingProxyType({})) == BOM_LINES


def test_every_line_is_to_check_when_the_run_does_not_ask() -> None:
    state = released()
    choices = named("parts_choices")(state)
    assert named("bom_lines_to_check")(nodes(), choices) != BOM_LINES
    off = named("parts_choices")(_not_asking())
    assert named("bom_lines_to_check")(nodes(), off) == BOM_LINES


def _not_asking() -> RunState:
    import json

    lines = [json.loads(json.dumps(x)) for x in _fixture_lines()]
    del lines[0]["parts_on_hand"]
    del lines[2]["components"]
    log = b"".join(json.dumps(one).encode() + b"\n" for one in lines[:8])
    return replay(parse_events(log, log="off"))


def _fixture_lines() -> Any:  # noqa: ANN401
    from parts_bom_fixture import LINES

    return LINES
