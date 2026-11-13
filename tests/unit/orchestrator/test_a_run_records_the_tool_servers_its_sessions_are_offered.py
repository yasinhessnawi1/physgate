"""A run that names a tool environment records the tool servers its sessions are offered.

The record names the servers per profile, the bound on one answer of a server
(``MAX_MCP_OUTPUT_TOKENS``) and the register's digest, so a run is reproduced with the same tools.
A run continued on another register, or another bound, is refused before any server starts; a
run that names no environment records none, and its record's bytes are what they always were.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orch_helpers import make_config
from pydantic import ValidationError

from physgate.orchestrator.exceptions import RunConfigError
from physgate.orchestrator.invocation import MAX_SERVER_OUTPUT_TOKENS
from physgate.orchestrator.run_config import ToolServers, load_run_config, write_run_config
from physgate.orchestrator.tool_environment import recorded_servers, server_launches
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.register import load_register, register_sha256

EVERY = ("control", "mujoco", "platformio")


def _environment(tmp_path: Path) -> ToolEnvironment:
    root = tmp_path.resolve() / "env"
    for relative in (
        "venv/bin/python",
        "node/bin/node",
        "servers/control_server.py",
        "servers/mujoco_server.py",
        "platformio-server/node_modules/platformio-mcp/build/cli.js",
        "platformio-server/policy.yaml",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text("")
    for store in ("platforms", "packages", "lib"):
        (root / "platformio" / store).mkdir(parents=True)
    return ToolEnvironment(
        interpreter=str(root / "venv" / "bin" / "python"),
        resolved=str(root / "venv" / "bin" / "python"),
        python_version="3.12.9",
        prefix=str(root / "venv"),
        distributions=(),
        native_tools=(),
        roots=(str(root),),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


def test_what_is_recorded_is_the_register_s_set_per_profile_its_bound_and_its_digest() -> None:
    recorded = recorded_servers()
    assert isinstance(recorded, ToolServers)
    assert recorded.profiles == {"role": EVERY, "baseline": EVERY}
    assert tuple(sorted(load_register().servers)) == EVERY
    assert recorded.max_output_tokens == MAX_SERVER_OUTPUT_TOKENS == 25_000
    assert recorded.register_sha256 == register_sha256()


def test_a_run_that_names_servers_without_an_environment_is_refused() -> None:
    with pytest.raises(ValidationError, match="tool environment"):
        make_config(tool_servers=recorded_servers())


def test_the_record_reads_back_and_a_run_naming_none_keeps_its_bytes(tmp_path: Path) -> None:
    plain = make_config()
    assert b"tool_servers" not in plain.canonical_bytes()
    config = make_config(
        tool_environment=_environment(tmp_path),
        tool_servers=recorded_servers(),
    )
    assert b'"tool_servers"' in config.canonical_bytes()
    path = tmp_path / "run.json"
    write_run_config(path, config)
    assert load_run_config(path) == config


def test_the_role_sessions_servers_start_from_the_record_and_the_register(tmp_path: Path) -> None:
    config = make_config(
        tool_environment=_environment(tmp_path),
        tool_servers=recorded_servers(),
    )
    assert [launch.name for launch in server_launches(config)] == list(EVERY)
    # A run that names no environment offers none.
    assert server_launches(make_config()) == ()


def test_a_run_continued_on_another_register_or_bound_starts_no_server(tmp_path: Path) -> None:
    recorded = recorded_servers()
    environment = _environment(tmp_path)
    for changed in ({"register_sha256": "0" * 64}, {"max_output_tokens": 1000}):
        config = make_config(
            tool_environment=environment,
            tool_servers=ToolServers.model_validate({**recorded.model_dump(), **changed}),
        )
        with pytest.raises(RunConfigError, match="tool server"):
            server_launches(config)


def test_a_run_whose_role_set_names_a_server_the_register_cannot_start_is_refused(
    tmp_path: Path,
) -> None:
    environment = _environment(tmp_path)
    (Path(environment.roots[0]) / "node" / "bin" / "node").unlink()
    config = make_config(
        tool_environment=environment,
        tool_servers=recorded_servers(),
    )
    with pytest.raises(RunConfigError, match="platformio"):
        server_launches(config)


@pytest.mark.parametrize("command", ["run", "resume"])
def test_the_command_gives_the_dispatcher_the_launches_from_the_run_s_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from test_a_role_session_runs_only_inside_the_os_layer_unless_allowed import (
        PRESENT,
        _recorded,
        _through_the_command,
    )

    from physgate.orchestrator import cli
    from physgate.orchestrator.dispatch import ClaudeDispatcher
    from physgate.oslayer.containment import ServerLaunch

    launch = ServerLaunch(name="control", command="/usr/bin/python3")
    asked: list[object] = []
    given: list[object] = []

    def launches(config: object) -> tuple[ServerLaunch, ...]:
        asked.append(config)
        return (launch,)

    built = ClaudeDispatcher.__init__

    def init(self: ClaudeDispatcher, *args: object, **kwargs: object) -> None:
        given.append(kwargs.get("tool_servers", ()))
        built(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "server_launches", launches)
    monkeypatch.setattr(ClaudeDispatcher, "__init__", init)
    _recorded(tmp_path, os_layer_absent="refuse", os_layer=PRESENT)
    # The stand-in stops the first session as it is about to start, after the dispatcher is built.
    with pytest.raises(AssertionError, match="about to start"):
        _through_the_command(tmp_path, monkeypatch, command, PRESENT)
    assert asked, "the run's launches were never asked for"
    assert given and given[0] == (launch,), given
