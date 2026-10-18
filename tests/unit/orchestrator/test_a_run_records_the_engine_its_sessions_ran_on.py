"""A run records the engine its sessions ran on, and the line changes nothing the log decides.

``physgate run`` and ``resume`` record, before anything is spawned and beside the OS layer's
state, the harness and its version, the provider and endpoint, every model string the run
sends with the model it is, and the layers held around a role's and a reviewer's sessions.
Like the installation check, the line is a record of the machine's work, not a transition:
the ledger and the position a resume rebuilds are what they would be without it, and it may
be written at any point, a halted run's resume included. ``physgate trace`` reads it back.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from loop_fakes import FakeDispatcher, Rig, plan
from orch_helpers import make_config

from physgate.engines.claude_code import ClaudeCodeEngine
from physgate.orchestrator import cli
from physgate.orchestrator.common import utc_stamp
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.events import EngineChecked, Envelope, read_events
from physgate.orchestrator.loop import Loop
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ABSENT = Absent(reason="stand-in: no sandbox here")
ENGINE = ClaudeCodeEngine(base_url=None, credential=Credential("api_key", "not-a-key"))


def _envelope() -> Envelope:
    stamp = utc_stamp(datetime(2026, 10, 18, tzinfo=UTC))
    return Envelope(seq=0, ts=stamp, run_id="run-1", gate_mode="on")


def test_the_record_names_every_model_the_run_sends_and_the_layers_held_here() -> None:
    config = make_config(claude_version="2.1.301")
    checked = cli._engine_checked(_envelope(), config, ENGINE, PRESENT)
    engine = checked.engine
    assert (engine.harness, engine.version, engine.endpoint) == (
        "claude-code",
        "2.1.301",
        "default",
    )
    sent = {
        config.models.decomposition,
        *config.models.roles.values(),
        *config.models.reviewers.values(),
    }
    assert {m.request_name for m in engine.models} == sent
    assert engine.role.os_layer == "harness_sandbox"
    assert cli._engine_checked(_envelope(), config, ENGINE, ABSENT).engine.role.os_layer == "absent"


def _checked(loop: Loop) -> None:
    loop.record.emit(cli._engine_checked(loop.record.envelope(), make_config(), ENGINE, ABSENT))


def _run(root: Path, with_checks: bool) -> tuple[bytes, dict[str, str]]:
    # One infrastructure failure with no retries halts the run; a resume continues it.
    rig = Rig(root, dispatcher=FakeDispatcher(infra={1: "api_error"}))
    loop = rig.open()
    loop.start(plan("s1", "s2"))
    if with_checks:
        _checked(loop)
    assert loop.run().kind == "halted"
    loop.close()
    loop = rig.open()
    if with_checks:
        _checked(loop)  # after the halt, before the resume: allowed
    assert loop.resume().kind == "done"
    statuses: dict[str, str] = {k: v.status for k, v in loop.state.subtasks.items()}
    loop.close()
    return (root / "ledger.jsonl").read_bytes(), statuses


def test_the_ledger_and_the_resume_are_the_same_with_and_without_the_line(
    tmp_path: Path,
) -> None:
    plain = _run(tmp_path / "plain", with_checks=False)
    checked = _run(tmp_path / "checked", with_checks=True)
    assert checked == plain
    assert plain[1] == {"s1": "done", "s2": "done"}
    lines = read_events(tmp_path / "checked" / "events.jsonl")
    found = [e.engine for e in lines if isinstance(e, EngineChecked)]
    expected = cli._engine_checked(_envelope(), make_config(), ENGINE, ABSENT).engine
    assert found == [expected] * 2  # read back whole
