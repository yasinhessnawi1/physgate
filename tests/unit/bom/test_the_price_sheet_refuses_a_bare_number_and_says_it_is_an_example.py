"""The price sheet is data with a unit on every number, and it says it is an example fixture.

A bare number where a quantity goes is a schema error, as in the design-state graph. A count is a
whole number of pieces with unit ``1``, a price carries a currency code, a lead time is in days or
weeks with the scope it holds for. A sheet whose header does not call it an example fixture is
refused, and so is one that answers a node id twice, since the check could not tell which entry
a line is. The sheet committed beside the code loads, says what it is, and marks every figure it
did not read from a distributor as an example value.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from bom_helpers import EXAMPLE, entry, sheet_data, write_json

from physgate.build.bom.sheet import EXAMPLE_SHEET, FACTS, SheetError, load_quantities, load_sheet


def _load(tmp_path: Path, data: dict[str, Any]) -> object:
    try:
        return load_sheet(write_json(tmp_path / "sheet.json", data))
    except SheetError as exc:
        return exc


def _refused(tmp_path: Path, data: dict[str, Any], *where: str) -> None:
    outcome = _load(tmp_path, data)
    assert isinstance(outcome, SheetError), "the sheet was taken"
    for part in where:
        assert part in str(outcome)


def test_a_well_formed_sheet_is_taken(tmp_path: Path) -> None:
    loaded = _load(tmp_path, sheet_data(entry(["a.part"])))
    assert not isinstance(loaded, SheetError), loaded


def test_a_unit_price_written_as_a_bare_number_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, sheet_data(entry(["a.part"], unit_price=12.5)), "unit_price")


def test_a_minimum_order_written_as_a_bare_number_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, sheet_data(entry(["a.part"], minimum_order_quantity=1)), "minimum_order")


def test_a_lead_time_written_as_a_bare_number_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, sheet_data(entry(["a.part"], lead_time_to_norway=7)), "lead_time")


def test_a_lead_time_without_its_unit_is_refused(tmp_path: Path) -> None:
    fact = {"value": 7, "scope": "norway", "source": EXAMPLE}
    _refused(tmp_path, sheet_data(entry(["a.part"], lead_time_to_norway=fact)), "unit")


def test_a_lead_time_in_a_unit_that_is_not_days_or_weeks_is_refused(tmp_path: Path) -> None:
    fact = {"value": 7, "unit": "month", "scope": "norway", "source": EXAMPLE}
    _refused(tmp_path, sheet_data(entry(["a.part"], lead_time_to_norway=fact)), "unit")


def test_a_price_without_a_currency_code_is_refused(tmp_path: Path) -> None:
    fact = {"value": 12.5, "unit": "kr", "source": EXAMPLE}
    _refused(tmp_path, sheet_data(entry(["a.part"], unit_price=fact)), "unit")


def test_a_count_in_another_unit_or_not_whole_is_refused(tmp_path: Path) -> None:
    other = {"value": 1, "unit": "kg", "source": EXAMPLE}
    _refused(tmp_path, sheet_data(entry(["a.part"], order_multiple=other)), "order_multiple")
    half = {"value": 1.5, "unit": "1", "source": EXAMPLE}
    _refused(tmp_path, sheet_data(entry(["a.part"], order_multiple=half)), "order_multiple")


def test_a_fact_with_no_source_note_is_refused(tmp_path: Path) -> None:
    fact = {"value": 12.5, "unit": "NOK"}
    _refused(tmp_path, sheet_data(entry(["a.part"], unit_price=fact)), "source")


def test_a_header_that_does_not_call_the_sheet_an_example_fixture_is_refused(
    tmp_path: Path,
) -> None:
    data = sheet_data(entry(["a.part"]))
    data["header"]["kind"] = "distributor data"
    _refused(tmp_path, data, "header")


def test_a_node_id_answered_by_two_entries_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, sheet_data(entry(["a.part"]), entry(["b.part", "a.part"])), "a.part")


def test_a_lead_time_in_weeks_is_counted_in_days_exactly(tmp_path: Path) -> None:
    weeks = {"value": 4, "unit": "week", "scope": "norway", "source": EXAMPLE}
    loaded = load_sheet(
        write_json(tmp_path / "s.json", sheet_data(entry(["a"], lead_time_to_norway=weeks)))
    )
    held = loaded.entries[0].facts.lead_time_to_norway
    assert held is not None
    assert held.days() == Fraction(28)


def test_a_quantity_needed_written_as_a_bare_number_is_refused(tmp_path: Path) -> None:
    path = write_json(tmp_path / "q.json", {"stated_by": "a person", "quantities": {"a.part": 2}})
    with pytest.raises(SheetError, match="quantities"):
        load_quantities(path)


def test_the_committed_sheet_loads_and_says_it_is_an_example_not_distributor_data() -> None:
    loaded = load_sheet(EXAMPLE_SHEET)
    assert loaded.header.kind == "example fixture"
    assert "not live distributor data" in loaded.header.statement
    assert loaded.header.written_on.isoformat() == "2026-11-24"
    assert loaded.entries


def test_every_figure_in_the_committed_sheet_is_marked_as_an_example_value() -> None:
    # No figure in it was read from a distributor, so none may claim to have been.
    raw = json.loads(EXAMPLE_SHEET.read_text())
    for one in raw["entries"]:
        for name in FACTS:
            fact = one["facts"].get(name)
            if fact is not None:
                assert fact["source"] == {"kind": "example"}, (one["answers"][0], name)
