"""The tool-server register: the servers a session may be offered, and each one's start and tools.

The register is data (:data:`REGISTER_FILE`), one entry per server:

- **how it starts:** its program and arguments, the variables it reads, and the directories and
  links it needs in a directory of its own. ``{root}`` stands for the root of the run's recorded
  tool environment that holds the program, ``{worktree}`` for the session's worktree and
  ``{server_dir}`` for the server's own directory, which the containment wrapper makes;
- **what it may be asked:** each admitted tool by name, with every argument it may be given and
  that argument's kind. A path's kind says whether a file tool would read or write it there, and
  the entry says whether a relative path is read from the worktree or refused;
- **what it is never asked:** every other tool the server offers, by name.

Apart from any server, the register names the tools that reach a board (an upload, a flash, a
monitor, a serial port, a debug probe, a test run on the device): no entry may admit one under
any server's name, and the hooks refuse a call to one whatever server it names.

The closed list a session runs on names exactly ``mcp__<server>__<tool>`` for the admitted tools
of the servers it is offered (:func:`server_tools`), and the hooks judge each call's arguments
against the same file (:mod:`physgate.hooks.server_arguments`), read there without this module so
the hooks' hot path stays on the standard library. Adding a server, a tool or an argument is an
entry here, never code.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.oslayer.containment import ServerLaunch
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import ToolEnvironment
from physgate.toolenv.session import (
    REFUSED_PREFIXES,
    REFUSED_VARIABLES,
    RelativePath,
    VariableName,
)

#: The register, beside this module.
REGISTER_FILE = Path(__file__).with_name("register.json")
#: How a tool server's tool is named in a session's closed list.
SERVER_TOOL_PREFIX = "mcp__"
#: The variables the containment wrapper sets for every server itself.
WRAPPER_VARIABLES = frozenset({"TMPDIR", "MPLCONFIGDIR"})

ServerName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9]{0,31}$")]
ToolName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
ArgumentName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")]
ArgumentKind = Literal[
    "string", "integer", "number", "boolean", "object", "array", "read_path", "write_path"
]
_PLACEHOLDERS = ("{root}", "{worktree}", "{server_dir}")


def _placeholders_only(allowed: tuple[str, ...]) -> AfterValidator:
    def check(value: str) -> str:
        rest = value
        for placeholder in allowed:
            rest = rest.replace(placeholder, "")
        if "{" in rest or "}" in rest:
            msg = f"a value here holds a placeholder other than {', '.join(allowed)}"
            raise ValueError(msg)
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            msg = "a value here holds a control character"
            raise ValueError(msg)
        return value

    return AfterValidator(check)


Command = Annotated[str, StringConstraints(pattern=r"^\{root\}/"), _placeholders_only(("{root}",))]
Argument = Annotated[
    str, StringConstraints(max_length=1024), _placeholders_only(("{root}", "{worktree}"))
]
VariableValue = Annotated[
    str, StringConstraints(max_length=1024), _placeholders_only(_PLACEHOLDERS)
]


def _no_dot_parts_after_root(value: str) -> str:
    if any(part in ("", ".", "..") for part in value.removeprefix("{root}/").split("/")):
        msg = "a link's target has no empty, '.' or '..' part"
        raise ValueError(msg)
    return value


LinkTarget = Annotated[
    str,
    StringConstraints(pattern=r"^\{root\}/[A-Za-z0-9._+@/-]+$"),
    _placeholders_only(("{root}",)),
    AfterValidator(_no_dot_parts_after_root),
]


class ServerEntry(BaseModel):
    """One server: how it starts, what it may be asked, and what it never is."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    command: Command
    args: tuple[Argument, ...] = ()
    #: Whether a relative path argument is read from the session's worktree (the server is
    #: started there and resolves it so) or refused (where the server resolves it is its own).
    relative_paths: Literal["worktree", "refused"]
    environment: dict[VariableName, VariableValue] = {}
    directories: tuple[RelativePath, ...] = ()
    links: dict[RelativePath, LinkTarget] = {}
    #: Where the server finds the programs it runs by name (a build server, its build tool).
    search_path: tuple[LinkTarget, ...] = ()
    tools: dict[ToolName, dict[ArgumentName, ArgumentKind]]
    denied: tuple[ToolName, ...] = ()

    @model_validator(mode="after")
    def _held(self) -> ServerEntry:
        both = sorted(set(self.tools) & set(self.denied))
        if both:
            msg = f"a tool is both admitted and denied: {both[0]}"
            raise ValueError(msg)
        for name in self.environment:
            if (
                name in REFUSED_VARIABLES
                or name.startswith(REFUSED_PREFIXES)
                or name in WRAPPER_VARIABLES
            ):
                msg = f"a variable is one a server's start is built on: {name}"
                raise ValueError(msg)
        for link in self.links:
            if link.split("/", 1)[0] not in self.directories or "/" not in link:
                msg = f"a link is not beneath a directory the entry makes: {link}"
                raise ValueError(msg)
        return self


class Register(BaseModel):
    """Every server a session may be offered, and the tools no server may be asked for."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    servers: dict[ServerName, ServerEntry]
    #: The tools that reach a board, by name: refused whatever server offers them.
    refused_tools: tuple[ToolName, ...]

    @model_validator(mode="after")
    def _none_admitted(self) -> Register:
        refused = set(self.refused_tools)
        for server, entry in sorted(self.servers.items()):
            both = sorted(set(entry.tools) & refused)
            if both:
                msg = f"the server {server!r} admits a tool that reaches a board: {both[0]}"
                raise ValueError(msg)
        return self


def load_register(path: Path = REGISTER_FILE) -> Register:
    """The register at ``path``.

    Raises:
        ToolEnvironmentError: the file cannot be read or is not a register.
    """
    try:
        return Register.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        msg = "the tool-server register is refused"
        raise ToolEnvironmentError(msg, path=str(path), why=str(exc)) from None


def register_sha256(path: Path = REGISTER_FILE) -> str:
    """The register's digest, which a run records so its tools are named exactly."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_name(server: str, tool: str) -> str:
    """How a server's tool is named in a session's closed list."""
    return f"{SERVER_TOOL_PREFIX}{server}__{tool}"


def server_tools(register: Register, servers: Sequence[str]) -> tuple[str, ...]:
    """Every admitted tool of ``servers``, as the closed list names it.

    Raises:
        ToolEnvironmentError: a server is not in the register.
    """
    return tuple(
        tool_name(server, tool) for server in servers for tool in _entry(register, server).tools
    )


def _entry(register: Register, server: str) -> ServerEntry:
    entry = register.servers.get(server)
    if entry is None:
        msg = "the tool-server register holds no such server"
        raise ToolEnvironmentError(msg, server=server)
    return entry


def launches(
    register: Register, servers: Sequence[str], recorded: ToolEnvironment
) -> tuple[ServerLaunch, ...]:
    """How each of ``servers`` is started from the run's recorded environment.

    ``{root}`` becomes the one recorded root that holds the server's program; the server runs
    and reads the recorded roots, and nothing else of the environment's. ``{worktree}`` and
    ``{server_dir}`` are left for the containment wrapper, which knows the session.

    Raises:
        ToolEnvironmentError: a server is not in the register, or no single root of the
            recorded environment holds its program.
    """
    found: list[ServerLaunch] = []
    for server in servers:
        entry = _entry(register, server)
        holding = [
            root
            for root in recorded.roots
            if os.path.isfile(entry.command.replace("{root}", root.rstrip("/")))
        ]
        if len(holding) != 1:
            msg = (
                f"the tool server {server} cannot be started: "
                f"{len(holding)} roots of the recorded environment hold its program"
            )
            raise ToolEnvironmentError(msg, server=server, command=entry.command)
        root = holding[0].rstrip("/")

        def placed(value: str, root: str = root) -> str:
            return value.replace("{root}", root)

        found.append(
            ServerLaunch(
                name=server,
                command=placed(entry.command),
                args=tuple(placed(arg) for arg in entry.args),
                exec_roots=recorded.roots,
                read_roots=recorded.roots,
                environment={name: placed(value) for name, value in entry.environment.items()},
                directories=entry.directories,
                links={link: placed(target) for link, target in entry.links.items()},
                search_path=tuple(placed(place) for place in entry.search_path),
            )
        )
    return tuple(found)
