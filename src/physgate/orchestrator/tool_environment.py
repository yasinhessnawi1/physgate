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

**Wiring a session.** The environment's own file says which programs, directories, links and
variables a session needs (:mod:`physgate.toolenv.session`); here they are made for one session
and joined to its environment, with the directory of its programs first on its search path.

**After every session.** The environment is scanned once more when a session has ended. A
change then was made while that session ran, by a write no layer refused; it is named with the
session, and nothing the session left is collected or committed.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from physgate.orchestrator.common import first_problem
from physgate.orchestrator.exceptions import InvocationError, RunConfigError
from physgate.orchestrator.invocation import MAX_SERVER_OUTPUT_TOKENS
from physgate.orchestrator.run_config import ToolServers
from physgate.oslayer.placement import machine_writable
from physgate.oslayer.session_temp import session_temps_root
from physgate.series.collect import SeriesEnvironment
from physgate.series.writer import ENVIRONMENT_VARIABLE
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
from physgate.toolenv.register import launches, load_register, register_sha256
from physgate.toolenv.session import wire

if TYPE_CHECKING:
    from physgate.orchestrator.run_config import RunConfig
    from physgate.oslayer.containment import ServerLaunch


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


def wire_session(
    recorded: ToolEnvironment, *, bin_dir: Path, temp: Path, taken: Collection[str]
) -> dict[str, str]:
    """Make what one session needs of the environment; the variables its environment gains.

    Raises:
        InvocationError: the environment's session file is refused; nothing was made.
    """
    try:
        return wire(recorded, bin_dir=bin_dir, temp=temp, taken=taken)
    except ToolEnvironmentError as exc:
        raise InvocationError(f"{exc}, so no session is started", **exc.context) from exc


def session_environment(
    env: Mapping[str, str], variables: Mapping[str, str], bin_dir: Path
) -> dict[str, str]:
    """``env`` with the environment's variables and its programs first on the search path.

    Raises:
        InvocationError: a variable is one the session's environment already holds. The file
            was judged against the environment as it stood then; what the installer added
            since is held here.
    """
    held = sorted(set(variables) & set(env))
    if held:
        msg = "the tool environment's session file names a variable the session already holds"
        raise InvocationError(msg, variable=held[0])
    return {**env, **variables, "PATH": f"{bin_dir}:{env['PATH']}"}


def series_environment(env: Mapping[str, str], recorded: ToolEnvironment) -> dict[str, str]:
    """``env`` telling the session's scripts the run's tool environment, for their records.

    The roots are spelt as the run recorded them, and the digest is the run's manifest digest:
    the writer names the environment's code once by them, and the collector holds the record
    to exactly these.

    Raises:
        InvocationError: the session's environment already holds the variable.
    """
    if ENVIRONMENT_VARIABLE in env:
        msg = "the session's environment already holds the variable that names its tool environment"
        raise InvocationError(msg, variable=ENVIRONMENT_VARIABLE)
    told = json.dumps({"roots": list(recorded.roots), "sha256": recorded.manifest_digest})
    return {**env, ENVIRONMENT_VARIABLE: told}


def sealing_environment(
    recorded: ToolEnvironment | None, *, held: bool, layer: bool
) -> SeriesEnvironment | None:
    """What the collector is told of the run's tool environment for a session's records.

    ``held``: the environment was measured equal to the run's record before the session;
    ``layer``: the OS layer ran around the session. ``None`` for a run that names none.
    """
    if recorded is None:
        return None
    return SeriesEnvironment(
        roots=tuple(recorded.roots), sha256=recorded.manifest_digest, held=held, layer=layer
    )


def changed_while_running(recorded: ToolEnvironment, at_start: str) -> str | None:
    """Why the environment is not what it was before the session that just ended, if it is not."""
    try:
        require_unchanged(recorded, at_start)
    except ToolEnvironmentError as exc:
        return f"the tool environment changed while the session ran: {exc}"
    return None


def recorded_servers() -> ToolServers:
    """The tool servers a run naming a tool environment records, from the register now.

    Every server of the register, for the role profile and the raw agent alike; the bound on one
    answer every session is told; the register's digest.
    """
    every = tuple(sorted(load_register().servers))
    return ToolServers(
        profiles={"role": every, "baseline": every},
        max_output_tokens=MAX_SERVER_OUTPUT_TOKENS,
        register_sha256=register_sha256(),
    )


def server_launches(config: RunConfig) -> tuple[ServerLaunch, ...]:
    """How the run's role sessions' tool servers start, from its record and the register.

    None for a run that records no tool servers.

    Raises:
        RunConfigError: the register or the token bound differs from the one the run recorded,
            or the register cannot start a recorded server from the recorded environment.
    """
    return profile_launches(config.tool_servers, config.tool_environment, "role")


def profile_launches(
    recorded: ToolServers | None,
    environment: ToolEnvironment | None,
    profile: Literal["role", "baseline"],
) -> tuple[ServerLaunch, ...]:
    """How one profile's tool servers start, from a tool-server record and its environment.

    The role sessions of a run and the raw arm held to it start theirs from the same records:
    each the servers its own profile names. None without a record or an environment.

    Raises:
        RunConfigError: the register or the token bound differs from the one recorded, or the
            register cannot start a recorded server from the recorded environment.
    """
    if recorded is None or environment is None:
        return ()
    if recorded.register_sha256 != register_sha256():
        msg = (
            "the tool-server register differs from the one the run recorded, so its sessions "
            "would be offered other tools; no tool server is started"
        )
        raise RunConfigError(msg, recorded=recorded.register_sha256)
    if recorded.max_output_tokens != MAX_SERVER_OUTPUT_TOKENS:
        msg = (
            "the bound on a tool server's answer differs from the one the run recorded; no tool "
            "server is started"
        )
        raise RunConfigError(msg, recorded=str(recorded.max_output_tokens))
    try:
        return launches(load_register(), recorded.profiles.get(profile, ()), environment)
    except ToolEnvironmentError as exc:
        raise RunConfigError(str(exc), **exc.context) from exc
