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

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import JOINT_POWER, POWER, UNITS
from git_rig import Reviewer, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.cli import main
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.events import (
    GateRan,
    IntegrationEscalated,
    IntegrationGateRan,
    IntegrationGateSkipped,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.injected,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

INTERFACE: dict[str, Any] = {
    "id": "iface.power_bus",
    "kind": "interface",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {"v": {"value": 12, "unit": "V", "source": "brief", "written_by": "electrical"}},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}


class _PayingReviewer(Reviewer):
    """A reviewer reporting the tokens a real one would, so a zero means it never ran."""

    def review(self, artefact: Any) -> ReviewResult:
        result = super().review(artefact)
        usage = Usage(
            input_tokens=40,
            output_tokens=9,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        message = MessageUsage(message_id=f"r{self.calls}", usage=usage)
        return result.model_copy(update={"usage": (message,)})


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("install") / "install"
    prepare_install(path, Path(__file__).resolve().parents[3])
    return path


def session(*payloads: dict[str, Any]) -> Script:
    """What every session does: read its specification, write its proposals, stop."""
    writes = [
        tool(
            "Write",
            file_path=f"{{cwd}}/.physgate/proposals/{p['id']}.json",
            content=json.dumps(p),
        )
        for p in payloads
    ]
    return Script(
        main=[tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"), *writes, text("done")]
    )


def drive_run(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    modules: list[tuple[str, str]],
    payloads: tuple[dict[str, Any], ...],
    label: str,
) -> tuple[dict[str, Any], list[Any], _PayingReviewer, list[dict[str, Any]]]:
    """Decompose and run one plan.

    Returns the printed outcome, the events, the reviewer and the gate events.
    """
    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    params = config().model_dump(include={"auth", "gate_mode", "models", "bounds", "token_ceiling"})
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("Build a self-balancing robot; start with its power.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": n, "role": "electrical", "module_dir": d, "spec": "Size the power."}
            for n, d in modules
        ],
        "interface_nodes": [INTERFACE],
    }
    reviewer = _PayingReviewer()
    registrations = Registrations(gate=PhysicsGate(), reviewers={"electrical": reviewer})
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        code = main(
            [
                "decompose",
                str(tmp_path / "brief.md"),
                *args,
                "--target",
                str(repo),
                "--run-dir",
                str(run_dir),
            ]
        )
        assert code == 0, capsys.readouterr().err
        capsys.readouterr()
        api.script = session(*payloads)
        common = ["--run-dir", str(run_dir), "--target", str(repo), "--install", str(install)]
        main(["run", *common], registrations)
        out = capsys.readouterr()
    printed = json.loads(out.out) if out.out.strip() else {"error": out.err}
    assert "error" not in printed, out.err
    assert main(["gate-events", "--run-dir", str(run_dir)]) == 0
    gate_lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    events = read_events(run_dir / "events.jsonl")
    evidence = os.environ.get("PHYSGATE_EVIDENCE_DIR")
    if evidence:
        target = Path(evidence) / label
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(run_dir / "events.jsonl", target / "events.jsonl")
        (target / "run_output.json").write_text(json.dumps(printed, indent=1, sort_keys=True))
        (target / "gate_events.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=True) + "\n" for x in gate_lines)
        )
    return printed, events, reviewer, gate_lines


def reviewer_tokens(events: list[Any]) -> int:
    return TokenAccount.from_events(events).by_kind()["reviewer"].total()


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
