"""A tool server's tool is asked only what its register entry names (the argument rule).

The hooks see a call's arguments, never what the server then does with them. So an admitted
tool's arguments are held to the register's schema for it, here, in the hook layer every
harness shares:

- an argument the schema does not name refuses the call, and so does one of another kind;
- an argument the schema marks as a path is judged as a file tool's read or write of that path
  would be (:func:`physgate.hooks.paths.protection`: the held-out tier, the protected roots,
  review material), and must lie inside the session's worktree as written and as the operating
  system resolves it. A relative path is read from the worktree where the server resolves it so,
  and refused where the server's own working directory decides. A case variant of the worktree's
  spelling is outside it.

This is the first layer. What a file the server reads in turn names (an MJCF include, a build
script) is held by the server's containment.

The register is read here with the standard library, as the hooks' hot path is; the harness
validates the same file with its schema (:mod:`physgate.toolenv.register`).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from functools import cache
from typing import TYPE_CHECKING, Any

from physgate.hooks.paths import protection

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView

#: The register, as the harness validates it.
REGISTER_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "toolenv", "register.json"
)
#: How a tool server's tool is named.
SERVER_TOOL = "mcp__"

NOT_REGISTERED = "The {tool} tool is not in the tool-server register, so it is refused."
NOT_AN_OBJECT = (
    "The {tool} tool is given its arguments as an object of named values, or not at all."
)
NOT_NAMED = (
    "The {tool} tool's register entry does not name the argument {argument}, so the call is "
    "refused. It may be given: {named}."
)
WRONG_KIND = (
    "The {tool} tool's argument {argument} is not of its kind in the register ({kind}), so the "
    "call is refused."
)
NO_PATH = "The {tool} tool's argument {argument} names no path a server could open."
RELATIVE = (
    "The {tool} tool's argument {argument} is a relative path, and where its server reads one "
    "from is the server's own affair: give the absolute path inside the session's worktree."
)
OUTSIDE = (
    "The {tool} tool's argument {argument} ({path}) lies outside the session's worktree, as "
    "written or once every link is followed, so the call is refused."
)
PROTECTED = "The {tool} tool's argument {argument} ({path}) is protected: {reason}."

#: Each kind's test of a value, as JSON gives it: a boolean is no number here.
_KINDS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, Mapping),
    "array": lambda v: isinstance(v, (list, tuple)),
    "read_path": lambda v: isinstance(v, str),
    "write_path": lambda v: isinstance(v, str),
}


@cache
def _servers() -> dict[str, Any]:
    """The register's servers. A file that cannot be read refuses every call it would judge."""
    with open(REGISTER_FILE, encoding="utf-8") as handle:
        loaded = json.load(handle)
    servers = loaded["servers"]
    if not isinstance(servers, dict):
        msg = "the tool-server register holds no servers"
        raise TypeError(msg)
    return servers


def _schema(tool: str) -> tuple[dict[str, Any], dict[str, str]] | None:
    """The tool's server entry and its arguments' kinds, or ``None`` if it is not admitted."""
    server, sep, name = tool.removeprefix(SERVER_TOOL).partition("__")
    if not tool.startswith(SERVER_TOOL) or not sep:
        return None
    entry = _servers().get(server)
    if not isinstance(entry, dict):
        return None
    tools = entry.get("tools")
    schema = tools.get(name) if isinstance(tools, dict) else None
    if not isinstance(schema, dict):
        return None
    return entry, schema


def _inside(path: str, place: str) -> bool:
    return path == place or path.startswith(place.rstrip("/") + "/")


def _path_refusal(
    tool: str,
    argument: str,
    value: str,
    entry: dict[str, Any],
    config: ConfigView,
    *,
    writing: bool,
) -> str | None:
    if not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return NO_PATH.format(tool=tool, argument=argument)
    if not os.path.isabs(value):
        if entry.get("relative_paths") != "worktree":
            return RELATIVE.format(tool=tool, argument=argument)
        value = os.path.join(config.worktree, value)
    worktree = os.path.normpath(config.worktree)
    lexical = os.path.normpath(value)
    physical = os.path.realpath(value)
    if not (_inside(lexical, worktree) and _inside(physical, os.path.realpath(config.worktree))):
        return OUTSIDE.format(tool=tool, argument=argument, path=value)
    reason = protection(value, config.worktree, config, writing=writing)
    if reason is not None:
        return PROTECTED.format(tool=tool, argument=argument, path=value, reason=reason)
    return None


def arguments_refusal(tool: str, arguments: object, cwd: str, config: ConfigView) -> str | None:
    """Why the admitted server tool ``tool`` may not be called with ``arguments``, or ``None``.

    ``cwd`` is not read: where the session's tools run says nothing of where its server does.
    """
    del cwd
    found = _schema(tool)
    if found is None:
        return NOT_REGISTERED.format(tool=tool)
    entry, schema = found
    if not isinstance(arguments, Mapping):
        return NOT_AN_OBJECT.format(tool=tool)
    for argument, value in arguments.items():
        kind = schema.get(argument)
        if not isinstance(kind, str):
            named = ", ".join(sorted(schema)) or "nothing"
            return NOT_NAMED.format(tool=tool, argument=argument, named=named)
        test = _KINDS.get(kind)
        if test is None or not test(value):
            return WRONG_KIND.format(tool=tool, argument=argument, kind=kind)
        if kind in ("read_path", "write_path"):
            reason = _path_refusal(
                tool, argument, value, entry, config, writing=kind == "write_path"
            )
            if reason is not None:
                return reason
    return None
