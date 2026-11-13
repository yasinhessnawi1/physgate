"""A tool server's containment: the session's own OS-layer policy, narrowed for a server."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.hooks.config import SessionConfig

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


class ContainmentError(RuntimeError):
    """A server cannot be contained as the session's policy says, so none is offered."""


class ServerLaunch(BaseModel):
    """One admitted tool server: its name, and its program by absolute path with arguments."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]
    command: Annotated[str, StringConstraints(pattern=r"^/")]
    args: tuple[str, ...] = ()


def server_read_denied(config: SessionConfig, platform: str) -> tuple[str, ...]:
    """Every path a contained server may not read."""
    return ()


def seatbelt_profile(*, read_denied: Sequence[str], server_dir: str, devices: Sequence[str]) -> str:
    """The Seatbelt profile a server runs under on macOS."""
    return ""


def bwrap_args(*, read_denied: Sequence[str], server_dir: str) -> list[str]:
    """The bubblewrap options a server runs under on Linux, before its command."""
    return []


def contained_servers(
    config: SessionConfig,
    servers: Sequence[ServerLaunch],
    *,
    platform: str,
    temp_dir: Path,
    profiles_dir: Path,
    bwrap: str | None,
) -> str:
    """The tool-server configuration a session is spawned with: each server in its wrapper."""
    return '{"mcpServers":{}}'


def wrappers(platform: str, bwrap: str | None) -> tuple[str, ...]:
    """The programs a contained server's entry may name as its command."""
    return ()
