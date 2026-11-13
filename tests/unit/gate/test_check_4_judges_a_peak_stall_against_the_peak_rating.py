"""Check 4, peak headroom: a motor's peak stall current against its driver's peak rating.

The owner settled the stall's basis as both, named apart. ``stall_current`` is the stall at the
command limit's duty times the supply's highest voltage, the current the design sizes for;
``peak_stall_current`` is the stall at full duty and that same voltage, the most the motor can
draw, if the duty limit is bypassed or during a PWM on-time. A driver's peak rating and a fuse
are judged at the peak. So where a node holds ``peak_stall_current``, check 4 holds it to the
``current_limit`` on its own node and on each supply its constrains edges name, as it holds the
stall current, under a relation of its own; a peak no limit bounds is recorded as unchecked.

Where no node holds the name, nothing forms and check 4 is as it was: the stall current's
relation is untouched, and every record it writes is the one it wrote before.

A law that restates the peak headroom, by its names and its comparator, is refused at load, as
any law restating a relation the checks form is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node
from law_fixtures import refused, sound_law

from physgate.gate import check_power
from physgate.gate.bounds_table import load_bounds
from physgate.gate.catalogue import RELATIONS
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.relations import RELATION_INPUTS, instances
from physgate.orchestrator.protocols import PowerDetails, Scope, UncheckedDetails

PEAK = "peak_current_limit"
DRIVER = "electrical.driver"
MOTOR = "electrical.motor_left"


def driver(amps: float = 1.8) -> dict[str, Any]:
    return node(DRIVER, quantities={"current_limit": (amps, "A")})


def motor(stall: float | None = 1.575, peak: float | None = 2.1, **extra: Any) -> dict[str, Any]:
    quantities: dict[str, Any] = dict(extra)
    if stall is not None:
        quantities["stall_current"] = (stall, "A")
    if peak is not None:
        quantities["peak_stall_current"] = (peak, "A")
    return node(MOTOR, quantities=quantities, constrains=[DRIVER])


def view_of(tmp_path: Path, *payloads: dict[str, Any], base: int = 0) -> GraphView:
    graph(tmp_path / "g", *payloads)
    return GraphView.read(tmp_path / "g", base_revision=base)


def check(tmp_path: Path, scope: Scope, *payloads: dict[str, Any]) -> Any:
    view = view_of(tmp_path, *payloads)
    return check_power.run(CheckContext(view=view, scope=scope, bounds=load_bounds()))


def test_the_peak_headroom_is_a_relation_of_its_own_judged_by_the_power_check() -> None:
    relation = RELATIONS.get(PEAK)
    assert relation is not None, f"the catalogue has no {PEAK} relation"
    assert relation.judged_by == 4
    assert "peak stall current" in relation.statement and "full duty" in relation.statement
    inputs = RELATION_INPUTS.get(PEAK)
    assert inputs is not None
    assert (inputs.names, inputs.comparator) == (
        frozenset({"peak_stall_current", "current_limit"}),
        "<=",
    )
    # The stall current's relation reads what it read.
    assert RELATION_INPUTS["current_limit"].names == frozenset({"stall_current", "current_limit"})


@pytest.mark.parametrize("scope", ["module", "system"])
def test_a_peak_above_the_driver_s_rating_is_refused_where_the_operating_stall_passes(
    tmp_path: Path, scope: Scope
) -> None:
    ran = check(tmp_path, scope, driver(1.8), motor(stall=1.575, peak=2.1))
    assert [o.outcome for o in ran.observations] == ["fail"]
    (finding,) = ran.observations
    assert finding.node == DRIVER
    assert finding.value is not None and (finding.value.value, finding.value.unit) == (0.3, "A")
    assert {q.name for q in finding.quantities} == {"peak_stall_current", "current_limit"}
    assert isinstance(finding.details, PowerDetails)
    assert finding.details.contributing == (DRIVER, MOTOR)
    assert f"{MOTOR} stalls at 2.1 A at full duty" in finding.message, finding.message
    assert "more than the 1.8 A current limit of electrical.driver by 0.3 A" in finding.message
    assert finding.expected == "a peak stall current of at most the 1.8 A current limit"
    # Both stalls are judged: the operating one passes, the peak does not.
    assert ran.evaluated == 2


def test_a_peak_above_its_own_node_s_limit_is_refused_as_that_node_s(tmp_path: Path) -> None:
    own = node(
        "electrical.drive",
        quantities={"peak_stall_current": (2.1, "A"), "current_limit": (1.8, "A")},
    )
    ran = check(tmp_path, "system", own)
    assert [o.outcome for o in ran.observations] == ["fail"]
    (finding,) = ran.observations
    assert finding.node == "electrical.drive"
    assert "the 1.8 A current limit on its own node" in finding.message, finding.message
    assert ran.evaluated == 1


def test_a_peak_within_the_rating_passes_and_is_counted(tmp_path: Path) -> None:
    ran = check(tmp_path, "system", driver(2.5), motor(stall=1.575, peak=2.1))
    assert ran.observations == () and ran.evaluated == 2


def test_a_peak_no_limit_bounds_is_recorded_unchecked_never_passed(tmp_path: Path) -> None:
    alone = node(MOTOR, quantities={"peak_stall_current": (2.1, "A")})
    ran = check(tmp_path, "system", alone)
    assert [o.outcome for o in ran.observations] == ["unchecked"]
    (record,) = ran.observations
    assert "the peak stall current of electrical.motor_left cannot be checked" in record.message
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("current_limit",)
    assert ran.evaluated == 0


def test_without_the_name_no_peak_relation_forms(tmp_path: Path) -> None:
    # Guard: a graph with no peak stall current forms what it formed before, and nothing else.
    view = view_of(tmp_path, driver(1.8), motor(stall=2.2, peak=None))
    found = instances(view)
    assert {i.relation.name for i in found} == {"current_limit"}
    assert len(found) == 1


def test_a_law_restating_the_peak_headroom_is_refused(tmp_path: Path) -> None:
    row = sound_law(
        expression="L >= P",
        tolerance="inequality",
        anchor="P",
        symbols={
            "P": {"name": "peak_stall_current", "place": "self"},
            "L": {"name": "current_limit", "place": "self"},
        },
    )
    assert PEAK in refused(tmp_path, [row])
