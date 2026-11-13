"""A tool server runs inside the session's own OS-layer policy, narrowed for a server.

The binary starts a session's tool servers itself, outside the sandbox it puts around the
session's shell commands. Each admitted server therefore runs inside a wrapper the harness
generates from the same policy: it reads nothing the session's commands may not read, nor the
series outbox at all (a long-lived server would outlast a rule naming the outbox's entries), it
writes only a directory of its own in the session's temporary directory, made empty for it, it
reaches no network, and it opens no serial device. The wrapper is ``sandbox-exec`` with a
generated profile on macOS and bubblewrap on Linux, and a server's entry names nothing else as
its command.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

import pytest

from physgate.hooks import settings
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.invocation import NO_TOOL_SERVERS, role_argv
from physgate.oslayer.containment import (
    SANDBOX_EXEC,
    ContainmentError,
    ServerLaunch,
    bwrap_args,
    contained_servers,
    seatbelt_profile,
    server_read_denied,
    wrappers,
)
from physgate.oslayer.policy import outbox_read_denial, sandbox_policy, serial_devices

SID = "5a4b3c2d-a-session"
OWN = "a1a1a1a1a1"
BWRAP = "/usr/bin/bwrap"
PLATFORMS = ("darwin", "linux")


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1" / ".physgate" / "series").mkdir(parents=True)
    (base / "run" / "sessions" / "other").mkdir(parents=True)
    (base / "run" / "sessions" / "other" / "login.txt").write_text("other\n")
    (base / "temps" / OWN).mkdir(parents=True)
    (base / "held-out").mkdir()
    monkeypatch.setattr(settings, "session_temps_root", lambda: str(base / "temps"), raising=False)
    return base


def _config(root: Path) -> SessionConfig:
    sdir = root / "run" / "sessions" / SID
    request = InstallRequest.model_validate(
        {
            "profile": "role",
            "role": "control",
            "worktree": str(root / "run" / "worktrees" / "s1"),
            "own_branch": None,
            "store_root": None,
            "state_dir": str(sdir / "state"),
            "target_dir": str(sdir / "session"),
            "claude_config_dir": str(sdir / "config"),
            "user_home": str(sdir / "home"),
            "token_ceiling": 1000,
            "sessions_root": str(root / "run" / "sessions"),
            "temp_dir": str(root / "temps" / OWN),
            "held_out": (str(root / "held-out"),),
        }
    )
    return build_config(request, installation())


def _outbox(config: SessionConfig) -> str:
    (found,) = (r.path for r in config.protected_roots if r.shell_writes == "allowed")
    return found


def _probe(root: Path) -> ServerLaunch:
    return ServerLaunch(name="probe", command="/usr/bin/python3", args=("-I", "probe.py"))


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_server_is_denied_every_read_the_session_s_commands_are_and_the_whole_outbox(
    root: Path, platform: str
) -> None:
    config = _config(root)
    outbox = _outbox(config)
    session = sandbox_policy(
        config,
        home=str(root / "run" / "sessions" / SID / "home"),
        temp_dir=str(root / "temps" / OWN),
        platform=platform,
    ).settings["sandbox"]["filesystem"]["denyRead"]
    devices = set(serial_devices(platform))
    expected = {p for p in session if p not in devices}
    expected = {p for p in expected if p != outbox_read_denial(outbox, platform)} | {outbox}
    denied = set(server_read_denied(config, platform))
    assert denied, "the server's deny list is empty"
    # The two lists are one, apart from the outbox: named whole for a server, on both platforms.
    assert {os.path.realpath(p) for p in denied} == {os.path.realpath(p) for p in expected}
    assert outbox in denied
    assert str(root / "held-out") in denied
    assert str(root / "run" / "sessions") in denied
    assert str(root / "temps") in denied
    assert not [p for p in denied if "*" in p]


def test_the_macos_profile_denies_the_network_every_write_but_its_own_and_every_denied_read(
    root: Path,
) -> None:
    server_dir = str(root / "temps" / OWN / "servers" / "probe")
    denied = (str(root / "held-out"), str(root / "temps"))
    profile = seatbelt_profile(
        read_denied=denied, server_dir=server_dir, devices=serial_devices("darwin")
    )
    lines = [line.strip() for line in profile.splitlines() if line.strip()]
    assert lines[:1] == ["(version 1)"], profile
    assert "(deny network*)" in lines
    assert "(deny file-write*)" in lines, profile
    deny_write = lines.index("(deny file-write*)")
    own_writes = [i for i, line in enumerate(lines) if line.startswith("(allow file-write*")]
    assert len(own_writes) == 1, profile
    own_write = own_writes[0]
    assert deny_write < own_write
    assert f'(subpath "{server_dir}")' in lines[own_write]
    assert '(literal "/dev/null")' in lines[own_write]
    for path in denied:
        assert any(
            line.startswith("(deny file-read*") and f'(subpath "{path}")' in line for line in lines
        ), path
    own_reads = [i for i, line in enumerate(lines) if line.startswith("(allow file-read*")]
    assert len(own_reads) == 1, profile
    own_read = own_reads[0]
    last_read_deny = max(i for i, line in enumerate(lines) if line.startswith("(deny file-read*"))
    # The last rule that matches decides: the server's own directory is opened after the denies.
    assert own_read > last_read_deny
    assert f'(subpath "{server_dir}")' in lines[own_read]
    devices = [line for line in lines if "file-read* file-write*" in line and "/dev/" in line]
    assert devices and r'#"^/dev/cu\..*$"' in devices[0] and r'#"^/dev/tty\..*$"' in devices[0]


@pytest.mark.parametrize("bad", ['/x/"y', "/x/\\y", "/x/\ny"])
def test_a_path_the_profile_cannot_quote_is_refused(root: Path, bad: str) -> None:
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(bad,), server_dir=str(root), devices=())
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(), server_dir=bad, devices=())


def test_the_linux_arguments_take_the_network_hide_each_denied_place_and_open_only_its_own(
    root: Path,
) -> None:
    server_dir = root / "temps" / OWN / "servers" / "probe"
    server_dir.mkdir(parents=True)
    secret = root / "run" / "sessions" / "other" / "login.txt"
    denied = (
        str(root / "temps"),
        str(root / "temps" / OWN / "inside"),  # beneath a hidden place: hidden with it
        str(secret),
        str(root / "not-there"),
    )
    args = bwrap_args(read_denied=denied, server_dir=str(server_dir))
    text = shlex.join(args)
    for option in ("--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc"):
        assert option in args, option
    assert "--new-session" not in args  # it stays in the session's process group
    assert text.startswith("--die-with-parent")
    assert "--ro-bind / /" in text and "--dev /dev" in text and "--proc /proc" in text
    assert f"--tmpfs {root / 'temps'}" in text
    assert f"--ro-bind /dev/null {secret}" in text
    assert str(root / "temps" / OWN / "inside") not in text
    assert str(root / "not-there") not in text
    bind = text.index(f"--bind {server_dir} {server_dir}")
    assert bind > text.index(f"--tmpfs {root / 'temps'}")
    # Each hidden place is made read-only last, after the server's directory is bound beneath it.
    assert text.index(f"--remount-ro {root / 'temps'}") > bind
    assert args[-1] != "--"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_each_server_is_named_by_its_wrapper_with_a_directory_of_its_own_made_empty(
    root: Path, platform: str
) -> None:
    config = _config(root)
    profiles = root / "run" / "sessions" / SID / "servers"
    loaded = json.loads(
        contained_servers(
            config,
            [_probe(root)],
            platform=platform,
            temp_dir=root / "temps" / OWN,
            profiles_dir=profiles,
            bwrap=BWRAP,
        )
    )
    assert list(loaded["mcpServers"]) == ["probe"], loaded
    entry = loaded["mcpServers"]["probe"]
    server_dir = root / "temps" / OWN / "servers" / "probe"
    assert server_dir.is_dir() and not any(server_dir.iterdir())
    assert entry["env"]["TMPDIR"] == str(server_dir)
    if platform == "darwin":
        assert entry["command"] == SANDBOX_EXEC
        assert entry["args"][:2] == ["-f", str(profiles / "probe.sb")]
        assert (profiles / "probe.sb").read_text().startswith("(version 1)")
    else:
        assert entry["command"] == BWRAP
        assert "--unshare-net" in entry["args"]
    assert entry["args"][-3:] == ["/usr/bin/python3", "-I", "probe.py"]
    assert entry["command"] in wrappers(platform, BWRAP)


def test_a_server_directory_already_there_is_refused(root: Path) -> None:
    (root / "temps" / OWN / "servers" / "probe").mkdir(parents=True)
    with pytest.raises(ContainmentError):
        contained_servers(
            _config(root),
            [_probe(root)],
            platform="darwin",
            temp_dir=root / "temps" / OWN,
            profiles_dir=root / "profiles",
            bwrap=None,
        )


def test_linux_without_bubblewrap_offers_no_server(root: Path) -> None:
    with pytest.raises(ContainmentError):
        contained_servers(
            _config(root),
            [_probe(root)],
            platform="linux",
            temp_dir=root / "temps" / OWN,
            profiles_dir=root / "profiles",
            bwrap=None,
        )


def test_two_servers_of_one_name_are_refused(root: Path) -> None:
    with pytest.raises(ContainmentError):
        contained_servers(
            _config(root),
            [_probe(root), _probe(root)],
            platform="darwin",
            temp_dir=root / "temps" / OWN,
            profiles_dir=root / "profiles",
            bwrap=None,
        )


def test_a_launch_names_its_program_by_absolute_path() -> None:
    with pytest.raises(ValueError, match="command"):
        ServerLaunch(name="probe", command="python3")
    with pytest.raises(ValueError, match="name"):
        ServerLaunch(name="../probe", command="/usr/bin/python3")


def _role(tool_servers: str) -> list[str]:
    return role_argv(
        "/bin/claude",
        prompt="p",
        spawn_args=("--setting-sources", ""),
        model="claude-opus-5-5",
        session_id="abc",
        max_turns=3,
        effort="high",
        thinking_display="summarized",
        tool_servers=tool_servers,
        wrappers=(SANDBOX_EXEC,),
    )


def test_a_role_session_carries_the_contained_configuration_it_is_given() -> None:
    config = json.dumps({"mcpServers": {"probe": {"command": SANDBOX_EXEC, "args": ["-f", "p"]}}})
    argv = _role(config)
    assert argv[argv.index("--mcp-config") + 1] == config
    assert "--strict-mcp-config" in argv
    argv = _role(NO_TOOL_SERVERS)
    assert argv[argv.index("--mcp-config") + 1] == NO_TOOL_SERVERS


@pytest.mark.parametrize(
    "servers",
    [
        {"probe": {"command": "/usr/bin/python3", "args": ["probe.py"]}},
        {"probe": {"command": "python3"}},
        {"probe": {"type": "http", "url": "http://127.0.0.1:1"}},
        {"probe": {"args": ["-f", "p"]}},
    ],
)
def test_a_server_not_named_by_its_wrapper_is_refused_at_the_spawn(
    servers: dict[str, object],
) -> None:
    with pytest.raises(InvocationError):
        _role(json.dumps({"mcpServers": servers}))
