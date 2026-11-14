"""The tool-server register: the closed list, the denied set, and each server's start.

The register names two servers, our own control and MuJoCo servers, and, for each, the tools a
session may call and every argument each may be given. A session's closed list names exactly
``mcp__<server>__<tool>`` for the admitted tools of the servers it is offered; a role session
and the raw agent may be offered the identical set, a reviewer and the orchestrator none. Each
server starts from the run's recorded environment by absolute path, reading and running its
roots. The tools that reach a board are refused by name, apart from any server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks import settings
from physgate.hooks.config import Profile
from physgate.hooks.settings import (
    PROFILE_SERVERS,
    PROFILE_TOOLS,
    InstallRequest,
    build_config,
)
from physgate.hooks.settings import current_installation as installation
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.register import (
    REGISTER_FILE,
    Register,
    ServerEntry,
    launches,
    load_register,
    server_tools,
    tool_name,
)

OWN = "pgs-0123456789abcdef"

CONTROL = {"frequency_response", "margins", "poles_zeros", "step_response"}
MUJOCO = {"load_model", "model_info", "reset", "state", "step"}
STORES = ("platforms", "packages", "lib")


# ---- the register ----------------------------------------------------------------------------


def test_the_register_admits_exactly_the_ruled_tools_of_two_servers() -> None:
    register = load_register()
    assert set(register.servers) == {"control", "mujoco"}
    assert set(register.servers["control"].tools) == CONTROL
    assert set(register.servers["mujoco"].tools) == MUJOCO


#: Words of a build server's tool's name (its parts between underscores, without a plural ``s``)
#: that say it reaches a board, a port or a probe.
HARDWARE_WORDS = frozenset({
    "upload", "flash", "monitor", "serial", "device", "debug", "port", "ota", "target",
    "coredump", "test", "power", "memory", "board",
})  # fmt: skip


def _words(name: str) -> set[str]:
    return {part.removesuffix("s") for part in name.split("_")}


def test_every_refused_tool_is_named_as_reaching_a_board_and_no_admitted_tool_is() -> None:
    register = load_register()
    refused = set(register.refused_tools)
    assert refused, "the register refuses no tool by name"
    assert {name for name in refused if not _words(name) & HARDWARE_WORDS} == set()
    admitted = {tool for entry in register.servers.values() for tool in entry.tools}
    assert {name for name in admitted if _words(name) & HARDWARE_WORDS} == set()


def test_only_our_own_mujoco_server_reads_a_relative_path_from_the_worktree() -> None:
    register = load_register()
    assert register.servers["mujoco"].relative_paths == "worktree"
    assert "{worktree}" in register.servers["mujoco"].args
    assert register.servers["control"].relative_paths == "refused"
    kinds = {
        (server, tool, arg): kind
        for server, entry in register.servers.items()
        for tool, args in entry.tools.items()
        for arg, kind in args.items()
    }
    paths = {key for key, kind in kinds.items() if kind.endswith("_path")}
    # Our own servers take no path but MuJoCo's model.
    assert paths == {("mujoco", "load_model", "path")}


def _entry(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    base: dict[str, Any] = {
        "command": "{root}/bin/server",
        "args": [],
        "relative_paths": "refused",
        "tools": {"run": {}},
    }
    return {**base, **changes}


@pytest.mark.parametrize(
    "changes",
    [
        {"denied": ["run"]},
        {"environment": {"PATH": "/x"}},
        {"environment": {"LD_PRELOAD": "/x"}},
        {"environment": {"DYLD_INSERT_LIBRARIES": "/x"}},
        {"environment": {"PYTHONPATH": "{worktree}"}},
        {"environment": {"NODE_OPTIONS": "--require /x"}},
        {"environment": {"TMPDIR": "{server_dir}"}},
        {"environment": {"MPLCONFIGDIR": "{server_dir}"}},
        {"environment": {"A": "{temp}/x"}},
        {"command": "/usr/bin/python3"},
        {"command": "{worktree}/server"},
        {"args": ["{server_dir}"]},
        {"links": {"core/store": "{root}/store"}},
        {"directories": ["core"], "links": {"core/store": "/elsewhere"}},
        {"directories": ["core"], "links": {"core/store": "{root}/../store"}},
        {"directories": ["../core"]},
        {"tools": {"run": {"x": "file"}}},
    ],
)
def test_an_entry_that_could_reach_past_its_server_is_refused(changes: dict[str, Any]) -> None:
    # Read as the register file is, from JSON: the entry without the change is one.
    ServerEntry.model_validate_json(json.dumps(_entry()))
    with pytest.raises(ValueError):  # noqa: PT011 - pydantic's, whichever rule refuses
        ServerEntry.model_validate_json(json.dumps(_entry(**changes)))


def test_a_register_that_is_not_one_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "register.json"
    bad.write_text(json.dumps({"servers": {"Two__names": _entry()}}))
    with pytest.raises(ToolEnvironmentError, match="register"):
        load_register(bad)
    bad.write_text("{")
    with pytest.raises(ToolEnvironmentError, match="register"):
        load_register(bad)


# ---- the closed list -------------------------------------------------------------------------


def test_a_server_s_tools_are_named_as_the_closed_list_names_them() -> None:
    register = load_register()
    assert tool_name("control", "margins") == "mcp__control__margins"
    named = server_tools(register, ["control", "mujoco"])
    assert set(named) == {tool_name("control", t) for t in CONTROL} | {
        tool_name("mujoco", t) for t in MUJOCO
    }
    assert server_tools(register, []) == ()
    with pytest.raises(ToolEnvironmentError, match="register"):
        server_tools(register, ["nosuch"])


def test_a_role_session_and_the_raw_agent_may_be_offered_every_server_and_no_one_else_any() -> None:
    every = tuple(sorted(load_register().servers))
    assert PROFILE_SERVERS["role"] == every
    assert PROFILE_SERVERS["baseline"] == PROFILE_SERVERS["role"]
    assert PROFILE_SERVERS["reviewer"] == ()
    assert PROFILE_SERVERS["orchestrator"] == ()
    # No profile's base list names a server tool: a session gets them only with its servers.
    for tools in PROFILE_TOOLS.values():
        assert not [t for t in tools if t.startswith("mcp__")], tools


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1").mkdir(parents=True)
    (base / "run" / "sessions").mkdir(parents=True)
    (base / "temps" / OWN).mkdir(parents=True)
    monkeypatch.setattr(settings, "session_temps_root", lambda: str(base / "temps"), raising=False)
    return base


def _request(root: Path, profile: str, servers: tuple[str, ...]) -> InstallRequest:
    sdir = root / "run" / "sessions" / "s"
    fields: dict[str, Any] = {
        "profile": profile,
        "role": "control" if profile == "role" else None,
        "worktree": str(root / "run" / "worktrees" / "s1"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "tool_servers": servers,
    }
    if profile in ("role", "baseline", "reviewer"):
        fields["temp_dir"] = str(root / "temps" / OWN)
    if profile in ("role", "baseline"):
        fields["sessions_root"] = str(root / "run" / "sessions")
    if profile == "reviewer":
        fields["read_roots"] = (str(root / "run" / "worktrees" / "s1"),)
    return InstallRequest.model_validate(fields)


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_session_offered_servers_runs_on_its_base_list_and_their_admitted_tools(
    root: Path, profile: Profile
) -> None:
    register = load_register()
    every = tuple(sorted(register.servers))
    config = build_config(_request(root, profile, every), installation())
    expected = set(PROFILE_TOOLS[profile]) | set(server_tools(register, every))
    assert set(config.tools_allowed) == expected
    assert len(config.tools_allowed) == len(PROFILE_TOOLS[profile]) + len(CONTROL) + len(MUJOCO)
    # Every server tool on the list is one the register admits.
    admitted = {tool_name(s, t) for s, e in register.servers.items() for t in e.tools}
    assert {t for t in config.tools_allowed if t.startswith("mcp__")} <= admitted
    # Offered none, the list is the base list as it always was.
    plain = build_config(_request(root, profile, ()), installation())
    assert set(plain.tools_allowed) == set(PROFILE_TOOLS[profile])


@pytest.mark.parametrize(
    ("profile", "servers"),
    [
        ("role", ("nosuch",)),
        ("role", ("control", "control")),
        ("reviewer", ("control",)),
        ("orchestrator", ("control",)),
        ("role", ("platformio",)),
    ],
)
def test_a_server_the_profile_may_not_be_offered_is_refused_at_install(
    root: Path, profile: str, servers: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError, match="tool server"):
        build_config(_request(root, profile, servers), installation())


# ---- how each server starts ------------------------------------------------------------------


#: A build server's entry, shaped as a firmware build server's would be: its own core directory
#: linked into the environment's read-only store, its build tool found by name in the environment.
BUILDER = ServerEntry.model_validate_json(
    json.dumps({
        "command": "{root}/builder/bin/builder",
        "args": ["{root}/builder/server.js"],
        "relative_paths": "refused",
        "environment": {
            "BUILDER_POLICY": "{root}/builder/policy.yaml",
            "BUILDER_CORE_DIR": "{server_dir}/core",
            "BUILDER_TELEMETRY": "no",
        },
        "search_path": ["{root}/venv/bin"],
        "directories": ["core", "state"],
        "links": {f"core/{store}": f"{{root}}/platformio/{store}" for store in STORES},
        "tools": {"build": {"projectDir": "write_path"}},
    })
)  # fmt: skip


def _with_builder() -> Register:
    real = load_register()
    return Register(servers={**real.servers, "builder": BUILDER}, refused_tools=real.refused_tools)


def _environment(tmp_path: Path, *, with_builder: bool = True) -> tuple[Path, ToolEnvironment]:
    root = tmp_path.resolve() / "env"
    for relative in (
        "venv/bin/python",
        "servers/control_server.py",
        "servers/mujoco_server.py",
        "builder/server.js",
        "builder/policy.yaml",
        *(("builder/bin/builder",) if with_builder else ()),
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("")
    for store in STORES:
        (root / "platformio" / store).mkdir(parents=True)
    other = tmp_path.resolve() / "other"
    other.mkdir()
    recorded = ToolEnvironment(
        interpreter=str(root / "venv" / "bin" / "python"),
        resolved=str(root / "venv" / "bin" / "python"),
        python_version="3.12.9",
        prefix=str(root / "venv"),
        distributions=(),
        native_tools=(),
        roots=(str(other), str(root)),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )
    return root, recorded


def test_each_server_starts_by_absolute_path_from_the_root_that_holds_its_program(
    tmp_path: Path,
) -> None:
    root, recorded = _environment(tmp_path)
    found = {
        launch.name: launch
        for launch in launches(_with_builder(), ["control", "mujoco", "builder"], recorded)
    }
    assert set(found) == {"control", "mujoco", "builder"}
    control = found["control"]
    assert control.command == str(root / "venv" / "bin" / "python")
    assert control.args == ("-I", str(root / "servers" / "control_server.py"))
    # It runs and reads the recorded environment's roots, and nothing else of its own.
    assert set(control.exec_roots) == set(recorded.roots)
    assert set(control.read_roots) == set(recorded.roots)
    assert control.environment == {"MPLBACKEND": "Agg"}
    mujoco = found["mujoco"]
    assert mujoco.args == ("-I", str(root / "servers" / "mujoco_server.py"), "--root", "{worktree}")
    builder = found["builder"]
    assert builder.command == str(root / "builder" / "bin" / "builder")
    assert builder.args == (str(root / "builder" / "server.js"),)
    assert builder.environment["BUILDER_POLICY"] == str(root / "builder" / "policy.yaml")
    assert builder.environment["BUILDER_CORE_DIR"] == "{server_dir}/core"
    assert builder.environment["BUILDER_TELEMETRY"] == "no"
    assert builder.directories == ("core", "state")
    # It runs its build tool by name, from the environment and nowhere else.
    assert builder.search_path == (str(root / "venv" / "bin"),)
    assert control.search_path == ()
    assert builder.links == {f"core/{store}": str(root / "platformio" / store) for store in STORES}
    assert not any("{root}" in value for value in json.dumps(builder.model_dump()).split('"'))
    # Only the servers asked for.
    assert [launch.name for launch in launches(load_register(), ["mujoco"], recorded)] == ["mujoco"]


def test_a_server_whose_program_no_root_holds_is_refused(tmp_path: Path) -> None:
    _, recorded = _environment(tmp_path, with_builder=False)
    with pytest.raises(ToolEnvironmentError, match="builder"):
        launches(_with_builder(), ["builder"], recorded)
    with pytest.raises(ToolEnvironmentError, match="register"):
        launches(load_register(), ["nosuch"], recorded)


def test_a_server_whose_program_two_roots_hold_is_refused(tmp_path: Path) -> None:
    root, recorded = _environment(tmp_path)
    twin = Path(recorded.roots[0]) / "venv" / "bin" / "python"
    twin.parent.mkdir(parents=True)
    twin.write_text("")
    with pytest.raises(ToolEnvironmentError, match="control"):
        launches(load_register(), ["control"], recorded)
    assert root.is_dir()


def test_the_register_file_is_the_one_the_hooks_read() -> None:
    from physgate.hooks import server_arguments

    assert Path(server_arguments.REGISTER_FILE).resolve() == REGISTER_FILE.resolve()
    assert isinstance(load_register(), Register)
