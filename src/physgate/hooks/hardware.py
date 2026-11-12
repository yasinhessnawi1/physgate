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
- the build tool and the other programs that both build and reach a board are **guarded**,
  and a guarded program's words are read exactly or refused. Each build-only use is named
  with every option it may carry and whether that option takes a value. A use that is not
  named, an option that is not named, short options run together, an option glued to its
  value, a bare ``--``, a missing value: each is refused, because this file is not the
  program's own parser and every word the two would read differently is a way past it. So
  an upload by a route this file does not know (a test on the target, a debug session, a
  remote run, a program run through the tool's packages, a target or an option added later)
  is refused without being named;
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
pattern is read as every word it becomes.

**A relative name is read from where the command could be.** Without a move that is the
call's own directory, as it resolves. One move is followed, when it is the call's only one
and its target is written from a known place (an absolute path, or one that starts with
``./``) and does not climb: the command is then there, or still where it started. Anything
else is not followed: a second move (the parser keeps no order in which two could be told
apart), a bare relative target (the shell's search path for ``cd`` may send it anywhere), a
target with ``..`` in it (the shell climbs from the directory as it was named, the kernel
from where it really is), a target only running decides. After one of those the command
could be anywhere, the devices' directories and the root among them, so a relative name that
would be a device from one of those is refused. A followed move into a directory of devices
is refused outright. The cost is a
false refusal of ``cd firmware && cc usb/x.c`` where a ``usb`` directory exists: name the
file from where the call starts.

**What this layer cannot see**, stated plainly:

- what only running decides: a path a program builds as it runs, an upload a program starts
  itself, a directory reached through a link;
- what a build is told to run by the files it builds from. A session writes its own project
  file, and a project file can name a script the build runs, a command of its own for a
  target, or an upload as the default target; a board definition can do the same for the
  sketch tool. A plain build of such a project is a build-only use by its words, and no
  reading of words can tell otherwise. That is also why the options that point a build at a
  project directory or a project file are allowed: the default one is the session's too;
- a flasher this file does not name, run under its own name;
- a programmer that talks to USB without a device node (on macOS, through the system's
  device framework).

For the first three the OS layer holds wherever the board is one of the devices in the table:
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

    Options = Mapping[str, int]
    Use = tuple[Options, frozenset[str], bool]
    Guard = tuple[Options, Mapping[str, Use]]

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
    "This use of {program} is refused: it is not one of its build-only uses, written with "
    "options this check knows, each as a word of its own. The others can reach a board. A "
    "session builds, checks and reads sizes; it uploads, tests on a target, debugs and "
    "monitors nothing."
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

#: Options every use of the build tool that reads a project takes, each with the number of
#: words that follow it.
_PROJECT = {"-d": 1, "--project-dir": 1, "-e": 1, "--environment": 1}
_QUIET = {"-s": 0, "--silent": 0, "-v": 0, "--verbose": 0}
_NONE: frozenset[str] = frozenset()
#: The build tool: the options before its first word, then each build-only use with the
#: options it takes, the options it must carry, and whether it takes words of its own.
_BUILD_TOOL: Guard = (
    {"--version": 0, "-h": 0, "--help": 0, "--no-ansi": 0, "-c": 1, "--caller": 1},
    {
        "run": (
            {
                **_PROJECT, **_QUIET, "-t": 1, "--target": 1, "-c": 1, "--project-conf": 1,
                "-j": 1, "--jobs": 1, "--disable-auto-clean": 0, "--list-targets": 0,
            },
            _NONE,
            False,
        ),
        "check": (
            {
                **_PROJECT, **_QUIET, "-c": 1, "--project-conf": 1, "--pattern": 1,
                "--severity": 1, "--fail-on-defect": 1, "--skip-packages": 0, "--json-output": 0,
            },
            _NONE,
            False,
        ),
        # Its tests upload and then read the board's port; with both stages off it only builds.
        "test": (
            {**_PROJECT, **_QUIET, "--without-uploading": 0, "--without-testing": 0},
            frozenset({"--without-uploading", "--without-testing"}),
            False,
        ),
        "boards": ({"--installed": 0, "--json-output": 0}, _NONE, True),
        "project config": ({**_PROJECT, "--json-output": 0}, _NONE, False),
        "project metadata": ({**_PROJECT, "--json-output": 0}, _NONE, False),
        "system info": ({"--json-output": 0}, _NONE, False),
        "settings get": ({}, _NONE, True),
        "pkg list": ({**_PROJECT, "-g": 0, "--global": 0}, _NONE, False),
        "pkg outdated": ({**_PROJECT}, _NONE, False),
        "pkg show": ({}, _NONE, True),
        "pkg search": ({}, _NONE, True),
        "device list": ({"--json-output": 0}, _NONE, False),
    },
)  # fmt: skip
_IMAGE = {"-o": 1, "--output": 1, "--flash_mode": 1, "--flash_freq": 1, "--flash_size": 1}
#: The image tool: what it does to files on disk, and nothing it does to a chip.
_IMAGE_TOOL: Guard = (
    {"-h": 0, "--help": 0, "--chip": 1},
    {
        "version": ({}, _NONE, False),
        "image_info": ({"--version": 1}, _NONE, True),
        "image-info": ({"--version": 1}, _NONE, True),
        "elf2image": ({**_IMAGE, "--version": 1}, _NONE, True),
        "merge_bin": ({**_IMAGE, "--format": 1}, _NONE, True),
        "merge-bin": ({**_IMAGE, "--format": 1}, _NONE, True),
    },
)
#: The sketch tool: a compile, with none of the options that upload after it, and without the
#: one that sets a build property, which can redefine a recipe or a hook to run any program.
_SKETCH_TOOL: Guard = (
    {},
    {
        "version": ({}, _NONE, False),
        "compile": (
            {
                "-b": 1, "--fqbn": 1, "--build-path": 1, "--output-dir": 1, "--warnings": 1,
                "--libraries": 1, "-v": 0, "--verbose": 0, "--clean": 0,
                "-e": 0, "--export-binaries": 0,
            },
            _NONE,
            True,
        ),
    },
)  # fmt: skip
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


# ---- serial devices ----------------------------------------------------------------------


def _device_names() -> tuple[str, ...]:
    """The start of every device's path beneath the devices' directory, case-folded."""
    names = []
    for patterns in BOARD_DEVICES.values():
        for pattern in patterns:
            names.append(pattern.split("/", 2)[2].rstrip("*").casefold())
    return tuple(names)


_NAMES = _device_names()


def _device_dirs() -> tuple[str, ...]:
    """Every directory on the way to a device: the devices' own, and any between it and one."""
    dirs = {"/" + _DEVICES}
    for name in _NAMES:
        parts = name.split("/")
        for depth in range(1, len(parts)):
            dirs.add("/" + "/".join([_DEVICES, *parts[:depth]]))
    return tuple(sorted(dirs))


_DEVICE_DIRS = _device_dirs()
#: Where a command could be after a move that is not followed: anywhere, the places from
#: which a short relative name is a device among them.
_ANYWHERE = ("/", *_DEVICE_DIRS)


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


def places_of(commands: Sequence[SimpleCommand], cwd: str) -> tuple[list[str], bool]:
    """Every directory a call's commands could be in, and whether a move enters the devices.

    The call's own directory, as it resolves; the target of an absolute move; the target of
    the call's only move when it is written from that directory (``./``) and does not climb;
    and the places of :data:`_ANYWHERE` once any other move is made.
    """
    here = _normal(os.path.realpath(cwd))
    places = [here]
    targets = [target for target in map(_moves_to, commands) if target is not False]
    anywhere = False
    entering = False
    for target in targets:
        if target is None:
            anywhere = True
            continue
        assert isinstance(target, str)
        # A target that climbs is never followed: the shell climbs from the directory as
        # it was named, the kernel from where it really is, and only one of them is known.
        from_here = (
            len(targets) == 1
            and (target == "." or target.startswith("./"))
            and ".." not in target.split("/")
        )
        if target.startswith("/"):
            reached = [_normal(target)]
            places += reached
        elif from_here:
            reached = [_normal(here + "/" + target)]
            places += reached
        else:
            # Not followed: the command could be anywhere after it, which already holds
            # every name that would be a device from a directory of devices.
            anywhere = True
            reached = []
        # A target that climbs is read from the root as well, as every such name is.
        climbed = _rooted(target if "/" in target else target + "/")
        reached += [climbed] if climbed is not None else []
        entering = entering or any(r in _DEVICE_DIRS or _is_device(r) for r in reached)
    if anywhere:
        places += _ANYWHERE
    return places, entering


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


def _read_options(
    words: Sequence[str], start: int, options: Options, *, positionals: bool | None
) -> tuple[int, dict[str, list[str]]] | None:
    """Read ``words`` from ``start`` as options of a known shape, or ``None`` if they are not.

    Each word that starts with a dash must be one of ``options``, written whole: alone, with
    the one word it takes after it, or as ``--name=value`` for a long one that takes a value.
    ``positionals`` says what another word is: allowed (``True``), refused (``False``), or
    where the reading stops (``None``). Returns where it stopped and each option's values.
    """
    seen: dict[str, list[str]] = {}
    n = start
    while n < len(words):
        word = words[n]
        if not word.startswith("-"):
            if positionals is None:
                break
            if not positionals:
                return None
            n += 1
            continue
        name, glued, value = word.partition("=")
        takes = options.get(name)
        if takes is None:
            return None
        if glued:
            if takes != 1 or not name.startswith("--"):
                return None
        elif takes == 1:
            n += 1
            if n >= len(words):
                return None
            value = words[n]
        seen.setdefault(name, []).append(value)
        n += 1
    return n, seen


def build_only(program: str, words: Sequence[str]) -> bool:
    """Whether ``words`` are, read exactly, one of a guarded program's build-only uses.

    A program that is not guarded has no uses to hold it to. One run with its own options
    alone (``--version``) does nothing.
    """
    guard = GUARDED.get(program)
    if guard is None:
        return True
    before, uses = guard
    opened = _read_options(words, 0, before, positionals=None)
    if opened is None:
        return False
    n = opened[0]
    if n == len(words):
        return True
    name = words[n]
    if name not in uses and n + 1 < len(words):
        name, n = f"{name} {words[n + 1]}", n + 1
    use = uses.get(name)
    if use is None:
        return False
    options, required, positionals = use
    read = _read_options(words, n + 1, options, positionals=positionals)
    if read is None or not required <= set(read[1]):
        return False
    given = [target for option in _TARGET_OPTIONS for target in read[1].get(option, [])]
    return program not in BUILD_TOOLS or all(target in BUILD_TARGETS for target in given)


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
    places, entering = places_of(commands, cwd)
    if entering:
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
