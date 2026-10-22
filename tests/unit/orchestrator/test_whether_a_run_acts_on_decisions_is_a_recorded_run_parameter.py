"""Whether a run acts on queue decisions is a flag of the register, required and recorded.

``queue_decisions`` is ``act`` or ``record`` (ARCH-133). A new run names it, or the command
refuses it before anything is written; it is never read from the environment. A run recorded
before the flag existed reads as ``record``, with exactly the digest its first line carries, and
so does every ``record`` run, whose recorded form leaves the field out; an ``act`` run records it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from orch_helpers import make_config

from physgate.cli import main
from physgate.orchestrator.run_config import load_run_config, write_run_config
from physgate.oslayer.probe import Present

ROOT = Path(__file__).resolve().parents[3]


def test_a_run_recorded_before_the_flag_reads_as_record_with_its_digest_unchanged(
    tmp_path: Path,
) -> None:
    config = make_config(queue_decisions="record")
    path = tmp_path / "run.json"
    write_run_config(path, config)
    recorded = json.loads(path.read_bytes())
    assert "queue_decisions" not in recorded  # what a run before the flag wrote, byte for byte
    loaded = load_run_config(path)
    assert loaded.queue_decisions == "record"
    assert loaded.sha256() == config.sha256()


def test_an_act_run_records_the_flag_in_its_manifest(tmp_path: Path) -> None:
    # The same run but for the flag; a run that acts is one configured inside the OS layer.
    layer = Present(mechanism="seatbelt", claude_version="2.1.301")
    act = make_config(queue_decisions="act", os_layer=layer)
    record = make_config(queue_decisions="record", os_layer=layer)
    assert b'"queue_decisions":"act"' in act.canonical_bytes()
    assert act.sha256() != record.sha256()
    path = tmp_path / "run.json"
    write_run_config(path, act)
    assert load_run_config(path).queue_decisions == "act"


def test_both_example_parameters_record_decisions_only() -> None:
    from physgate.orchestrator.cli import EXAMPLES

    paths = sorted(EXAMPLES.glob("params.*.json"))
    assert len(paths) == 2
    for path in paths:
        assert json.loads(path.read_text())["queue_decisions"] == "record"


def test_the_command_refuses_a_new_run_whose_parameters_do_not_name_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_the_physgate_command_starts_and_decides import (  # noqa: PLC0415
        PARAMS,
        _decompose_args,
        fake_binary,
    )

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-dummy-not-a-credential")
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    unnamed = {k: v for k, v in PARAMS.items() if k != "queue_decisions"}
    assert main(_decompose_args(tmp_path, unnamed)) == 2
    # Refused by the configuration's own schema, as any other missing parameter is: the legacy
    # reading as ``record`` belongs to a recorded run only.
    assert json.loads(capsys.readouterr().err)["reason"].startswith("queue_decisions")
    assert not (tmp_path / "run").exists()


def test_the_comparison_reports_the_flag() -> None:
    from physgate.evaluation.observe.compare import REPORTED

    assert "queue_decisions" in REPORTED
