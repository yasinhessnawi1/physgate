"""The Python a role session finds on its PATH: a standard-library interpreter, named and recorded.

A role session's environment is built from nothing (``invocation.isolated_env``), so it
has whatever Python the machine keeps in ``/usr/bin``, and some machines keep none: on
the server, both control sessions of the first run there spent requests hunting for one.
A run may therefore name an interpreter in its parameters (``role_python``). The run
records what it measured of it, never what the parameters claim: the resolved path, the
version, the prefix and the distributions it can import.

**It must not be the harness's own.** An interpreter that can import ``physgate``, or
whose prefix lies inside the harness checkout or the hooks' installation, would hand a
role session the orchestrator's code and site-packages, so it is refused. Only role
sessions get it; a reviewer has no shell.

Each session is given it as ``python3`` in a directory of its own put first on its PATH,
and the interpreter is measured again before every session, so a run never spawns a
session on an interpreter other than the one it recorded.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.exceptions import RunConfigError

#: The name a role session calls the interpreter by.
NAME = "python3"
#: What is asked of the interpreter: one line of JSON, from an isolated start (``-I``: no
#: environment variables, no user site, no current directory on its path). The process is
#: run by the dispatcher's ``probe_interpreter``, one of the modules whose job is a process.
PROBE = (
    "import importlib.metadata as m, importlib.util as u, json, sys;"
    "print(json.dumps({'version': sys.version.split()[0], 'prefix': sys.prefix,"
    "'physgate': u.find_spec('physgate') is not None,"
    "'distributions': sorted({d.metadata['Name'] for d in m.distributions()})}))"
)
#: Runs an interpreter on :data:`PROBE` and returns what it printed, or ``None``.
Probe = Callable[[Path], Mapping[str, object] | None]


class RolePython(BaseModel):
    """The interpreter a run's role sessions find as ``python3``, as measured."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The path as named, which is what a session's ``python3`` links to and what runs.
    path: Annotated[str, StringConstraints(pattern=r"^/")]
    #: Where that path leads once every link is followed.
    resolved: Annotated[str, StringConstraints(pattern=r"^/")]
    version: NonEmptyStr
    prefix: Annotated[str, StringConstraints(pattern=r"^/")]
    #: Every distribution the interpreter can import, by name.
    distributions: tuple[NonEmptyStr, ...]


def _within(path: Path, root: Path | None) -> bool:
    """Whether ``path``, as spelt (made absolute, no link followed), lies under ``root``."""
    if root is None:
        return False
    spelt = Path(os.path.abspath(path))
    return spelt.is_relative_to(Path(os.path.abspath(root))) or spelt.is_relative_to(root.resolve())


def measure(
    path: str, *, probe: Probe, harness: Path | None, install: Path | None = None
) -> RolePython:
    """What the interpreter at ``path`` is, refused if it is the harness's own.

    Raises:
        RunConfigError: ``path`` is not an absolute path to an executable that answers
            the probe, or it can import the harness, or its prefix lies inside the
            harness checkout or the hooks' installation.
    """
    given = Path(path)
    if not given.is_absolute():
        msg = "the role sessions' Python is named by an absolute path"
        raise RunConfigError(msg, role_python=path)
    given = Path(os.path.abspath(given))
    resolved = given.resolve()
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        msg = "the role sessions' Python is not an executable file"
        raise RunConfigError(msg, role_python=path)
    for root, what in ((harness, "the harness checkout"), (install, "the hooks' installation")):
        if _within(given, root) or _within(resolved, root) or _within(given.parent.resolve(), root):
            msg = f"the role sessions' Python lies inside {what}"
            raise RunConfigError(msg, role_python=path, root=str(root))
    found = probe(given)
    if not isinstance(found, Mapping):
        msg = "the role sessions' Python did not answer as a Python 3 interpreter"
        raise RunConfigError(msg, role_python=path)
    if found.get("physgate"):
        msg = "the role sessions' Python can import the harness: it is the harness's own"
        raise RunConfigError(msg, role_python=path, prefix=str(found.get("prefix")))
    prefix = Path(str(found.get("prefix")))
    for root, what in ((harness, "the harness checkout"), (install, "the hooks' installation")):
        if _within(prefix, root):
            msg = f"the role sessions' Python has its prefix inside {what}"
            raise RunConfigError(msg, role_python=path, prefix=str(prefix))
    return RolePython(
        path=str(given),
        resolved=str(resolved),
        version=str(found.get("version")),
        prefix=str(prefix.resolve()),
        distributions=tuple(str(d) for d in _names(found.get("distributions"))),
    )


def _names(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def require_same(
    recorded: RolePython, *, probe: Probe, harness: Path | None, install: Path | None
) -> None:
    """Refuse to give a session an interpreter other than the one the run recorded.

    Raises:
        RunConfigError: it is refused now (``measure``), or it measures differently.
    """
    now = measure(recorded.path, probe=probe, harness=harness, install=install)
    if now != recorded:
        changed = sorted(k for k, v in recorded.model_dump().items() if now.model_dump()[k] != v)
        msg = "the role sessions' Python is not the one this run recorded"
        raise RunConfigError(msg, role_python=recorded.path, changed=",".join(changed))


def session_bin(sdir: Path, recorded: RolePython) -> Path:
    """A directory holding only ``python3``, a link to the recorded interpreter, for one session."""
    directory = sdir / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    link = directory / NAME
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(recorded.path)
    return directory
