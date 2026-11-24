"""The round's driver relays nothing a trial's command prints: it goes to the trial's log.

``physgate decompose`` prints the planner's module names, words of a protected task's brief; the
round calls the command in its own process, so whatever it prints, to Python's streams or to
the process's own descriptors, is written to the log beneath the withheld root that the round
names, and nothing reaches the terminal the round was started from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from physgate.evaluation.harness_round import CommandDriver, Decompose, Drive


def test_a_decomposition_s_output_goes_to_its_log_and_nothing_to_the_terminal(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    params = tmp_path / "params.json"
    params.write_text("{}")  # no auth mode: the command refuses, and says so
    log = tmp_path / "decompose.log"
    code = CommandDriver().decompose(
        Decompose(
            brief=tmp_path / "brief.md",
            seed=1,
            run_id="r-1",
            params=params,
            target=tmp_path / "target",
            run_dir=tmp_path / "run",
            install=tmp_path / "install",
            review_root=tmp_path / "review",
            log=log,
        )
    )
    printed = capfd.readouterr()
    assert code == 2
    assert printed.out == "" and printed.err == ""
    assert "error" in log.read_text()


def test_what_a_child_writes_to_the_process_s_descriptors_goes_to_the_log(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def child_writes(_argv: list[str], _registrations: object) -> int:
        os.write(1, b"module names on the descriptor\n")
        print("module names on the stream", file=sys.stderr)
        return 0

    monkeypatch.setattr("physgate.cli.main", child_writes)
    log = tmp_path / "drive.log"
    code = CommandDriver().drive(
        Drive(
            resume=True,
            run_dir=tmp_path / "run",
            target=tmp_path / "target",
            install=tmp_path / "install",
            review_root=tmp_path / "review",
            limit_reset=False,
            log=log,
        )
    )
    printed = capfd.readouterr()
    assert code == 0 and printed.out == "" and printed.err == ""
    assert log.read_text().splitlines() == [
        "module names on the descriptor",
        "module names on the stream",
    ]
