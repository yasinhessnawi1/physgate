"""How a Claude Code session is invoked: the one module that names the binary.

Every invocation is isolated the same way: no settings source at all, a settings
file from outside every worktree, a scratch home and configuration directory, an
environment built from nothing, stdin from ``/dev/null``, a full model string and
a session id the orchestrator chose. The binary's own retries are set explicitly,
because its default was measured to retry an overloaded endpoint for minutes and
to hide those requests from the orchestrator's count.

The version is pinned: the headless contract the orchestrator relies on (the
stream's shape, the result fields, what a resume replays) was measured on
these versions and on no other.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.managed import TrafficSettings

#: The Claude Code versions the headless contract was measured on: the stream's
#: shape, the result fields and what a resume replays match on both (measured
#: 28.09.2026, evidence/t9). One small, reproducible stream-ordering difference
#: between them, confined to the decomposition-shaped call and not touching
#: result content or fields, is recorded in MAINTENANCE.md rather than here.
PINNED_VERSIONS = frozenset({"2.1.272", "2.1.283"})
_BINARY = "claude"


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
    prompt: str,
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
    remote feature flags is read (measured not to change the request body).
    """
    return [
        binary,
        "-p",
        prompt,
        "--setting-sources",
        "",
        "--settings",
        str(settings),
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


def isolated_env(
    *,
    home: Path,
    config_dir: Path,
    binary: str,
    max_retries: int,
    max_output_tokens: int,
    base_url: str | None,
    api_key: str | None,
) -> dict[str, str]:
    """An environment built from nothing for one session.

    The output-token limit is the run's: left unset, the binary takes the
    request's ``max_tokens`` from its model catalog, like the effort level.
    """
    env = {
        "HOME": str(home),
        "PATH": f"{Path(binary).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "TERM": "dumb",
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "CLAUDE_CODE_MAX_RETRIES": str(max_retries),
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output_tokens),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
    }
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


def traffic_settings() -> TrafficSettings:
    """The traffic settings every invocation's environment carries, read from that environment."""
    env = isolated_env(
        home=Path("/"),
        config_dir=Path("/"),
        binary="claude",
        max_retries=0,
        max_output_tokens=1,
        base_url=None,
        api_key=None,
    )
    nonessential = env.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC") == "1"
    telemetry = env.get("DISABLE_TELEMETRY") == "1"
    return TrafficSettings(
        nonessential_traffic="disabled" if nonessential else "enabled",
        telemetry="disabled" if telemetry else "enabled",
    )


def role_argv(
    binary: str,
    *,
    prompt: str,
    spawn_args: tuple[str, ...],
    model: str,
    session_id: str,
    max_turns: int,
    effort: str,
) -> list[str]:
    """A role session: the hook layer's spawn arguments, the stream the trajectory is.

    Never ``--resume``: a resumed session replays turns from a file the session's
    own user can write, including turns the model never produced (measured).
    """
    return [
        binary,
        "-p",
        prompt,
        *spawn_args,
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
        "--session-id",
        session_id,
        "--max-turns",
        str(max_turns),
        "--permission-mode",
        "bypassPermissions",
    ]
