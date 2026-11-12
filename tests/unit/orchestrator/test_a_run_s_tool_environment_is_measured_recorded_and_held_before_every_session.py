"""A run's tool environment is named by its parameters, measured, recorded and held to its bytes.

The parameters name an interpreter, the environment's roots and its native tools; what the run
records is what was measured, never anything the parameters claim. A run that names none records
exactly what it did before the field existed. Before every session the environment is held to
the record: measured in full the first time a process dispatches (a new run and every resume),
scanned against that measure before each later session, and refused on any difference before
anything of the session exists. Each session is installed with the environment's roots, so its
hooks and the OS layer keep its writes out.

The interpreter and the native tool are small programs that answer as the real ones do.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config
from pydantic import ValidationError
from test_the_physgate_command_starts_and_decides import PARAMS, fake_binary

from physgate.orchestrator import cli, dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.run_config import RunConfig, load_run_config, write_run_config
from physgate.orchestrator.tool_environment import (
    forbidden_places,
    hold_before_session,
    measure_named,
)
from physgate.oslayer.probe import Absent
from physgate.oslayer.session_temp import session_temps_root
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import manifest, scan
from physgate.toolenv.record import ToolEnvironment, hold, run_program

ABSENT = Absent(reason="stand-in: no sandbox here")


def _program(path: Path, says: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{says}'\n")
    path.chmod(0o755)


def _environment(tmp_path: Path) -> dict[str, Any]:
    """An environment's tree, and how a run's parameters name it."""
    root = Path(os.path.realpath(tmp_path)) / "tools" / "env"
    (root / "bin").mkdir(parents=True)
    (root / "lib" / "control").mkdir(parents=True)
    answer = {
        "version": "3.12.9",
        "prefix": str(root),
        "base_prefix": str(root),
        "physgate": False,
        "distributions": [["control", "0.10.1"], ["numpy", "2.1.2"]],
    }
    _program(root / "bin" / "python3", json.dumps(answer))
    _program(root / "bin" / "avr-gcc", "avr-gcc (GCC) 7.3.0")
    (root / "lib" / "control" / "margins.py").write_text("def margin(): return 1\n")
    return {
        "interpreter": str(root / "bin" / "python3"),
        "roots": [str(root)],
        "native": {"avr-gcc": str(root / "bin" / "avr-gcc")},
    }


def _library(named: dict[str, Any]) -> Path:
    return Path(named["roots"][0]) / "lib" / "control" / "margins.py"


# -- the parameters name it; the run records what was measured ---------------------------------


def test_what_is_recorded_is_what_was_measured(tmp_path: Path) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    walked = manifest([Path(named["roots"][0])])
    assert found.manifest_digest == walked.digest and found.entries == walked.entries
    assert found.interpreter == named["interpreter"]
    assert found.python_version == "3.12.9"
    assert [(d.name, d.version) for d in found.distributions] == [
        ("control", "0.10.1"),
        ("numpy", "2.1.2"),
    ]
    assert [(t.name, t.version) for t in found.native_tools] == [("avr-gcc", "avr-gcc (GCC) 7.3.0")]


def test_an_environment_that_names_no_native_tool_is_measured(tmp_path: Path) -> None:
    named = {k: v for k, v in _environment(tmp_path).items() if k != "native"}
    assert measure_named(named, forbidden={}).native_tools == ()


@pytest.mark.parametrize(
    "change",
    [
        # Nothing but the three names is the parameters' to say.
        {"manifest_digest": "0" * 64},
        {"python_version": "3.12.9"},
        {"interpreter": "bin/python3"},
        {"interpreter": 7},
        {"roots": []},
        {"roots": "/opt/tools"},
        {"native": ["avr-gcc"]},
        {"native": {"avr-gcc": "avr-gcc"}},
    ],
)
def test_parameters_that_claim_or_misname_anything_are_refused(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    with pytest.raises(RunConfigError, match="tool environment"):
        measure_named({**_environment(tmp_path), **change}, forbidden={})


@pytest.mark.parametrize("named", ["/opt/tools/env", ["/opt/tools/env"], 7, True])
def test_parameters_that_are_not_the_three_names_are_refused(named: object) -> None:
    with pytest.raises(RunConfigError, match="tool environment"):
        measure_named(named, forbidden={})


def test_an_environment_in_a_forbidden_place_is_refused_as_a_configuration_error(
    tmp_path: Path,
) -> None:
    named = _environment(tmp_path)
    place = Path(named["roots"][0]).parent
    with pytest.raises(RunConfigError, match="overlaps the run's directory"):
        measure_named(named, forbidden={"the run's directory": place})


def test_the_places_it_may_not_lie_in_are_the_harness_s_the_run_s_and_every_temporary_one(
    tmp_path: Path,
) -> None:
    places = forbidden_places(
        harness=tmp_path / "harness",
        install=tmp_path / "install",
        run_dir=tmp_path / "run",
        target=tmp_path / "target",
    )
    held = {str(place) for place in places.values()}
    assert {str(tmp_path / n) for n in ("harness", "install", "run", "target")} <= held
    assert session_temps_root() in held
    assert "/tmp" in held
    assert len(places) == len(held), "two places share a description, so one was dropped"
    fewer = forbidden_places(harness=None, install=None, run_dir=tmp_path / "run", target=None)
    assert str(tmp_path / "run") in {str(place) for place in fewer.values()}
    assert not {str(tmp_path / n) for n in ("harness", "install", "target")} & {
        str(place) for place in fewer.values()
    }


# -- the record ------------------------------------------------------------------------------


def test_a_run_that_names_none_records_what_it_did_before_the_field_existed(
    tmp_path: Path,
) -> None:
    config = make_config()
    assert config.tool_environment is None
    assert b"tool_environment" not in config.canonical_bytes()
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert b"tool_environment" not in path.read_bytes()
    loaded = load_run_config(path)
    assert loaded.tool_environment is None and loaded.sha256() == config.sha256()


def test_a_named_environment_is_in_the_run_s_record_and_reads_back(tmp_path: Path) -> None:
    found = measure_named(_environment(tmp_path), forbidden={})
    config = make_config(tool_environment=found)
    assert found.manifest_digest.encode() in config.canonical_bytes()
    assert config.sha256() != make_config().sha256()
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert load_run_config(path).tool_environment == found


def _role_python(path: str) -> RolePython:
    return RolePython(
        path=path, resolved=path, version="3.12.9", prefix="/opt/py", distributions=()
    )


def test_a_run_that_names_another_interpreter_beside_the_environment_s_is_refused(
    tmp_path: Path,
) -> None:
    found = measure_named(_environment(tmp_path), forbidden={})
    with pytest.raises(ValueError, match="role_python"):
        make_config(tool_environment=found, role_python=_role_python("/opt/py/bin/python3"))
    same = make_config(tool_environment=found, role_python=_role_python(found.interpreter))
    assert same.role_python is not None and same.role_python.path == found.interpreter


def test_a_new_run_s_configuration_measures_the_environment_its_parameters_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = _environment(tmp_path)
    asked: list[dict[str, Path | None]] = []

    def places(**given: Path | None) -> dict[str, Path]:
        asked.append(given)
        return {}

    monkeypatch.setattr(cli, "forbidden_places", places)
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(fake_binary(tmp_path, "2.1.272")))
    (tmp_path / "brief.md").write_text("Build a robot.\n")
    # A target repository of the test's own, so the test holds wherever its file lies.
    target = tmp_path / "target"
    target.mkdir()
    author = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    for argv in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "commit", "-q", "--allow-empty", "-m", "fixture"],
    ):
        subprocess.run(argv, cwd=target, env=author, check=True)

    def configured(params: dict[str, object]) -> RunConfig:
        (tmp_path / "params.json").write_text(json.dumps(params))
        return cli._config(
            argparse.Namespace(
                params=tmp_path / "params.json",
                run_id="run-1",
                seed=7,
                brief=tmp_path / "brief.md",
                target=target,
                run_dir=tmp_path / "run",
            )
        )

    config = configured({**PARAMS, "tool_environment": named})
    assert config.tool_environment == measure_named(named, forbidden={})
    assert len(asked) == 1, "the places it may not lie in were not asked for once"
    given = asked[0]
    assert given["run_dir"] == (tmp_path / "run").resolve()
    assert given["target"] == target.resolve()
    assert given["harness"] == cli._harness_root()
    # Named null: no environment, and nothing is measured.
    assert configured({**PARAMS, "tool_environment": None}).tool_environment is None
    assert len(asked) == 1
    # Not named at all: not a complete configuration, as for every other input of a run.
    with pytest.raises(ValidationError) as missing:
        configured({k: v for k, v in PARAMS.items() if k != "tool_environment"})
    assert missing.value.errors()[0]["loc"] == ("tool_environment",)
    with pytest.raises(RunConfigError, match="tool environment"):
        configured({**PARAMS, "tool_environment": {**named, "manifest_digest": "0" * 64}})


# -- held to the record ----------------------------------------------------------------------


def test_holding_measures_in_full_and_returns_the_scan_the_sessions_are_held_to(
    tmp_path: Path,
) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    assert hold(found, forbidden={}) == scan([Path(named["roots"][0])])


def test_holding_refuses_an_environment_that_is_not_the_recorded_one(tmp_path: Path) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    _library(named).write_text("def margin(): return 2\n")
    with pytest.raises(ToolEnvironmentError, match="not the one this run recorded"):
        hold(found, forbidden={})


def test_holding_refuses_an_environment_now_in_a_forbidden_place(tmp_path: Path) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    with pytest.raises(ToolEnvironmentError, match="overlaps a session's worktree"):
        hold(found, forbidden={"a session's worktree": Path(named["roots"][0])})


def test_holding_refuses_an_environment_that_changed_while_it_was_measured(
    tmp_path: Path,
) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    library = _library(named)
    before = library.read_bytes()

    def runner(argv: Sequence[str]) -> str | None:
        # Written and written back while the full measure runs: the bytes digest as recorded,
        # and only the scans on either side of the measure can tell.
        library.write_bytes(b"def margin(): return 2\n")
        library.write_bytes(before)
        return run_program(argv)

    with pytest.raises(ToolEnvironmentError, match="changed while it was measured"):
        hold(found, forbidden={}, runner=runner)


def test_the_first_session_is_held_in_full_and_each_later_one_by_the_scan(tmp_path: Path) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    calls: list[list[str]] = []

    def runner(argv: Sequence[str]) -> str | None:
        calls.append(list(argv))
        return run_program(argv)

    first = hold_before_session(found, None, forbidden={}, runner=runner)
    assert first == scan([Path(named["roots"][0])])
    assert calls, "the first session of a process was not held to a full measure"
    asked = len(calls)
    assert hold_before_session(found, first, forbidden={}, runner=runner) == first
    assert len(calls) == asked, "a later session ran the full measure again"


@pytest.mark.parametrize("change", ["edited", "added", "removed", "same bytes written again"])
def test_any_change_since_the_first_session_refuses_the_next(tmp_path: Path, change: str) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    held = hold_before_session(found, None, forbidden={})
    library = _library(named)
    if change == "edited":
        library.write_text("def margin(): return 2\n")
    elif change == "added":
        (library.parent / "sitecustomize.py").write_text("import os\n")
    elif change == "removed":
        library.unlink()
    else:
        library.write_bytes(library.read_bytes())
    with pytest.raises(InvocationError, match="tool environment") as refused:
        hold_before_session(found, held, forbidden={})
    assert refused.value.context["roots"] == named["roots"][0]


def test_a_first_session_on_a_changed_environment_is_refused_as_an_invocation(
    tmp_path: Path,
) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    _library(named).write_text("def margin(): return 2\n")
    with pytest.raises(InvocationError, match="not the one this run recorded") as refused:
        hold_before_session(found, None, forbidden={})
    assert refused.value.context["changed"] == "manifest_digest"


# -- the dispatcher --------------------------------------------------------------------------


def _value(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


class _Rig:
    """A dispatcher whose installer is stood in for, and what it was asked."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, run_dir: Path, recorded: ToolEnvironment | None
    ) -> None:
        self.installs: list[list[str]] = []
        self.opened: list[str] = []
        self.places: list[dict[str, Path | None]] = []
        config = make_config(os_layer_absent="allow", tool_environment=recorded)
        real_run = subprocess.run

        def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
            if list(argv[1:3]) == ["hooks", "install"]:
                self.installs.append(list(argv))
                return subprocess.CompletedProcess(argv, 2, "", "stood in: no session is started")
            return real_run(argv, **kw)

        def places(**given: Path | None) -> dict[str, Path]:
            self.places.append(given)
            return {}

        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
        monkeypatch.setattr(dispatch, "empty_outbox", lambda *_a: ())
        monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
        monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
        monkeypatch.setattr(dispatch, "forbidden_places", places)
        monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: ABSENT)
        monkeypatch.setattr(
            ClaudeDispatcher, "environment", lambda _self: SimpleNamespace(system_managed=())
        )

        def open_subtask(subtask_id: str, reopen: int = 0) -> Path:
            self.opened.append(subtask_id)
            worktree = run_dir / "worktrees" / subtask_id
            worktree.mkdir(parents=True, exist_ok=True)
            return worktree

        self.run_dir = run_dir
        self.dispatcher = ClaudeDispatcher(
            config=config,
            run=SimpleNamespace(  # type: ignore[arg-type]
                open_subtask=open_subtask,
                run_dir=run_dir,
                repo=run_dir / "repo",
                subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}",
            ),
            store_root=run_dir / "store",
            install_bin=run_dir / "install" / "bin" / "physgate",
            binary="claude",
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=run_dir / "reviews",
        )
        self.request = SessionRequest(
            subtask_id="s1",
            attempt=1,
            assigned_role="electrical",
            spec_path=".physgate/specs/s1.md",
            module_dir="modules/power",
            model=config.models.roles["electrical"],
            repair_instruction=None,
            bounds=SCRIPTED_BOUNDS,
        )

    def attempt(self) -> str:
        """Dispatch one attempt; what refused it."""
        with pytest.raises(InvocationError) as refused:
            self.dispatcher.run(self.request)
        return str(refused.value)


def test_a_session_is_installed_with_each_root_of_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = _environment(tmp_path)
    store = Path(named["roots"][0]).parent / "store"
    store.mkdir()
    (store / "package.json").write_text("{}\n")
    found = measure_named({**named, "roots": [*named["roots"], str(store)]}, forbidden={})
    rig = _Rig(monkeypatch, tmp_path / "run", found)
    assert "installer refused" in rig.attempt()
    assert len(rig.installs) == 1
    argv = rig.installs[0]
    assert _value(argv, "--tool-environment-root") == [named["roots"][0], str(store)]
    # The places it may not lie in are asked for with this run's own.
    assert rig.places, "the places it may not lie in were not asked for"
    assert rig.places[0]["run_dir"] == tmp_path / "run"
    assert rig.places[0]["install"] == tmp_path / "run" / "install"


def test_a_run_that_names_no_environment_installs_no_such_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = _Rig(monkeypatch, tmp_path / "run", None)
    assert "installer refused" in rig.attempt()
    assert len(rig.installs) == 1
    argv = rig.installs[0]
    assert _value(argv, "--tool-environment-root") == []
    assert rig.places == []


def test_a_changed_environment_refuses_the_session_before_anything_of_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    rig = _Rig(monkeypatch, tmp_path / "run", found)
    assert "installer refused" in rig.attempt()
    assert (len(rig.installs), rig.opened) == (1, ["s1"])
    _library(named).write_text("def margin(): return 2\n")
    assert "tool environment changed since the run" in rig.attempt()
    # Nothing of the refused session: no worktree opened, no installer run, no session directory.
    assert (len(rig.installs), rig.opened) == (1, ["s1"])
    sessions = rig.run_dir / "sessions"
    assert len(list(sessions.iterdir())) == 1
    # And it stays refused: the run does not go on with an environment it did not record.
    assert "tool environment changed since the run" in rig.attempt()
    assert (len(rig.installs), rig.opened) == (1, ["s1"])


def test_a_resumed_run_s_first_session_is_refused_on_an_environment_changed_since_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    named = _environment(tmp_path)
    found = measure_named(named, forbidden={})
    _library(named).write_text("def margin(): return 2\n")
    rig = _Rig(monkeypatch, tmp_path / "run", found)
    assert "not the one this run recorded" in rig.attempt()
    assert (rig.installs, rig.opened) == ([], [])
    assert not (rig.run_dir / "sessions").exists()
