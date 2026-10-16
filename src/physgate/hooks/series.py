"""How a series record reaches the outbox: only by running a script, never by a tool or a command.

A role's simulation output is a series record, written by the series writer from the script
that ran the simulation, into ``.physgate/series/`` in the worktree. When the session ends,
the orchestrator collects the outbox and seals what holds. The record names the code that
produced it, so the one honest way in is the script itself:

- **the Write, Edit and NotebookEdit tools may not write into the outbox**, nor into a
  directory above it inside the worktree: a record typed by a tool would be a curve no
  simulation produced, with a script named by hand;
- **a shell command that names the outbox**, or such a directory, is refused unless it only
  reads (``cat``, ``ls``, ``grep`` and the like), and **any output redirection into it** is
  refused whatever the command: ``echo``, ``cat <<EOF``, ``cp``, ``tee``, ``python3 -c``
  with the path written out. A ``cd`` is followed, so a relative path after one is judged
  where it lands.

``python3 modules/control/sim.py`` names no part of the outbox, and is how a record is
written. A path assembled while a command runs (a variable, a substitution, a script) cannot
be judged before it runs, and lands in the outbox the way a script's write does; the
collector then judges it like any record, by the code it names. The second layer is the
change check, which refuses an attempt whose commit holds a record anywhere: records leave
the worktree before the commit, so a committed one was put where it does not belong.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import ShellSyntaxError, parse, unwrap
from physgate.hooks.shell_paths import (
    _WRITE_REDIRECTS,
    _candidates,
    _expand,
    _next_cwd,
    _only_reads,
)

if TYPE_CHECKING:
    from physgate.hooks.views import ConfigView, InputView

#: Where records are written, relative to the worktree.
OUTBOX_DIR = os.path.join(".physgate", "series")

TOOL_WRITE = (
    "A series record is written only by running the script that produced it, which records it "
    "through the series writer; the {tool} tool may not write into {path}."
)
SHELL_WRITE = (
    "This command names the series outbox ({path}). A record is written there only by running "
    "the script that produced it (for example python3 modules/<module>/sim.py), and a command "
    "may name the outbox only to read it (cat, ls, grep and the like)."
)
UNCHECKABLE = (
    "This command could not be split into the commands it would run ({detail}), so whether it "
    "writes into the series outbox cannot be checked, and it is refused."
)


def _spellings(path: str, cwd: str) -> set[str]:
    target = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    return {target, os.path.realpath(target)}


def _reaches_outbox(path: str, cwd: str, config: ConfigView) -> bool:
    """True if ``path`` is the outbox, anything in it, or a directory between it and the worktree.

    The worktree itself, and anything above it, is every command's home, and naming it is
    not naming the outbox.
    """
    outbox = os.path.join(config.worktree, OUTBOX_DIR).casefold()
    worktree = os.path.normpath(config.worktree).casefold()
    for spelling in _spellings(path, cwd):
        folded = spelling.casefold().rstrip("/")
        if folded == outbox or folded.startswith(outbox + "/"):
            return True
        if outbox.startswith(folded + "/") and folded.startswith(worktree + "/"):
            return True
    return False


def _file_tool(hook_input: InputView, config: ConfigView) -> Decision:
    tool_input = hook_input.tool_input or {}
    key = "notebook_path" if hook_input.tool_name == "NotebookEdit" else "file_path"
    path = str(tool_input.get(key, ""))
    cwd = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    if path and _reaches_outbox(path, cwd, config):
        return refuse(TOOL_WRITE.format(tool=hook_input.tool_name, path=path))
    return ALLOW


def _shell(hook_input: InputView, config: ConfigView) -> Decision:
    command = (hook_input.tool_input or {}).get("command")
    if not isinstance(command, str):
        return ALLOW  # the shell layer refuses a call without a command
    try:
        commands = parse(command)
    except ShellSyntaxError as exc:
        return refuse(UNCHECKABLE.format(detail=exc))
    start = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    cwd: str | None = start
    for cmd in commands:
        here = cwd or start
        argv = unwrap(cmd.argv)
        reads_only = bool(argv) and _only_reads(argv)
        words = [(r.target, "$" in r.target) for r in cmd.redirects if r.op in _WRITE_REDIRECTS]
        if not reads_only:
            words += [(w, n in cmd.dynamic) for n, w in enumerate(cmd.argv)]
        for word, dynamic in words:
            expanded = _expand(word, dynamic)
            if expanded is None:
                continue
            for candidate in _candidates(expanded, here):
                if _reaches_outbox(candidate, here, config):
                    return refuse(SHELL_WRITE.format(path=candidate))
        cwd = _next_cwd(cmd, cwd)
    return ALLOW


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a tool's or a command's write into the series outbox; a script's run is allowed."""
    if hook_input.tool_name in ("Write", "Edit", "NotebookEdit"):
        return _file_tool(hook_input, config)
    if hook_input.tool_name == "Bash":
        return _shell(hook_input, config)
    return ALLOW


HOOK = HookSpec("series", {"PreToolUse": pre_tool_use})
