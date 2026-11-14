"""How a Claude Code session is invoked: the one module that names the binary.

Every invocation is isolated the same way: no settings source at all, a settings
file from outside every worktree, no tool server but those the harness names, a
scratch home and configuration directory, an environment built from nothing, stdin
from ``/dev/null``, a full model string and a session id the orchestrator chose.
The binary's own retries are set explicitly, because its default was measured to
retry an overloaded endpoint for minutes and to hide those requests from the
orchestrator's count.

The version is pinned: the headless contract the orchestrator relies on (the
stream's shape, the result fields, what a resume replays) was measured on
these versions and on no other.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.managed import FLAGS_SETTING, FLAGS_SILENT_VERSIONS, TrafficSettings

#: The Claude Code versions the headless contract was measured on: the stream's
#: shape, the result fields and what a resume replays match on 2.1.272 and
#: 2.1.283 (measured 28.09.2026). One small, reproducible stream-ordering
#: difference between them, confined to the decomposition-shaped call and not
#: touching result content or fields, is recorded with the maintenance notes
#: rather than here. 2.1.301 is the version the shell sandbox is used on: it is
#: the first that keeps a denied path denied when it is reached through a
#: symbolic link on macOS, and it holds a sandbox started from the settings flag
#: against a repository's settings. The two older versions stay pinned so that
#: runs recorded on them can still be resumed and reproduced. 2.1.322 is a second, independent
#: pin beside 2.1.301, the first version that serves Claude Fable 5.2; nothing measured on
#: 2.1.301 is assumed of it, and a run never mixes the two.
PINNED_VERSIONS = frozenset({"2.1.272", "2.1.283", "2.1.301", "2.1.322"})
_BINARY = "claude"

#: The tool-server configuration every session is spawned with: none. The binary starts
#: a tool server named in a ``.mcp.json`` of the working directory or any directory above
#: it, or in the user scope of its configuration directory, as a process of its own outside
#: the OS layer, where it can write anywhere, read what no session may and reach the
#: network whatever the session's network setting says. In print mode it does so with no
#: approval step (measured on 2.1.301 and 2.1.272). ``--setting-sources ""`` closes those
#: sources today; the strict mode with this explicit configuration closes them by itself,
#: so a server starts only where the harness names one.
NO_TOOL_SERVERS = '{"mcpServers":{}}'
#: The most a tool server's answer may hold, in tokens. Set rather than left to the binary,
#: whose default (25,000 on 2.1.301) a remote feature flag can replace when it is unset.
MAX_SERVER_OUTPUT_TOKENS = 25_000
#: The arguments that pin a session's tool servers to :data:`NO_TOOL_SERVERS`.
NO_TOOL_SERVER_ARGS = ("--strict-mcp-config", "--mcp-config", NO_TOOL_SERVERS)


def claude_binary() -> str:
    """The Claude Code binary: ``PHYSGATE_CLAUDE_BIN`` if set, else ``claude`` on the path.

    Raises:
        InvocationError: there is none.
    """
    found = os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which(_BINARY)
    if not found:
        msg = "no Claude Code binary found (set PHYSGATE_CLAUDE_BIN)"
        raise InvocationError(msg)
    return found


def version_argv(binary: str) -> list[str]:
    """The command that prints the binary's version."""
    return [binary, "--version"]


def require_pinned(version_output: str) -> str:
    """Return the version if it is one of the pinned ones.

    Raises:
        InvocationError: it is any other.
    """
    version = version_output.strip().split(" ", 1)[0]
    if version not in PINNED_VERSIONS:
        pinned = ", ".join(sorted(PINNED_VERSIONS))
        msg = f"the binary reports {version!r}; the contract was measured on {pinned}"
        raise InvocationError(msg, reported=version, pinned=pinned)
    return version


def decomposition_argv(
    binary: str,
    *,
    schema: str,
    model: str,
    session_id: str,
    settings: Path,
    effort: str,
    debug_file: Path,
) -> list[str]:
    """The run's one model call: no tools but the structured answer, one turn.

    With one turn the call is exactly one request: a valid answer succeeds, and a
    plain-text or schema-violating one ends the call instead of the binary asking
    again on its own (both measured). The effort level is the run's, never the
    binary's default, which comes from a catalog its version does not pin. The call
    writes the binary's debug log, from which the state of that catalog and of the
    remote feature flags is read (measured not to change the request body). The prompt
    is not among the arguments: it goes on the binary's stdin, since Linux caps one
    argument at 128 KiB and a re-plan's prompt quotes a whole plan (measured on
    2.1.301 against the scripted endpoint: the request body is the same either way).
    """
    return [
        binary,
        "-p",
        "--setting-sources",
        "",
        "--settings",
        str(settings),
        *NO_TOOL_SERVER_ARGS,
        "--tools",
        "",
        "--json-schema",
        schema,
        "--max-turns",
        "1",
        "--model",
        model,
        "--effort",
        effort,
        "--session-id",
        session_id,
        "--output-format",
        "stream-json",
        "--verbose",
        # Each message's final usage arrives only in its message_delta event.
        "--include-partial-messages",
        "--debug-file",
        str(debug_file),
    ]


def session_search_path(binary: str) -> str:
    """The search path every session gets: the binary's directory, then the system's."""
    return f"{Path(binary).parent}:/usr/bin:/bin:/usr/sbin:/sbin"


#: Pins whose sessions carry the traffic the advisor needs, by the owner's choice: every variable
#: the provider documents as stopping feature-flag fetching is left unset. Earlier pins keep the
#: switches below, because runs recorded and frozen on them were measured with them.
TRAFFIC_ALLOWED_VERSIONS = frozenset({"2.1.322"})

#: What a session on a traffic-allowed pin still carries, each because a pinned binary must not
#: do it: update itself (nothing else stops that once the umbrella switch is gone), send error or
#: bug reports, move a command into the background where no hook sees it (including a command at
#: its timeout), answer a flagged request with another model, or reload a mod a session wrote.
_TRAFFIC_ALLOWED_SWITCHES = (
    ("DISABLE_AUTOUPDATER", "1"),
    ("DISABLE_ERROR_REPORTING", "1"),
    ("DISABLE_BUG_COMMAND", "1"),
    ("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "1"),
    ("CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK", "1"),
    ("CLAUDE_CODE_PLUGIN_DIR_WATCH", "0"),
)


def session_env_settings(claude_version: str) -> dict[str, str]:
    """The switches every session on ``claude_version`` carries, as a run records them.

    Only switches: nothing about the machine, the session's paths or its credential.
    """
    if claude_version in TRAFFIC_ALLOWED_VERSIONS:
        return dict(_TRAFFIC_ALLOWED_SWITCHES)
    switches = {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
    }
    if claude_version in FLAGS_SILENT_VERSIONS:
        name, value = FLAGS_SETTING
        switches[name] = value
    return switches


def isolated_env(
    *,
    home: Path,
    config_dir: Path,
    binary: str,
    claude_version: str,
    max_retries: int,
    max_output_tokens: int,
    base_url: str | None,
    api_key: str | None,
) -> dict[str, str]:
    """An environment built from nothing for one session.

    The output-token limit is the run's: left unset, the binary takes the
    request's ``max_tokens`` from its model catalog, like the effort level. The
    switches are the pin's own (``session_env_settings``): on the earlier pins,
    traffic is off and a version whose debug log never reports its feature flags
    also carries the documented setting that turns their fetch off; on a
    traffic-allowed pin, the flag fetch is left on.
    """
    env = {
        "HOME": str(home),
        "PATH": session_search_path(binary),
        "TERM": "dumb",
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "CLAUDE_CODE_MAX_RETRIES": str(max_retries),
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output_tokens),
        **session_env_settings(claude_version),
        # Set on every pin, at the binary's own default, so a remote flag cannot move the
        # bound on one tool server's answer; recorded with the run's tool servers.
        "MAX_MCP_OUTPUT_TOKENS": str(MAX_SERVER_OUTPUT_TOKENS),
    }
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


def traffic_settings(claude_version: str) -> TrafficSettings:
    """What every session on ``claude_version`` carries about the catalog and flags, as recorded.

    Read from that pin's own switches, which the record also lists whole. On a traffic-allowed
    pin the catalog and flag traffic is on by the owner's choice, and what each session saw is
    recorded with it instead of being measured off.
    """
    switches = session_env_settings(claude_version)
    nonessential = switches.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"
    telemetry = switches.get("DISABLE_TELEMETRY") == "1"
    recorded = TrafficSettings(
        nonessential_traffic="disabled" if nonessential else "enabled",
        telemetry="disabled" if telemetry else "enabled",
        switches=tuple(switches.items()),
    )
    if claude_version in TRAFFIC_ALLOWED_VERSIONS:
        return recorded.model_copy(update={"measured": _TRAFFIC_ALLOWED_MEASURED})
    return recorded


#: What a traffic-allowed pin's record says in place of the earlier pins' measurement of "off".
_TRAFFIC_ALLOWED_MEASURED = (
    "feature-flag and non-essential traffic left on by the owner's choice on this pin; the "
    "catalog and flags the decomposition call and each role session saw are recorded with them"
)


def _require_contained(tool_servers: str, wrappers: tuple[str, ...]) -> None:
    """Refuse a tool-server configuration that names a server outside its wrapper."""
    try:
        loaded = json.loads(tool_servers)
    except ValueError as exc:
        msg = "the tool-server configuration is not JSON"
        raise InvocationError(msg) from exc
    servers = loaded.get("mcpServers") if isinstance(loaded, dict) else None
    if not isinstance(servers, dict) or set(loaded) != {"mcpServers"}:
        msg = "the tool-server configuration names anything but its servers"
        raise InvocationError(msg)
    for name, entry in servers.items():
        command = entry.get("command") if isinstance(entry, dict) else None
        kind = entry.get("type", "stdio") if isinstance(entry, dict) else None
        if kind != "stdio" or command not in wrappers:
            msg = f"the tool server {name!r} is not started in a wrapper that contains it"
            raise InvocationError(msg, server=str(name), command=str(command))


def role_argv(
    binary: str,
    *,
    prompt: str,
    spawn_args: tuple[str, ...],
    model: str,
    session_id: str,
    max_turns: int,
    effort: str,
    thinking_display: str,
    tool_servers: str = NO_TOOL_SERVERS,
    wrappers: tuple[str, ...] = (),
    debug_file: Path | None = None,
) -> list[str]:
    """A role session: the hook layer's spawn arguments, the stream the trajectory is.

    Never ``--resume``: a resumed session replays turns from a file the session's
    own user can write, including turns the model never produced (measured).

    ``tool_servers`` is the session's tool-server configuration, none unless given. Every
    server it names is started by the binary outside the sandbox around the session's
    commands, so each must name one of ``wrappers`` (the programs that contain a server here)
    as its command, and a local one: a server named by anything else is refused here.

    Raises:
        InvocationError: the configuration names a server that is not in its wrapper.
    """
    _require_contained(tool_servers, wrappers)
    return [
        binary,
        "-p",
        prompt,
        *spawn_args,
        "--strict-mcp-config",
        "--mcp-config",
        tool_servers,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        # Each message's final usage arrives only in its message_delta event.
        "--include-partial-messages",
        "--model",
        model,
        "--effort",
        effort,
        # Measured on both pinned binaries: an option they accept without listing it.
        # A test runs each pinned binary with it and fails if one stops accepting it.
        "--thinking-display",
        thinking_display,
        "--session-id",
        session_id,
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "bypassPermissions",
        # Only on a pin whose sessions carry the catalog and flag traffic: its log says what
        # the session saw. It may hold the session's credential, so it is read and removed
        # with it. Earlier pins' sessions get the argv they always had.
        *(() if debug_file is None else ("--debug-file", str(debug_file))),
    ]


#: What a reviewer session's environment adds: the binary's compaction switched off.
#: A compaction summarises what the reviewer has read, which is a trim of its input
#: made silently by the runtime (measured to be off with this set, on both pinned
#: binaries, and on without it). A review that runs out of window instead is not a
#: verdict, and is recorded as such.
REVIEWER_ENV = {"DISABLE_COMPACT": "1"}


def reviewer_argv(
    binary: str,
    *,
    prompt: str,
    spawn_args: tuple[str, ...],
    schema: str,
    model: str,
    session_id: str,
    max_turns: int,
    effort: str,
    resume: bool = False,
    debug_file: Path | None = None,
) -> list[str]:
    """A reviewer session: reading only, then one structured verdict.

    ``--tools Read`` offers the Read tool and, with ``--json-schema``, the structured
    verdict tool beside it, nothing else. The thinking display is the binary's own:
    a reviewer's reasoning is read by nobody.

    With ``resume``, the session ``session_id`` is continued, to repair a refused
    verdict. A role session is never resumed, because its shell could write the file a
    resume replays; a reviewer has no tool that writes, so the file is the binary's own.
    """
    return [
        binary,
        "-p",
        prompt,
        *spawn_args,
        *NO_TOOL_SERVER_ARGS,
        "--tools",
        "Read",
        "--json-schema",
        schema,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        # Each message's final usage arrives only in its message_delta event.
        "--include-partial-messages",
        "--model",
        model,
        "--effort",
        effort,
        "--resume" if resume else "--session-id",
        session_id,
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "bypassPermissions",
        # Only on a pin whose sessions carry the catalog and flag traffic, as for a role
        # session: earlier pins' review sessions get the argv they always had.
        *(() if debug_file is None else ("--debug-file", str(debug_file))),
    ]
