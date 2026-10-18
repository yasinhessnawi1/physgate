"""Check 2, envelopes: a quantity is held to its kind's sourced envelope, whatever its domain.

A range is looked up by the writer's domain and the quantity's name, so a 10.8 kV supply on a
control node, or a voltage under an invented name, met no range at all. An envelope is a
sourced span for a whole kind (every voltage, every temperature) of the class of machine this
gate judges, kept in the cross-domain table and applied in every domain, by the quantity's
kind, to the size of its value. A range in the writer's own domain still comes first and is
never replaced, so nothing is loosened; the envelope only adds a judgement where there was
none. Every envelope carries the date its figures were confirmed in the document it names, or
it does not load.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import graph, node

from physgate.gate import check_magnitude
from physgate.gate.bounds_table import (
    BOUNDS_NAME,
    KNOWLEDGE_DIR,
    BoundsTableError,
    load_bounds,
)
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.protocols import MagnitudeDetails, UncheckedDetails

CROSS = KNOWLEDGE_DIR / "cross" / BOUNDS_NAME
C = "control"


def check(tmp_path: Path, *payloads: dict[str, Any], bounds_dir: Path = KNOWLEDGE_DIR) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds(bounds_dir))
    return check_magnitude.run(ctx)


def board(volts: float | int, unit: str = "V", name: str = "supply_voltage") -> dict[str, Any]:
    return node(f"{C}.board", domain=C, quantities={name: (volts, unit)})


def test_the_cross_table_holds_the_envelopes_each_confirmed_in_its_document() -> None:
    envelopes = load_bounds().envelopes
    # Mass and length are drafted in the table's comments and withheld for a ruling: each
    # refuses graphs the equilibrium suite builds on purpose far outside any hobby robot.
    assert set(envelopes) == {"voltage", "temperature"}
    assert all(e.source and e.note and e.component_class for e in envelopes.values())
    assert all(e.confirmed.isoformat() == "2026-10-19" for e in envelopes.values())
    assert (envelopes["voltage"].low, envelopes["voltage"].high, envelopes["voltage"].unit) == (
        0,
        60,
        "V",
    )
    assert (envelopes["temperature"].low, envelopes["temperature"].high) == (200, 550)


def test_a_board_rated_10800_volts_is_refused_in_any_domain_with_the_envelope(
    tmp_path: Path,
) -> None:
    # A millivolt figure mislabelled as volts, on a node of any domain: the own-domain
    # table has no range for the name, and the voltage envelope holds in every domain.
    for domain in ("mechanical", "control", "firmware"):
        payload = node(
            f"{domain}.board", domain=domain, quantities={"supply_voltage": (10800, "V")}
        )
        ran = check(tmp_path / domain, payload)
        (finding,) = ran.observations
        assert finding.outcome == "fail" and finding.node == f"{domain}.board", domain
        details = finding.details
        assert isinstance(details, MagnitudeDetails)
        assert (details.high.value, details.high.unit) == (60, "V")
        assert details.table_sha256 == hashlib.sha256(CROSS.read_bytes()).hexdigest()
        assert "envelope" in finding.message and "voltage" in finding.message
        assert ran.evaluated == 1


def test_a_7_2_volt_supply_passes_and_is_counted(tmp_path: Path) -> None:
    ran = check(tmp_path, board(7.2))
    assert ran.observations == () and ran.evaluated == 1


def test_a_voltage_under_an_invented_name_is_held_to_the_envelope_too(tmp_path: Path) -> None:
    (finding,) = check(tmp_path, board(3300, name="logic_voltage")).observations
    assert finding.outcome == "fail" and "logic_voltage" in finding.message


def test_the_size_of_the_value_is_what_is_judged(tmp_path: Path) -> None:
    # A sign is the unit check's business; the envelope bounds the size of the value.
    assert check(tmp_path / "a", board(-0.3, name="max_input_voltage")).observations == ()
    (below,) = check(tmp_path / "b", board(-100, name="max_input_voltage")).observations
    assert below.outcome == "fail"


def test_the_envelope_is_compared_after_unit_conversion_and_exactly_at_its_edge(
    tmp_path: Path,
) -> None:
    assert check(tmp_path / "a", board(60000, "mV")).observations == ()
    (finding,) = check(tmp_path / "b", board(60000.001, "mV")).observations
    assert finding.outcome == "fail"


def test_a_temperature_in_celsius_is_converted_before_the_envelope_is_applied(
    tmp_path: Path,
) -> None:
    inside = check(
        tmp_path / "a", node("electrical.driver", quantities={"max_temperature": (125, "degC")})
    )
    assert inside.observations == () and inside.evaluated == 1
    (finding,) = check(
        tmp_path / "b", node("electrical.driver", quantities={"max_temperature": (1250, "degC")})
    ).observations
    assert finding.outcome == "fail"


def test_a_range_in_the_writer_s_own_domain_comes_first_and_is_never_replaced(
    tmp_path: Path,
) -> None:
    # A table that gives electrical.supply_voltage a range wider than the envelope: a 70 V
    # figure is inside that range and outside the envelope, and passes, because the
    # own-domain range decides; a 90 V figure is outside the range and is refused by it.
    tables = tmp_path / "tables"
    (tables / "cross").mkdir(parents=True)
    (tables / "cross" / BOUNDS_NAME).write_text(CROSS.read_text())
    (tables / "electrical").mkdir()
    (tables / "electrical" / BOUNDS_NAME).write_text(
        '[meta]\ndomain = "electrical"\ncurated_by = "a test"\n\n[[range]]\n'
        'quantity = "supply_voltage"\nlow = 0\nhigh = 80\nunit = "V"\nclass = "a test class"\n'
        'source = "a test"\nretrieved = 2026-10-19\nconfirmed = 2026-10-19\nnote = "a test"\n'
    )
    wide = node("electrical.x", quantities={"supply_voltage": (70, "V")})
    inside = check(tmp_path / "a", wide, bounds_dir=tables)
    assert inside.observations == () and inside.evaluated == 1
    wider = node("electrical.y", quantities={"supply_voltage": (90, "V")})
    (finding,) = check(tmp_path / "b", wider, bounds_dir=tables).observations
    assert isinstance(finding.details, MagnitudeDetails)
    assert finding.details.high.value == 80 and "envelope" not in finding.message


def test_a_kind_with_no_envelope_and_a_name_with_no_range_is_unchecked_never_passed(
    tmp_path: Path,
) -> None:
    ran = check(
        tmp_path,
        node("mechanical.shaft", domain="mechanical", quantities={"torque_peak": (110, "N*m")}),
    )
    (record,) = ran.observations
    assert record.outcome == "unchecked" and ran.evaluated == 0
    assert isinstance(record.details, UncheckedDetails)
    assert record.details.quantities == ("torque_peak",)
    assert "no envelope for their kind" in record.message


def test_an_envelope_naming_an_unknown_kind_does_not_load(tmp_path: Path) -> None:
    tables = tmp_path / "tables"
    (tables / "cross").mkdir(parents=True)
    (tables / "cross" / BOUNDS_NAME).write_text(
        CROSS.read_text().replace('kind = "voltage"', 'kind = "pressure"', 1)
    )
    with pytest.raises(BoundsTableError):
        load_bounds(tables)


def test_an_envelope_without_a_confirmation_date_does_not_load(tmp_path: Path) -> None:
    tables = tmp_path / "tables"
    (tables / "cross").mkdir(parents=True)
    (tables / "cross" / BOUNDS_NAME).write_text(
        CROSS.read_text().replace("confirmed = 2026-10-19\n", "", 1)
    )
    with pytest.raises(BoundsTableError):
        load_bounds(tables)


def test_two_tables_giving_one_kind_an_envelope_do_not_load(tmp_path: Path) -> None:
    tables = tmp_path / "tables"
    for domain in ("cross", "mechanical"):
        (tables / domain).mkdir(parents=True)
        (tables / domain / BOUNDS_NAME).write_text(
            CROSS.read_text().replace('domain = "cross"', f'domain = "{domain}"', 1)
        )
    with pytest.raises(BoundsTableError):
        load_bounds(tables)


def test_the_envelopes_come_from_the_table_file_not_the_code(tmp_path: Path) -> None:
    tables = tmp_path / "tables"
    (tables / "cross").mkdir(parents=True)
    text = CROSS.read_text().replace("high = 60\n", "high = 20000\n", 1)
    assert text != CROSS.read_text()
    (tables / "cross" / BOUNDS_NAME).write_text(text)
    assert check(tmp_path / "g", board(10800), bounds_dir=tables).observations == ()


def test_the_real_gate_refuses_a_10800_volt_board_at_subtask_scope(tmp_path: Path) -> None:
    graph(tmp_path / "g", board(10800))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "fail" and result.failing_check == "magnitude"
    assert result.numeric_output is not None and result.numeric_output.value == 10800
