"""No session uploads or flashes to hardware, or opens a serial device.

A session builds firmware and shows its behaviour in simulation. Nothing it runs reaches a
board: an upload would write a device no check has seen, and a serial port is a channel in
and out of the machine that no other layer watches. So both are refused, for every profile,
through each door a session has:

- **a shell command** that runs a build tool with an upload target, a flashing program, or a
  serial monitor, and any command at all that names a serial device;
- **a file tool** whose path is a serial device, as written or as it resolves;
- **a tool server's tool** whose arguments name a serial device or an upload.

**What is refused is data** (the tables below): the build tool's names and the targets that
write to a board, the programs that only ever flash, the programs that flash when given one of
a few words, and the serial devices of each platform. The OS layer reads the same device table
(``oslayer.policy``), so the two layers cannot name different devices.

**Commands are matched, not text.** The parser hands over each command a call would run, those
inside substitutions, ``sh -c``, ``eval`` and a script fed to a shell on its input included, and
the commands another program runs among its own words (``timeout 5 …``, ``xargs …``) are
found the way the git rule finds them, with that rule's own list of such programs. A document
that names an upload is text and passes. A word of such a command that only running it decides
(``$TARGET``) is refused: the tool would not get the word that was read.

**A serial device is matched wherever it is named**, in any word, assignment, redirection or
text a command is fed: a device is opened by whatever program is handed its name, so there is
no list of commands that may name one. A path is folded in case and normalised first, a
pattern that could expand to a device is refused as the device, and so is moving into the
devices' directory, after which a bare name would reach one.

**What this layer cannot see** is what only running decides: a path a program builds as it
runs, an upload a program starts itself, a project file that names an upload as its default
target. There the OS layer holds: its sandbox denies the serial devices to every command of
the session, read and write, so an upload that got that far finds no board.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import TYPE_CHECKING

from physgate.hooks import git_ops
from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import ShellSyntaxError, SimpleCommand, command_key, parse, unwrap

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from physgate.hooks.views import ConfigView, InputView

UPLOAD = (
    "Uploading or flashing to hardware is refused: no session reaches a board, and behaviour "
    "on the target is shown in simulation. Build without an upload target, and leave the "
    "board to the person who owns it."
)
SERIAL = (
    "Opening a serial device is refused: no session reaches a board or a port of the machine. "
    "The call names {device}. Work from the build's own output and from simulation."
)
DYNAMIC = (
    "A word of this command is decided only when it runs, and the command is one that can "
    "upload to hardware, so it is refused. Write its words out."
)
UNREADABLE = (
    "This call's arguments could not be read to their end ({detail}), so whether they name "
    "an upload or a serial device is not known, and the call is refused."
)

#: The serial devices of each platform, as the patterns the OS layer denies. A board on USB
#: appears under these names; the machine's own terminals (``/dev/tty``, the pseudo-terminals)
#: do not.
SERIAL_DEVICES: Mapping[str, tuple[str, ...]] = {
    "darwin": ("/dev/cu.*", "/dev/tty.*"),
    "linux": ("/dev/ttyACM*", "/dev/ttyUSB*"),
}
#: The directory every one of them lies in.
_DEVICES = "dev"

#: The build tool, by each name it is run under.
BUILD_TOOLS = frozenset({"pio", "platformio"})
#: Its targets that write to a board: the program, a filesystem image, the fuses, the
#: bootloader, the EEPROM, or an erase.
UPLOAD_TARGETS = frozenset(
    {"upload", "uploadfs", "uploadfsota", "program", "fuses", "bootloader", "erase", "uploadeep"}
)
#: How it is given a target.
_TARGET_OPTIONS = ("-t", "--target")
#: Its serial monitor: these two words, in this order, among its own.
MONITOR = ("device", "monitor")
#: Programs that do nothing but write to a board.
FLASHERS = frozenset({"avrdude"})
#: Programs that write to a board when given one of these words.
FLASH_WORDS: Mapping[str, frozenset[str]] = {
    "esptool": frozenset({"write_flash", "erase_flash", "write-flash", "erase-flash"}),
    "esptool.py": frozenset({"write_flash", "erase_flash", "write-flash", "erase-flash"}),
}
#: Interpreters that run one of the programs above as a module (``python -m platformio``).
_MODULE_RUNNERS = re.compile(r"python[0-9.]*|pypy[0-9.]*")
_PROGRAMS = BUILD_TOOLS | FLASHERS | frozenset(FLASH_WORDS)

#: The tools that name the one file they act on, and the argument that names it.
_PATH_KEYS = {
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "NotebookEdit": "notebook_path",
}
#: How a tool server's tool is named.
_SERVER_TOOL = "mcp__"
#: How deep a tool's arguments are read. Deeper than this they are refused, not skipped.
MAX_DEPTH = 16

#: Where a path-like token ends inside a word.
_TOKEN_END = re.compile(r"""[\s'"=,;:()<>|&`]+""")
#: Characters the shell, or a program reading a pattern, turns into something else.
_OPEN = frozenset("*?[{$\\")
_CD = frozenset({"cd", "pushd", "chdir"})


# ---- serial devices ----------------------------------------------------------------------


def _device_names() -> tuple[str, ...]:
    """The start of every serial device's name within the devices' directory, case-folded."""
    names = []
    for patterns in SERIAL_DEVICES.values():
        for pattern in patterns:
            names.append(pattern.rsplit("/", 1)[1].rstrip("*").casefold())
    return tuple(names)


_NAMES = _device_names()


def _could_start(pattern: str, start: str) -> bool:
    """Whether a name written as ``pattern`` could begin with ``start``."""
    for n, wanted in enumerate(start):
        if n >= len(pattern):
            return False
        char = pattern[n]
        if char in _OPEN and char != "?":
            return True
        if char not in ("?", wanted):
            return False
    return True


def _could_be(pattern: str, name: str) -> bool:
    """Whether a path part written as ``pattern`` could be the directory ``name``."""
    if any(char in pattern for char in "{$\\"):
        return True
    return fnmatch.fnmatchcase(name, pattern)


def _is_device(path: str) -> bool:
    """Whether an absolute, normalised, case-folded path is, or could expand to, a device."""
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != "" or not _could_be(parts[1], _DEVICES):
        return False
    return any(_could_start(parts[2], name) for name in _NAMES)


def _normal(path: str) -> str:
    """``path`` as an absolute one: case-folded, with ``.``, ``..`` and ``//`` resolved."""
    return os.path.normpath("/" + path.casefold().lstrip("/"))


def _rooted(token: str) -> str | None:
    """The absolute path a token could name, or ``None`` for one that stays where it is.

    A token that starts at the root is one. So is what follows an option glued to its value
    (``-P/dev/…``), and a relative path that climbs (``../../dev/…``), which reaches the
    root from somewhere. Any other relative path (``src/dev/tty.c``, ``~/dev/…``) names a
    file beneath the directory it is read from, and is not a device.
    """
    slash = token.find("/")
    if slash < 0:
        return None
    before = token[:slash]
    if before == "" or before.startswith("-") or ".." in token.split("/"):
        return _normal(token[slash:])
    return None


def serial_device_in(text: str) -> str | None:
    """The serial device ``text`` names, as written, or ``None``.

    Every path-like token is read as the absolute path it could name (:func:`_rooted`).
    """
    for token in _TOKEN_END.split(text):
        rooted = _rooted(token)
        if rooted is not None and _is_device(rooted):
            return token
    return None


def serial_device_path(path: str, cwd: str) -> str | None:
    """The serial device a file tool's ``path`` is, as written or as it resolves, or ``None``."""
    absolute = path if os.path.isabs(path) else os.path.join(cwd, path)
    for spelling in (absolute, os.path.realpath(absolute)):
        if _is_device(_normal(spelling)):
            return path
    return None


def _enters_devices(argv: Sequence[str]) -> bool:
    """Whether a command moves the shell into the devices' directory."""
    if not argv or command_key(argv[0]) not in _CD:
        return False
    for word in argv[1:]:
        rooted = _rooted(word if "/" in word else word + "/")
        if rooted is not None:
            parts = rooted.split("/")
            if len(parts) == 2 and parts[1] and _could_be(parts[1], _DEVICES):
                return True
    return False


def _words_of(cmd: SimpleCommand) -> Iterator[str]:
    """Every piece of text a command carries: its words, and what it is assigned and fed."""
    yield from cmd.assignments
    yield from cmd.argv
    for alternatives in cmd.alternatives.values():
        yield from alternatives or ()
    for redirect in cmd.redirects:
        yield redirect.target
        yield from redirect.alternatives or ()
        if redirect.body is not None:
            yield redirect.body


# ---- uploads -----------------------------------------------------------------------------


def _names_upload_target(words: Sequence[str]) -> bool:
    """Whether ``words`` give the build tool a target that writes to a board."""
    for n, word in enumerate(words):
        folded = word.casefold()
        if folded in _TARGET_OPTIONS:
            given = words[n + 1].casefold() if n + 1 < len(words) else ""
        elif folded.startswith("--target="):
            given = folded.split("=", 1)[1]
        elif folded.startswith("-t") and not folded.startswith("--"):
            given = folded[2:]
        else:
            continue
        if given in UPLOAD_TARGETS:
            return True
    return False


def _names_monitor(words: Sequence[str]) -> bool:
    """Whether ``words`` hold the serial monitor's two words, in their order."""
    folded = [word.casefold() for word in words]
    first, second = MONITOR
    return first in folded and second in folded[folded.index(first) + 1 :]


def upload_in(program: str, words: Sequence[str]) -> bool:
    """Whether ``program``, run with ``words``, uploads, flashes or opens the serial monitor."""
    if program in FLASHERS:
        return True
    if program in BUILD_TOOLS:
        return _names_upload_target(words) or _names_monitor(words)
    refused = FLASH_WORDS.get(program)
    return refused is not None and any(word.casefold() in refused for word in words)


def _program_at(argv: Sequence[str], position: str) -> tuple[int, str] | None:
    """Where in ``argv`` a program this rule judges starts, and which one, or ``None``.

    In command position always. Among the words of a program that runs its arguments, and of
    an interpreter given it as a module, the first one found. Among any other program's
    words it is text.
    """
    if not argv:
        return None
    head = command_key(argv[0])
    if head in _PROGRAMS:
        return 0, head
    if _MODULE_RUNNERS.fullmatch(head):
        for n, word in enumerate(argv[1:], 1):
            if word == "-m" and n + 1 < len(argv) and command_key(argv[n + 1]) in _PROGRAMS:
                return n + 1, command_key(argv[n + 1])
            if word.startswith("-m") and command_key(word[2:]) in _PROGRAMS:
                return n, command_key(word[2:])
        return None
    # The git rule's own list of programs that run their arguments: one list for both rules.
    if head in git_ops._RUNNERS or position == "runner":
        for n, word in enumerate(argv[1:], 1):
            if command_key(word) in _PROGRAMS:
                return n, command_key(word)
    return None


def _check_command(cmd: SimpleCommand, position: str) -> str | None:
    """The reason ``cmd`` is refused, or ``None``."""
    for text in _words_of(cmd):
        device = serial_device_in(text)
        if device is not None:
            return SERIAL.format(device=device)
    argv = unwrap(cmd.argv)
    if _enters_devices(argv):
        return SERIAL.format(device="the devices' directory, as the place to work from")
    unread = cmd.dynamic | cmd.expanding
    stepped = len(cmd.argv) - len(argv)
    found = _program_at(argv, position)
    if found is None:
        # A program named only when the command runs, given an upload target all the same.
        named_late = bool(argv) and stepped in unread
        return UPLOAD if named_late and _names_upload_target(argv[1:]) else None
    start, program = found
    if upload_in(program, argv[start + 1 :]):
        return UPLOAD
    if any(n >= stepped + start for n in unread):
        return DYNAMIC
    return None


def command_refusal(command: str) -> str | None:
    """The reason a shell command is refused, or ``None`` when this rule lets it run.

    A command the parser cannot split is left to the rules that refuse it for that.
    """
    try:
        commands = parse(command)
    except ShellSyntaxError:
        return None
    pending: list[tuple[SimpleCommand, str]] = [(c, "command") for c in commands]
    while pending:
        cmd, position = pending.pop(0)
        reason = _check_command(cmd, position)
        if reason is not None:
            return reason
        try:
            # The git rule's own walk: one reading of what a command runs, for both rules.
            pending[0:0] = git_ops._found_in(cmd, position)
        except ShellSyntaxError:
            return None
    return None


# ---- a tool server's arguments -----------------------------------------------------------


def _strings(value: object, depth: int = 0) -> Iterator[tuple[str, str]]:
    """Every string in a tool's arguments, each with the key it was found under."""
    if depth > MAX_DEPTH:
        msg = f"nested more than {MAX_DEPTH} deep"
        raise ValueError(msg)
    if isinstance(value, str):
        yield "", value
    elif isinstance(value, dict):
        for key, inner in value.items():
            yield "", str(key)
            for _, found in _strings(inner, depth + 1):
                yield str(key), found
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _strings(inner, depth + 1)


def _lists(value: object, depth: int = 0) -> Iterator[list[str]]:
    """Every list in a tool's arguments, as the strings it holds."""
    if depth > MAX_DEPTH:
        return
    if isinstance(value, dict):
        for inner in value.values():
            yield from _lists(inner, depth + 1)
    elif isinstance(value, (list, tuple)):
        yield [item for item in value if isinstance(item, str)]
        for inner in value:
            yield from _lists(inner, depth + 1)


def _upload_among(words: Sequence[str]) -> bool:
    """Whether ``words``, read as a command line or the end of one, name an upload."""
    if _names_upload_target(words):
        return True
    for n, word in enumerate(words):
        program = command_key(word)
        if program in _PROGRAMS and upload_in(program, words[n + 1 :]):
            return True
    return False


def arguments_refusal(arguments: object) -> str | None:
    """The reason a tool server's tool is refused for its arguments, or ``None``.

    The hooks see what a tool is asked, never what its server then does, so the arguments are
    read as text: a serial device named in any string or key; an upload target under a key
    that asks for a target; and any string, or list of strings, that reads as a command line
    with an upload in it.
    """
    try:
        found = list(_strings(arguments))
    except ValueError as exc:
        return UNREADABLE.format(detail=exc)
    for key, text in found:
        device = serial_device_in(text)
        if device is not None:
            return SERIAL.format(device=device)
        if "target" in key.casefold() and text.casefold() in UPLOAD_TARGETS:
            return UPLOAD
        if _upload_among(text.split()):
            return UPLOAD
    if any(_upload_among(words) for words in _lists(arguments)):
        return UPLOAD
    return None


# ---- the hook ----------------------------------------------------------------------------


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a call that uploads to hardware or opens a serial device."""
    tool = hook_input.tool_name or ""
    tool_input = hook_input.tool_input or {}
    reason: str | None = None
    if tool == "Bash":
        command = tool_input.get("command")
        reason = command_refusal(command) if isinstance(command, str) else None
    elif tool in _PATH_KEYS:
        path = tool_input.get(_PATH_KEYS[tool])
        if isinstance(path, str) and path:
            cwd = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
            device = serial_device_path(path, cwd)
            reason = None if device is None else SERIAL.format(device=device)
    elif tool.startswith(_SERVER_TOOL):
        reason = arguments_refusal(tool_input)
    return ALLOW if reason is None else refuse(reason)


HOOK = HookSpec("hardware", {"PreToolUse": pre_tool_use})
