"""The raw arm computes and builds with the harness run's tools, as a role session does (ARCH-143).

Both arms are given the identical tool environment and tool-server records: the raw session
is installed with each root of the environment (read and run, written by none), finds the
environment's programs first on its search path, is told the environment for its records, is
held to the environment before it starts and after it ends, and is offered the raw agent's
servers where the OS layer contains them. What it was given is in its pins, which the
comparison holds to the harness run's. A stand-in environment and installer throughout; no
real binary runs.
"""

from __future__ import annotations

import dataclasses
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from task_fixtures import own_task
from test_the_raw_arm_is_a_role_session_on_the_brief_held_to_the_harness_s_budget import (
    _install_argv,
)
from test_the_raw_arm_is_a_role_session_on_the_brief_held_to_the_harness_s_budget import (
    _setup as _bare_setup,
)
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _script
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import (
    _setup as _session_setup,
)

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task
from physgate.hooks.settings import session_tool_search
from physgate.orchestrator.invocation import MAX_SERVER_OUTPUT_TOKENS, NO_TOOL_SERVERS
from physgate.orchestrator.run_config import ToolServers, harness_root
from physgate.orchestrator.tool_environment import measure_named
from physgate.oslayer.probe import Absent, Present
from physgate.series.writer import ENVIRONMENT_VARIABLE
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.register import register_sha256
from physgate.toolenv.session import SESSION_FILE

TASK = parse_task(json.dumps(own_task()).encode())
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
TEMP = Path("/tmp/pg-0123456789ab")
#: What the stand-in environment's own file wires a session to.
WIRING = {
    "programs": {"avr-size": "bin/avr-gcc"},
    "directories": ["core"],
    "links": {"core/lib": "lib"},
    "variables": {"BUILD_CORE_DIR": "{temp}/core", "BUILD_QUIET": "yes"},
}


def _program(path: Path, says: str) -> None:
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{says}'\n")
    path.chmod(0o755)


def _environment(tmp_path: Path) -> dict[str, Any]:
    """A stand-in environment's tree, with the register's servers' program, and its three names."""
    root = Path(os.path.realpath(tmp_path)) / "tools" / "env"
    (root / "bin").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "lib" / "control").mkdir(parents=True)
    answer = {
        "version": "3.12.9",
        "prefix": str(root),
        "base_prefix": str(root),
        "physgate": False,
        "distributions": [["control", "0.10.1"]],
    }
    _program(root / "bin" / "python3", json.dumps(answer))
    _program(root / "bin" / "avr-gcc", "avr-gcc (GCC) 7.3.0")
    _program(root / "venv" / "bin" / "python", "a server's interpreter")
    (root / "lib" / "control" / "margins.py").write_text("def margin(): return 1\n")
    (root / SESSION_FILE).write_text(json.dumps(WIRING))
    # Provisioned an hour before, as a real one is, so a same-size edit within the clock's tick
    # is not what a row below tests.
    an_hour_ago = time.time() - 3600
    for path in (root, *root.rglob("*")):
        os.utime(path, (an_hour_ago, an_hour_ago), follow_symlinks=False)
    return {
        "interpreter": str(root / "bin" / "python3"),
        "roots": [str(root)],
        "native": {"avr-gcc": str(root / "bin" / "avr-gcc")},
    }


def _measured(tmp_path: Path) -> ToolEnvironment:
    return measure_named(_environment(tmp_path), forbidden={})


def _servers(**changes: Any) -> ToolServers:
    fields: dict[str, Any] = {
        "profiles": {"role": ("control", "mujoco"), "baseline": ("control",)},
        "max_output_tokens": MAX_SERVER_OUTPUT_TOKENS,
        "register_sha256": register_sha256(),
    }
    fields.update(changes)
    return ToolServers(**fields)


def _value(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]


# -- installed with the environment's roots and the raw agent's servers --------------------------


def test_the_raw_session_is_installed_with_each_root_of_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _measured(tmp_path)
    setup = _bare_setup(tmp_path, tool_environment=recorded, os_layer=PRESENT)
    argv = _install_argv(tmp_path, monkeypatch, setup, TEMP)
    assert _value(argv, "--tool-environment-root") == list(recorded.roots)
    # Its programs are linked in the session's own directory, which the layer opens again.
    sdir = Path(_value(argv, "--target")[0]).parent
    assert _value(argv, "--os-layer-readable") == [str(sdir / "bin")]
    bare = _install_argv(tmp_path, monkeypatch, _bare_setup(tmp_path, os_layer=PRESENT), TEMP)
    assert _value(bare, "--tool-environment-root") == []
    assert _value(bare, "--os-layer-readable") == []


def test_the_raw_session_is_offered_the_raw_agent_s_servers_where_the_layer_contains_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = _bare_setup(
        tmp_path, tool_environment=_measured(tmp_path), tool_servers=_servers(), os_layer=PRESENT
    )
    argv = _install_argv(tmp_path, monkeypatch, setup, TEMP)
    # The raw agent's set, as the harness run recorded it; never the role profile's.
    assert _value(argv, "--tool-server") == ["control"]
    absent = dataclasses.replace(setup, os_layer=Absent(reason="test", no_os_protection=False))
    assert _value(_install_argv(tmp_path, monkeypatch, absent, None), "--tool-server") == []


def test_tool_servers_without_a_tool_environment_are_refused(tmp_path: Path) -> None:
    with pytest.raises(raw.RawArmError, match="tool environment"):
        _bare_setup(tmp_path, tool_servers=_servers())


# -- what it was given is in its pins ------------------------------------------------------------


def test_the_raw_arm_records_the_tools_it_was_given(tmp_path: Path) -> None:
    recorded, servers = _measured(tmp_path), _servers()
    pins = raw.pins(TASK, _bare_setup(tmp_path, tool_environment=recorded, tool_servers=servers))
    assert pins.get("tool_environment") == recorded.model_dump(mode="json")
    assert pins.get("tool_servers") == servers.model_dump(mode="json")
    # Read from the deny lists its settings were installed from, as a run records it.
    assert pins.get("tool_search") == session_tool_search()
    bare = raw.pins(TASK, _bare_setup(tmp_path))
    assert (bare.get("tool_environment"), bare.get("tool_servers")) == (None, None)
    assert "tool_environment" in bare and "tool_servers" in bare


# -- a session on the environment, end to end with a stand-in binary ----------------------------


#: A session that writes what it was given into its worktree, then ends.
TELLS = 'env > env.txt\necho \'{"type":"result","subtype":"success","usage":{}}\'\n'


def _tooled_setup(
    tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch, **changes: Any
) -> tuple[raw.RawSetup, list[dict[str, Any]]]:
    """A raw setup on the stand-in environment; the places it was told it may not lie in."""
    asked: list[dict[str, Any]] = []

    def places(**given: Any) -> dict[str, Path]:
        asked.append(given)
        return {}

    monkeypatch.setattr(raw, "forbidden_places", places)
    setup = dataclasses.replace(
        _session_setup(tmp_path, _script(tmp_path / "claude", body)),
        tool_environment=_measured(tmp_path),
        **changes,
    )
    return setup, asked


def test_the_session_finds_the_environment_s_programs_first_and_is_told_it_for_its_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, asked = _tooled_setup(tmp_path, TELLS, monkeypatch)
    recorded = setup.tool_environment
    assert recorded is not None
    work = tmp_path / "work"
    raw.run_raw(TASK, setup, work, cap=10**9)
    lines = (work / "worktree" / "env.txt").read_text().splitlines()
    env = dict(line.split("=", 1) for line in lines if "=" in line)
    sdir = work / "session"
    assert env["PATH"].split(":")[0] == str(sdir / "bin")
    assert (sdir / "bin" / "python3").read_text() == (
        f'#!/bin/sh\nexec {recorded.interpreter} "$@"\n'
    )
    assert env["BUILD_QUIET"] == "yes"
    assert json.loads(env[ENVIRONMENT_VARIABLE]) == {
        "roots": list(recorded.roots),
        "sha256": recorded.manifest_digest,
    }
    # Held before the session to the places a run's environment may not lie in, its own among them.
    assert asked == [
        {
            "harness": harness_root(),
            "install": setup.install_bin.parent.parent,
            "run_dir": work,
            "target": None,
        }
    ]
    assert json.loads((tmp_path / "raw.json").read_text())["pins"]["tool_environment"] == (
        recorded.model_dump(mode="json")
    )


def test_a_changed_environment_refuses_the_session_before_anything_of_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, _ = _tooled_setup(tmp_path, "touch ran\n" + TELLS, monkeypatch)
    assert setup.tool_environment is not None
    library = Path(setup.tool_environment.roots[0]) / "lib" / "control" / "margins.py"
    library.write_text("def margin(): return 2\n")
    work = tmp_path / "work"
    with pytest.raises(raw.RawArmError, match="no session is started"):
        raw.run_raw(TASK, setup, work, cap=10**9)
    assert not work.exists()


def test_a_change_made_while_the_session_ran_refuses_its_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(os.path.realpath(tmp_path)) / "tools" / "env"
    writes = f"printf '# more\\n' >> {root}/lib/control/margins.py\n" + TELLS
    setup, _ = _tooled_setup(tmp_path, writes, monkeypatch)
    work = tmp_path / "work"
    with pytest.raises(raw.RawArmError, match="changed while the session ran"):
        raw.run_raw(TASK, setup, work, cap=10**9)
    assert (work / "worktree" / "env.txt").exists(), "the session did not run"
    assert not (tmp_path / "raw.json").exists()


def test_servers_from_a_register_other_than_the_recorded_one_start_no_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, _ = _tooled_setup(
        tmp_path, TELLS, monkeypatch, tool_servers=_servers(register_sha256="0" * 64)
    )
    work = tmp_path / "work"
    with pytest.raises(raw.RawArmError, match="register differs"):
        raw.run_raw(TASK, setup, work, cap=10**9)
    assert not work.exists()


# -- the servers are contained as a role session's are -------------------------------------------


def test_the_raw_agent_s_servers_start_from_the_environment_and_only_inside_the_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = _measured(tmp_path)
    given: list[tuple[Any, ...]] = []

    def contained(config: Any, servers: Any, **kw: Any) -> str:  # noqa: ANN401
        given.append((config, tuple(servers), kw))
        return '{"mcpServers":{"control":{}}}'

    monkeypatch.setattr(raw, "contained_servers", contained)
    monkeypatch.setattr(raw, "wrappers", lambda platform, bwrap: ("/usr/bin/sandbox-exec",))
    monkeypatch.setattr(
        raw, "SessionConfig", SimpleNamespace(model_validate_json=lambda _b: "config")
    )
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    setup = _bare_setup(
        tmp_path, tool_environment=recorded, tool_servers=_servers(), os_layer=PRESENT
    )
    launches = raw.server_launches_for(setup)
    root = recorded.roots[0].rstrip("/")
    assert [(s.name, s.command) for s in launches] == [("control", f"{root}/venv/bin/python")]
    assert all(s.read_roots == recorded.roots for s in launches)
    env = {"PATH": "/usr/bin:/bin"}
    found = raw.contained_servers_for(
        setup, launches, config_file, tmp_path / "s", tmp_path / "temp", env
    )
    assert found == ('{"mcpServers":{"control":{}}}', ("/usr/bin/sandbox-exec",))
    assert [server.name for server in given[0][1]] == ["control"]
    assert given[0][2]["temp_dir"] == tmp_path / "temp"
    assert given[0][2]["profiles_dir"] == tmp_path / "s" / "servers"
    absent = dataclasses.replace(setup, os_layer=Absent(reason="test", no_os_protection=False))
    assert raw.contained_servers_for(
        absent, launches, config_file, tmp_path / "s", tmp_path / "temp", env
    ) == (NO_TOOL_SERVERS, ())
    assert len(given) == 1


def test_the_raw_session_is_spawned_with_the_servers_it_was_offered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup, _ = _tooled_setup(tmp_path, TELLS, monkeypatch, tool_servers=_servers())
    seen: list[dict[str, Any]] = []
    real = raw.role_argv

    def spy(*a: Any, **k: Any) -> list[str]:  # noqa: ANN401
        seen.append(k)
        # The stand-in binary runs outside any wrapper, so it is spawned with none.
        return real(*a, **{**k, "tool_servers": NO_TOOL_SERVERS, "wrappers": ()})

    offered = ('{"mcpServers":{"control":{}}}', ("/usr/bin/sandbox-exec",))
    monkeypatch.setattr(raw, "role_argv", spy)
    monkeypatch.setattr(raw, "contained_servers_for", lambda *_a: offered)
    raw.run_raw(TASK, setup, tmp_path / "work", cap=10**9)
    assert len(seen) == 1
    assert (seen[0].get("tool_servers"), seen[0].get("wrappers")) == offered
