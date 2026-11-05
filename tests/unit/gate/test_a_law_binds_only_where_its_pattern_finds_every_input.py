"""A law binds to the graph only by its pattern, and judges only where it finds every input.

A law forms an instance where its anchor is: on a node (``node``), on a node and each node its
``constrains`` edges name (``edge``), or on a subject and every member whose edge names it
(``members``). Where the anchor is absent there is no instance and no record. Where the anchor
is present and the law cannot be judged, the instance is recorded **unchecked**, naming the law
and why, and never passed:

- an input the law needs is missing, or a name it requires is absent;
- a name that excuses it is present (its idealisation does not hold there);
- its edge leads into an interface node, fixed at decomposition, or into no node at all;
- its subject has no member that holds what the law sums (an empty sum is never evaluated);
- an input is in a unit the unit check refuses, or the law would divide by zero.

A law's count says how many instances it judged, so a law that judged nothing is never hidden
behind one that judged much.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from gate_fixtures import graph, node
from law_cases import (
    evaluated,
    laws_records,
    of_law,
    one,
    rate_throughput,
    reaction_sum,
    stall_by_resistance,
    table,
    within_rating,
)
from law_fixtures import sound_law

from physgate.gate.graph import GraphView
from physgate.orchestrator.protocols import CheckRecord, LawDetails, UncheckedDetails

IMU = {"power_draw": (12.9, "mW"), "supply_voltage": (3.3, "V"), "current_draw": (3.9, "mA")}


def view_of(tmp_path: Path, *payloads: dict[str, object], base: int = 0) -> GraphView:
    graph(tmp_path / "g", *payloads)
    return GraphView.read(tmp_path / "g", base_revision=base)


def unchecked_of(records: list[CheckRecord], law_id: str) -> list[CheckRecord]:
    found = [r for r in of_law(records, law_id) if r.outcome == "unchecked"]
    for record in found:
        assert isinstance(record.details, UncheckedDetails)
        assert record.details.law_id == law_id
    return found


def judged_of(records: list[CheckRecord], law_id: str) -> list[CheckRecord]:
    return [r for r in of_law(records, law_id) if r.outcome in ("fail", "warn")]


# --- node ----------------------------------------------------------------------------------


def test_a_node_law_judges_the_node_that_holds_every_input(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    view = view_of(tmp_path, node("electrical.imu", quantities=IMU))
    records = laws_records(laws, view)
    assert evaluated(records, "electrical_power") == 1
    assert judged_of(records, "electrical_power") == []
    assert unchecked_of(records, "electrical_power") == []


def test_a_node_law_refuses_a_node_whose_numbers_break_it(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    wrong = {**IMU, "power_draw": (19.5, "mW")}
    view = view_of(tmp_path, node("electrical.imu", quantities=wrong))
    record = one(judged_of(laws_records(laws, view), "electrical_power"))
    assert record.node == "electrical.imu" and record.outcome == "warn"
    assert isinstance(record.details, LawDetails) and record.details.evaluated == 1


def test_no_anchor_means_no_instance_and_no_record_but_the_law_s_own_count(
    tmp_path: Path,
) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    view = view_of(
        tmp_path,
        node(
            "electrical.imu", quantities={"supply_voltage": (3.3, "V"), "current_draw": (4, "mA")}
        ),
    )
    records = of_law(laws_records(laws, view), "electrical_power")
    assert [r.outcome for r in records] == ["pass"]
    assert evaluated(records, "electrical_power") == 0


@pytest.mark.parametrize("dropped", ["supply_voltage", "current_draw"])
def test_an_anchor_without_another_input_is_unchecked_naming_it(
    tmp_path: Path, dropped: str
) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    partial = {k: v for k, v in IMU.items() if k != dropped}
    view = view_of(tmp_path, node("electrical.imu", quantities=partial))
    records = laws_records(laws, view)
    record = one(unchecked_of(records, "electrical_power"))
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == (dropped,)
    assert dropped in record.message and "electrical_power" in record.message
    # Judged nothing: no pass of what was not read.
    assert [r.outcome for r in of_law(records, "electrical_power")] == ["unchecked"]


def test_a_missing_required_name_is_unchecked_naming_it(tmp_path: Path) -> None:
    law = within_rating(requires=[{"name": "supply_voltage", "place": "self"}])
    laws = table(tmp_path / "t", [law])
    bare = node("electrical.imu", quantities={"current_draw": (1, "A"), "current_limit": (2, "A")})
    records = laws_records(laws, view_of(tmp_path, bare))
    record = one(unchecked_of(records, "within_rating"))
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("supply_voltage",)
    supplied = node(
        "electrical.imu",
        quantities={
            "current_draw": (1, "A"),
            "current_limit": (2, "A"),
            "supply_voltage": (5, "V"),
        },
    )
    assert evaluated(laws_records(laws, view_of(tmp_path / "s", supplied)), "within_rating") == 1


def test_a_present_excusing_name_is_unchecked_with_the_law_s_reason(tmp_path: Path) -> None:
    reason = "a switched node's mean power is not its mean voltage times its mean current"
    law = sound_law(unless=[{"name": "duty_cycle", "place": "self", "reason": reason}])
    laws = table(tmp_path / "t", [law])
    # Wrong numbers, so a lenient evaluator would refuse it; the excuse leaves it unjudged.
    switched = {**IMU, "power_draw": (19.5, "mW"), "duty_cycle": (0.5, "dimensionless")}
    records = laws_records(laws, view_of(tmp_path, node("electrical.imu", quantities=switched)))
    record = one(unchecked_of(records, "electrical_power"))
    assert reason in record.message
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("duty_cycle",)
    assert judged_of(records, "electrical_power") == []


# --- edge ----------------------------------------------------------------------------------


def consumer(rate: float, *targets: str) -> dict[str, object]:
    return node(
        "firmware.estimator",
        domain="firmware",
        quantities={"update_rate": (rate, "Hz")},
        constrains=list(targets),
    )


def producer(
    node_id: str = "electrical.imu", rate: float = 200, kind: str = "component"
) -> dict[str, object]:
    return node(node_id, kind=kind, quantities={"output_data_rate": (rate, "Hz")})


def test_an_edge_law_judges_the_node_its_edge_names(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [rate_throughput()])
    fine = laws_records(laws, view_of(tmp_path / "a", producer(), consumer(100, "electrical.imu")))
    assert evaluated(fine, "rate_throughput") == 1 and judged_of(fine, "rate_throughput") == []
    fast = laws_records(laws, view_of(tmp_path / "b", producer(), consumer(400, "electrical.imu")))
    record = one(judged_of(fast, "rate_throughput"))
    assert record.node == "firmware.estimator"
    assert isinstance(record.details, LawDetails)
    assert {(i.node_id, i.name) for i in record.details.inputs} == {
        ("firmware.estimator", "update_rate"),
        ("electrical.imu", "output_data_rate"),
    }


def test_an_edge_into_an_interface_node_is_unchecked(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [rate_throughput()])
    bus = producer("iface.sensor_bus", kind="interface")
    records = laws_records(laws, view_of(tmp_path, bus, consumer(400, "iface.sensor_bus")))
    record = one(unchecked_of(records, "rate_throughput"))
    assert "interface" in record.message and "iface.sensor_bus" in record.message
    assert judged_of(records, "rate_throughput") == []


def test_an_edge_into_no_node_is_unchecked(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [rate_throughput()])
    records = laws_records(laws, view_of(tmp_path, consumer(400, "electrical.missing")))
    record = one(unchecked_of(records, "rate_throughput"))
    assert "electrical.missing" in record.message and "not in the graph" in record.message


def test_an_anchor_whose_edges_name_no_holder_is_unchecked_naming_the_target_input(
    tmp_path: Path,
) -> None:
    laws = table(tmp_path / "t", [rate_throughput()])
    other = node("electrical.motor", quantities={"stall_current": (2, "A")})
    for root, payloads in (
        ("a", (consumer(400),)),
        ("b", (other, consumer(400, "electrical.motor"))),
    ):
        records = laws_records(laws, view_of(tmp_path / root, *payloads))
        record = one(unchecked_of(records, "rate_throughput"))
        assert isinstance(record.details, UncheckedDetails)
        assert record.details.quantities == ("output_data_rate",)


def test_an_edge_law_judges_each_edge_on_its_own(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [rate_throughput()])
    view = view_of(
        tmp_path,
        producer("electrical.fast", 800),
        producer("electrical.slow", 100),
        producer("iface.bus", kind="interface"),
        consumer(400, "electrical.fast", "electrical.slow", "iface.bus"),
    )
    records = laws_records(laws, view)
    assert evaluated(records, "rate_throughput") == 2
    failed = one(judged_of(records, "rate_throughput"))
    assert isinstance(failed.details, LawDetails)
    assert "electrical.slow" in failed.details.expression
    assert len(unchecked_of(records, "rate_throughput")) == 1


# --- members -------------------------------------------------------------------------------


def carrier(moment: float) -> dict[str, object]:
    return node(
        "mechanical.chassis",
        kind="module",
        domain="mechanical",
        quantities={"reaction_moment": (moment, "N*m")},
    )


def unit(name: str, moment: float) -> dict[str, object]:
    return node(
        f"mechanical.{name}",
        domain="mechanical",
        quantities={"reaction_moment": (moment, "N*m")},
        constrains=["mechanical.chassis"],
    )


def test_a_members_law_sums_every_member_whose_edge_names_the_subject(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [reaction_sum()])
    held = laws_records(
        laws, view_of(tmp_path / "a", carrier(3), unit("left", 1), unit("right", 2))
    )
    assert evaluated(held, "reaction_moment_sum") == 1
    assert judged_of(held, "reaction_moment_sum") == []
    short = laws_records(
        laws, view_of(tmp_path / "b", carrier(2), unit("left", 1), unit("right", 2))
    )
    record = one(judged_of(short, "reaction_moment_sum"))
    assert record.node == "mechanical.chassis"
    assert isinstance(record.details, LawDetails)
    assert len(record.details.inputs) == 3


@pytest.mark.parametrize("moment", [0, 5])
def test_a_subject_no_member_names_is_unchecked_never_an_empty_sum(
    tmp_path: Path, moment: float
) -> None:
    # An empty sum would pass a carrier declaring 0 and refuse one declaring 5; neither is judged.
    laws = table(tmp_path / "t", [reaction_sum()])
    loose = node("mechanical.motor", domain="mechanical", quantities={"mass": (1, "kg")})
    records = laws_records(laws, view_of(tmp_path, carrier(moment), loose))
    record = one(unchecked_of(records, "reaction_moment_sum"))
    assert "no member" in record.message
    assert [r.outcome for r in of_law(records, "reaction_moment_sum")] == ["unchecked"]


# --- inputs the law cannot evaluate --------------------------------------------------------


def test_an_input_the_unit_check_refuses_is_unchecked(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [sound_law()])
    for root, bad in (
        ("dimension", {**IMU, "current_draw": (3.9, "V")}),
        ("sign", {**IMU, "power_draw": (-12.9, "mW")}),
    ):
        records = laws_records(
            laws, view_of(tmp_path / root, node("electrical.imu", quantities=bad))
        )
        record = one(unchecked_of(records, "electrical_power"))
        assert "unit check refuses" in record.message
        assert judged_of(records, "electrical_power") == []


def test_a_law_that_would_divide_by_zero_is_unchecked(tmp_path: Path) -> None:
    laws = table(tmp_path / "t", [stall_by_resistance()])
    motor = node(
        "electrical.motor",
        quantities={
            "stall_current": (2, "A"),
            "rated_voltage": (12, "V"),
            "motor_resistance": (0, "ohm"),
        },
    )
    records = laws_records(laws, view_of(tmp_path, motor))
    record = one(unchecked_of(records, "stall_by_resistance"))
    assert "zero" in record.message
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("motor_resistance",)


# --- scope ---------------------------------------------------------------------------------


def test_at_module_scope_a_law_judges_only_what_the_attempt_could_have_changed(
    tmp_path: Path,
) -> None:
    laws = table(tmp_path / "t", [within_rating()])
    given = node("electrical.old", quantities={"current_draw": (3, "A"), "current_limit": (2, "A")})
    written = node(
        "electrical.new", quantities={"current_draw": (4, "A"), "current_limit": (2, "A")}
    )
    graph(tmp_path / "g", given)
    base = graph(tmp_path / "g", written) - 1
    view = GraphView.read(tmp_path / "g", base_revision=base)
    module = judged_of(laws_records(laws, view, ("module",)), "within_rating")
    assert [r.node for r in module] == ["electrical.new"]
    system = judged_of(laws_records(laws, view, ("system",)), "within_rating")
    assert sorted(r.node or "" for r in system) == ["electrical.new", "electrical.old"]
    assert not laws_records(laws, view, ("subtask",))
