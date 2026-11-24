"""The command exits 75 while the round waits for the usage limit, 77 while it waits for a person.

A wrapper reads these codes and nothing else: 75 says start it again after the instant its line
gives, 77 says a person acts first (a refused credential to replace, or a trial's directory to set
aside, which the line names). Neither is a wait: the command returns at once.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from round_rig import SCORED, make_rig

from physgate.cli import main
from physgate.evaluation import harness_round


def _score(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


@pytest.mark.parametrize(
    ("cause", "code", "status"),
    [("usage_limit", 75, "waiting_for_limit"), ("credential_refused", 77, "waiting_for_a_person")],
)
def test_the_command_exits_with_the_wait_the_round_stands_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cause: str,
    code: int,
    status: str,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(fails={1: cause})
    monkeypatch.setattr(harness_round, "CommandDriver", lambda: driver)
    monkeypatch.setattr("physgate.evaluation.harness_round_cli._score", _score)
    argv = [
        "harness-round",
        *("--store", str(rig.made.store), "--role", "control", "--version", rig.made.version),
        *("--tier", "visible", "--trials", "1", "--seed-base", "100", "--tasks", "1"),
        *("--params", str(rig.params), "--run-root", str(rig.run_root)),
        *("--target-from", str(rig.target), "--install", str(rig.root / "install")),
        *("--prices", "2026-10-16", "--out", str(rig.root / "out")),
    ]
    assert main(argv) == code
    (line,) = capsys.readouterr().out.strip().splitlines()
    printed = json.loads(line)
    assert printed["status"] == status
    assert printed["waiting"]["index"] == 0
