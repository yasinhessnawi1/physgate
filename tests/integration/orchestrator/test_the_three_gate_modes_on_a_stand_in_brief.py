"""The physics gate's three modes on one stand-in brief, through the ``physgate`` command.

The gate mode is the architecture's most important ablation switch (ARCH-140):
the count of errors the gate catches that a reviewer had approved is only
interpretable against a run where the gate watches without blocking. So one plan
and one session run three times with the real binary on the scripted endpoint,
and only the mode differs:

- ``on``: the gate refuses the module, the reviewer never sees it, the subtask is
  escalated;
- ``off``: no check runs, the log says the gate stage was skipped and why, the
  reviewer runs and the subtask merges;
- ``observe``: every check runs and is recorded, stamped ``observe`` on every
  line, and nothing is refused.

**The brief is a stand-in**, written for this test: the drive power module of the
self-balancing robot, not the reference design's brief. Its proposals carry two
deliberate errors: 15 W drawn from a 10 W module (blocking at module and system
scope), and a driver at 145 degC against its 125 degC limit (a warning at module
scope, blocking at system scope). Everything else is sound: the module draws what
it supplies from a battery, which declares the energy it stores, so the power
check's rule that a supply is a declared source or draws from one holds.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import node
from gate_run import build_install, drive_run, reviewer_tokens

from physgate.orchestrator.events import (
    GateRan,
    GateSkipped,
    IntegrationGateRan,
    IntegrationGateSkipped,
    Merged,
    ReviewRan,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

STAND_IN_BRIEF = (
    "STAND-IN BRIEF, written for the physics gate's three-mode test; not the reference "
    "design's brief.\n\n"
    "Size the drive power module of a two-wheeled self-balancing robot: two brushed DC "
    "gearmotors on one motor driver, fed from the module's power supply, which is fed "
    "from a battery.\n"
)

DRIVE_MODULE: tuple[dict[str, Any], ...] = (
    # A declared source: a battery declares the energy it stores.
    node(
        "electrical.battery",
        quantities={"power_supply": (20, "W"), "energy_capacity": (20, "W*h")},
    ),
    # The module draws what it supplies from the battery.
    node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (10, "W"), "power_draw": (10, "W"), "mass": (0.4, "kg")},
        constrains=["electrical.battery"],
    ),
    *(
        node(
            f"electrical.motor_{side}",
            quantities={"power_draw": (7.5, "W"), "stall_current": (2.4, "A"), "mass": (0.2, "kg")},
            constrains=["electrical.drive", "electrical.driver"],
        )
        for side in ("left", "right")
    ),
    node(
        "electrical.driver",
        quantities={
            "current_limit": (3, "A"),
            "thermal_resistance": (40, "K/W"),
            "heat_dissipation": (3, "W"),
            "ambient_temperature": (25, "degC"),
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.drive"],
    ),
)
SIX = {"units", "magnitude", "equilibrium", "power", "conservation", "thermal"}


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def run_in(
    mode: str,
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[dict[str, Any], list[Any], Any, list[dict[str, Any]]]:
    return drive_run(
        tmp_path,
        install,
        monkeypatch,
        capsys,
        [("drive", "modules/power")],
        DRIVE_MODULE,
        f"mode_{mode}",
        gate_mode=mode,
        brief=STAND_IN_BRIEF,
    )


def test_on_the_gate_refuses_the_module_and_the_reviewer_never_sees_it(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = run_in("on", tmp_path, install, monkeypatch, capsys)
    gated = [e for e in events if isinstance(e, GateRan)]
    assert [(g.result.verdict, g.result.failing_check, g.result.mode) for g in gated] == [
        ("fail", "power", "on")
    ] * 3
    warned = [r for r in gated[0].result.checks if r.outcome == "warn"]
    assert [(r.name, r.scope) for r in warned] == [("thermal", "module")]
    for g in gated:
        failed = [(r.name, r.scope, r.node) for r in g.result.checks if r.outcome == "fail"]
        assert failed == [("power", "module", "electrical.drive")]
    assert [e for e in events if isinstance(e, ReviewRan)] == []
    assert reviewer.calls == 0 and reviewer_tokens(events) == 0
    assert list(printed["subtasks"].values()) == ["escalated"]
    (skipped,) = [e for e in events if isinstance(e, IntegrationGateSkipped)]
    assert skipped.reason == "not_all_merged"
    assert {e.gate_mode for e in events} == {"on"}
    assert {x["gate_mode"] for x in gate_lines} == {"on"}
    assert printed["tokens"]["routing"] == 0


def test_off_no_check_runs_the_skip_is_recorded_and_the_reviewer_decides(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = run_in("off", tmp_path, install, monkeypatch, capsys)
    assert [e for e in events if isinstance(e, GateRan | IntegrationGateRan)] == []
    (skipped,) = [e for e in events if isinstance(e, GateSkipped)]
    assert skipped.reason == "gate_mode=off"
    assert len([e for e in events if isinstance(e, ReviewRan)]) == 1 and reviewer.calls == 1
    assert len([e for e in events if isinstance(e, Merged)]) == 1
    (integration,) = [e for e in events if isinstance(e, IntegrationGateSkipped)]
    assert (integration.reason, integration.subtasks) == ("gate_mode=off", ())
    assert gate_lines == []
    assert {e.gate_mode for e in events} == {"off"}
    assert printed["step"] == "done" and printed["tokens"]["routing"] == 0


def test_observe_every_check_runs_every_line_says_observe_and_nothing_is_refused(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, gate_lines = run_in(
        "observe", tmp_path, install, monkeypatch, capsys
    )
    (gated,) = [e for e in events if isinstance(e, GateRan)]
    assert (gated.result.verdict, gated.result.mode) == ("fail", "observe")
    assert {r.name for r in gated.result.checks} == SIX
    outcomes = {(r.name, r.outcome) for r in gated.result.checks}
    assert ("power", "fail") in outcomes and ("thermal", "warn") in outcomes
    assert len([e for e in events if isinstance(e, ReviewRan)]) == 1 and reviewer.calls == 1
    assert len([e for e in events if isinstance(e, Merged)]) == 1
    (integrated,) = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert (integrated.result.verdict, integrated.result.mode) == ("fail", "observe")
    at_system = {(r.name, r.node) for r in integrated.result.checks if r.outcome == "fail"}
    assert at_system == {("power", "electrical.drive"), ("thermal", "electrical.driver")}
    assert printed["step"] == "done" and printed["open_queue_items"] == []
    assert {e.gate_mode for e in events} == {"observe"}
    assert gate_lines and {x["gate_mode"] for x in gate_lines} == {"observe"}
    assert all(x["reviewer_had_passed"] is None for x in gate_lines)
    assert printed["tokens"]["routing"] == 0
