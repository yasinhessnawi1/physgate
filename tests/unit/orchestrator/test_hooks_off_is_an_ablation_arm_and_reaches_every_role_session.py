"""``hooks: off`` is an ablation run's arm, and every role session of such a run is installed so.

A run takes ``hooks: off`` only as an ablation run: a run that is not one is refused at its
configuration by a rule that names the arm, so the product can never set it and no reportable
number is measured without the discipline. An ablation run takes it, and each of its role
sessions is installed with the run's recorded value, and with the run's recorded configuration,
so the installer holds the two equal rather than trusting a word on its command line.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from design_review_rig import outcome_of
from orch_helpers import CLEAN_HARNESS, SCRIPTED_BOUNDS, make_config

import physgate.flags as flags
from physgate.orchestrator import dispatch, run_config
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig


def _config(**fields: Any) -> Any:  # noqa: ANN401 - a configuration, or why there is none
    return outcome_of(lambda: make_config(**({"harness": CLEAN_HARNESS} | fields)))


def test_both_values_of_the_hooks_switch_are_built() -> None:
    assert run_config.BUILT["hooks"] == flags.HOOKS.values


def test_an_ablation_run_takes_hooks_off() -> None:
    config = _config(hooks="off", ablation=True)
    assert isinstance(config, RunConfig), config
    assert config.hooks == "off"
    assert b'"hooks":"off"' in config.canonical_bytes()


@pytest.mark.parametrize("reportable", [False, True])
def test_a_run_that_is_not_an_ablation_is_refused_hooks_off_by_a_rule_that_names_it(
    reportable: bool,
) -> None:
    refused = _config(hooks="off", ablation=False, reportable=reportable)
    assert not isinstance(refused, RunConfig), refused
    assert "hooks: off is an ablation arm" in str(refused)
    # The same run with the discipline on is a run.
    assert isinstance(_config(ablation=False, reportable=reportable), RunConfig)


def test_the_register_says_which_runs_take_hooks_off() -> None:
    meaning = flags.HOOKS.meanings["off"]
    assert "only an ablation run takes it" in meaning
    assert "until the arm is built" not in meaning


def _install_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config: RunConfig) -> list[str]:
    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    dispatcher = ClaudeDispatcher(
        config=config,
        run=SimpleNamespace(  # type: ignore[arg-type]
            subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=tmp_path / "run"
        ),
        store_root=tmp_path / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    temp = Path("/var/tmp/pgs/0123456789")
    dispatcher._install(request, tmp_path / "worktree", tmp_path / "sdir", temp, own_temp=temp)
    return seen[0]


def _values(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


@pytest.mark.parametrize("hooks", ["on", "off"])
def test_every_role_session_is_installed_with_the_run_s_recorded_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hooks: str
) -> None:
    # The configuration as the run recorded it; the installer, not this rig, judges the arm.
    config = make_config().model_copy(update={"hooks": hooks, "ablation": hooks == "off"})
    argv = _install_argv(tmp_path, monkeypatch, config)
    assert _values(argv, "--hooks") == [hooks]


def test_with_hooks_off_the_installer_is_given_the_run_s_record_even_inside_the_os_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on = _install_argv(tmp_path / "on", monkeypatch, make_config())
    assert "--run-config" not in on  # inside the layer, as before
    config = make_config().model_copy(update={"hooks": "off", "ablation": True})
    off = _install_argv(tmp_path / "off", monkeypatch, config)
    assert _values(off, "--run-config") == [str(tmp_path / "off" / "run" / "run.json")]
