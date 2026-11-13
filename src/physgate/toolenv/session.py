"""How a session is wired to the tool environment: from a file the environment itself carries.

Which programs a session finds by name, which directories and links its tools need in the
session's temporary directory, and which variables they read are facts of the tools. They are
therefore data in the environment, one optional file at a root (:data:`SESSION_FILE`), written
when the environment is provisioned and covered by its digest like every other file, and never
names in this package: adding a tool adds entries to that file, not code here.

The file is read as data, bounded, and applied only where it can be held:

- a **program** is a name a session finds on its search path and a path inside the root that
  is an executable file once every link is followed; the interpreter's own name is not the
  file's to give;
- a **directory** is made in the session's temporary directory, and a **link** is made there
  beneath one of them, to a path that exists inside the root: a tool that takes lock files
  beside its store is given a directory of the session's own that links into the read-only
  store;
- a **variable** has an upper-case name that the session's environment does not already hold
  and that no loader, interpreter or shell reads at start-up, and a printable value in which
  ``{temp}`` and ``{root}`` stand for the session's temporary directory and the root.

Everything is judged before anything is made, so a refused file leaves a session nothing
half-wired. Nothing is ever written into the environment.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import stat
from collections.abc import Collection
from pathlib import Path
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
)

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import ToolEnvironment

#: The file at a root of the environment that says how a session is wired to it.
SESSION_FILE = "session.json"
#: The most the file may hold; a longer one is refused unparsed.
MAX_SESSION_FILE_BYTES = 1 << 20
#: The name a session calls the environment's interpreter by, which only the record gives.
INTERPRETER_NAME = "python3"

ProgramName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")]


def _no_dot_parts(path: str) -> str:
    if any(part in (".", "..") for part in path.split("/")):
        msg = "a path here has no '.' or '..' part"
        raise ValueError(msg)
    return path


#: A path beneath a root or the temporary directory: parts of plain characters, none of them
#: ``.`` or ``..``, no leading or doubled separator.
RelativePath = Annotated[
    str,
    StringConstraints(max_length=512, pattern=r"^[A-Za-z0-9._+@-]+(/[A-Za-z0-9._+@-]+)*$"),
    AfterValidator(_no_dot_parts),
]
VariableName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
VariableValue = Annotated[str, StringConstraints(max_length=1024, pattern=r"^[\x20-\x7e]*$")]

#: Variables no file may set: where a session's programs are found, where it keeps its files,
#: and what a shell or another runtime runs or loads at start-up.
REFUSED_VARIABLES = frozenset(
    {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "SHELL", "ENV", "BASH_ENV", "ZDOTDIR", "IFS"}
    | {"NODE_OPTIONS", "NODE_PATH", "PERL5LIB", "PERL5OPT", "RUBYOPT", "RUBYLIB", "CDPATH"}
)
#: And every variable beginning so: the dynamic loaders', the interpreter's own, the
#: harness's and its runtime's.
REFUSED_PREFIXES = ("LD_", "DYLD_", "PYTHON", "ANTHROPIC_", "CLAUDE_", "PHYSGATE_", "GIT_")
_PLACEHOLDERS = ("{temp}", "{root}")


class SessionWiring(BaseModel):
    """What one root's file says a session needs."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    programs: dict[ProgramName, RelativePath] = {}
    directories: tuple[RelativePath, ...] = ()
    links: dict[RelativePath, RelativePath] = {}
    variables: dict[VariableName, VariableValue] = {}


def _refuse(why: str, **context: str) -> ToolEnvironmentError:
    return ToolEnvironmentError(f"the tool environment's session file is refused: {why}", **context)


def read_wiring(root: Path) -> SessionWiring | None:
    """The wiring ``root``'s file names, or ``None`` where the root carries no file.

    Raises:
        ToolEnvironmentError: the file is a link or not a regular file, too large, not text,
            not JSON, or not of the shape :class:`SessionWiring` holds.
    """
    path = root / SESSION_FILE
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _refuse("it cannot be opened as a plain file", path=str(path)) from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise _refuse("it is not a regular file", path=str(path))
        raw = handle.read(MAX_SESSION_FILE_BYTES + 1)
    if len(raw) > MAX_SESSION_FILE_BYTES:
        raise _refuse("it is too large to be one", path=str(path))
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        # Parsed as data only; text nested past the parser's depth is no file either.
        raise _refuse("it is not JSON text", path=str(path)) from None
    try:
        return SessionWiring.model_validate_json(json.dumps(found))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ()))[:120]
        raise _refuse(f"it does not have the file's shape at {where!r}", path=str(path)) from None


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _value(name: str, value: str, temp: Path, root: Path) -> str:
    rest = value
    for placeholder in _PLACEHOLDERS:
        rest = rest.replace(placeholder, "")
    if "{" in rest or "}" in rest:
        why = "a variable's value holds a placeholder other than {temp} and {root}"
        raise _refuse(why, variable=name)
    return value.replace("{temp}", str(temp)).replace("{root}", str(root))


def _judged(
    root: Path,
    wiring: SessionWiring,
    temp: Path,
    taken: Collection[str],
) -> tuple[dict[str, Path], list[Path], dict[Path, Path], dict[str, str]]:
    """One root's wiring as what is to be made, each entry held to the root or refused."""
    real_root = os.path.realpath(root)
    programs: dict[str, Path] = {}
    for name, relative in wiring.programs.items():
        if name == INTERPRETER_NAME:
            raise _refuse("the interpreter's name is given by the run's record alone", program=name)
        target = root / relative
        real = os.path.realpath(target)
        if not (_inside(real, real_root) and os.path.isfile(real) and os.access(real, os.X_OK)):
            raise _refuse("a program is not an executable file inside the root", program=name)
        programs[name] = target
    directories = [temp / relative for relative in wiring.directories]
    made = {str(directory) for directory in directories}
    links: dict[Path, Path] = {}
    for name, relative in wiring.links.items():
        link = temp / name
        if str(link) in made or str(link.parent) not in made:
            raise _refuse("a link is not beneath a directory the file makes", link=name)
        target = root / relative
        real = os.path.realpath(target)
        if not (_inside(real, real_root) and os.path.exists(real)):
            raise _refuse("a link's target does not exist inside the root", link=name)
        links[link] = target
    variables: dict[str, str] = {}
    for name, value in wiring.variables.items():
        if name in REFUSED_VARIABLES or name.startswith(REFUSED_PREFIXES) or name in taken:
            raise _refuse("a variable is one the session's start is built on", variable=name)
        variables[name] = _value(name, value, temp, root)
    return programs, directories, links, variables


def _launcher(path: Path, interpreter: Path) -> None:
    """Write ``path`` as a program that runs ``interpreter`` under the interpreter's own name.

    Not a link: an interpreter of a virtual environment finds its packages from the path it
    was started by, so started through a link elsewhere it is the bare interpreter beneath,
    with none of the environment's libraries (measured: ``import control`` failed).
    """
    path.write_text(f'#!/bin/sh\nexec {shlex.quote(str(interpreter))} "$@"\n', encoding="utf-8")
    path.chmod(0o555)


def wire(
    recorded: ToolEnvironment, *, bin_dir: Path, temp: Path, taken: Collection[str]
) -> dict[str, str]:
    """Wire one session to the recorded environment; the variables its environment gains.

    ``bin_dir`` is made afresh holding ``python3``, which starts the interpreter by its own
    path, and a link to each program by its name, to be put on the session's search path;
    the directories and links are made in
    ``temp``, the session's own temporary directory; ``taken`` names every variable the
    session's environment already holds. Call it only once the environment has been held to
    the run's record, so the files read here are the recorded ones.

    Raises:
        ToolEnvironmentError: a root's file is refused (:func:`read_wiring`), an entry cannot
            be held to its root or to the temporary directory, or two roots name the same
            program, link or variable. Nothing has been made then.
    """
    programs: dict[str, Path] = {INTERPRETER_NAME: Path(recorded.interpreter)}
    directories: list[Path] = []
    links: dict[Path, Path] = {}
    variables: dict[str, str] = {}
    for named in recorded.roots:
        root = Path(named)
        wiring = read_wiring(root)
        if wiring is None:
            continue
        more_programs, more_directories, more_links, more_variables = _judged(
            root, wiring, temp, taken
        )
        clash = sorted(
            (programs.keys() & more_programs.keys())
            | (variables.keys() & more_variables.keys())
            | {str(link) for link in links.keys() & more_links.keys()}
        )
        if clash:
            raise _refuse("two roots name the same program, link or variable", name=clash[0])
        programs.update(more_programs)
        directories += more_directories
        links.update(more_links)
        variables.update(more_variables)
    # Judged in full above; made only now.
    if bin_dir.is_symlink() or bin_dir.is_file():
        bin_dir.unlink()
    elif bin_dir.exists():
        shutil.rmtree(bin_dir)
    bin_dir.mkdir(parents=True)
    for name, target in programs.items():
        if name == INTERPRETER_NAME:
            _launcher(bin_dir / name, target)
        else:
            (bin_dir / name).symlink_to(target)
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
    for link, target in links.items():
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    return variables
