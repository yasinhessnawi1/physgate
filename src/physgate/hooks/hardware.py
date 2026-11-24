"""No session uploads or flashes to hardware, or opens a board's device.

A session builds firmware and shows its behaviour in simulation. Nothing it runs reaches a
board: an upload would write a device no check has seen, and a serial port or a USB node is a
channel in and out of the machine that no other layer watches. So both are refused, for every
profile, the orchestrator's own session among them (work on a target, when it comes, is a
mechanism of its own with a person's sign-off, never an exception here), through each door a
session has:

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
- the interactive consoles the design libraries bring (``ipython``, ``ipython3``, ``isympy``)
  are guarded with no build-only use: an interpreter whose module and script this file does
  not read is refused in every use, alone included;
- the devices of each platform, which the OS layer reads from here too (``oslayer.policy``),
  so the two layers cannot name different devices.

**Commands are matched, not text.** The parser hands over each command a call would run, those
inside substitutions, ``sh -c``, ``eval`` and a script fed to a shell on its input included, and
the commands another program runs among its own words (``timeout 5 …``, ``xargs …``) are
found the way the git rule finds them, with that rule's own list of such programs. So are those
behind a wrapper's option that takes a value (``exec -a name …``, ``env --unset X …``,
``/usr/bin/time -o out …``): the parser steps over the option, and the value it leaves where
the program should be is not taken for it; the program is searched for among the words after.
An interpreter runs one as a module (``-m``, run together with other options, a package's
``__main__`` included) or as the script it is given. ``env -S`` is refused outright: it splits
a string into a command by env's own rules, which are not the shell's, and this file reads the
shell's. A document that names an upload is text and passes. A word of such a command that only
running it decides (``$TARGET``) is refused: the tool would not get the word that was read.

**A program named only when the command runs** (``$p``, or the module or script an interpreter
is given that way) cannot be known from the words, so it is refused only for the shapes named
here: the build tool's upload, monitor, tests, debugger or devices, and a flasher's options
(any ``-U``, or ``-p`` beside ``-U``, ``-e`` or ``-c``). Given other words, or none, it passes
this hook, and what holds is the OS layer's denial of the board's devices. The exact reading of
a guarded program's words, which refuses an upload by a route not named, is for a program
named in the command's own words.

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
  reading of words can tell otherwise. **This hook does not stop a flash such a build
  starts; the OS layer's denial of the device does**, and a real session holds that (a plain
  build whose project file runs a script that opens a device node finds it denied). That is
  also why the options that point a build at a project directory or a project file are
  allowed: the default one is the session's too;
- a flasher this file does not name, run under its own name;
- a programmer that talks to USB without a device node (on macOS, through the system's
  device framework).

For the first three the OS layer holds wherever the board is one of the devices in the table:
its sandbox denies them to every command of the session, read and write, so an upload that
got that far finds no board. **On Linux the sandbox's own device directory is what stops the
open**: each command gets a ``/dev`` of its own that holds no board at all, and a build's script
opening a device was measured to be refused with the table's patterns taken out of the
settings. There this hook's rule, and the table's denial with it (the USB nodes included), are
the second hold. On macOS a USB device is not a file and the table cannot
name it. The sandbox's profile, as the pinned binaries write it, denies by default and lets a
command open only three named kernel clients, none of them USB's or HID's; that has been read
in the profile, not measured with a device opened, and it is the residual of both layers.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import TYPE_CHECKING

from physgate.hooks import git_ops
from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import (
    ShellSyntaxError,
    SimpleCommand,
    command_key,
    parse,
    unwrap,
    wrapper_options,
)

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
NAMED_LATE = (
    "A program named only when the command runs was given options this check reads as a "
    "flasher's (-U, or -p beside -U, -e or -c), or the build tool's device words, so the "
    "command is refused. If it is an ordinary program, name the program in the command's own "
    "words."
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
SPLIT = (
    "env -S is refused: it splits a string into a command by env's own rules, which are not "
    "the shell's, so what it would run is not the command this check read. Write the command "
    "out as words."
)
NO_FORM = (
    "{program} is refused in every use: it is an interpreter that runs whatever it is given, "
    "a board's flasher among them, and this check does not read what it is told to run. Run "
    "Python as python, with a script or a module named in the command's own words."
)
UNREADABLE = (
    "This call's arguments could not be read to their end ({detail}), so whether they name "
    "an upload or a serial device is not known, and the call is refused."
)

#: The devices of each platform a board appears as, as the patterns the OS layer denies: its
#: serial ports (USB, built-in, ARM and Bluetooth ones on Linux), and on Linux the USB and HID
#: nodes a programmer opens directly. The machine's own terminal (``/dev/tty``) is not among
#: them. The text rule folds case, so it also refuses a name that differs from one of these
#: in case only (a pseudo-terminal of macOS among them), which the OS layer leaves alone.
BOARD_DEVICES: Mapping[str, tuple[str, ...]] = {
    "darwin": ("/dev/cu.*", "/dev/tty.*"),
    "linux": (
        "/dev/bus/usb",
        "/dev/hidraw*",
        "/dev/rfcomm*",
        "/dev/ttyACM*",
        "/dev/ttyAMA*",
        "/dev/ttyS*",
        "/dev/ttyUSB*",
    ),
}
#: The directory every one of them lies in.
_DEVICES = "dev"

#: Programs that only ever reach a board: flashers, the servers of debug probes, and serial
#: terminals, those the run's own tool environment installs among them (the build tool's
#: debugger front end, and the serial library's terminal by both its names).
FLASHERS = frozenset(
    {
        "avrdude", "dfu-util", "dfu-programmer", "bossac", "openocd", "st-flash", "st-info",
        "pyocd", "teensy_loader_cli", "picotool", "stm32flash", "jlinkexe", "nrfjprog",
        "micronucleus", "piodebuggdb", "pyserial-miniterm", "miniterm.py",
    }
)  # fmt: skip
#: Modules an interpreter runs that only ever reach a board: the serial library's terminal,
#: which opens the first port it finds when it is named none.
FLASHER_MODULES = frozenset({"serial.tools.miniterm"})
_ONLY_A_BOARD = FLASHERS | FLASHER_MODULES

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
#: The interactive consoles the design libraries put in the environment (an IPython shell by
#: both its names, and SymPy's): interpreters the module rule below does not read, so
#: ``ipython -m <flasher module>`` is not seen through. Guarded with no build-only use and no
#: option of their own, so every use is refused, the bare one included.
_NO_FORM: Guard = ({}, {})
#: The programs that both build and reach a board, each held to its build-only uses, and the
#: consoles that may run one, held to none.
GUARDED: Mapping[str, Guard] = {
    "pio": _BUILD_TOOL,
    "platformio": _BUILD_TOOL,
    "esptool": _IMAGE_TOOL,
    "esptool.py": _IMAGE_TOOL,
    "arduino-cli": _SKETCH_TOOL,
    "ipython": _NO_FORM,
    "ipython3": _NO_FORM,
    "isympy": _NO_FORM,
}
#: Interpreters that run one of the programs above as a module (``python -m platformio``) or
#: as the script they are given.
_MODULE_RUNNERS = re.compile(r"python[0-9.]*|pypy[0-9.]*")
#: Their options that take no value, which may run together in one word before another.
_PYTHON_FLAGS = "bBdEhiIOPqRsSuvVx"
#: ``-m``, after any of those, with the module glued to it if it is.
_MODULE_OPTION = re.compile(f"-[{_PYTHON_FLAGS}]*m(.*)", re.DOTALL)
#: The options whose value is the next word.
_PYTHON_VALUE = re.compile(f"-[{_PYTHON_FLAGS}]*[WX]|--check-hash-based-pycs")
#: Code handed over as a string, or read from standard input: no program is named by a word.
_PYTHON_CODE = re.compile(f"-[{_PYTHON_FLAGS}]*c.*|-", re.DOTALL)
_PROGRAMS = _ONLY_A_BOARD | frozenset(GUARDED)
#: A program named only when the command runs is refused given these first words of the build
#: tool's: its tests (which upload), its debugger (which loads the board), its devices.
_LATE_USES = frozenset({"test", "debug", "device"})
#: A flasher's options, read as words and not modelled further: any ``-U`` (a memory operation
#: or an image to write), and ``-p`` (a part) beside ``-U``, ``-e`` (an erase) or ``-c`` (a
#: programmer). Only ``-U`` is read glued to its value as well: ``-p`` and ``-c`` glued are a
#: compiler's ``-pthread`` and ``-pipe`` beside its ``-c``.
_FLASHER_OPTION = "-U"
_PART_OPTION = "-p"
_BESIDE_A_PART = frozenset({"-U", "-e", "-c"})

#: Each program that runs its arguments (the parser's own list): its short options that take no
#: value, those that take one, and its long options that take none, GNU's and BSD's together.
#: The parser steps over every option word; after one whose value is the next word, the first
#: word it leaves is that value, so the program is searched for among the words after it.
_WRAPPERS: Mapping[str, tuple[str, str, frozenset[str]]] = {
    "env": ("i0v", "uCSPLU", frozenset({"--ignore-environment", "--null", "--debug"})),
    "exec": ("cl", "a", frozenset()),
    "command": ("pvV", "", frozenset()),
    "nice": ("0123456789", "n", frozenset()),
    "nohup": ("", "", frozenset()),
    "time": ("aphlqv", "of", frozenset({"--append", "--portability", "--quiet", "--verbose"})),
    "builtin": ("", "", frozenset()),
    "sudo": ("AbEeHiKklnPSsVv", "CDghpRrTtUu", frozenset()),
}
#: The programs that run a command somewhere else by an option of their own, wrappers and
#: runners alike, all read by one reader (:func:`_moving_option`): the short options of each
#: that take no value (so a short option may stand among them in one word), the options (short
#: letter, long name) naming the directory the command runs in, and those that leave it where
#: no word says: a new root, a login's home.
_MOVING: Mapping[str, tuple[str, tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]] = {
    "env": ("i0v", (("C", "--chdir"),), ()),
    "sudo": ("AbEeHiKklnPSsVv", (("D", "--chdir"),), (("R", "--chroot"), ("i", "--login"))),
    "uv": ("qvn", (("", "--directory"),), ()),
    "uvx": ("qvn", (("", "--directory"),), ()),
    "poetry": ("qvnhV", (("C", "--directory"),), ()),
    "parallel": ("", (("", "--wd"), ("", "--workdir")), ()),
    "su": ("fmp", (), (("l", "--login"),)),
    "runuser": ("fmp", (), (("l", "--login"),)),
}
#: Words that are no option of that kind and leave the command anywhere all the same: a login
#: by a bare dash, and each found file's directory (``find``'s own words are matched whole).
_ANYWHERE_WORDS: Mapping[str, frozenset[str]] = {
    "su": frozenset({"-"}),
    "runuser": frozenset({"-"}),
    "find": frozenset({"-execdir", "-okdir"}),
}
_NEW_ROOT = frozenset({"chroot"})

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


def _option_in(word: str, flags: str, short: str, long: str) -> tuple[bool, str | None]:
    """Whether the option word ``word`` is ``-short`` or ``long``, and the value glued to it.

    As a program's own option reader takes it: among a run of short options after any of
    ``flags`` (those that take no value), or as any start of the long name (``--split`` is
    ``--split-string``). A word that is no option is neither.
    """
    if word.startswith("--"):
        name, glued, value = word.partition("=")
        return len(name) > 2 and long.startswith(name), (value if glued else None)
    if not word.startswith("-"):
        return False, None
    for n, char in enumerate(word[1:], 1):
        if char == short:
            return True, word[n + 1 :] or None
        if char not in flags:
            return False, None
    return False, None


def _hides_the_program(argv: Sequence[str], index: int, wrapper: str, taken: bool) -> bool:
    """Whether the wrapper's option at ``index`` may have left its value where the program is."""
    word = argv[index]
    if taken or word in ("-", "--"):
        return False
    flags, values, long_flags = _WRAPPERS.get(wrapper, ("", "", frozenset()))
    if word.startswith("--"):
        return "=" not in word and word not in long_flags
    for n, char in enumerate(word[1:], 1):
        if char in values:
            # Its value is the next word unless it is glued to the option.
            return n + 1 == len(word)
        if char not in flags:
            return True
    return False


def _value_at(
    argv: Sequence[str], index: int, glued: str | None, unread: frozenset[int]
) -> str | None:
    """An option's value: glued to the option at ``index``, or the next word; ``None`` unread."""
    at = index if glued is not None else index + 1
    target = glued if glued is not None else (argv[at] if at < len(argv) else None)
    return None if target is None or at in unread else target


def _moving_option(
    program: str, argv: Sequence[str], index: int, unread: frozenset[int]
) -> tuple[bool, str | None] | None:
    """Whether the word at ``index`` moves the command ``program`` runs, and where to.

    ``None`` for a word that does not; else ``(True, target)``, the target ``None`` where only
    running decides it or no word says it, as for a new root or a login.
    """
    word = argv[index]
    if word in _ANYWHERE_WORDS.get(program, ()):
        return True, None
    flags, to, anywhere = _MOVING.get(program, ("", (), ()))
    for short, long in to:
        named, glued = _option_in(word, flags, short, long)
        if named:
            return True, _value_at(argv, index, glued, unread)
    if any(_option_in(word, flags, short, long)[0] for short, long in anywhere):
        return True, None
    return None


def _runner_moves(argv: Sequence[str], stepped: int, unread: frozenset[int]) -> list[str | None]:
    """The moves a program that runs a command makes by any of its words, from ``argv`` on."""
    key = command_key(argv[0])
    if key in _NEW_ROOT:
        return [None]
    relative = frozenset(u - stepped for u in unread)
    found = (_moving_option(key, argv, n, relative) for n in range(1, len(argv)))
    return [move[1] for move in found if move is not None]


def _moves_to(cmd: SimpleCommand) -> str | None | bool:
    """Where a command moves the shell, or the program it runs, if it does.

    A written target; ``None`` for a move only running decides, one that goes where no word
    says, or more than one; ``False`` for a command that moves nowhere. ``cd`` and its kin move
    the shell; a wrapper's or a runner's own option (``env -C``, ``sudo -D``, ``uv
    --directory``) moves the program it runs, and ``find -execdir``, ``chroot``, ``sudo -R``
    and a login (``su -``) leave it anywhere.
    """
    unread = cmd.dynamic | cmd.expanding
    moves: list[str | None] = []
    options = wrapper_options(cmd.argv)
    for index, wrapper, _ in options:
        move = _moving_option(wrapper, cmd.argv, index, unread)
        if move is not None:
            moves.append(move[1])
    argv = unwrap(cmd.argv)
    stepped = len(cmd.argv) - len(argv)
    if argv and command_key(argv[0]) in _CD:
        moves.append(_cd_target(argv, stepped, unread))
    if argv:
        among = any(_hides_the_program(cmd.argv, *option) for option in options)
        for n in range(len(argv) if _searched(argv, among) else 1):
            moves += _runner_moves(argv[n:], stepped + n, unread)
    if not moves:
        return False
    return moves[0] if len(moves) == 1 else None


def _cd_target(argv: Sequence[str], stepped: int, unread: frozenset[int]) -> str | None:
    """The target ``cd`` and its kin are given, as written, or ``None``."""
    for n, word in enumerate(argv[1:], 1):
        if word.startswith(("-", "+")) and word not in ("-", "+"):
            continue
        # A target such as ``-`` or ``~`` is returned as written: it is not written from a
        # known place, so it is not followed.
        return None if stepped + n in unread else word
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
            # Nothing is added to the places: a directory beneath this one from which a
            # short name is a device is a directory of devices, and entering it is refused.
            reached = [_normal(here + "/" + target)]
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
    if program in _ONLY_A_BOARD:
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
    alone (``--version``) does nothing, unless the program has no build-only use at all: a
    console run alone reads what to run from its input.
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
        return bool(uses)
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


def _not_build(program: str) -> str:
    """The refusal of a guarded program's use that is not build-only, for its kind of guard."""
    reason = NO_FORM if not GUARDED[program][1] else NOT_BUILD
    return reason.format(program=program)


def refusal_of(program: str, words: Sequence[str]) -> str | None:
    """The reason ``program`` may not be run with ``words``, or ``None``."""
    if upload_in(program, words):
        return UPLOAD
    return None if build_only(program, words) else _not_build(program)


def _module_program(module: str, at: int) -> tuple[int, str] | None:
    """The program a module an interpreter runs is, by its package, at ``at``, or ``None``."""
    key = command_key(module).removesuffix(".__main__")
    if key in FLASHER_MODULES:
        return at, key
    package = key.split(".", 1)[0]
    return (at, package) if package in _PROGRAMS else None


def _interpreter_target(argv: Sequence[str]) -> tuple[int, str, bool] | None:
    """Where the module or the script an interpreter runs is named, or ``None`` for neither.

    The word's position, the module or script as written, and whether it is a module (``-m``,
    after other options run together with it, or glued to the module's name).
    """
    n = 1
    while n < len(argv):
        word = argv[n]
        option = _MODULE_OPTION.fullmatch(word)
        if option is not None:
            if option.group(1):
                return n, option.group(1), True
            return (n + 1, argv[n + 1], True) if n + 1 < len(argv) else None
        if _PYTHON_CODE.fullmatch(word):
            return None
        if _PYTHON_VALUE.fullmatch(word):
            n += 2
            continue
        if word.startswith("-"):
            n += 1
            continue
        return n, word, False
    return None


def _run_by_interpreter(argv: Sequence[str]) -> tuple[int, str] | None:
    """Where an interpreter's words name a program this rule judges, and which, or ``None``.

    The module it is given (a package's ``__main__`` included), or the script it runs, when
    that script is such a program by its name.
    """
    target = _interpreter_target(argv)
    if target is None:
        return None
    n, named, module = target
    if module:
        return _module_program(named, n)
    key = command_key(named)
    return (n, key) if key in _PROGRAMS else None


def _program_here(argv: Sequence[str]) -> tuple[int, str] | None:
    """The program this rule judges that ``argv`` runs in command position, or ``None``."""
    head = command_key(argv[0])
    if head in _PROGRAMS:
        return 0, head
    if _MODULE_RUNNERS.fullmatch(head):
        return _run_by_interpreter(argv)
    return None


def _searched(argv: Sequence[str], among: bool) -> bool:
    """Whether a program is searched for among ``argv``'s words, not only in command position.

    Behind a wrapper's option whose value may stand where the program is (``among``), and among
    the words of a program that runs its arguments: the git rule's own list of them, one list
    for both rules.
    """
    return among or command_key(argv[0]) in git_ops._RUNNERS


def _program_at(argv: Sequence[str], *, among: bool = False) -> tuple[int, str] | None:
    """Where in ``argv`` a program this rule judges starts, and which one, or ``None``.

    In command position always, an interpreter's module or script included. Where it is
    searched for (:func:`_searched`), the first one found. Among any other program's words it
    is text.
    """
    if not argv:
        return None
    found = _program_here(argv)
    if found is not None or not _searched(argv, among):
        return found
    for n in range(1, len(argv)):
        inner = _program_here(argv[n:])
        if inner is not None:
            return n + inner[0], inner[1]
    return None


def _named_late(
    argv: Sequence[str], stepped: int, unread: frozenset[int], *, among: bool
) -> str | None:
    """The reason a program named only when the command runs is refused, or ``None``.

    Wherever a program could stand (:func:`_program_at`), the module or script an interpreter
    there runs among them, a word only running decides is read as the build tool or a flasher:
    given an upload, the build tool's monitor or a flasher's words it is refused as an upload,
    and given the build tool's tests, its debugger or its devices as a word that may not be
    left to running. With any other words, or none, it passes: what it runs is the OS layer's.
    """
    if not argv:
        return None
    for n in range(len(argv) if _searched(argv, among) else 1):
        late = [n] if stepped + n in unread else []
        if _MODULE_RUNNERS.fullmatch(command_key(argv[n])):
            target = _interpreter_target(argv[n:])
            if target is not None and stepped + n + target[0] in unread:
                late.append(n + target[0])
        for at in late:
            words = argv[at + 1 :]
            if upload_in("pio", words) or _flasher_words(words):
                return NAMED_LATE
            opened = _read_options(words, 0, _BUILD_TOOL[0], positionals=None)
            first = words[opened[0]] if opened is not None and opened[0] < len(words) else ""
            if first.casefold() in _LATE_USES:
                return DYNAMIC
    return None


def _flasher_words(words: Sequence[str]) -> bool:
    """Whether ``words`` carry a flasher's options (:data:`_FLASHER_OPTION`, :data:`_PART_OPTION`).

    Any ``-U``, or ``-p`` beside ``-U``, ``-e`` or ``-c``. Every occurrence counts, whatever its
    value; the flasher's grammar is not modelled, so a program named only when the command runs
    and given other words passes here, and the OS layer's device denial is what holds for it.
    """
    if any(word.startswith(_FLASHER_OPTION) for word in words):
        return True
    return _PART_OPTION in words and bool(_BESIDE_A_PART & set(words))


def _check_command(cmd: SimpleCommand, places: Sequence[str]) -> str | None:
    """The reason ``cmd`` is refused, or ``None``."""
    for text in _words_of(cmd):
        device = serial_device_in(text, places)
        if device is not None:
            return DEVICE.format(device=device)
    options = wrapper_options(cmd.argv)
    for index, wrapper, _ in options:
        split = _option_in(cmd.argv[index], _WRAPPERS["env"][0], "S", "--split-string")
        if wrapper == "env" and split[0]:
            return SPLIT
    argv = unwrap(cmd.argv)
    unread = cmd.dynamic | cmd.expanding
    stepped = len(cmd.argv) - len(argv)
    among = any(_hides_the_program(cmd.argv, *option) for option in options)
    found = _program_at(argv, among=among)
    if found is None:
        return _named_late(argv, stepped, unread, among=among)
    start, program = found
    words = argv[start + 1 :]
    if upload_in(program, words):
        return UPLOAD
    if any(n >= stepped + start for n in unread):
        return DYNAMIC
    return None if build_only(program, words) else _not_build(program)


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
