"""Check 2, envelopes: the mechanism for holding a kind to a span, and the table that loads none.

A range is looked up by the writer's domain and the quantity's name, so a 10.8 kV supply on a
control node, or a voltage under an invented name, met no range at all. An envelope is a
sourced span for a whole kind (every voltage, every temperature), kept in the cross-domain
table and applied in every domain, by the quantity's kind, to the size of its value. A range
in the writer's own domain still comes first and is never replaced, so nothing is loosened.

**No envelope is loaded.** Every one drafted is a product-class assumption, not physics: a
72 V pack, a 400 V bus, a 300 C hotend and a 350 C soldering tip are correct figures outside
them, and the gate must fail no correct design. They stay in the cross-domain table's
comments, each with its source, until a ruling loads one; the real gate records such a
quantity as unchecked. The mechanism is held here on a table a test writes, so a ruling that
loads one has it ready, and the empty table is held to loading nothing.
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
#: A cross-domain table a test writes: the two envelopes once drafted, loaded for the test.
TEST_CROSS = """[meta]
domain = "cross"
curated_by = "a test"

[[envelope]]
kind = "voltage"
low = 0
high = 60
unit = "V"
class = "a test class"
source = "a test"
retrieved = 2026-10-19
confirmed = 2026-10-19
note = "a test"

[[envelope]]
kind = "temperature"
low = 200
high = 550
unit = "K"
class = "a test class"
source = "a test"
retrieved = 2026-10-19
confirmed = 2026-10-19
note = "a test"
"""


def tables(tmp_path: Path, cross: str = TEST_CROSS, electrical: str | None = None) -> Path:
    root = tmp_path / "tables"
    (root / "cross").mkdir(parents=True)
    (root / "cross" / BOUNDS_NAME).write_text(cross)
    if electrical is not None:
        (root / "electrical").mkdir()
        (root / "electrical" / BOUNDS_NAME).write_text(electrical)
    return root


def check(tmp_path: Path, *payloads: dict[str, Any], bounds_dir: Path = KNOWLEDGE_DIR) -> Any:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds(bounds_dir))
    return check_magnitude.run(ctx)


def board(volts: float | int, unit: str = "V", name: str = "supply_voltage") -> dict[str, Any]:
    return node(f"{C}.board", domain=C, quantities={name: (volts, unit)})


# --- the real table loads no envelope ----------------------------------------------------


def test_the_real_cross_table_loads_no_envelope_and_keeps_the_drafts_in_its_comments() -> None:
    assert load_bounds().envelopes == {}
    text = CROSS.read_text()
    assert "No envelope is loaded" in text and "Withheld" in text
    for draft in ("voltage, 0 to 60 V", "temperature, 200 K to 550 K", "mass, 0 to 13.6 kg"):
        assert draft in text
    assert all(
        line.startswith(("#", "[meta]")) or not line.strip() or "=" in line
        for line in text.splitlines()
    )
    assert "[[envelope]]" not in text


@pytest.mark.parametrize(
    ("domain", "name", "value", "unit"),
    [
        ("electrical", "supply_voltage", 72, "V"),
        ("electrical", "supply_voltage", 400, "V"),
        ("electrical", "rated_voltage", 63, "V"),
        ("firmware", "mains_voltage", 230, "V"),
        ("mechanical", "max_temperature", 300, "degC"),
        ("electrical", "max_temperature", 150, "degF"),
        ("electrical", "ambient_temperature", -100, "degC"),
    ],
)
def test_the_real_gate_holds_no_correct_figure_to_a_class_envelope(
    tmp_path: Path, domain: str, name: str, value: float, unit: str
) -> None:
    ran = check(tmp_path, node(f"{domain}.part", domain=domain, quantities={name: (value, unit)}))
    assert not any(o.outcome == "fail" for o in ran.observations)
    assert ran.evaluated == 0


def test_the_real_gate_records_a_10800_volt_board_as_unchecked_never_refused(
    tmp_path: Path,
) -> None:
    graph(tmp_path / "g", board(10800))
    result = PhysicsGate().run(GraphView.read(tmp_path / "g", 0), ["subtask"], "on")
    assert result.verdict == "pass"
    (magnitude,) = [c for c in result.checks if c.name == "magnitude"]
    assert magnitude.outcome == "unchecked" and "no envelope" in magnitude.message


# --- the mechanism, on a table a test writes ---------------------------------------------


def test_a_loaded_envelope_refuses_a_10800_volt_board_in_any_domain(tmp_path: Path) -> None:
    # A millivolt figure mislabelled as volts, on a node of any domain: the own-domain
    # table has no range for the name, and the voltage envelope holds in every domain.
    root = tables(tmp_path)
    for domain in ("mechanical", "control", "firmware"):
        payload = node(
            f"{domain}.board", domain=domain, quantities={"supply_voltage": (10800, "V")}
        )
        ran = check(tmp_path / domain, payload, bounds_dir=root)
        (finding,) = ran.observations
        assert finding.outcome == "fail" and finding.node == f"{domain}.board", domain
        details = finding.details
        assert isinstance(details, MagnitudeDetails)
        assert (details.high.value, details.high.unit) == (60, "V")
        assert details.table_sha256 == hashlib.sha256(TEST_CROSS.encode()).hexdigest()
        assert "envelope" in finding.message and "voltage" in finding.message
        assert ran.evaluated == 1


def test_a_7_2_volt_supply_passes_a_loaded_envelope_and_is_counted(tmp_path: Path) -> None:
    ran = check(tmp_path, board(7.2), bounds_dir=tables(tmp_path))
    assert ran.observations == () and ran.evaluated == 1


def test_a_voltage_under_an_invented_name_is_held_to_a_loaded_envelope_too(
    tmp_path: Path,
) -> None:
    (finding,) = check(
        tmp_path, board(3300, name="logic_voltage"), bounds_dir=tables(tmp_path)
    ).observations
    assert finding.outcome == "fail" and "logic_voltage" in finding.message


def test_the_size_of_the_value_is_what_a_loaded_envelope_judges(tmp_path: Path) -> None:
    # A sign is the unit check's business; the envelope bounds the size of the value.
    root = tables(tmp_path)
    assert (
        check(tmp_path / "a", board(-0.3, name="max_input_voltage"), bounds_dir=root).observations
        == ()
    )
    (below,) = check(
        tmp_path / "b", board(-100, name="max_input_voltage"), bounds_dir=root
    ).observations
    assert below.outcome == "fail"


def test_a_loaded_envelope_is_compared_after_unit_conversion_and_exactly_at_its_edge(
    tmp_path: Path,
) -> None:
    root = tables(tmp_path)
    assert check(tmp_path / "a", board(60000, "mV"), bounds_dir=root).observations == ()
    (finding,) = check(tmp_path / "b", board(60000.001, "mV"), bounds_dir=root).observations
    assert finding.outcome == "fail"


def test_a_temperature_in_celsius_is_converted_before_a_loaded_envelope_is_applied(
    tmp_path: Path,
) -> None:
    root = tables(tmp_path)
    inside = check(
        tmp_path / "a",
        node("electrical.driver", quantities={"max_temperature": (125, "degC")}),
        bounds_dir=root,
    )
    assert inside.observations == () and inside.evaluated == 1
    (finding,) = check(
        tmp_path / "b",
        node("electrical.driver", quantities={"max_temperature": (1250, "degC")}),
        bounds_dir=root,
    ).observations
    assert finding.outcome == "fail"


def test_a_range_in_the_writer_s_own_domain_comes_first_and_is_never_replaced(
    tmp_path: Path,
) -> None:
    # A table that gives electrical.supply_voltage a range wider than the envelope: a 70 V
    # figure is inside that range and outside the envelope, and passes, because the
    # own-domain range decides; a 90 V figure is outside the range and is refused by it.
    root = tables(
        tmp_path,
        electrical=(
            '[meta]\ndomain = "electrical"\ncurated_by = "a test"\n\n[[range]]\n'
            'quantity = "supply_voltage"\nlow = 0\nhigh = 80\nunit = "V"\nclass = "a test class"\n'
            'source = "a test"\nretrieved = 2026-10-19\nconfirmed = 2026-10-19\nnote = "a test"\n'
        ),
    )
    wide = node("electrical.x", quantities={"supply_voltage": (70, "V")})
    inside = check(tmp_path / "a", wide, bounds_dir=root)
    assert inside.observations == () and inside.evaluated == 1
    wider = node("electrical.y", quantities={"supply_voltage": (90, "V")})
    (finding,) = check(tmp_path / "b", wider, bounds_dir=root).observations
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
    root = tables(tmp_path, TEST_CROSS.replace('kind = "voltage"', 'kind = "pressure"', 1))
    with pytest.raises(BoundsTableError):
        load_bounds(root)


def test_an_envelope_without_a_confirmation_date_does_not_load(tmp_path: Path) -> None:
    root = tables(tmp_path, TEST_CROSS.replace("confirmed = 2026-10-19\n", "", 1))
    with pytest.raises(BoundsTableError):
        load_bounds(root)


def test_two_tables_giving_one_kind_an_envelope_do_not_load(tmp_path: Path) -> None:
    root = tables(tmp_path)
    (root / "mechanical").mkdir()
    (root / "mechanical" / BOUNDS_NAME).write_text(
        TEST_CROSS.replace('domain = "cross"', 'domain = "mechanical"', 1)
    )
    with pytest.raises(BoundsTableError):
        load_bounds(root)


def test_the_envelopes_come_from_the_table_file_not_the_code(tmp_path: Path) -> None:
    root = tables(tmp_path, TEST_CROSS.replace("high = 60\n", "high = 20000\n", 1))
    assert check(tmp_path / "g", board(10800), bounds_dir=root).observations == ()


def test_a_table_with_nothing_but_drafts_loads_with_nothing_in_it(tmp_path: Path) -> None:
    root = tables(tmp_path, '# a draft\n[meta]\ndomain = "cross"\ncurated_by = "a test"\n')
    bounds = load_bounds(root)
    assert bounds.envelopes == {} and bounds.tables["cross"].ranges == {}
