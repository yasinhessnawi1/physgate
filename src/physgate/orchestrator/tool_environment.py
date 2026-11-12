"""A run's tool environment: named by the parameters, measured, and held before every session.

The record, the measure and the comparison are the tool environment's own
(:mod:`physgate.toolenv`). This module is what the orchestrator adds: reading the three names
a run's parameters may give, saying where on this machine an environment may not lie, and
holding the environment to the run's record before a session is made.

**What the parameters may name.** The interpreter, the roots and the native tools, by absolute
paths. Everything else in the record is measured; a parameters file that states a version or a
digest is refused, so nothing in the record is a claim.

**Where it may not lie.** Not in the harness checkout or the hooks' installation, which would
hand a session the orchestrator's code; not in the run's directory or the target repository,
which hold the sessions' worktrees, homes and records; and not in any temporary directory a
session writes. Anywhere else the OS layer denies a session's writes, since it lets a session
write only its worktree, its home and the temporary directories.

**Before every session.** The first session a process dispatches is preceded by a full measure
against the record, so a new run and every resume start from the recorded bytes; each later one
by a scan against that measure. Any difference refuses the session before its worktree is
opened or anything of it is installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from physgate.orchestrator.common import first_problem
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.oslayer.placement import machine_writable
from physgate.oslayer.session_temp import session_temps_root
from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import (
    AbsolutePath,
    Name,
    Runner,
    ToolEnvironment,
    hold,
    measure,
    require_unchanged,
    run_program,
)


class NamedToolEnvironment(BaseModel):
    """What a run's parameters say of its tool environment: three names and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    interpreter: AbsolutePath
    roots: tuple[AbsolutePath, ...] = Field(min_length=1)
    #: The name a session knows each native tool by, and its path.
    native: dict[Name, AbsolutePath] = Field(default_factory=dict)


def forbidden_places(
    *, harness: Path | None, install: Path | None, run_dir: Path, target: Path | None
) -> dict[str, Path]:
    """Every place on this machine a run's tool environment may not lie in or hold.

    ``harness`` and ``install`` are ``None`` where the orchestrator runs from no checkout or
    the installation is not yet named; ``target`` where no target repository is.
    """
    places: dict[str, Path] = {"the run's directory": run_dir}
    if harness is not None:
        places["the harness checkout"] = harness
    if install is not None:
        places["the hooks' installation"] = install
    if target is not None:
        places["the target repository"] = target
    places["the sessions' temporary directories"] = Path(session_temps_root())
    for index, place in enumerate(machine_writable()):
        places[f"a temporary directory every session writes ({index + 1})"] = Path(place)
    return places


def measure_named(
    named: object, *, forbidden: Mapping[str, Path], runner: Runner = run_program
) -> ToolEnvironment:
    """The environment a run's parameters name, as measured.

    Raises:
        RunConfigError: the parameters do not name an interpreter, roots and native tools by
            absolute paths and nothing else, or the environment is refused
            (``toolenv.record.measure``).
    """
    try:
        asked = NamedToolEnvironment.model_validate(named, strict=False)
    except ValidationError as exc:
        msg = (
            "tool_environment names the tool environment's interpreter, its roots and its "
            "native tools by absolute paths, and nothing else, or is null"
        )
        raise RunConfigError(msg, reason=first_problem(exc)) from None
    try:
        return measure(
            asked.interpreter,
            asked.roots,
            native=asked.native,
            forbidden=forbidden,
            runner=runner,
        )
    except ToolEnvironmentError as exc:
        msg = f"the tool environment the parameters name is refused: {exc}"
        raise RunConfigError(msg, **exc.context) from exc


def hold_before_session(
    recorded: ToolEnvironment,
    at_start: str | None,
    *,
    forbidden: Mapping[str, Path],
    runner: Runner = run_program,
) -> str:
    """Hold the environment to the run's record before a session; the scan to hold the next to.

    ``at_start`` is what the last call returned, or ``None`` before this process's first
    session: then the environment is measured in full against the record.

    Raises:
        InvocationError: the environment is not the recorded one, lies where it may not, or
            an entry changed since this process first held it.
    """
    try:
        if at_start is None:
            return hold(recorded, forbidden=forbidden, runner=runner)
        require_unchanged(recorded, at_start)
    except ToolEnvironmentError as exc:
        why = (
            f"{exc}, so no session is started on it"
            if at_start is None
            else "the tool environment changed since the run last measured it, so no session "
            f"is started on it: {exc}"
        )
        raise InvocationError(why, **exc.context) from exc
    return at_start
