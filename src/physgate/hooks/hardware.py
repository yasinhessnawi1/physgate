"""No session uploads or flashes to hardware, or opens a board's device.

A session builds firmware and shows its behaviour in simulation. Nothing it runs reaches a
board: an upload would write a device no check has seen, and a serial port or a USB node is a
channel in and out of the machine that no other layer watches. So both are refused, for every
profile, through each door a session has:

- **a shell command** that runs a program which only ever reaches a board, or a guarded
  program in any but its build-only uses, and any command at all that names a board's device;
- **a file tool** whose path is such a device, as written or as it resolves;
- **a tool server's tool** whose arguments name a device, an upload, or either kind of command.

**What is refused is data** (the tables below), and where a list of what to refuse could not
be complete the table says what is allowed instead:

- the programs that only ever reach a board (flashers, debug probes' servers) are a list, and
  it is not complete: a flasher it does not name is refused by nothing here;
- the build tool and the other programs that both build and reach a board are **guarded**:
  only the uses named as build-only pass (a build with build-only targets, a static check, a
  listing), so an upload by a route this file does not know (a test on the target, a debug
  session, a remote run, a program run through the tool's packages, a target added later) is
  refused without being named;
- the devices of each platform, which the OS layer reads from here too (``oslayer.policy``),
  so the two layers cannot name different devices.

**Commands are matched, not text.** The parser hands over each command a call would run, those
inside substitutions, ``sh -c``, ``eval`` and a script fed to a shell on its input included, and
the commands another program runs among its own words (``timeout 5 …``, ``xargs …``) are
found the way the git rule finds them, with that rule's own list of such programs. A document
that names an upload is text and passes. A word of such a command that only running it decides
(``$TARGET``) is refused: the tool would not get the word that was read.

**A device is matched wherever it is named**, in any word, assignment, redirection or text a
command is fed: a device is opened by whatever program is handed its name, so there is no
list of commands that may name one. A path is folded in case and normalised first, a pattern
that could expand to a device (a glob, a variable) is refused as the device, and a brace
pattern is read as every word it becomes. **A relative name is read from every directory the
command could be in**: the call's own, and each one a ``cd`` of the call names, since the
parser keeps no order a failed or skipped ``cd`` could be told by. A ``cd`` whose target only
running decides could be anywhere, the devices' directory and the root among them, so after
one a name that would be a device there is refused. Moving into the devices' directory is
refused outright.

**What this layer cannot see**, stated plainly:

- what only running decides: a path a program builds as it runs, an upload a program starts
  itself, a project file that names an upload as its default target, a directory reached
  through a link;
- a flasher this file does not name, run under its own name;
- a programmer that talks to USB without a device node (on macOS, through the system's
  device framework).

For the first two the OS layer holds wherever the board is one of the devices in the table:
its sandbox denies them to every command of the session, read and write, so an upload that
got that far finds no board. On Linux the table holds the USB nodes too. On macOS a USB
device is not a file, the table cannot name it, and what the sandbox allows there has not
been measured: that is the residual of both layers.
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

    Use = tuple[frozenset[str] | None, frozenset[str]]
    Guard = tuple[Mapping[str, Use], frozenset[str], frozenset[str]]

UPLOAD = (
    "Uploading or flashing to hardware is refused: no session reaches a board, and behaviour "
    "on the target is shown in simulation. Build without an upload target, and leave the "
    "board to the person who owns it."
)
DEVICE = (
    "Opening a board's device is refused: no session reaches a board, a serial port or a USB "
    "device of the machine. The call names {device}. Work from the build's own output and "
    "from simulation."
)
ENTERING = DEVICE.format(device="the devices' directory, as the place to work from")
NOT_BUILD = (
    "This use of {program} is refused: it is not one of its build-only uses, and the others "
    "can reach a board. A session builds, checks and reads sizes; it uploads, tests on a "
    "target, debugs and monitors nothing."
)
DYNAMIC = (
    "A word of this command is decided only when it runs, and the command is one that can "
    "upload to hardware, so it is refused. Write its words out."
)
UNREADABLE = (
    "This call's arguments could not be read to their end ({detail}), so whether they name "
    "an upload or a serial device is not known, and the call is refused."
)

#: The devices of each platform a board appears as, as the patterns the OS layer denies: its
#: serial ports, and on Linux the USB and HID nodes a programmer opens directly. The
#: machine's own terminals (``/dev/tty``, the pseudo-terminals) are not among them.
BOARD_DEVICES: Mapping[str, tuple[str, ...]] = {
    "darwin": ("/dev/cu.*", "/dev/tty.*"),
    "linux": ("/dev/bus/usb", "/dev/hidraw*", "/dev/ttyACM*", "/dev/ttyUSB*"),
}
#: The directory every one of them lies in.
_DEVICES = "dev"

#: Programs that only ever reach a board: flashers, and the servers of debug probes.
FLASHERS = frozenset(
    {
        "avrdude", "dfu-util", "dfu-programmer", "bossac", "openocd", "st-flash", "st-info",
        "pyocd", "teensy_loader_cli", "picotool", "stm32flash", "jlinkexe", "nrfjprog",
        "micronucleus",
    }
)  # fmt: skip

#: The build tool, by each name it is run under.
BUILD_TOOLS = frozenset({"pio", "platformio"})
#: Its targets that write to a board: the program, a filesystem image, the fuses, the
#: bootloader, the EEPROM, or an erase. Named so the refusal can say what was asked.
UPLOAD_TARGETS = frozenset(
    {"upload", "uploadfs", "uploadfsota", "program", "fuses", "bootloader", "erase", "uploadeep"}
)
#: Its targets that only build, clean or report. A target not named here is refused.
BUILD_TARGETS = frozenset(
    {"clean", "cleanall", "size", "checkprogsize", "buildprog", "buildfs", "compiledb", "envdump"}
)
#: How it is given a target.
_TARGET_OPTIONS = ("-t", "--target")
#: Its serial monitor: these two words, in this order, among its own.
MONITOR = ("device", "monitor")

#: One guarded program's build-only uses: each first word that is one, with the second words
#: it is held to (``None``: any) and the options it must carry; the options that are refused
#: with any use; and the options before the first word that take a value.
#: (The shape is ``Guard``, named with the other types above.)
_ANY: Use = (None, frozenset())
_BUILD_TOOL: Guard = (
    {
        "run": _ANY,
        "check": _ANY,
        "boards": _ANY,
        "project": _ANY,
        "system": (frozenset({"info"}), frozenset()),
        "settings": (frozenset({"get"}), frozenset()),
        "pkg": (frozenset({"list", "show", "outdated", "search"}), frozenset()),
        "device": (frozenset({"list"}), frozenset()),
        # Its tests upload and then read the board's port; with both stages off it only builds.
        "test": (None, frozenset({"--without-uploading", "--without-testing"})),
    },
    frozenset({"--upload-port", "--monitor-port"}),
    frozenset({"-c", "--caller"}),
)
_IMAGE_TOOL: Guard = (
    {
        name: _ANY
        for name in ("version", "image_info", "image-info", "elf2image", "merge_bin", "merge-bin")
    },
    frozenset({"-p", "--port"}),
    frozenset({"-c", "--chip"}),
)
_SKETCH_TOOL: Guard = (
    {"compile": _ANY, "version": _ANY},
    frozenset({"-u", "--upload", "-p", "--port", "-P", "--programmer"}),
    frozenset(),
)
#: The programs that both build and reach a board, each held to its build-only uses.
GUARDED: Mapping[str, Guard] = {
    "pio": _BUILD_TOOL,
    "platformio": _BUILD_TOOL,
    "esptool": _IMAGE_TOOL,
    "esptool.py": _IMAGE_TOOL,
    "arduino-cli": _SKETCH_TOOL,
}
#: Interpreters that run one of the programs above as a module (``python -m platformio``).
_MODULE_RUNNERS = re.compile(r"python[0-9.]*|pypy[0-9.]*")
_PROGRAMS = FLASHERS | frozenset(GUARDED)

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
#: Where a command could be after a move only running decides: anywhere, these two among
#: them, which are the two from which a short relative name is a device.
_ANYWHERE = ("/", "/" + _DEVICES)
#: The most directories a call's moves are followed to; past it they count as anywhere.
MAX_PLACES = 64


# ---- serial devices ----------------------------------------------------------------------


def _device_names() -> tuple[str, ...]:
    """The start of every device's path beneath the devices' directory, case-folded."""
    names = []
    for patterns in BOARD_DEVICES.values():
        for pattern in patterns:
            names.append(pattern.split("/", 2)[2].rstrip("*").casefold())
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
    rest = "/".join(parts[2:])
    return any(_could_start(rest, name) for name in _NAMES)


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


def serial_device_in(text: str, places: Sequence[str] = ()) -> str | None:
    """The device ``text`` names, as written, or ``None``.

    Every path-like token is read as the absolute path it could name (:func:`_rooted`), and
    a relative one from each of ``places`` as well: the directories the command could be in.
    A token that starts with a variable is not a relative name: where it leads only running
    decides.
    """
    for token in _TOKEN_END.split(text):
        if not token:
            continue
        rooted = _rooted(token)
        if rooted is not None and _is_device(rooted):
            return token
        if not token.startswith(("/", "$")) and any(
            _is_device(_normal(place + "/" + token)) for place in places
        ):
            return token
    return None


def serial_device_path(path: str, cwd: str) -> str | None:
    """The device a file tool's ``path`` is, as written or as it resolves, or ``None``."""
    absolute = path if os.path.isabs(path) else os.path.join(cwd, path)
    for spelling in (absolute, os.path.realpath(absolute)):
        if _is_device(_normal(spelling)):
            return path
    return None


def _moves_to(cmd: SimpleCommand) -> str | None | bool:
    """Where a command moves the shell, if it does.

    A written target; ``None`` for a move only running decides; ``False`` for a command that
    moves nowhere.
    """
    argv = unwrap(cmd.argv)
    if not argv or command_key(argv[0]) not in _CD:
        return False
    stepped = len(cmd.argv) - len(argv)
    unread = cmd.dynamic | cmd.expanding
    for n, word in enumerate(argv[1:], 1):
        if word.startswith(("-", "+")) and word not in ("-", "+"):
            continue
        if stepped + n in unread or word in ("-", "+") or word.startswith("~"):
            return None
        return word
    # No target: the home, which the command's own text may have set.
    return None


def places_of(commands: Sequence[SimpleCommand], cwd: str) -> tuple[list[str], list[str]]:
    """Every directory the commands of a call could be in, and those a move of theirs names.

    The first holds the call's own directory, as it resolves, each directory a
    move names read from every directory before it, and the two of :data:`_ANYWHERE` once a
    move is one only running decides or there are more than :data:`MAX_PLACES`.
    """
    places = [_normal(os.path.realpath(cwd))]
    moved: list[str] = []
    anywhere = False
    for cmd in commands:
        target = _moves_to(cmd)
        if target is False:
            continue
        if target is None or len(places) > MAX_PLACES:
            anywhere = True
            continue
        assert isinstance(target, str)
        if target.startswith("/"):
            reached = [_normal(target)]
        else:
            reached = [_normal(place + "/" + target) for place in places]
        moved += reached
        places += [place for place in reached if place not in places]
    if anywhere:
        places += _ANYWHERE
    return places, moved


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
    """Every piece of text a command carries: its words, and what it is assigned and fed.

    Every word a brace pattern becomes comes first, so a device is named as the shell would
    open it; the pattern itself follows, for one with too many words to list.
    """
    for alternatives in cmd.alternatives.values():
        yield from alternatives or ()
    for redirect in cmd.redirects:
        yield from redirect.alternatives or ()
    yield from cmd.assignments
    yield from cmd.argv
    for redirect in cmd.redirects:
        yield redirect.target
        if redirect.body is not None:
            yield redirect.body


# ---- uploads -----------------------------------------------------------------------------


def _targets(words: Sequence[str]) -> list[str]:
    """Every target ``words`` give the build tool, case-folded."""
    given = []
    for n, word in enumerate(words):
        folded = word.casefold()
        if folded in _TARGET_OPTIONS:
            given.append(words[n + 1].casefold() if n + 1 < len(words) else "")
        elif folded.startswith("--target="):
            given.append(folded.split("=", 1)[1])
        elif folded.startswith("-t") and not folded.startswith("--"):
            given.append(folded[2:])
    return given


def _names_upload_target(words: Sequence[str]) -> bool:
    """Whether ``words`` give the build tool a target that writes to a board."""
    return any(target in UPLOAD_TARGETS for target in _targets(words))


def _names_monitor(words: Sequence[str]) -> bool:
    """Whether ``words`` hold the serial monitor's two words, in their order."""
    folded = [word.casefold() for word in words]
    first, second = MONITOR
    return first in folded and second in folded[folded.index(first) + 1 :]


def upload_in(program: str, words: Sequence[str]) -> bool:
    """Whether ``program``, run with ``words``, is a flasher, an upload or the serial monitor."""
    if program in FLASHERS:
        return True
    return program in BUILD_TOOLS and (_names_upload_target(words) or _names_monitor(words))


def build_only(program: str, words: Sequence[str]) -> bool:
    """Whether ``words`` are one of a guarded program's build-only uses.

    A program that is not guarded has no uses to hold it to. One run with options alone
    (``--version``) does nothing.
    """
    guard = GUARDED.get(program)
    if guard is None:
        return True
    uses, refused, valued = guard
    folded = [word.casefold() for word in words]
    if any(word.split("=", 1)[0] in refused for word in folded):
        return False
    bare: list[str] = []
    skip = False
    for word in folded:
        if skip:
            skip = False
        elif word.startswith("-"):
            # Only before the first word does an option's value need stepping over.
            skip = not bare and word in valued
        else:
            bare.append(word)
    if not bare:
        return True
    use = uses.get(bare[0])
    if use is None:
        return False
    seconds, required = use
    if seconds is not None and (len(bare) < 2 or bare[1] not in seconds):
        return False
    if not required <= set(folded):
        return False
    if program in BUILD_TOOLS and bare[0] == "run":
        return all(target in BUILD_TARGETS for target in _targets(words))
    return True


def refusal_of(program: str, words: Sequence[str]) -> str | None:
    """The reason ``program`` may not be run with ``words``, or ``None``."""
    if upload_in(program, words):
        return UPLOAD
    return None if build_only(program, words) else NOT_BUILD.format(program=program)


def _program_at(argv: Sequence[str]) -> tuple[int, str] | None:
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
    if head in git_ops._RUNNERS:
        for n, word in enumerate(argv[1:], 1):
            if command_key(word) in _PROGRAMS:
                return n, command_key(word)
    return None


def _check_command(cmd: SimpleCommand, places: Sequence[str]) -> str | None:
    """The reason ``cmd`` is refused, or ``None``."""
    for text in _words_of(cmd):
        device = serial_device_in(text, places)
        if device is not None:
            return DEVICE.format(device=device)
    argv = unwrap(cmd.argv)
    if _enters_devices(argv):
        return ENTERING
    unread = cmd.dynamic | cmd.expanding
    stepped = len(cmd.argv) - len(argv)
    found = _program_at(argv)
    if found is None:
        # A program named only when the command runs, given an upload target all the same.
        named_late = bool(argv) and stepped in unread
        return UPLOAD if named_late and _names_upload_target(argv[1:]) else None
    start, program = found
    words = argv[start + 1 :]
    if upload_in(program, words):
        return UPLOAD
    if any(n >= stepped + start for n in unread):
        return DYNAMIC
    return None if build_only(program, words) else NOT_BUILD.format(program=program)


def command_refusal(command: str, cwd: str) -> str | None:
    """The reason a shell command run from ``cwd`` is refused, or ``None``.

    A command the parser cannot split is left to the rules that refuse it for that.
    """
    try:
        pending: list[tuple[SimpleCommand, str]] = [(c, "command") for c in parse(command)]
        commands: list[SimpleCommand] = []
        while pending:
            cmd, position = pending.pop(0)
            commands.append(cmd)
            # The git rule's own walk: one reading of what a command runs, for both rules.
            pending[0:0] = git_ops._found_in(cmd, position)
    except ShellSyntaxError:
        return None
    places, moved = places_of(commands, cwd)
    if "/" + _DEVICES in moved:
        return ENTERING
    for cmd in commands:
        reason = _check_command(cmd, places)
        if reason is not None:
            return reason
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


def _lists(value: object) -> Iterator[list[str]]:
    """Every list in a tool's arguments, as the strings it holds; its depth is checked before."""
    if isinstance(value, dict):
        for inner in value.values():
            yield from _lists(inner)
    elif isinstance(value, (list, tuple)):
        yield [item for item in value if isinstance(item, str)]
        for inner in value:
            yield from _lists(inner)


def _refused_among(words: Sequence[str]) -> str | None:
    """The reason ``words``, read as a command line or the end of one, are refused, or ``None``."""
    if _names_upload_target(words):
        return UPLOAD
    for n, word in enumerate(words):
        program = command_key(word)
        if program in _PROGRAMS:
            reason = refusal_of(program, words[n + 1 :])
            if reason is not None:
                return reason
    return None


def arguments_refusal(arguments: object) -> str | None:
    """The reason a tool server's tool is refused for its arguments, or ``None``.

    The hooks see what a tool is asked, never what its server then does, so the arguments are
    read as text: a device named in any string or key; an upload target under a key that
    asks for a target; and any string, or list of strings, that reads as a command line with
    a flasher, an upload or a use of a guarded program that is not build-only in it. A
    relative name is read from the root only: where a server runs is its own affair.
    """
    try:
        found = list(_strings(arguments))
    except ValueError as exc:
        return UNREADABLE.format(detail=exc)
    for key, text in found:
        device = serial_device_in(text)
        if device is not None:
            return DEVICE.format(device=device)
        if "target" in key.casefold() and text.casefold() in UPLOAD_TARGETS:
            return UPLOAD
        reason = _refused_among(text.split())
        if reason is not None:
            return reason
    for words in _lists(arguments):
        reason = _refused_among(words)
        if reason is not None:
            return reason
    return None


# ---- the hook ----------------------------------------------------------------------------


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Refuse a call that uploads to hardware or opens a serial device."""
    tool = hook_input.tool_name or ""
    tool_input = hook_input.tool_input or {}
    reason: str | None = None
    cwd = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    if tool == "Bash":
        command = tool_input.get("command")
        reason = command_refusal(command, cwd) if isinstance(command, str) else None
    elif tool in _PATH_KEYS:
        path = tool_input.get(_PATH_KEYS[tool])
        if isinstance(path, str) and path:
            device = serial_device_path(path, cwd)
            reason = None if device is None else DEVICE.format(device=device)
    elif tool.startswith(_SERVER_TOOL):
        reason = arguments_refusal(tool_input)
    return ALLOW if reason is None else refuse(reason)


HOOK = HookSpec("hardware", {"PreToolUse": pre_tool_use})
