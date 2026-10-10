"""The Python a role session finds is named by the run, measured, and never the harness's own.

A run names an interpreter by its path; what is recorded is what it measures: the
resolved path, the version, the prefix and the distributions it can import. An
interpreter that can import the harness, or that lies inside the harness checkout or
the hooks' installation, is refused, so a role session is never handed the
orchestrator's code. A configuration that names none records exactly what it did
before the field existed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from physgate.orchestrator.dispatch import probe_interpreter
from physgate.orchestrator.exceptions import RunConfigError
from physgate.orchestrator.role_python import RolePython, measure, require_same, session_bin
from physgate.orchestrator.run_config import RunConfig

REPO = Path(__file__).resolve().parents[3]
#: The interpreter the harness's own environment is built on: a standard Python with no
#: harness installed into it.
BASE = Path(sys.base_prefix) / "bin" / "python3"


def test_a_standard_interpreter_is_measured_and_recorded() -> None:
    found = measure(str(BASE), probe=probe_interpreter, harness=REPO)
    assert found.path == str(BASE) and found.resolved == str(BASE.resolve())
    assert found.version == ".".join(str(n) for n in sys.version_info[:3])
    assert "physgate" not in found.distributions


def test_the_harness_s_own_interpreter_is_refused() -> None:
    with pytest.raises(RunConfigError, match="inside the harness checkout|can import the harness"):
        measure(sys.executable, probe=probe_interpreter, harness=REPO)


def test_an_interpreter_that_can_import_the_harness_is_refused_wherever_it_lies() -> None:
    with pytest.raises(RunConfigError, match="can import the harness"):
        measure(sys.executable, probe=probe_interpreter, harness=None)


def test_an_interpreter_inside_the_hooks_installation_is_refused(tmp_path: Path) -> None:
    install = tmp_path / "install"
    (install / "bin").mkdir(parents=True)
    (install / "bin" / "python3").symlink_to(BASE)
    with pytest.raises(RunConfigError, match="inside the hooks' installation"):
        measure(
            str(install / "bin" / "python3"), probe=probe_interpreter, harness=REPO, install=install
        )


@pytest.mark.parametrize("named", ["python3", "/nonexistent/python3"])
def test_a_relative_or_missing_path_is_refused(named: str) -> None:
    with pytest.raises(RunConfigError):
        measure(named, probe=probe_interpreter, harness=REPO)


def test_something_that_is_not_a_python_is_refused(tmp_path: Path) -> None:
    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\necho not-python\n")
    os.chmod(fake, 0o755)
    with pytest.raises(RunConfigError, match="did not answer"):
        measure(str(fake), probe=probe_interpreter, harness=REPO)


def test_a_session_is_given_only_python3_linked_to_the_recorded_one(tmp_path: Path) -> None:
    found = measure(str(BASE), probe=probe_interpreter, harness=REPO)
    directory = session_bin(tmp_path / "session", found)
    assert [p.name for p in directory.iterdir()] == ["python3"]
    assert (directory / "python3").readlink() == Path(found.path)
    require_same(found, probe=probe_interpreter, harness=REPO, install=None)
    with pytest.raises(RunConfigError, match="not the one this run recorded"):
        require_same(
            found.model_copy(update={"version": "2.7.0"}),
            probe=probe_interpreter,
            harness=REPO,
            install=None,
        )


def test_a_configuration_that_names_none_records_what_it_did_before() -> None:
    from orch_helpers import make_config

    cfg = make_config()
    assert cfg.role_python is None
    assert b"role_python" not in cfg.canonical_bytes()
    measured = measure(str(BASE), probe=probe_interpreter, harness=REPO)
    named = cfg.model_copy(update={"role_python": measured})
    assert b"role_python" in named.canonical_bytes()
    assert RunConfig.model_validate_json(named.canonical_bytes()).role_python == (named.role_python)
    assert isinstance(named.role_python, RolePython)


def _params(tmp_path: Path, role_python: object) -> object:
    import argparse
    import json

    from orch_helpers import make_config

    cfg = make_config()
    params = {
        "auth": cfg.auth,
        "gate_mode": cfg.gate_mode,
        "models": cfg.models.model_dump(),
        "bounds": cfg.bounds.model_dump(mode="json"),
        "token_ceiling": cfg.token_ceiling,
        "reportable": False,
        "effort": cfg.effort,
        "max_output_tokens": cfg.max_output_tokens,
        "thinking_display": cfg.thinking_display,
        "role_python": role_python,
    }
    (tmp_path / "params.json").write_text(json.dumps(params))
    (tmp_path / "brief.md").write_text("brief\n")
    return argparse.Namespace(
        params=tmp_path / "params.json",
        brief=tmp_path / "brief.md",
        run_id="run-1",
        seed=7,
        target=tmp_path,
    )


def test_the_run_records_what_it_measured_never_what_the_parameters_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import physgate.orchestrator.cli as cli

    monkeypatch.setattr(cli, "binary_version", lambda: "2.1.283")
    monkeypatch.setattr(cli, "head_of", lambda *_: "c" * 40)
    cfg = cli._config(_params(tmp_path, str(BASE)))  # type: ignore[arg-type]
    assert cfg.role_python == measure(str(BASE), probe=probe_interpreter, harness=REPO)
    claimed = {"path": str(BASE), "resolved": str(BASE), "version": "9.9", "prefix": "/"}
    with pytest.raises(RunConfigError, match="by its path"):
        cli._config(_params(tmp_path, claimed))  # type: ignore[arg-type]
    with pytest.raises(RunConfigError):
        cli._config(_params(tmp_path, sys.executable))  # type: ignore[arg-type]
