"""Each line is judged on the five facts of ARCH-120 and the two limits of the frozen risk row.

A line passes only when the sheet names its node id exactly, all five facts are there, and both
limits are judged and met: a lead time to Norway of at most four weeks, and a minimum order of at
most five times the quantity needed. Above either fails; exactly at either passes. A part the
sheet does not name, a missing fact, a lead time the sheet holds only in general and a quantity
nobody stated each leave the line incomplete, never passed. A part that cannot be bought fails.
"""

from __future__ import annotations

from typing import Any

from bom_helpers import EXAMPLE, count, entry, line, sheet

from physgate.build.bom.check import (
    EXIT_FAILS,
    EXIT_INCOMPLETE,
    EXIT_NO_LINES,
    EXIT_PASSES,
    NO_QUANTITY,
    NOT_FOUND,
    UNVERIFIABLE,
    LineResult,
    check_line,
    check_lines,
    exit_status,
)
from physgate.build.bom.sheet import FACTS

NODE = "electrical.wheel_encoder"


def _judged(quantity: int | None = 1, **changed: Any) -> LineResult:  # noqa: ANN401
    held = sheet(entry([NODE], **changed))
    return check_line(line(NODE), held, None if quantity is None else count(quantity))


def _outcome(result: LineResult, rule: str) -> str:
    (found,) = [one for one in result.findings if one.rule == rule]
    return found.outcome


def _lead(value: float, unit: str = "d", scope: str = "norway") -> dict[str, Any]:
    return {"value": value, "unit": unit, "scope": scope, "source": EXAMPLE}


def _minimum(value: int) -> dict[str, Any]:
    return {"value": value, "unit": "1", "source": EXAMPLE}


def test_a_line_with_all_five_facts_and_both_limits_met_passes() -> None:
    result = _judged()
    assert result.missing == ()
    assert _outcome(result, "lead_time") == "met"
    assert _outcome(result, "minimum_order") == "met"
    assert result.verdict == "passes"


def test_a_line_no_entry_names_is_not_found_and_never_passes() -> None:
    result = check_line(line("electrical.other"), sheet(entry([NODE])), count(1))
    assert result.entry is None
    assert result.verdict == "incomplete"
    assert result.missing == FACTS
    assert NOT_FOUND == "not found in the sheet"


def test_a_line_is_matched_by_its_exact_node_id_only() -> None:
    held = sheet(entry(["electrical.wheel_encoder_left", "Electrical.Wheel_Encoder"]))
    result = check_line(line(NODE), held, count(1))
    assert result.entry is None
    assert result.verdict == "incomplete"


def test_an_entry_answers_every_node_id_it_lists() -> None:
    held = sheet(entry(["part.encoder", NODE]))
    assert check_line(line(NODE), held, count(1)).entry is not None
    assert check_line(line("part.encoder"), held, count(1)).entry is not None


def test_each_missing_fact_is_named_and_the_line_is_incomplete() -> None:
    for name in FACTS:
        result = _judged(**{name: None})
        assert result.missing == (name,), name
        assert result.verdict == "incomplete", name


def test_a_lead_time_held_only_in_general_is_unverifiable_for_norway_and_not_passed() -> None:
    result = _judged(lead_time_to_norway=_lead(3, scope="generic"))
    assert _outcome(result, "lead_time") == "not judged"
    assert any(one.message == UNVERIFIABLE for one in result.findings)
    assert "unverifiable for Norway" in UNVERIFIABLE
    assert result.verdict == "incomplete"


def test_a_lead_time_of_exactly_four_weeks_to_norway_passes() -> None:
    for fact in (_lead(28), _lead(4, "week"), _lead(4.0, "week")):
        result = _judged(lead_time_to_norway=fact)
        assert _outcome(result, "lead_time") == "met", fact
        assert result.verdict == "passes", fact


def test_a_lead_time_a_day_above_four_weeks_to_norway_fails() -> None:
    for fact in (_lead(29), _lead(28.5), _lead(4.2, "week")):
        result = _judged(lead_time_to_norway=fact)
        assert _outcome(result, "lead_time") == "fails", fact
        assert result.verdict == "fails", fact


def test_a_minimum_order_of_exactly_five_times_the_quantity_needed_passes() -> None:
    result = _judged(quantity=4, minimum_order_quantity=_minimum(20))
    assert _outcome(result, "minimum_order") == "met"
    assert result.verdict == "passes"


def test_a_minimum_order_one_above_five_times_the_quantity_needed_fails() -> None:
    result = _judged(quantity=4, minimum_order_quantity=_minimum(21))
    assert _outcome(result, "minimum_order") == "fails"
    assert result.verdict == "fails"


def test_with_no_quantity_needed_the_minimum_order_rule_is_not_judged_and_never_passes() -> None:
    result = _judged(quantity=None)
    assert result.missing == ()
    assert _outcome(result, "minimum_order") == "not judged"
    assert any(one.message == NO_QUANTITY for one in result.findings)
    assert result.verdict == "incomplete"


def test_with_no_quantity_a_huge_minimum_order_is_still_not_judged_as_a_failure() -> None:
    result = _judged(quantity=None, minimum_order_quantity=_minimum(10_000))
    assert _outcome(result, "minimum_order") == "not judged"
    assert result.verdict == "incomplete"


def test_a_part_that_is_not_purchasable_fails() -> None:
    result = _judged(availability={"status": "not_purchasable", "source": EXAMPLE})
    assert _outcome(result, "availability") == "fails"
    assert result.verdict == "fails"


def test_an_orderable_part_is_available() -> None:
    result = _judged(availability={"status": "orderable", "source": EXAMPLE})
    assert _outcome(result, "availability") == "met"
    assert result.verdict == "passes"


def test_a_failing_limit_outweighs_what_is_missing() -> None:
    result = _judged(quantity=None, unit_price=None, lead_time_to_norway=_lead(60))
    assert result.verdict == "fails"


def test_the_exit_status_says_whether_any_line_fails_and_no_lines_is_not_a_pass() -> None:
    passing = sheet(entry([NODE]))
    failing = sheet(entry([NODE], lead_time_to_norway=_lead(29)))
    ok = check_lines([line(NODE)], passing, {NODE: count(1)})
    assert exit_status(ok) == EXIT_PASSES == 0
    assert exit_status(check_lines([line(NODE)], failing, {NODE: count(1)})) == EXIT_FAILS
    assert exit_status(check_lines([line(NODE)], passing, {})) == EXIT_INCOMPLETE
    assert exit_status(()) == EXIT_NO_LINES
    mixed = check_lines([line(NODE), line("electrical.gone")], failing, {NODE: count(1)})
    assert exit_status(mixed) == EXIT_FAILS
    assert len({EXIT_PASSES, EXIT_FAILS, EXIT_INCOMPLETE, EXIT_NO_LINES}) == 4
