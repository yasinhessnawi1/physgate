"""The escalation binding is a run parameter: required, recorded, never from the environment.

The run names which backend answers "does this subtask go to the approval queue"
(ARCH-131) by its register name (ARCH-132), like the gate mode: the configuration
refuses a run without it, records it in ``run.json`` and therefore in the manifest id,
and puts it on the run's first line. A run recorded before the binding existed still
reads, with its digest unchanged, as naming none; no loop drives such a run, and the
command refuses to start a new one that names none.
"""

from __future__ import annotations

import hashlib
import json
import typing
from pathlib import Path

import pytest
from loop_fakes import FakeGate, FakeReviewer, Rig, plan
from orch_helpers import make_config
from pydantic import ValidationError

from physgate.cli import main
from physgate.orchestrator.escalation import BackendRow, EscalationInterface, RulesBackend
from physgate.orchestrator.events import RunStarted, read_events
from physgate.orchestrator.exceptions import EscalationBackendError, RunConfigError
from physgate.orchestrator.loop import escalation_for
from physgate.orchestrator.record import RunRecord
from physgate.orchestrator.run_config import (
    RunConfig,
    load_run_config,
    require_recorded,
    write_run_config,
)

ROOT = Path(__file__).resolve().parents[3]
#: A ``run.json`` written by the code as it was before the binding existed (the branch
#: point of this change), committed as it was written.
RECORDED_BEFORE = Path(__file__).parent / "recorded" / "run_recorded_before_the_binding.json"
RECORDED_BEFORE_SHA256 = "d2be63af107c5714ad071d18bf6b8a565aab0ddb0d7b30b040093dda526957ac"


def test_the_binding_is_a_required_field_with_no_default() -> None:
    field = RunConfig.model_fields["escalation_backend"]
    assert field.is_required()
    with pytest.raises(ValidationError) as caught:
        RunConfig.model_validate({})
    missing = {tuple(e["loc"]) for e in caught.value.errors() if e["type"] == "missing"}
    assert ("escalation_backend",) in missing


@pytest.mark.parametrize("name", ["llm", "tsetlin", "laya", "learned", "Rules", ""])
def test_a_name_that_is_not_a_shipping_row_is_refused_by_the_configuration(name: str) -> None:
    with pytest.raises(ValidationError):
        make_config(escalation_backend=name)


def test_the_binding_is_recorded_in_run_json_and_so_in_the_manifest_id(tmp_path: Path) -> None:
    bound = make_config()
    assert bound.escalation_backend == "rules"
    assert b'"escalation_backend":"rules"' in bound.canonical_bytes()
    unbound = make_config(escalation_backend=None)
    assert b"escalation_backend" not in unbound.canonical_bytes()
    assert bound.sha256() != unbound.sha256()
    write_run_config(tmp_path / "run.json", bound)
    assert load_run_config(tmp_path / "run.json") == bound


def test_a_run_json_written_before_the_binding_reads_as_none_with_its_digest_unchanged() -> None:
    raw = RECORDED_BEFORE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RECORDED_BEFORE_SHA256
    assert b"escalation_backend" not in raw
    loaded = load_run_config(RECORDED_BEFORE)
    assert loaded.escalation_backend is None
    assert loaded.canonical_bytes() == raw
    assert loaded.sha256() == RECORDED_BEFORE_SHA256
    assert require_recorded(RECORDED_BEFORE, loaded) == loaded


def test_the_run_s_first_line_names_its_binding(tmp_path: Path) -> None:
    loop = Rig(tmp_path).open()
    loop.start(plan("s1"))
    loop.close()
    first = read_events(tmp_path / "events.jsonl")[0]
    assert isinstance(first, RunStarted)
    assert first.escalation_backend == "rules"


def test_a_first_line_written_before_the_binding_reads_as_naming_none() -> None:
    # The first line's shape before the binding existed: no such field.
    old = (
        '{"seq":0,"ts":"2026-10-10T00:00:00.000000Z","run_id":"r","gate_mode":"on",'
        '"kind":"run_started","config_sha256":"' + "a" * 64 + '"}'
    )
    line = RunStarted.model_validate_json(old)
    assert line.escalation_backend is None


def test_a_log_that_names_another_binding_than_its_config_is_not_this_run(tmp_path: Path) -> None:
    record = RunRecord(make_config(), tmp_path)
    record.start([])
    record.close()
    log = tmp_path / "events.jsonl"
    first, rest = log.read_bytes().split(b"\n", 1)
    line = json.loads(first)
    line["escalation_backend"] = None
    log.write_bytes(json.dumps(line).encode() + b"\n" + rest)
    with pytest.raises(RunConfigError) as caught:
        RunRecord(make_config(), tmp_path)
    assert caught.value.context["logged"] == "None"


def test_the_loop_refuses_a_run_that_names_no_binding(tmp_path: Path) -> None:
    rig = Rig(tmp_path, config_overrides={"escalation_backend": None})
    with pytest.raises(EscalationBackendError):
        rig.open()
    assert not (tmp_path / "events.jsonl").exists()
    with pytest.raises(EscalationBackendError):
        escalation_for(make_config(escalation_backend=None))


def test_the_loop_refuses_an_interface_over_another_backend(tmp_path: Path) -> None:
    other = BackendRow(
        name="stand_in", status="ships", entry_condition="a test's", evidence=(), version="s/1"
    )
    rig = Rig(tmp_path, escalation=EscalationInterface(RulesBackend(), other))
    with pytest.raises(EscalationBackendError) as caught:
        rig.open()
    assert (caught.value.context["named"], caught.value.context["asked"]) == ("rules", "stand_in")


def test_the_binding_the_run_names_is_bound_through_the_register() -> None:
    assert escalation_for(make_config()).backend_id == "rules"


def test_both_example_parameters_name_the_rules_binding() -> None:
    from physgate.orchestrator.cli import EXAMPLES

    paths = sorted(EXAMPLES.glob("params.*.json"))
    assert len(paths) == 2
    for path in paths:
        assert json.loads(path.read_text())["escalation_backend"] == "rules"


@pytest.mark.parametrize("spelling", ["ESCALATION_BACKEND", "PHYSGATE_ESCALATION_BACKEND"])
def test_the_binding_is_never_read_from_the_environment(spelling: str) -> None:
    source = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    example = (ROOT / ".env.example").read_text()
    assert f'environ.get("{spelling}"' not in source
    assert f'environ["{spelling}"' not in source
    assert f'getenv("{spelling}"' not in source
    assert f"\n{spelling}=" not in example


def test_the_command_refuses_a_new_run_whose_parameters_name_no_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_the_physgate_command_starts_and_decides import (  # noqa: PLC0415
        PARAMS,
        _decompose_args,
        fake_binary,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    assert main(_decompose_args(tmp_path, {**PARAMS, "escalation_backend": None})) == 2
    assert "names its escalation backend" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()
    assert main(_decompose_args(tmp_path, {**PARAMS, "escalation_backend": "laya"})) == 2
    assert "parked" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


def test_the_command_refuses_to_drive_a_run_recorded_with_no_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_the_physgate_command_starts_and_decides import _run_args  # noqa: PLC0415

    from physgate.orchestrator.cli import Registrations

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.delenv("PHYSGATE_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")
    record = RunRecord(make_config(escalation_backend=None), tmp_path / "run")
    record.start([])
    record.close()
    events = (tmp_path / "run" / "events.jsonl").read_bytes()
    registrations = Registrations(gate=FakeGate(), reviewers={"electrical": FakeReviewer()})
    for command in ("run", "resume"):
        assert main([command, *_run_args(tmp_path)[1:]], registrations) == 2
        assert "names no escalation backend" in capsys.readouterr().err
    assert (tmp_path / "run" / "events.jsonl").read_bytes() == events


def test_the_comparison_reports_a_different_binding_and_does_not_refuse_it() -> None:
    from physgate.evaluation.observe.compare import REPORTED, RunNumbers, drift

    assert "escalation_backend" in REPORTED
    assert "escalation_backend" in RunNumbers.model_fields
    assert drift(make_config(), make_config(escalation_backend=None)) == []
    assert typing.get_args(RunNumbers.model_fields["escalation_backend"].annotation)
