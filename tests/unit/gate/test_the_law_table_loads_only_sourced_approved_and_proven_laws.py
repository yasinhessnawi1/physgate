"""The law table loads only laws that are sourced, approved, proven one dimension, and new.

A law is a row of data that a person approved, and the gate refuses at build time any row that
could not have been approved as written: one without its literature source, its approval and
the promotion line that recorded it, one whose two sides are not one dimension, one that reads a
name the catalogue does not hold exactly, one that restates a relation the checks already form,
and one that blocks before an audit over enough clean designs found nothing it could not
explain. A table that does not load stops the gate from being built, so no row is ever judged
half-read. Each refusal names the row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from law_fixtures import AUDIT, cleared, laws_module, load, refused, sound_law


def test_a_sound_law_loads_at_its_status_with_its_digest(tmp_path: Path) -> None:
    table = load(tmp_path, [sound_law()])
    law = table.laws["electrical_power"]
    assert law.status == "warn"
    assert table.statuses() == {"electrical_power": "warn"}
    assert table.input_names() == frozenset({"power_draw", "supply_voltage", "current_draw"})
    assert len(table.sha256) == 64


def test_a_table_with_no_law_loads_empty(tmp_path: Path) -> None:
    table = load(tmp_path, [])
    assert dict(table.laws) == {}


def test_a_missing_table_is_refused(tmp_path: Path) -> None:
    module = laws_module()
    try:
        module.load_laws(tmp_path / "laws.toml", tmp_path / "promotions.jsonl")
    except module.LawTableError as exc:
        assert "law table" in str(exc)
        return
    raise AssertionError("a missing table loaded")


def test_the_block_bar_is_ten_clean_instances_from_two_designs() -> None:
    module = laws_module()
    assert (module.BLOCK_MIN_EVALUATED, module.BLOCK_MIN_DESIGNS) == (10, 2)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"id": "Electrical-Power"}, "id"),
        ({"statement": ""}, "statement"),
        ({"idealisation": ""}, "idealisation"),
        ({"pattern": "pair"}, "pattern"),
        ({"overlaps": "ohm"}, "overlaps"),
        ({"tolerance": "loose"}, "tolerance"),
        ({"status": "probation"}, "status"),
        ({"anchor": "Q"}, "anchor"),
    ],
)
def test_a_row_with_a_bad_field_is_refused_naming_the_field(
    tmp_path: Path, change: dict[str, Any], expected: str
) -> None:
    assert expected in refused(tmp_path, [sound_law(**change)])


def test_a_row_without_its_symbols_is_refused(tmp_path: Path) -> None:
    row = sound_law()
    del row["symbols"]
    assert "symbols" in refused(tmp_path, [row])


def test_a_repeated_law_is_refused(tmp_path: Path) -> None:
    assert "electrical_power" in refused(tmp_path, [sound_law(), sound_law()])


@pytest.mark.parametrize("missing", ["kind", "title", "edition", "section", "read", "reading"])
def test_a_law_without_every_part_of_its_source_is_refused(tmp_path: Path, missing: str) -> None:
    row = sound_law()
    row["source"] = {k: v for k, v in row["source"].items() if k != missing}
    message = refused(tmp_path, [row])
    assert "electrical_power" in message and "source" in message


def test_a_data_sheet_is_not_a_law_s_source(tmp_path: Path) -> None:
    row = sound_law()
    row["source"] = {**row["source"], "kind": "data_sheet"}
    assert "source" in refused(tmp_path, [row])


def test_a_law_without_its_approval_is_refused(tmp_path: Path) -> None:
    row = sound_law()
    del row["approved"]
    assert "approved" in refused(tmp_path, [row])


def test_an_approval_no_promotion_line_records_is_refused(tmp_path: Path) -> None:
    message = refused(tmp_path, [sound_law()], promotions="")
    assert "promotion" in message and "electrical_power" in message


def test_a_promotion_line_for_another_law_does_not_approve_this_one(tmp_path: Path) -> None:
    from law_fixtures import promotion_lines

    other = promotion_lines([sound_law("within_rating")])
    assert "promotion" in refused(tmp_path, [sound_law()], promotions=other)


def test_a_promotion_line_for_another_candidate_does_not_approve_this_one(tmp_path: Path) -> None:
    from law_fixtures import promotion_lines

    other = promotion_lines([sound_law(approved={"candidate_id": "f" * 32, "date": "2026-11-05"})])
    assert "promotion" in refused(tmp_path, [sound_law()], promotions=other)


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("stall_current_max", "suffix or qualifier"),
        ("motor_voltage", "suffix or qualifier"),
        ("gizmo_flux", "catalogue"),
        ("gain_crossover_frequency", "radian"),
        ("torque_constant", "radian"),
        ("max_temperature", "absolute"),
    ],
)
def test_a_symbol_that_is_not_a_plain_catalogue_name_is_refused(
    tmp_path: Path, name: str, why: str
) -> None:
    row = sound_law()
    row["symbols"] = {**row["symbols"], "P": {"name": name, "place": "self"}}
    assert why in refused(tmp_path, [row])


def test_a_place_the_pattern_does_not_have_is_refused(tmp_path: Path) -> None:
    row = sound_law()
    row["symbols"] = {**row["symbols"], "V": {"name": "supply_voltage", "place": "target"}}
    assert "place" in refused(tmp_path, [row])


@pytest.mark.parametrize("field", ["requires", "unless"])
def test_a_condition_on_a_name_outside_the_catalogue_is_refused(tmp_path: Path, field: str) -> None:
    condition: dict[str, str] = {"name": "max_duty", "place": "self"}
    if field == "unless":
        condition["reason"] = "a duty limit lowers the mean voltage"
    row = sound_law()
    row[field] = [condition]
    assert field in refused(tmp_path, [row])


def test_an_unless_without_its_reason_is_refused(tmp_path: Path) -> None:
    row = sound_law(unless=[{"name": "duty_cycle", "place": "self"}])
    assert "reason" in refused(tmp_path, [row])


def test_two_sides_of_different_dimension_are_refused(tmp_path: Path) -> None:
    assert "dimension" in refused(tmp_path, [sound_law(expression="P == V")])


def test_two_bare_terms_of_different_kinds_are_refused(tmp_path: Path) -> None:
    # A torque and an energy share a dimension and are never the same quantity.
    row = sound_law(
        expression="M == E",
        anchor="M",
        symbols={
            "M": {"name": "reaction_moment", "place": "self"},
            "E": {"name": "energy_capacity", "place": "self"},
        },
    )
    assert "kind" in refused(tmp_path, [row])


def test_a_law_restating_a_relation_the_checks_form_is_refused(tmp_path: Path) -> None:
    row = sound_law(
        expression="M == Mi",
        pattern="members",
        anchor="M",
        symbols={
            "M": {"name": "mass", "place": "subject"},
            "Mi": {"name": "mass", "place": "each"},
        },
    )
    assert "mass_sum" in refused(tmp_path, [row])


def test_a_relation_with_the_comparator_turned_round_is_still_restated(tmp_path: Path) -> None:
    row = sound_law(
        expression="L >= S",
        tolerance="inequality",
        anchor="S",
        symbols={
            "S": {"name": "stall_current", "place": "self"},
            "L": {"name": "current_limit", "place": "self"},
        },
    )
    assert "current_limit" in refused(tmp_path, [row])


def test_a_model_allowance_needs_a_source_and_at_most_a_quarter(tmp_path: Path) -> None:
    model = {"share": "1/10", "source": "a motor text, the stated error of the model"}
    load(tmp_path / "a", [sound_law(tolerance="model", model=model)])
    assert "model" in refused(tmp_path / "b", [sound_law(tolerance="model")])
    over = {**model, "share": "3/10"}
    assert "model" in refused(tmp_path / "c", [sound_law(tolerance="model", model=over)])
    assert "model" in refused(tmp_path / "d", [sound_law(model=model)])


@pytest.mark.parametrize("outcome", ["pass", "fail"])
def test_a_law_without_both_worked_examples_is_refused(tmp_path: Path, outcome: str) -> None:
    row = sound_law()
    row["example"] = [e for e in row["example"] if e["outcome"] != outcome]
    assert "example" in refused(tmp_path, [row])


def test_an_example_missing_a_symbol_is_refused(tmp_path: Path) -> None:
    row = sound_law()
    first = dict(row["example"][0])
    first["values"] = {k: v for k, v in first["values"].items() if k != "I"}
    row["example"] = [first, row["example"][1]]
    assert "example" in refused(tmp_path, [row])


def test_a_law_blocks_only_with_a_clearance_that_meets_the_bar(tmp_path: Path) -> None:
    load(tmp_path / "ok", [sound_law(status="block", cleared=cleared())])
    assert "cleared" in refused(tmp_path / "none", [sound_law(status="block")])
    few = cleared(evaluated_clean=9)
    assert "10" in refused(tmp_path / "few", [sound_law(status="block", cleared=few)])
    one = cleared(designs=["practice-set"])
    assert "2" in refused(tmp_path / "one", [sound_law(status="block", cleared=one)])
    twice = cleared(designs=["practice-set", "practice-set"])
    assert "design" in refused(tmp_path / "twice", [sound_law(status="block", cleared=twice)])
    open_block = cleared(unexplained=1)
    message = refused(tmp_path / "open", [sound_law(status="block", cleared=open_block)])
    assert "unexplained" in message


def test_a_clearance_on_a_probation_law_is_refused(tmp_path: Path) -> None:
    assert "cleared" in refused(tmp_path, [sound_law(cleared=cleared())])


def test_a_block_move_needs_its_own_promotion_line(tmp_path: Path) -> None:
    from law_fixtures import promotion_lines

    row = sound_law(status="block", cleared=cleared())
    approval_only = promotion_lines([sound_law()])
    assert "status" in refused(tmp_path, [row], promotions=approval_only)
    moved = promotion_lines([row]).replace(AUDIT, "c" * 64)
    assert "status" in refused(tmp_path / "other", [row], promotions=moved)


def test_members_need_a_subject_and_a_summed_term(tmp_path: Path) -> None:
    row = sound_law(
        id="reaction_moment_sum",
        expression="R == Ri",
        pattern="members",
        anchor="R",
        symbols={
            "R": {"name": "reaction_moment", "place": "subject"},
            "Ri": {"name": "reaction_moment", "place": "each"},
        },
        example=[
            {
                "outcome": "pass",
                "source": "two motors reacting on one chassis",
                "values": {
                    "R": {"value": 0.4, "unit": "N*m"},
                    "Ri": [{"value": 0.2, "unit": "N*m"}, {"value": 0.2, "unit": "N*m"}],
                },
            },
            {
                "outcome": "fail",
                "source": "the same, with one motor left out of the sum",
                "values": {
                    "R": {"value": 0.2, "unit": "N*m"},
                    "Ri": [{"value": 0.2, "unit": "N*m"}, {"value": 0.2, "unit": "N*m"}],
                },
            },
        ],
    )
    assert "reaction_moment_sum" in load(tmp_path / "ok", [row]).laws
    squared = {**row, "expression": "R * R == Ri * Ri", "id": "squared_sum"}
    assert "summed" in refused(tmp_path / "squared", [squared])
