"""The tool environment as a run records it, measured from the environment itself.

A run names an interpreter and the environment's roots (the interpreter's installation, and any
further tree such as a firmware toolchain's package store), and the native tools to report. What
is recorded is what was measured, never what the parameters claim: the interpreter's resolved
path, version and prefix, every distribution it can import with its version, each native tool's
own version line, and the manifest digest over every file of every root.

**Where it may not lie.** An environment inside the harness checkout, the hooks' installation, a
session's worktree, temporary directory or home, or a directory every session shares would be
code a session or the harness itself could change, so a root inside any of the ``forbidden``
places (or holding one) is refused, as is an interpreter that can import the harness: the
harness's own interpreter would hand a session the orchestrator's code.

**Held to the record.** Before every session the environment is scanned again and compared with
the scan taken when the run started (:func:`require_unchanged`); at every resume it is measured
again in full and compared with the record (:func:`require_same`).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.manifest import manifest, scan

AbsolutePath = Annotated[str, StringConstraints(pattern=r"^/")]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Version = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

#: What the interpreter is asked, from an isolated start: one line of JSON.
PROBE = (
    "import importlib.metadata as m, importlib.util as u, json, sys;"
    "print(json.dumps({'version': sys.version.split()[0], 'prefix': sys.prefix,"
    "'base_prefix': sys.base_prefix,"
    "'physgate': u.find_spec('physgate') is not None,"
    "'distributions': sorted({(d.metadata['Name'] or '', d.version or '')"
    " for d in m.distributions()})}))"
)
#: The most an answer to the probe, or a tool's version line, may hold.
MAX_ANSWER_BYTES = 1 << 20
#: How long the interpreter or a tool has to answer.
ANSWER_TIMEOUT_S = 60

#: Runs a program with arguments and returns its standard output, or ``None`` if it failed.
Runner = Callable[[Sequence[str]], str | None]


class Distribution(BaseModel):
    """One distribution the interpreter can import."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Name
    version: Version


class NativeTool(BaseModel):
    """A program of the environment, by the name sessions know it and its own version line."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Name
    path: AbsolutePath
    version: Version


class ToolEnvironment(BaseModel):
    """The tool environment a run's role sessions use, as measured when the run started."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The interpreter as named, and where it leads once every link is followed.
    interpreter: AbsolutePath
    resolved: AbsolutePath
    python_version: Version
    prefix: AbsolutePath
    distributions: tuple[Distribution, ...]
    native_tools: tuple[NativeTool, ...]
    #: Every root the manifest covers, as named (each its own real path).
    roots: tuple[AbsolutePath, ...] = Field(min_length=1)
    manifest_digest: Digest
    entries: int = Field(gt=0)
    total_bytes: int = Field(ge=0)


def run_program(argv: Sequence[str]) -> str | None:
    """Run ``argv`` from an empty environment at the filesystem root; its bounded output.

    The answer is read only up to :data:`MAX_ANSWER_BYTES`; a longer answer is no answer.
    """
    try:
        done = subprocess.run(
            list(argv),
            capture_output=True,
            timeout=ANSWER_TIMEOUT_S,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LC_ALL": "C"},
            cwd="/",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or len(done.stdout) > MAX_ANSWER_BYTES:
        return None
    try:
        return done.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _overlaps(root: str, place: Path) -> bool:
    spellings = {os.path.abspath(place), os.path.realpath(place)}
    return any(_under(root, p) or _under(p, root) for p in spellings)


def _probe(interpreter: str, runner: Runner) -> dict[str, object]:
    answer = runner([interpreter, "-I", "-c", PROBE])
    if answer is None:
        msg = "the tool environment's interpreter did not answer the probe"
        raise ToolEnvironmentError(msg, interpreter=interpreter)
    try:
        found = json.loads(answer)
    except ValueError:
        found = None
    if not isinstance(found, dict):
        msg = "the tool environment's interpreter answered something that is not one JSON object"
        raise ToolEnvironmentError(msg, interpreter=interpreter)
    return found


def _distributions(value: object) -> tuple[Distribution, ...]:
    if not isinstance(value, list):
        msg = "the interpreter's distributions are not a list"
        raise ToolEnvironmentError(msg)
    found: list[Distribution] = []
    for item in value:
        if not (
            isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item)
        ):
            msg = "a distribution is not a name and a version"
            raise ToolEnvironmentError(msg)
        found.append(Distribution(name=item[0], version=item[1]))
    return tuple(found)


def _version_line(name: str, path: str, runner: Runner) -> str:
    answer = runner([path, "--version"])
    line = (answer or "").strip().splitlines()[0:1]
    if not line or not line[0].isprintable():
        msg = "a native tool of the environment gave no printable version line"
        raise ToolEnvironmentError(msg, tool=name, path=path)
    return line[0][:200]


def measure(
    interpreter: str,
    roots: Sequence[str],
    *,
    native: Mapping[str, str],
    forbidden: Mapping[str, Path],
    runner: Runner = run_program,
) -> ToolEnvironment:
    """What the environment at ``roots`` is, with the interpreter at ``interpreter``.

    ``native`` maps the name a session knows a tool by to its absolute path; ``forbidden`` maps
    a description to each place the environment may not lie in or hold.

    Raises:
        ToolEnvironmentError: a path is not absolute; a root overlaps a forbidden place; the
            interpreter or a native tool lies outside the roots, is not executable or does not
            answer; the interpreter can import the harness; or the manifest refuses an entry.
    """
    for path in (interpreter, *roots, *native.values()):
        if not os.path.isabs(path):
            msg = "the tool environment is named by absolute paths"
            raise ToolEnvironmentError(msg, path=path)
    for root in roots:
        for what, place in forbidden.items():
            if _overlaps(os.path.abspath(root), place) or _overlaps(os.path.realpath(root), place):
                msg = f"the tool environment overlaps {what}"
                raise ToolEnvironmentError(msg, root=root, place=str(place))
    named = {"python": interpreter, **native}
    for name, path in named.items():
        real = os.path.realpath(path)
        if not any(_under(real, os.path.realpath(root)) for root in roots):
            msg = "a program of the tool environment lies outside its roots"
            raise ToolEnvironmentError(msg, tool=name, path=path, resolved=real)
        if not (os.path.isfile(real) and os.access(real, os.X_OK)):
            msg = "a program of the tool environment is not an executable file"
            raise ToolEnvironmentError(msg, tool=name, path=path)
    found = _probe(interpreter, runner)
    if found.get("physgate") is not False:
        msg = "the tool environment's interpreter can import the harness"
        raise ToolEnvironmentError(msg, interpreter=interpreter)
    version, prefix = found.get("version"), found.get("prefix")
    if not (isinstance(version, str) and isinstance(prefix, str) and os.path.isabs(prefix)):
        msg = "the interpreter's answer has no version or no absolute prefix"
        raise ToolEnvironmentError(msg, interpreter=interpreter)
    if not any(_under(os.path.realpath(prefix), os.path.realpath(r)) for r in roots):
        msg = "the interpreter's prefix lies outside the tool environment's roots"
        raise ToolEnvironmentError(msg, prefix=prefix)
    tools = tuple(
        NativeTool(name=name, path=path, version=_version_line(name, path, runner))
        for name, path in sorted(native.items())
    )
    walked = manifest([Path(root) for root in roots])
    return ToolEnvironment(
        interpreter=interpreter,
        resolved=os.path.realpath(interpreter),
        python_version=version,
        prefix=os.path.realpath(prefix),
        distributions=_distributions(found.get("distributions")),
        native_tools=tools,
        roots=tuple(roots),
        manifest_digest=walked.digest,
        entries=walked.entries,
        total_bytes=walked.total_bytes,
    )


def require_same(
    recorded: ToolEnvironment,
    *,
    forbidden: Mapping[str, Path],
    runner: Runner = run_program,
) -> None:
    """Measure the environment again in full; refuse anything but the recorded one.

    Raises:
        ToolEnvironmentError: it is refused now (:func:`measure`), or it measures differently.
    """
    native = {tool.name: tool.path for tool in recorded.native_tools}
    now = measure(
        recorded.interpreter, recorded.roots, native=native, forbidden=forbidden, runner=runner
    )
    if now != recorded:
        changed = sorted(k for k, v in recorded.model_dump().items() if now.model_dump()[k] != v)
        msg = "the tool environment is not the one this run recorded"
        raise ToolEnvironmentError(msg, changed=",".join(changed))


def require_unchanged(recorded: ToolEnvironment, at_start: str) -> None:
    """Refuse a session when any entry of the environment changed since ``at_start``'s scan.

    Raises:
        ToolEnvironmentError: the scan differs, or an entry is refused (:func:`scan`).
    """
    if scan([Path(root) for root in recorded.roots]) != at_start:
        msg = "an entry of the tool environment changed since the run started"
        raise ToolEnvironmentError(msg, roots=",".join(recorded.roots))
