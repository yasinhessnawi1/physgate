"""The lines are the plan's parts a person answered "find", whatever their domain, in plan order.

The choice is read from the run's release line, through the parts module's one read function;
the domain and label from the plan's component list. A part a person has or makes is no line. A
run that asks nothing has no lines; a run that asks and is not released yet is refused, since a
check then would take every part a person has as one to buy.
"""

from __future__ import annotations

import json

import pytest
from bom_helpers import before, not_asking
from parts_bom_fixture import EVENT_LOG

from physgate.build.bom.check import Line, lines_of
from physgate.orchestrator.events import PartsReleased, ReleasedPart, parse_events
from physgate.orchestrator.parts import PartsChoiceError
from physgate.orchestrator.plan import Component
from physgate.orchestrator.replay import RunState, replay


def _replayed(lines: list[dict[str, object]]) -> RunState:
    data = b"".join(json.dumps(one).encode() + b"\n" for one in lines)
    return replay(parse_events(data, log="rows"))


def test_the_fixture_run_s_one_part_to_find_is_its_one_line() -> None:
    state = replay(parse_events(EVENT_LOG, log="fixture"))
    assert lines_of(state) == (
        Line(node="electrical.wheel_encoder", domain="electrical", label="Wheel encoder"),
    )


def test_a_run_that_asks_nothing_has_no_lines() -> None:
    assert lines_of(_replayed(not_asking())) == ()


def test_a_run_that_asks_and_is_not_released_is_refused() -> None:
    with pytest.raises(PartsChoiceError, match="not released"):
        lines_of(_replayed(before("parts_write_intended")))


def _released(choices: dict[str, str], domains: dict[str, str]) -> RunState:
    """A state that asks, whose plan lists ``domains`` and whose release took ``choices``."""
    fixture = replay(parse_events(EVENT_LOG, log="fixture"))
    assert fixture.parts_released is not None
    state = RunState()
    state.asks_parts = True
    state.components = tuple(
        Component.model_validate(
            {
                "node": node,
                "domain": domain,
                "role": "control",
                "label": f"the {node}",
                "own": (),
                "shared": (),
            }
        )
        for node, domain in domains.items()
    )
    parts = tuple(
        ReleasedPart.model_validate(
            {
                "item_id": f"run-1-parts-{n}",
                "node": node,
                "choice": choice,
                "parts": None if choice == "find" else {"declared": {}, "texts": ("stated",)},
            }
        )
        for n, (node, choice) in enumerate(choices.items(), start=1)
    )
    state.parts_released = PartsReleased.model_validate(
        {**fixture.parts_released.model_dump(), "components": parts}
    )
    return state


def test_every_part_answered_find_is_a_line_whatever_its_domain_and_in_plan_order() -> None:
    domains = {
        "part.wheels": "mechanical",
        "part.battery": "electrical",
        "part.gearmotor": "electrical",
        "part.chassis": "mechanical",
        "part.board": "firmware",
    }
    choices = {
        "part.wheels": "find",
        "part.battery": "have",
        "part.gearmotor": "find",
        "part.chassis": "make",
        "part.board": "find",
    }
    lines = lines_of(_released(choices, domains))
    assert [(one.node, one.domain) for one in lines] == [
        ("part.wheels", "mechanical"),
        ("part.gearmotor", "electrical"),
        ("part.board", "firmware"),
    ]
    assert lines[0].label == "the part.wheels"


def test_a_run_where_every_part_is_had_or_made_has_no_lines() -> None:
    domains = {"part.a": "electrical", "part.b": "mechanical"}
    assert lines_of(_released({"part.a": "have", "part.b": "make"}, domains)) == ()


def test_a_part_the_release_does_not_name_is_no_line() -> None:
    # Replay holds the release to the plan, so this does not happen on a real log; the check
    # still never takes a part as one to buy by default.
    domains = {"part.a": "electrical", "part.b": "electrical"}
    lines = lines_of(_released({"part.a": "find"}, domains))
    assert [one.node for one in lines] == ["part.a"]
