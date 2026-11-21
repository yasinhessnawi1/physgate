"""Each part's choice is read from the release alone, and sourcing skips what is owned or made.

ARCH-122. One function gives the roles after the release what a person decided of each component:
its choice and the values it declared, keyed by the component's own node id, read only from the
replayed release line, never more than a plan's components. A node it does not name is to find;
a run that does not ask names none; a run that asks and is not released yet is refused, since a
reader then would take every part a person has as one to find.

A stub stands where sourcing will: over the bill of materials' lines it records a part a person has
as skipped because it is owned, one a person makes as skipped because it is custom, and leaves a
part to find unchecked. It validates nothing, so no line is ever recorded as validated.

Every row runs over the run in ``parts_bom_fixture``, the one the bill of materials' reader asserts
against too. Each name of the parts module is looked up when a row asks for it, so a row fails on
an assertion, not at collection, in a tree without it.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
from types import ModuleType
from typing import Any

import pytest
from parts_bom_fixture import BOM_LINES, CHOICES, EVENT_LOG, LINES, NODES, SOURCING

from physgate.orchestrator.events import PartsReleased, parse_events
from physgate.orchestrator.plan import MAX_COMPONENTS
from physgate.orchestrator.replay import RunState, replay
from physgate.state.schema import Node

PARTS = "physgate.orchestrator.parts"


def _module() -> ModuleType:
    assert importlib.util.find_spec(PARTS) is not None, "the parts module is not built"
    return importlib.import_module(PARTS)


def named(name: str) -> Any:  # noqa: ANN401 - whatever the name holds
    module = _module()
    assert hasattr(module, name), f"the parts module has no {name}"
    return getattr(module, name)


def outcome_of(call: Any, *args: Any) -> Any:  # noqa: ANN401
    """What ``call`` returns, or the error it raises, so a row asserts on either."""
    try:
        return call(*args)
    except Exception as exc:  # noqa: BLE001 - the refusal is what a row asserts on
        return exc


def _log(lines: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(one).encode() + b"\n" for one in lines)


def released() -> RunState:
    """The fixture's run, replayed to its release."""
    return replay(parse_events(EVENT_LOG, log="fixture"))


def _before(kind: str) -> list[dict[str, Any]]:
    kinds = [one["kind"] for one in LINES]
    return [dict(one) for one in LINES[: kinds.index(kind)]]


def unreleased() -> RunState:
    """The fixture's run, every part decided, nothing yet written or released."""
    return replay(parse_events(_log(_before("parts_write_intended")), log="decided"))


def not_asking() -> RunState:
    """The fixture's opening as a run that does not ask: the switch off, no components."""
    lines = _before("decision_taken")
    del lines[0]["parts_on_hand"]
    del lines[2]["components"]
    return replay(parse_events(_log(lines), log="off"))


def _as_expected(choices: Any) -> dict[str, tuple[str, dict[str, tuple[Any, str]]]]:  # noqa: ANN401
    return {
        node: (
            one.choice,
            {name: (value.value, value.unit) for name, value in one.declared.items()},
        )
        for node, one in choices.items()
    }


def _release_of(state: RunState, components: tuple[Any, ...]) -> RunState:
    """A state holding only that the run asks and a release naming ``components``."""
    line = state.parts_released
    assert line is not None
    fresh = RunState()
    fresh.asks_parts = True
    fresh.parts_released = PartsReleased.model_validate(
        {**line.model_dump(), "components": tuple(one.model_dump() for one in components)}
    )
    return fresh


def _many(count: int) -> RunState:
    state = released()
    assert state.parts_released is not None
    first = state.parts_released.components[2]
    copies = tuple(
        first.model_copy(update={"node": f"electrical.part_{n}", "item_id": f"run-1-parts-{n}"})
        for n in range(1, count + 1)
    )
    return _release_of(state, copies)


# --- the fixture itself -----------------------------------------------------------------------


def test_the_fixture_replays_to_its_release_and_its_nodes_are_graph_nodes() -> None:
    state = released()
    assert state.asks_parts
    assert state.parts_released is not None
    assert [one.node for one in state.parts_released.components] == list(CHOICES)
    for node in NODES:
        Node.model_validate(node)


def test_the_fixture_s_bom_lines_are_its_electrical_components_and_no_sizing_node() -> None:
    lines = named("bom_lines")(Node.model_validate(n) for n in NODES)
    assert lines == BOM_LINES
    sizing = [n for n in NODES if n["domain"] == "cross"]
    assert len(sizing) == 1
    assert sizing[0]["quantities"], "the sizing node holds a declared value"
    assert sizing[0]["id"] not in BOM_LINES
    assert set(BOM_LINES) == set(SOURCING)


# --- the read function ------------------------------------------------------------------------


def test_each_component_s_choice_and_declared_values_are_read_from_the_release() -> None:
    choices = named("parts_choices")(released())
    assert _as_expected(choices) == CHOICES


def test_the_map_is_keyed_by_the_component_s_own_node_and_names_no_sizing_node() -> None:
    choices = named("parts_choices")(released())
    assert set(choices) == set(CHOICES)
    assert "sizing.electrical_motor_driver" not in choices
    assert set(BOM_LINES) <= set(choices)


def test_a_choice_holds_its_choice_and_declared_values_and_no_text() -> None:
    choices = named("parts_choices")(released())
    made = choices["electrical.battery_pack"]
    assert made.choice == "make"
    assert not hasattr(made, "texts")
    assert {field.name for field in dataclasses.fields(made)} == {"choice", "declared"}


def test_a_part_to_find_declares_nothing() -> None:
    choices = named("parts_choices")(released())
    assert choices["electrical.wheel_encoder"].choice == "find"
    assert dict(choices["electrical.wheel_encoder"].declared) == {}


def test_the_map_and_each_choice_s_values_cannot_be_changed_by_a_reader() -> None:
    choices = named("parts_choices")(released())
    with pytest.raises(TypeError):
        choices["electrical.wheel_encoder"] = choices["electrical.motor_driver"]
    with pytest.raises(TypeError):
        choices["electrical.motor_driver"].declared["mass"] = None


def test_a_node_the_map_does_not_name_is_to_find() -> None:
    choice_of = named("choice_of")
    choices = named("parts_choices")(released())
    assert choice_of(choices, "electrical.motor_driver") == "have"
    assert choice_of(choices, "electrical.battery_pack") == "make"
    assert choice_of(choices, "electrical.fuse") == "find"
    assert choice_of({}, "electrical.motor_driver") == "find"


def test_a_run_that_does_not_ask_gives_an_empty_map() -> None:
    state = not_asking()
    assert not state.asks_parts
    assert outcome_of(dict, outcome_of(named("parts_choices"), state)) == {}
    assert outcome_of(dict, outcome_of(named("parts_choices"), RunState())) == {}


def test_a_run_that_asks_and_is_not_released_is_refused() -> None:
    state = unreleased()
    assert state.asks_parts
    assert state.parts_released is None
    refused = named("PartsChoiceError")
    with pytest.raises(refused) as caught:
        named("parts_choices")(state)
    assert "not released" in str(caught.value)


def test_the_release_line_alone_is_read() -> None:
    state = released()
    assert state.parts_released is not None
    only = _release_of(state, state.parts_released.components)
    assert _as_expected(named("parts_choices")(only)) == CHOICES


def test_a_release_of_as_many_components_as_a_plan_may_hold_is_read() -> None:
    choices = outcome_of(named("parts_choices"), _many(MAX_COMPONENTS))
    assert not isinstance(choices, Exception), choices
    assert len(choices) == MAX_COMPONENTS


def test_a_release_of_more_components_than_a_plan_may_hold_is_refused() -> None:
    refused = named("PartsChoiceError")
    with pytest.raises(refused) as caught:
        named("parts_choices")(_many(MAX_COMPONENTS + 1))
    assert str(MAX_COMPONENTS) in str(caught.value)


# --- the stub sourcing consumer ---------------------------------------------------------------


def _records(lines: Any) -> dict[str, tuple[str, str | None]]:  # noqa: ANN401
    return {one.node: (one.status, one.reason) for one in lines}


def test_sourcing_skips_a_part_owned_or_made_and_leaves_a_part_to_find_unchecked() -> None:
    lines = named("sourcing_lines")(BOM_LINES, named("parts_choices")(released()))
    assert _records(lines) == SOURCING


def test_sourcing_records_each_line_once_in_the_order_given() -> None:
    choices = named("parts_choices")(released())
    backwards = tuple(reversed(BOM_LINES))
    lines = named("sourcing_lines")(backwards, choices)
    assert [one.node for one in lines] == list(backwards)


@pytest.mark.parametrize(
    ("node", "status", "reason"),
    [
        ("electrical.motor_driver", "skipped", "owned"),
        ("electrical.battery_pack", "skipped", "custom"),
        ("electrical.wheel_encoder", "unchecked", None),
        ("mechanical.chassis_plate", "skipped", "owned"),
    ],
    ids=["have", "make", "find", "have, not electrical"],
)
def test_each_choice_is_recorded_as_its_status_and_reason(
    node: str, status: str, reason: str | None
) -> None:
    lines = named("sourcing_lines")((node,), named("parts_choices")(released()))
    assert _records(lines) == {node: (status, reason)}


def test_no_line_is_ever_recorded_as_validated() -> None:
    choices = named("parts_choices")(released())
    every = (*CHOICES, "electrical.fuse")
    lines = named("sourcing_lines")(every, choices)
    assert {one.status for one in lines} == {"skipped", "unchecked"}
    for one in lines:
        assert (one.status == "skipped") == (one.reason is not None), one


def test_a_line_the_map_does_not_name_is_unchecked() -> None:
    lines = named("sourcing_lines")(("electrical.fuse",), named("parts_choices")(released()))
    assert _records(lines) == {"electrical.fuse": ("unchecked", None)}


def test_a_run_that_does_not_ask_leaves_every_line_unchecked() -> None:
    choices = outcome_of(named("parts_choices"), not_asking())
    assert not isinstance(choices, Exception), choices
    lines = named("sourcing_lines")(BOM_LINES, choices)
    assert _records(lines) == dict.fromkeys(BOM_LINES, ("unchecked", None))
