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
import re
import shlex
from pathlib import Path

import pytest

from physgate.hooks import settings
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.invocation import NO_TOOL_SERVERS, role_argv
from physgate.oslayer import containment
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
from physgate.oslayer.policy import board_devices, outbox_read_denial, sandbox_policy

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


def _named(program: str) -> str:
    """A program as a profile names it: as given and where it really is.

    On a runner ``/usr/bin/python3`` is a link to the versioned interpreter.
    """
    return " ".join(f'(literal "{p}")' for p in sorted({program, os.path.realpath(program)}))


def _probe(root: Path) -> ServerLaunch:
    return ServerLaunch(
        name="probe",
        command="/usr/bin/python3",
        args=("-I", "probe.py"),
        exec_roots=(str(root / "env" / "bin"),),
    )


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
    devices = set(board_devices(platform))
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
        read_denied=denied,
        server_dir=server_dir,
        devices=board_devices("darwin"),
        command="/usr/bin/python3",
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
    own_reads = [
        i for i, line in enumerate(lines) if line == f'(allow file-read* (subpath "{server_dir}"))'
    ]
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
    python = "/usr/bin/python3"
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(bad,), server_dir=str(root), devices=(), command=python)
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(), server_dir=bad, devices=(), command=python)
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(), server_dir=str(root), devices=(), command=bad)
    with pytest.raises(ContainmentError):
        seatbelt_profile(
            read_denied=(), server_dir=str(root), devices=(), command=python, exec_roots=(bad,)
        )


@pytest.mark.parametrize("bad", ['/dev/cu."))(allow default)', "/dev/cu.(x)", "cu.*", "/dev/a\\b"])
def test_a_device_pattern_the_profile_cannot_hold_is_refused(root: Path, bad: str) -> None:
    with pytest.raises(ContainmentError):
        seatbelt_profile(
            read_denied=(), server_dir=str(root), devices=(bad,), command="/usr/bin/python3"
        )


def test_a_server_that_names_no_command_is_refused(root: Path) -> None:
    with pytest.raises(ContainmentError):
        seatbelt_profile(read_denied=(), server_dir=str(root), devices=(), command="")


def test_a_path_holding_parentheses_stays_one_quoted_path(root: Path) -> None:
    # A parenthesis inside a quoted string is a character of the path, not a rule.
    odd = str(root / "a) (allow default) (b")
    profile = seatbelt_profile(
        read_denied=(odd,), server_dir=str(root / "own"), devices=(), command="/usr/bin/python3"
    )
    lines = [line.strip() for line in profile.splitlines()]
    assert f'(deny file-read* (subpath "{odd}"))' in lines, profile
    assert "(allow default)" not in lines


def test_a_denial_given_through_a_link_is_named_where_it_really_is_too(root: Path) -> None:
    # Seatbelt judges an access where it lands: a denial named only through a link (``/var``
    # on macOS) would deny nothing.
    real = root / "real" / "held-out"
    real.mkdir(parents=True)
    (root / "linked").symlink_to(root / "real")
    given = str(root / "linked" / "held-out")
    profile = seatbelt_profile(
        read_denied=(given,), server_dir=str(root / "own"), devices=(), command="/usr/bin/python3"
    )
    denials = [line for line in profile.splitlines() if line.startswith("(deny file-read*")]
    assert any(f'(subpath "{real}")' in line for line in denials), profile
    assert any(f'(subpath "{given}")' in line for line in denials), profile


def test_the_linux_arguments_take_the_network_hide_each_denied_place_and_open_only_its_own(
    root: Path,
) -> None:
    server_dir = root / "temps" / OWN / "servers" / "probe"
    server_dir.mkdir(parents=True)
    secret = root / "run" / "sessions" / "other" / "login.txt"
    (root / "temps" / "other").mkdir()
    denied = (
        str(root / "temps"),
        str(root / "temps" / OWN / "inside"),  # beneath a hidden place: hidden with it
        str(root / "temps" / "other"),  # there, beneath a hidden place: not named again
        str(secret),
        str(root / "elsewhere" / "not-there"),
    )
    (root / "elsewhere").mkdir()
    args = bwrap_args(read_denied=denied, server_dir=str(server_dir), read_roots=(str(root),))
    text = shlex.join(args)
    for option in ("--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc"):
        assert option in args, option
    assert "--new-session" not in args  # it stays in the session's process group
    assert text.startswith("--die-with-parent")
    assert "--dev /dev" in text and "--proc /proc" in text
    assert f"--tmpfs {root / 'temps'}" in text
    assert f"--ro-bind /dev/null {secret}" in text
    assert str(root / "temps" / OWN / "inside") not in text
    assert str(root / "temps" / "other") not in text
    assert str(root / "elsewhere" / "not-there") not in text
    assert f"--tmpfs {root / 'elsewhere'}" in text
    bind = text.index(f"--bind {server_dir} {server_dir}")
    assert bind > text.index(f"--tmpfs {root / 'temps'}")
    # Each hidden place is made read-only last, after the server's directory is bound beneath it.
    assert text.index(f"--remount-ro {root / 'temps'}") > bind
    # The root's own filesystem is made read-only last of all.
    assert args[-2:] == ["--remount-ro", "/"], args


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
    # Its own directory is its temporary one and matplotlib's, which warns without one.
    assert entry.get("env") == {"TMPDIR": str(server_dir), "MPLCONFIGDIR": str(server_dir)}, entry
    if platform == "darwin":
        assert entry["command"] == SANDBOX_EXEC
        assert entry["args"][:2] == ["-f", str(profiles / "probe.sb")]
        profile = (profiles / "probe.sb").read_text()
        assert profile.startswith("(version 1)")
        # The server's own command and its named roots, and nothing else, are what it runs.
        assert (
            f'(allow process-exec {_named("/usr/bin/python3")} (subpath "{root / "env" / "bin"}"))'
            in profile
        ), profile
        # Every server reads the session's worktree, less what the session may not read there.
        assert f'(subpath "{config.worktree}")' in profile, profile
        # The session's denials and the board devices reach the server's own profile.
        assert f'(deny file-read* (subpath "{_outbox(config)}"))' in profile, profile
        assert re.search(r'\(deny file-read\* file-write\* \(regex #"\^/dev/cu', profile), profile
    else:
        assert entry["command"] == BWRAP
        assert "--unshare-net" in entry["args"]
        at = entry["args"].index(config.worktree)
        assert entry["args"][at - 1 : at + 2] == ["--ro-bind", config.worktree, config.worktree]
        # The session's denials reach the server's own arguments: the outbox in its worktree.
        assert f"--tmpfs {_outbox(config)}" in shlex.join(entry["args"]), entry["args"]
    assert entry["args"][-3:] == ["/usr/bin/python3", "-I", "probe.py"]
    assert entry["command"] in wrappers(platform, BWRAP)


def test_a_command_given_through_a_link_is_run_by_both_spellings(root: Path) -> None:
    real = root / "env" / "bin" / "python3.12"
    real.parent.mkdir(parents=True)
    real.write_text("")
    real.chmod(0o755)
    link = root / "python3"
    link.symlink_to(real)
    profile = seatbelt_profile(
        read_denied=(),
        server_dir=str(root / "temps" / OWN / "servers" / "probe"),
        devices=(),
        command=str(link),
    )
    (runs,) = [line for line in profile.splitlines() if line.startswith("(allow process-exec")]
    assert f'(literal "{link}")' in runs and f'(literal "{real}")' in runs, runs


def test_a_server_directory_already_there_is_refused(root: Path) -> None:
    (root / "temps" / OWN / "servers" / "probe").mkdir(parents=True)
    with pytest.raises(ContainmentError, match="already there"):
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
    # Refused for the name itself, before the second server's directory is reached.
    with pytest.raises(ContainmentError, match="share a name"):
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
        # Named by its wrapper, yet a kind the binary does not start as a program.
        {"probe": {"type": "http", "command": SANDBOX_EXEC, "url": "http://127.0.0.1:1"}},
        {"probe": {"type": "sse", "command": SANDBOX_EXEC, "url": "http://127.0.0.1:1"}},
        {"probe": {"args": ["-f", "p"]}},
    ],
)
def test_a_server_not_named_by_its_wrapper_is_refused_at_the_spawn(
    servers: dict[str, object],
) -> None:
    with pytest.raises(InvocationError):
        _role(json.dumps({"mcpServers": servers}))


@pytest.mark.parametrize(
    "configuration",
    [
        "not json",
        json.dumps(["mcpServers"]),
        json.dumps({"servers": {}}),
        # A contained server beside a key the binary reads as more than servers.
        json.dumps({"mcpServers": {"probe": {"command": SANDBOX_EXEC}}, "other": {}}),
    ],
)
def test_a_configuration_naming_anything_but_its_servers_is_refused_at_the_spawn(
    configuration: str,
) -> None:
    with pytest.raises(InvocationError):
        _role(configuration)


#: The Mach services the sandbox runtime's own base profile (0.0.79, the OS layer's family)
#: lets a sandboxed process look up: a server is allowed no other.
RUNTIME_MACH_SERVICES = frozenset(
    {
        "com.apple.audio.systemsoundserver",
        "com.apple.distributed_notifications@Uv3",
        "com.apple.FontObjectsServer",
        "com.apple.fonts",
        "com.apple.logd",
        "com.apple.lsd.mapdb",
        "com.apple.PowerManagement.control",
        "com.apple.system.logger",
        "com.apple.system.notification_center",
        "com.apple.system.opendirectoryd.libinfo",
        "com.apple.system.opendirectoryd.membership",
        "com.apple.bsd.dirhelper",
        "com.apple.securityd.xpc",
        "com.apple.coreservices.launchservicesd",
        "com.apple.SecurityServer",
    }
)


def test_the_macos_profile_denies_by_default_and_opens_only_what_a_server_needs(
    root: Path,
) -> None:
    command = "/usr/bin/python3"
    exec_root = str(root / "env" / "bin")
    profile = seatbelt_profile(
        read_denied=(str(root / "held-out"),),
        server_dir=str(root / "own"),
        devices=board_devices("darwin"),
        command=command,
        exec_roots=(exec_root,),
    )
    lines = [line.strip() for line in profile.splitlines() if line.strip()]
    assert "(allow default)" not in lines, profile
    assert lines[1:2] == ["(deny default)"], profile
    for refused in (
        "(allow mach-register",
        "(allow ipc-posix",
        "(allow appleevent",
        "(allow lsopen",
        "(allow network",
        "(allow mach-priv",
        "(allow process-exec)",
        "(allow file-write*)",
    ):
        assert not [line for line in lines if line.startswith(refused)], (refused, profile)
    execs = [line for line in lines if line.startswith("(allow process-exec")]
    assert execs == [f'(allow process-exec {_named(command)} (subpath "{exec_root}"))'], profile
    signals = [line for line in lines if line.startswith("(allow signal")]
    assert signals == ["(allow signal (target same-sandbox))"], profile
    infos = [line for line in lines if line.startswith("(allow process-info")]
    assert infos == ["(allow process-info* (target same-sandbox))"], profile
    # The system values and the devices it may touch are named, never all of them.
    sysctls = [line for line in lines if line.startswith("(allow sysctl")]
    assert len(sysctls) == 1 and sysctls[0].startswith("(allow sysctl-read (sysctl-name "), profile
    ioctls = [line for line in lines if line.startswith("(allow file-ioctl")]
    assert ioctls == [
        '(allow file-ioctl (literal "/dev/null") (literal "/dev/zero") (literal "/dev/random") '
        '(literal "/dev/urandom") (literal "/dev/tty"))'
    ], profile
    writes = [line for line in lines if line.startswith("(allow file-write")]
    assert writes == [f'(allow file-write* (subpath "{root / "own"}") (literal "/dev/null"))'], (
        profile
    )
    looked_up = set(re.findall(r'\(global-name "([^"]+)"\)', profile))
    assert looked_up, profile
    assert looked_up <= RUNTIME_MACH_SERVICES, looked_up - RUNTIME_MACH_SERVICES
    assert "global-name-prefix" not in profile


def test_a_denied_place_absent_at_launch_is_left_out_of_its_parent_s_listing(root: Path) -> None:
    present = root / "present"
    (present / "kept").mkdir(parents=True)
    server_dir = root / "temps" / OWN / "servers" / "probe"
    server_dir.mkdir(parents=True)
    denied = (str(root / "absent" / "deeper"), str(present / "missing"), str(root / "temps"))
    args = bwrap_args(read_denied=denied, server_dir=str(server_dir), read_roots=(str(root),))
    text = shlex.join(args)
    # Nothing is bound whole: the root is built from the entries it has at launch.
    assert "--ro-bind / /" not in text, text
    assert "--ro-bind /usr /usr" in text, text
    # Each absent place's nearest existing parent is rebuilt from the entries it has now, so a
    # name made there later is not there inside.
    for parent, kept in ((present, present / "kept"), (root, present)):
        assert f"--tmpfs {parent}" in text, parent
        assert f"--ro-bind {kept} {kept}" in text, kept
        assert f"--remount-ro {parent}" in text, parent
    assert str(root / "absent") not in text
    # A denied place the rebuilt parent holds is left out of its listing, not bound.
    assert f"--ro-bind {root / 'temps'} " not in text, text
    assert str(present / "missing") not in text
    assert "--remount-ro /" in text


#: What a server's root may hold on Linux beyond its own roots: the system's libraries and
#: programs, and the loader's and the clock's files.
LINUX_LISTED = (
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/localtime",
    "/etc/passwd",
    "/etc/group",
    "/etc/nsswitch.conf",
)


def _bound(args: list[str]) -> list[str]:
    """Every place the arguments put into the server's root, by where it lands."""
    found: list[str] = []
    for i, word in enumerate(args):
        if word in ("--ro-bind", "--bind", "--symlink"):
            found.append(args[i + 2])
    return found


def test_the_linux_root_holds_only_the_listed_places(root: Path) -> None:
    worktree = root / "run" / "worktrees" / "s1"
    env = root / "env"
    (env / "bin").mkdir(parents=True)
    own = root / "temps" / OWN / "servers" / "probe"
    own.mkdir(parents=True)
    args = bwrap_args(
        read_denied=(str(worktree / ".physgate" / "series"),),
        server_dir=str(own),
        read_roots=(str(worktree), str(env)),
    )
    allowed = (*LINUX_LISTED, str(worktree), str(env), str(own))
    bound = _bound(args)
    assert bound, args
    stray = [p for p in bound if not any(p == a or p.startswith(a + "/") for a in allowed)]
    assert stray == [], stray
    for socket_place in ("/run", "/var/run", "/tmp", "/var", "/home", "/Users", "/private"):
        assert socket_place not in bound, socket_place
    assert str(worktree) in bound and str(env) in bound
    assert "--ro-bind / /" not in shlex.join(args)


def test_the_macos_profile_reads_only_the_listed_places(root: Path) -> None:
    worktree = str(root / "run" / "worktrees" / "s1")
    env = str(root / "env")
    profile = seatbelt_profile(
        read_denied=(),
        server_dir=str(root / "own"),
        devices=(),
        command="/usr/bin/python3",
        read_roots=(worktree, env),
    )
    lines = [line.strip() for line in profile.splitlines()]
    assert "(allow file-read*)" not in lines, profile
    assert "(allow file-read-metadata)" in lines, profile
    reads = [line for line in lines if line.startswith("(allow file-read*")]
    assert reads, profile
    # The root's own listing, never what lies beneath it: the loader reads it as a program starts.
    assert '(subpath "/")' not in profile
    places = [
        p
        for line in reads
        for p in re.findall(r'\((?:subpath|literal) "([^"]+)"\)', line)
        if p != "/"
    ]
    listed = ("/System", "/usr", "/bin", "/sbin", "/dev", "/private/etc", "/private/var/db")
    allowed = (*listed, worktree, env, str(root / "own"))
    stray = [p for p in places if not any(p == a or p.startswith(a + "/") for a in allowed)]
    assert stray == [], stray
    assert worktree in places and env in places


def test_a_root_inside_a_denied_place_is_refused_the_same_on_both_platforms(root: Path) -> None:
    denied = root / "held-out"
    inside = denied / "env"
    (inside / "bin").mkdir(parents=True)
    own = str(root / "own")
    for roots in ((str(inside),), (str(denied),)):
        with pytest.raises(ContainmentError):
            bwrap_args(read_denied=(str(denied),), server_dir=own, read_roots=roots)
        with pytest.raises(ContainmentError):
            seatbelt_profile(
                read_denied=(str(denied),),
                server_dir=own,
                devices=(),
                command="/usr/bin/python3",
                read_roots=roots,
            )
    # A program under a denied place, as the server's command or its exec root, likewise.
    with pytest.raises(ContainmentError):
        seatbelt_profile(
            read_denied=(str(denied),),
            server_dir=own,
            devices=(),
            command=str(inside / "bin" / "python3"),
        )
    with pytest.raises(ContainmentError):
        seatbelt_profile(
            read_denied=(str(denied),),
            server_dir=own,
            devices=(),
            command="/usr/bin/python3",
            exec_roots=(str(inside),),
        )


def test_a_denial_under_a_system_place_is_masked_after_its_bind(root: Path) -> None:
    own = root / "own"
    own.mkdir()
    under = "/usr/share" if os.path.isdir("/usr/share") else "/usr/lib"
    args = bwrap_args(read_denied=(under,), server_dir=str(own), read_roots=())
    text = shlex.join(args)
    assert f"--tmpfs {os.path.realpath(under)}" in text, text
    assert text.index(f"--tmpfs {os.path.realpath(under)}") > text.index("--ro-bind /usr /usr")


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_denial_named_by_a_pattern_is_refused_for_a_server(
    root: Path, platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A server lives as long as its session, so a denial naming entries as they stand when a
    # command starts would not cover one made after the server started: no server is offered.
    config = _config(root)
    patterned = str(root / "held-out" / "*")
    monkeypatch.setattr(
        containment, "_read_denied", lambda _config, _platform: {patterned, config.state_dir}
    )
    with pytest.raises(ContainmentError, match="pattern"):
        server_read_denied(config, platform)


# ---- a server's own variables, directories and links (task 12) -------------------------------


def _store(root: Path) -> Path:
    store = root / "env" / "platformio"
    for name in ("platforms", "packages"):
        (store / name).mkdir(parents=True, exist_ok=True)
    return store


def _builder(root: Path, **changes: object) -> ServerLaunch:
    store = _store(root)
    fields: dict[str, object] = {
        "name": "builder",
        "command": "/usr/bin/python3",
        "args": ("-I", "builder.py", "--root", "{worktree}"),
        "exec_roots": (str(root / "env"),),
        "read_roots": (str(root / "env"),),
        "environment": {
            "CORE_DIR": "{server_dir}/core",
            "PROJECTS": "{worktree}/projects",
            "QUIET": "1",
        },
        "directories": ("core",),
        "links": {
            "core/platforms": str(store / "platforms"),
            "core/packages": str(store / "packages"),
        },
    }
    return ServerLaunch.model_validate({**fields, **changes})


def _contain(root: Path, platform: str, *servers: ServerLaunch) -> dict[str, object]:
    loaded = json.loads(
        contained_servers(
            _config(root),
            list(servers),
            platform=platform,
            temp_dir=root / "temps" / OWN,
            profiles_dir=root / "run" / "sessions" / SID / "servers",
            bwrap=BWRAP,
        )
    )
    return loaded["mcpServers"]  # type: ignore[no-any-return]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_server_s_variables_name_its_own_directory_and_the_session_s_worktree(
    root: Path, platform: str
) -> None:
    entry = _contain(root, platform, _builder(root))["builder"]
    assert isinstance(entry, dict)
    server_dir = root / "temps" / OWN / "servers" / "builder"
    worktree = _config(root).worktree
    assert entry["env"] == {
        "TMPDIR": str(server_dir),
        "MPLCONFIGDIR": str(server_dir),
        "CORE_DIR": f"{server_dir}/core",
        "PROJECTS": f"{worktree}/projects",
        "QUIET": "1",
    }, entry
    assert entry["args"][-4:] == ["-I", "builder.py", "--root", worktree], entry["args"]
    assert not any("{" in arg for arg in entry["args"]), entry["args"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_a_server_s_directories_and_links_are_made_in_its_own_directory(
    root: Path, platform: str
) -> None:
    _contain(root, platform, _builder(root))
    core = root / "temps" / OWN / "servers" / "builder" / "core"
    assert core.is_dir() and not core.is_symlink()
    store = _store(root)
    for name in ("platforms", "packages"):
        assert (core / name).is_symlink()
        assert os.readlink(core / name) == str(store / name)


@pytest.mark.parametrize(
    "changes",
    [
        # A link to a place the server neither reads nor runs.
        {"links": {"core/platforms": "/etc"}},
        {"links": {"core/platforms": "{worktree}"}},
        # A link out of its own directory, or beneath none it makes.
        {"links": {"../escape": "/usr/bin"}},
        {"links": {"other/platforms": "/usr/bin"}},
        {"directories": ("../up",), "links": {}},
        {"directories": ("/abs",), "links": {}},
        # A variable the wrapper sets, or one a start is built on.
        {"environment": {"TMPDIR": "/tmp"}},
        {"environment": {"MPLCONFIGDIR": "/tmp"}},
        {"environment": {"PATH": "/tmp"}},
        {"environment": {"LD_PRELOAD": "/x.so"}},
        {"environment": {"DYLD_INSERT_LIBRARIES": "/x.dylib"}},
        {"environment": {"NODE_OPTIONS": "--require=/x"}},
        # A placeholder other than the two it may name, left in a variable or an argument.
        {"environment": {"A": "{temp}/x"}},
        {"args": ("{root}/x",)},
    ],
)
def test_a_server_that_would_reach_past_its_own_directory_is_refused_and_nothing_is_made(
    root: Path, changes: dict[str, object]
) -> None:
    with pytest.raises(ContainmentError):
        _contain(root, "darwin", _builder(root, **changes))
    assert not (root / "temps" / OWN / "servers" / "builder").exists()
