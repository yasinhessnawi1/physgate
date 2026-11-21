"""The per-role report leaves out of a held-out suite what its version's blind check flagged.

A held-out suite that names its tier version is held to that version's check record: with none
the report is refused, since a held-out tier nobody checked is not scored. The suite must be the
whole tier the record checked; the tasks it flags, found by the digest of their ids, are left out
of every figure of the suite and of the gap, their records with them, and how many were left out,
the check record's digest and its source are printed beside the suite and the gap, never which
tasks: a task's id may be guessed, and its digest would then say which held-out task was flagged.
What is left is reported exactly as a suite of the unflagged tasks alone would be. The command
reads the record bound to the version's manifest in the store (its held-out tier's digest and
count), and refuses one that is not. A held-out suite that names no version is as it was.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from report_fixtures import design, trials

from physgate.evaluation.per_role import cli
from physgate.evaluation.per_role.report import ReportError, parse_design, parse_trials, render
from physgate.evaluation.tiers.checks import CheckRecord, make_check
from physgate.evaluation.tiers.task import id_digest

VERSION = "a" * 64
PINS = {
    "model": "claude-sonnet-5",
    "implementer_model": "claude-opus-5-5",
    "claude_version": "2.1.301",
    "effort": "high",
    "max_output_tokens": 64000,
    "endpoint": "default",
    "commit": None,
    "clean": None,
}


def _check(flagged: list[str], tasks: int = 3, role: str = "control") -> CheckRecord:
    return make_check(
        role=role,
        version=VERSION,
        tier="held_out",
        tier_sha256="b" * 64,
        source="check",
        checked="2026-11-19T20:49:00Z",
        pins=PINS,
        kept={"session_id": "s-1", "stream_sha256": None, "bound_by": "ran"},
        session={"end": "ended", "tokens": 1, "cap": 1, "wall_clock_s": 1.0},
        tasks=tasks,
        all_yes=tasks - len(flagged),
        flagged=[id_digest(task) for task in flagged],
        answer_sha256="a" * 64,
    )


def _versioned(**suite: Any) -> dict[str, Any]:  # noqa: ANN401
    spec = design()
    held = next(s for s in spec["suites"] if s["name"] == "control_held_out")
    held.update(version=VERSION, **suite)
    return spec


def _render(
    spec: dict[str, Any], records: list[dict[str, Any]], check: CheckRecord | None = None
) -> str:
    return render(
        parse_design(json.dumps(spec).encode()),
        parse_trials(json.dumps(r) for r in records),
        checks={} if check is None else {VERSION: check},
    )


def test_a_held_out_suite_whose_version_has_no_check_record_is_refused() -> None:
    spec = _versioned()
    with pytest.raises(ReportError) as refused:
        _render(spec, trials(spec))
    assert refused.value.context.get("refused_because") == "held_out_unchecked"


def test_the_flagged_task_is_left_out_and_what_is_left_reads_as_its_own_suite() -> None:
    spec = _versioned()
    text = _render(spec, trials(spec), check=_check(["control.d"]))
    # The same design with the flagged task never in it, and no version to be held to.
    alone = design()
    held = next(s for s in alone["suites"] if s["name"] == "control_held_out")
    held["tasks"] = ["control.e", "control.f"]
    expected = _render(alone, [r for r in trials(spec) if r["task"] != "control.d"])
    said = [line for line in text.splitlines() if line.startswith("Held-out tasks left out")]
    assert len(said) == 2, "the count left out is not beside the suite and the gap"
    record = _check(["control.d"])
    for line in said:
        assert f"flagged: 1 (check record `{record.sha256}`, the check's own record)" in line
        assert id_digest("control.d") not in line, "a flagged task's digest is printed"
    without = text
    for line in said:
        # Each is a paragraph of its own: the line and the blank line after it.
        without = without.replace(f"{line}\n\n", "", 1)
    assert without == expected, "what is left is not reported as a suite of it alone"
    assert "control.d" not in text and id_digest("control.d") not in text


def test_a_check_that_flags_none_is_said_beside_the_figures_all_the_same() -> None:
    spec = _versioned()
    text = _render(spec, trials(spec), check=_check([]))
    assert text.count("left out as the version's blind check flagged: 0 (check record") == 2


@pytest.mark.parametrize(
    "record",
    [
        _check(["control.a"]),
        _check(["control.d"], tasks=8),
        _check(["control.d"], role="firmware"),
    ],
    ids=["a task of another suite", "another count", "another role"],
)
def test_a_record_that_is_not_the_suite_s_check_is_refused(record: CheckRecord) -> None:
    spec = _versioned()
    with pytest.raises(ReportError) as refused:
        _render(spec, trials(spec), check=record)
    assert refused.value.context.get("refused_because") == "check_record_not_the_suite"


def _cli(tmp_path: Path, spec: dict[str, Any], *extra: str) -> int:
    (tmp_path / "design.json").write_text(json.dumps(spec))
    (tmp_path / "trials.jsonl").write_text("".join(json.dumps(r) + "\n" for r in trials(spec)))
    argv = ["per-role", "report", "--design", str(tmp_path / "design.json")]
    argv += ["--trials", str(tmp_path / "trials.jsonl"), "--out", str(tmp_path / "out.md")]
    try:
        code: int = cli._report(cli_args(argv, *extra))
    except SystemExit as exc:
        pytest.fail(f"the report command does not take these arguments: {exc}")
    return code


def cli_args(argv: list[str], *extra: str) -> Any:  # noqa: ANN401
    import argparse

    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers()
    cli.add_parser(commands)
    return parser.parse_args([*argv, *extra])


BASELINE_TESTS = Path(__file__).resolve().parents[1] / "baseline"


def _stand_in(tmp_path: Path, **flags: Any) -> Any:  # noqa: ANN401
    """A store of one version whose held-out tier the design's held-out suite is, whole."""
    if str(BASELINE_TESTS) not in sys.path:
        sys.path.insert(0, str(BASELINE_TESTS))
    from baseline_fixtures import stand_in_store

    made = stand_in_store(tmp_path / "s", **flags)
    spec = design()
    held = next(s for s in spec["suites"] if s["name"] == "control_held_out")
    held.update(version=made.version, tasks=[t.id for t in made.tasks["held_out"]])
    return made, spec


def test_the_report_command_reads_the_check_record_bound_to_the_version(tmp_path: Path) -> None:
    made, spec = _stand_in(tmp_path, flagged=(0,))
    assert _cli(tmp_path, spec) == 1, "a suite of a version was scored with no record read"
    assert _cli(tmp_path, spec, "--store", str(made.store)) == 0
    text = (tmp_path / "out.md").read_text()
    assert "flagged: 1 (check record `" in text
    for task in made.tasks["held_out"]:
        assert task.id not in text and id_digest(task.id) not in text, "a held-out task is named"


def test_the_report_command_refuses_a_record_not_bound_to_the_version_s_manifest(
    tmp_path: Path,
) -> None:
    from baseline_fixtures import record_check

    from physgate.evaluation.tiers.checks import check_path

    made, spec = _stand_in(tmp_path, checked=False)
    # A record that names itself, filed under the version, of another held-out tier.
    record_check(made.store, made.version, [made.tasks["held_out"][0].id], tier_sha256="f" * 64)
    assert check_path(made.store, "control", made.version).is_file()
    assert _cli(tmp_path, spec, "--store", str(made.store)) == 1, "an unbound record was read"
    assert not (tmp_path / "out.md").exists()
