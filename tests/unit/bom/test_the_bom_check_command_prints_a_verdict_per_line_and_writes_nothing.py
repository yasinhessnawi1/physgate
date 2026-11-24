"""``physgate bom check <run>`` prints a table and a verdict per line, or the same as data.

It reads the run's event log and a sheet and writes nothing into the run. A figure the sheet marks
as an example is marked in the table, so nobody reads it as a price. A run with no parts decision
has no lines, which is its own exit status and never a pass. A quantity needed comes only from a
file a person gives, and is recorded in the output as an operator's input. The help says what is
shown, what the lines are, and what this check leaves out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from bom_helpers import EXAMPLE, before, entry, not_asking, sheet_data, write_json, write_run

from physgate.build.bom.check import EXIT_FAILS, EXIT_INCOMPLETE, EXIT_NO_LINES, EXIT_PASSES
from physgate.cli import main

NODE = "electrical.wheel_encoder"


def _run(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, *extra: str, run: Path | None = None
) -> tuple[int, str, str]:
    run_dir = write_run(tmp_path / "run") if run is None else run
    status = main(["bom", "check", str(run_dir), *extra])
    out, err = capsys.readouterr()
    return status, out, err


def _sheet(tmp_path: Path, **changed: Any) -> str:  # noqa: ANN401
    return str(write_json(tmp_path / "sheet.json", sheet_data(entry([NODE], **changed))))


def _quantities(tmp_path: Path, quantities: dict[str, object]) -> str:
    data = {"stated_by": "the operator", "quantities": quantities}
    return str(write_json(tmp_path / "quantities.json", data))


def _one(tmp_path: Path) -> str:
    return _quantities(tmp_path, {NODE: {"value": 1, "unit": "1"}})


def test_the_table_names_the_line_its_verdict_and_marks_an_example_value(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    status, out, _ = _run(
        capsys, tmp_path, "--sheet", _sheet(tmp_path), "--quantities", _one(tmp_path)
    )
    assert status == EXIT_PASSES
    assert "shown, not measured" in out
    # The table comes before the reasons, which start with the node id too.
    row = next(one for one in out.splitlines() if one.startswith(NODE + " "))
    assert "PASSES" in row
    assert "12.5 NOK*" in row  # an example value is marked
    assert "7 d (Norway)" in row and "7 d (Norway)*" not in row  # a figure read is not
    assert "* example value" in out
    assert "quantities: operator's input" in out


def test_a_line_left_without_a_quantity_is_incomplete_with_its_reason_printed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    status, out, _ = _run(capsys, tmp_path, "--sheet", _sheet(tmp_path))
    assert status == EXIT_INCOMPLETE
    assert "quantity needed not recorded: the minimum-order rule is not judged" in out
    assert "INCOMPLETE" in out


def test_a_failing_line_fails_the_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    lead = {"value": 5, "unit": "week", "scope": "norway", "source": EXAMPLE}
    sheet = _sheet(tmp_path, lead_time_to_norway=lead)
    status, out, _ = _run(capsys, tmp_path, "--sheet", sheet, "--quantities", _one(tmp_path))
    assert status == EXIT_FAILS
    assert "above the four-week limit" in out


def test_json_gives_the_same_verdicts_and_records_the_quantity_as_the_operator_s(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sheet, quantities = _sheet(tmp_path), _one(tmp_path)
    status, out, _ = _run(capsys, tmp_path, "--sheet", sheet, "--quantities", quantities, "--json")
    data = json.loads(out)
    assert status == data["exit_status"] == EXIT_PASSES
    (only,) = data["lines"]
    assert only["node"] == NODE
    assert only["verdict"] == "passes"
    assert only["quantity_needed"] == {"value": 1, "unit": "1", "stated_by": "operator"}
    assert only["facts"]["unit_price"]["example_value"] is True
    assert only["facts"]["lead_time_to_norway"]["example_value"] is False
    assert data["quantities"]["operator_input"] is True
    assert data["sheet"]["kind"] == "example fixture"
    assert data["summary"] == {"lines": 1, "passes": 1, "incomplete": 0, "fails": 0}
    assert "not measured" in data["shown"]


def test_a_part_the_sheet_does_not_name_is_not_found_in_the_sheet(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    other = str(write_json(tmp_path / "s.json", sheet_data(entry(["electrical.other"]))))
    status, out, _ = _run(capsys, tmp_path, "--sheet", other, "--json")
    (only,) = json.loads(out)["lines"]
    assert status == EXIT_INCOMPLETE
    assert only["found_in_sheet"] is False
    assert only["verdict"] == "incomplete"
    _, table, _ = _run(capsys, tmp_path, "--sheet", other)
    assert "  part: not found in the sheet" in table


def test_a_run_with_no_parts_decision_has_no_lines_and_that_is_not_a_pass(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    run = write_run(tmp_path / "off", not_asking())
    status, out, _ = _run(capsys, tmp_path, run=run)
    assert status == EXIT_NO_LINES
    assert "no lines" in out
    assert "No lines is not a pass." in out


def test_a_run_whose_parts_are_not_released_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    run = write_run(tmp_path / "open", before("parts_write_intended"))
    status, out, err = _run(capsys, tmp_path, run=run)
    assert status == 2
    assert out == ""
    assert "not released" in json.loads(err)["error"]


def test_a_directory_with_no_run_event_log_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    status, _, err = _run(capsys, tmp_path, run=empty)
    assert status == 2
    assert "no run-event log" in json.loads(err)["error"]


def test_a_quantity_written_as_a_bare_number_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bare = _quantities(tmp_path, {NODE: 1})
    status, out, err = _run(capsys, tmp_path, "--sheet", _sheet(tmp_path), "--quantities", bare)
    assert status == 2
    assert out == ""
    assert "quantities" in json.loads(err)["error"]


def test_a_quantity_for_a_node_that_is_no_line_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    stray = _quantities(tmp_path, {"electrical.motor_driver": {"value": 2, "unit": "1"}})
    status, _, err = _run(capsys, tmp_path, "--sheet", _sheet(tmp_path), "--quantities", stray)
    assert status == 2
    assert "electrical.motor_driver" in json.loads(err)["nodes"]


def test_a_sheet_with_a_bare_number_is_refused_by_the_command(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    status, _, err = _run(capsys, tmp_path, "--sheet", _sheet(tmp_path, unit_price=12.5))
    assert status == 2
    assert "unit_price" in json.loads(err)["error"]


def test_the_command_writes_nothing_into_the_run(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    run = write_run(tmp_path / "run")
    before_files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.rglob("*")}
    _run(capsys, tmp_path, "--sheet", _sheet(tmp_path), "--json", run=run)
    _run(capsys, tmp_path, "--sheet", _sheet(tmp_path), run=run)
    after_files = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in run.rglob("*")}
    assert after_files == before_files


def test_the_command_runs_on_the_committed_example_sheet_by_default(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    status, out, _ = _run(capsys, tmp_path, "--json")
    data = json.loads(out)
    assert data["sheet"]["kind"] == "example fixture"
    assert status == data["exit_status"]
    (only,) = data["lines"]
    assert only["node"] == NODE
    assert only["verdict"] != "passes"


def test_the_help_says_it_is_shown_not_measured_and_what_it_leaves_out(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["bom", "check", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "shown, not measured" in out
    assert "the plan's parts a person answered 'find'" in out
    assert "not a bill of materials a design produced" in out
    assert "no lines is not a pass" in out
    assert "live distributor" in out
    assert "sending a failing line back to a role" in out
    assert "cannot order" in out
