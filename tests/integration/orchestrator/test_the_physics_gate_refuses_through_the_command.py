"""The physics gate refusing work through the ``physgate`` command, with the real binary.

`physgate decompose`, then `physgate run`, against the scripted endpoint: the
session reads its specification and writes node proposals under the hooks,
exactly as a model's tool calls would, and the gate the command registers judges
them. No model is called and no key is real. Three runs, one refusal each:

- a current compared with a voltage, refused at subtask scope;
- a module whose consumers draw more than it supplies, refused at module scope;
- two modules that each balance but together exceed their battery, refused at
  the integration call.

In each, the refused work is never reviewed and spends no review token. When
``PHYSGATE_EVIDENCE_DIR`` is set, each run's event log, its printed outcome and
the output of ``physgate gate-events`` are copied there.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from gate_fixtures import JOINT_POWER, POWER, UNITS
from gate_run import build_install, drive_run, reviewer_tokens

from physgate.orchestrator.events import (
    GateRan,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    ReviewRan,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.injected,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def test_a_current_compared_with_a_voltage_is_refused_at_subtask_scope_through_the_command(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = drive_run(
        tmp_path, install, monkeypatch, capsys, [("power", "modules/power")], UNITS, "subtask"
    )
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check) for g in gated] == [("fail", "units")] * 3
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0
    assert printed["tokens"]["reviewer"] == 0 and printed["tokens"]["routing"] == 0
    (skipped,) = [e for e in events if isinstance(e, IntegrationGateSkipped)]
    assert skipped.reason == "not_all_merged"
    fails = [x for x in gate_lines if x["outcome"] == "fail"]
    assert {(x["name"], x["scope"]) for x in fails} == {("units", "subtask")}
    assert all(x["reviewer_had_passed"] is None for x in gate_lines)


def test_an_unbalanced_module_is_refused_at_module_scope_through_the_command(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = drive_run(
        tmp_path, install, monkeypatch, capsys, [("power", "modules/power")], POWER, "module"
    )
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check) for g in gated] == [("fail", "power")] * 3
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0
    fails = [x for x in gate_lines if x["outcome"] == "fail"]
    assert {(x["name"], x["scope"]) for x in fails} == {("power", "module")}


def test_a_joint_power_deficit_is_refused_at_the_integration_call_through_the_command(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = drive_run(
        tmp_path,
        install,
        monkeypatch,
        capsys,
        [("power", "modules/power"), ("control", "modules/control")],
        JOINT_POWER,
        "integration",
    )
    assert printed["step"] == "escalated"
    (integrated,) = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert (integrated.result.verdict, integrated.result.failing_check) == ("fail", "power")
    assert len([e for e in events if isinstance(e, IntegrationEscalated)]) == 1
    reviews = [e for e in events if isinstance(e, ReviewRan)]
    # The subtasks passed the gate and were reviewed; the integrated design was not.
    assert len(reviews) == 2 and all(r.seq < integrated.seq for r in reviews)
    assert reviewer_tokens(events) == 2 * 49
    at_integration = [x for x in gate_lines if x["subtask_id"] == "integration"]
    assert any(x["outcome"] == "fail" and x["name"] == "power" for x in at_integration)
    assert all(x["attempt"] is None and x["scope"] == "system" for x in at_integration)
