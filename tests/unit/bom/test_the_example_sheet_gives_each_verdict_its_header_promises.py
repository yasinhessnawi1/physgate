"""The committed example sheet's own entries give each verdict its header says they show.

Its header says its values were written to show each verdict of the check. Each entry is run here
against a line carrying one of the node ids it answers: one passes when a quantity is stated, one
fails on its lead time, one is incomplete for a missing fact, one is unverifiable for Norway, and
one sits at the four-week edge with a minimum order that fails at two needed and passes at five.
The default command, on a run built here whose part to find carries one of the sheet's ids,
answers from the sheet, not "not found".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bom_helpers import FIXTURE_FIND, count, line, renamed, write_run
from parts_bom_fixture import LINES

from physgate.build.bom.check import NOT_FOUND, UNVERIFIABLE, LineResult, check_line
from physgate.build.bom.sheet import EXAMPLE_SHEET, load_sheet
from physgate.cli import main

SHEET = load_sheet(EXAMPLE_SHEET)


def _judged(node: str, needed: int | None) -> LineResult:
    return check_line(line(node), SHEET, None if needed is None else count(needed))


def _outcome(result: LineResult, rule: str) -> str:
    (found,) = [one for one in result.findings if one.rule == rule]
    return found.outcome


def test_the_gearmotor_passes_once_a_quantity_is_stated_and_not_before() -> None:
    assert _judged("balboa.gearmotor", 2).verdict == "passes"
    assert _judged("balboa.gearmotor", None).verdict == "incomplete"


def test_the_wheels_fail_on_a_lead_time_above_four_weeks() -> None:
    result = _judged("balboa.wheels", 1)
    assert _outcome(result, "lead_time") == "fails"
    assert result.verdict == "fails"


def test_the_gear_set_is_incomplete_for_its_missing_order_multiple() -> None:
    result = _judged("balboa.gear_stage", 1)
    assert result.missing == ("order_multiple",)
    assert result.verdict == "incomplete"


def test_the_control_board_s_generic_lead_time_is_unverifiable_for_norway() -> None:
    result = _judged("balboa.control_board", 1)
    assert any(one.message == UNVERIFIABLE for one in result.findings)
    assert result.verdict == "incomplete"


def test_the_encoders_sit_at_the_four_week_edge_and_their_minimum_order_is_judged_on_the_need() -> (
    None
):
    two = _judged("balboa.encoders", 2)
    assert _outcome(two, "lead_time") == "met"
    assert _outcome(two, "minimum_order") == "fails"
    assert two.verdict == "fails"
    assert _judged("balboa.encoders", 5).verdict == "passes"


def test_a_part_no_entry_answers_is_not_found_in_the_sheet() -> None:
    result = _judged("balboa.imu", 1)
    assert result.entry is None
    assert result.verdict == "incomplete"


def test_every_node_id_an_entry_lists_finds_that_entry() -> None:
    for entry in SHEET.entries:
        for node in entry.answers:
            assert SHEET.entry_for(node) is entry, node


def test_the_rows_renamed_run_is_the_fixture_run_when_nothing_is_renamed() -> None:
    # The digest is remade the way replay makes it: unchanged, the fixture's own comes back.
    assert renamed(FIXTURE_FIND) == [json.loads(json.dumps(one)) for one in LINES]


def test_the_default_command_answers_from_the_sheet_for_a_part_it_names(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    run = write_run(tmp_path / "run", renamed("balboa.encoders"))
    status = main(["bom", "check", str(run), "--json"])
    (only,) = json.loads(capsys.readouterr().out)["lines"]
    assert only["node"] == "balboa.encoders"
    assert only["found_in_sheet"] is True
    assert only["verdict"] == "incomplete"  # no quantity stated: the five-times rule waits
    assert status == 3
    status = main(["bom", "check", str(run)])
    table = capsys.readouterr().out
    assert NOT_FOUND not in table
    assert "4 week (Norway)*" in table
    assert status == 3
