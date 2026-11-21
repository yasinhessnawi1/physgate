"""The harness arm's whole-run answer, exported from the run's design-state graph.

A raw agent writes its whole-run answer by hand. A harness run's design lives in its graph,
spread over the nodes its roles wrote, so its answer is exported from the graph as the run
left it: the canonical store's journal at its newest revision, read without opening a store
(opening one runs recovery, which writes), and nothing in the run's directory is written.

**Only a finished run.** The store cannot say, without being opened, which of its revisions a
merge kept: a role's nodes are applied before its merge, so a merge that then fails leaves them
in the journal. So the export asks the run's event log instead, read once and replayed: every
module of the plan must have its completion line, or have ended for want of a person's sign-off
alone in a run that records decisions. A run short of that is ``unfinished`` and has no answer.

**A sign-off owed in a run that records decisions.** A module whose role owes a person's
sign-off (ARCH-130) is complete only once a person signed its values, and such a run takes no
decision: the module merged, every other precondition of its completion held, integration's own
subtask merged, and the run ended escalated naming it. That module has ended, and its merges
stand, so the run is exported and its record names each such module (``sign_offs_owed``). An
integration that ended without its merge (escalated, or rejected) leaves the run ``unfinished``,
whatever else is open: its own attempts' writes may be in the journal with no merge keeping them.
A run that acts is ``unfinished`` until a person has signed: there a decision could still close
the sign-off, or a rejected one left it unsigned.

**By name, never by guess.** Each field of the answer is the quantity of exactly that name in
the graph, in whichever node holds it, copied as the graph holds it: its value and its unit,
unconverted. A near name is not the name (``sample_rate`` is not ``update_rate``), and a value
in another unit is exported in that unit, so the scorer refuses it exactly as it would refuse
the raw agent's: an exporter that chose which near name was meant, or converted a unit, would
be judging its own guess. The names are taken from the answer's own schema
(:mod:`physgate.evaluation.whole.answer`), so the two cannot drift apart. A value is not
checked against its bound either; the scorer does that. Nothing here tells a run these names:
a run whose graph does not use them exports no answer.

**The structure** is the one of the closed list whose every required name the graph holds.
None is no answer (``contract_lost``); more than one is no answer either (``ambiguous``),
since nothing in the graph says which is the controller the firmware runs. A name the graph
holds in several nodes is taken when every node agrees on its value and unit. Disagreements
are weighed before the structure is chosen: one on a setting, or on any name of a structure
that would be whole were the disagreeing name agreed, makes the answer ``ambiguous``, since
either changes what the answer says or which structure it states. A disagreement on any other
name changes nothing in the answer, and is only listed in the record. Names of another
structure that the chosen one does not read are left out of the answer and listed too.

**What is not exported.** No ``analysed_controller``: the graph holds one set of coefficients,
and which controller a run's analysis was shown for is not yet exported from its records; the
scorer then leaves the same-coefficients criterion unjudged. No ``files``: the answer names
none. No simulation record: where the graph read a quantity off a sealed record, the
quantity's value is what is exported, its record staying beside the run.

**The record beside the answer.** The scorer reads the answer alone, and the answer of a run
that ended owing a sign-off is byte for byte the answer of a signed one. So an exported answer
has its record beside it, at :func:`record_path` (the answer's name with ``.record.json``
added): the status, the structure, each exported name with the nodes it was taken from, the
names left out, the disagreements, the modules whose sign-off is owed, and the answer's sha256.
Where a sign-off is owed the record says so in words: no person signed those values, and a raw
agent's answer carries no person's sign-off either, so the comparison of the two arms is
symmetric on it. An export that is not ``exported`` writes neither file.

**The write.** Nothing is ever written inside the run's directory. The answer's name and its
record's are each claimed first by creating them, so nothing left at either is overwritten or
written through; each file is written whole to a new name beside it and renamed onto its claim,
and a write that fails at any point leaves neither file behind. The record is put in place
first, so a process killed between the two renames leaves a record and never an answer without
one.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import tempfile
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.whole import law as law_module
from physgate.evaluation.whole.answer import (
    Controller,
    Parameters,
    ParametersV3,
    WholeRun,
    WholeRunV3,
    parse_answer,
    setting_problem,
)
from physgate.orchestrator.completion import open_preconditions
from physgate.orchestrator.events import Merged, SubtaskPlanned, parse_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.replay import RunState, replay
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import journal_records_after

#: Where a run keeps its canonical store and its event log, as ``physgate run`` keeps them.
STORE_DIRNAME = "store"
EVENTS_NAME = "events.jsonl"

#: How the export ended. ``unfinished``: the run did not record every module complete, nor end
#: one for want of a person's sign-off alone in a run that records decisions.
#: ``contract_lost``: the graph holds no structure whole, or lacks a setting. ``ambiguous``:
#: two nodes disagree on a name that matters, or the graph holds two structures whole.
#: ``law_missing``: asked to look for the control module's law file, the export found none and no
#: named structure whole. ``law_unverified``: the file exists and is refused, by name (see
#: :attr:`Export.law_reason`); it never reaches the scorer.
Status = Literal[
    "exported", "unfinished", "contract_lost", "ambiguous", "law_missing", "law_unverified"
]

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_CLAIM_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC

#: What the record says where a sign-off is owed: the answer alone does not show it.
UNSIGNED = (
    "No person signed the values of the modules named in sign_offs_owed. The scorer reads the "
    "answer alone, and a raw agent's answer carries no person's sign-off either, so the "
    "comparison of the two arms is symmetric on it."
)


def record_path(out: Path) -> Path:
    """Where the record of an answer exported to ``out`` is written: beside it, named after it."""
    return out.with_name(f"{out.name}.record.json")


class ExportError(Exception):
    """The run has no graph or log to export from, or the answer cannot be written where asked."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class Export(BaseModel):
    """What the export found in the run, and the digest of the answer it wrote, if any.

    ``taken_from``, each exported name with the nodes that hold it; ``missing``, by structure
    (or ``parameters``), the required names the graph lacks; ``conflicts``, each name two nodes
    disagree on, with the nodes that hold it, whether or not it refused the answer;
    ``complete``, the structures the graph holds whole; ``left_out``, the names of the
    answer's form the graph holds that the chosen structure does not read; ``sign_offs_owed``,
    in plan order, the modules a run that records decisions ended with their sign-off owed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    status: Status
    revision: int
    structure: str | None = None
    complete: tuple[str, ...] = ()
    taken_from: dict[str, tuple[str, ...]] = {}
    missing: dict[str, tuple[str, ...]] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    left_out: tuple[str, ...] = ()
    sign_offs_owed: tuple[str, ...] = ()
    sha256: str | None = None
    #: Caveat for every law answer: the vectors carry signals already in rad and rad/s, so the
    #: conversion from the sensors' counts (encoder counts per wheel revolution, gyro full scale)
    #: is outside the vector check and a wrong one in the transcription is not caught.
    #: A control law read from the module's law file (the other fields below are for it): why a
    #: file that exists was refused, and what is wrong in words; the file's digest, the commit it
    #: was read at, its path in that commit; the vector rows it reproduced; and the settings the
    #: caller supplied that the graph does not hold.
    law_reason: str | None = None
    law_detail: str | None = None
    law_sha256: str | None = None
    law_commit: str | None = None
    law_path: str | None = None
    vector_rows: int | None = None
    law_signals: tuple[str, ...] = ()
    #: For the period, each delay and the limit: the graph names used, their nodes and writers,
    #: the value, the interface value it was held against, or the flag that the run's interface
    #: states nothing to hold it against.
    law_timing: dict[str, dict[str, Any]] = {}
    supplied: dict[str, dict[str, float | int | str]] = {}
    #: Each mode the loop analysis will set aside (memory states, what feeds them, whether the
    #: command reads them, the note that a held state can grow in the firmware); the pin the
    #: vectors achieve for each term and coefficient (the smallest relative change they notice);
    #: and the out-of-scope terms that cannot affect the command, taken out of the law.
    law_held_modes: tuple[dict[str, Any], ...] = ()
    #: The flag, by its name, where a mode set aside is fed by a signal and read by the command:
    #: such an answer is a class of its own (:data:`physgate.evaluation.whole.law.HELD_STATE_FLAG`).
    law_held_state_flags: tuple[str, ...] = ()
    law_pins: dict[str, dict[str, float | None]] = {}
    law_set_aside: tuple[dict[str, Any], ...] = ()


def _literal(model: type[BaseModel], field: str) -> Any:
    """The one value a ``Literal`` field of ``model`` may take."""
    (value,) = typing.get_args(model.model_fields[field].annotation)
    return value


def _names(model: type[BaseModel], *, leave: str = "") -> dict[str, bool]:
    """``model``'s fields other than ``leave``, each with whether it is required."""
    return {name: info.is_required() for name, info in model.model_fields.items() if name != leave}


#: Each structure of the closed list, by its name, with its fields and whether each is required.
STRUCTURES: dict[str, dict[str, bool]] = {
    _literal(cls, "structure"): _names(cls, leave="structure")
    for cls in typing.get_args(typing.get_args(Controller)[0])
}
#: The settings, with whether each is required.
PARAMETERS: dict[str, bool] = _names(Parameters)
#: The settings of version 3, under the catalogue's names, with whether each is required.
PARAMETERS_V3: dict[str, bool] = _names(ParametersV3)
#: Where a control module states its law, beside its design note, and the structure it makes.
LAW_FILE = "law.json"
LAW_STRUCTURE = "sampled_law"
#: The control module's role, as a plan names it.
CONTROL_ROLE = "control"
#: Every name of the answer's form the export reads from the graph.
CONTRACT_NAMES: frozenset[str] = frozenset(PARAMETERS).union(*STRUCTURES.values())
_FORM = _literal(WholeRun, "form")
_VERSION = _literal(WholeRun, "version")
_VERSION_3 = _literal(WholeRunV3, "version")


def _graph(run_dir: Path) -> tuple[int, dict[str, dict[str, Any]]]:
    """The graph's newest revision, and each node's payload as that revision leaves it."""
    store = run_dir / STORE_DIRNAME
    if not store.is_dir():
        msg = "the run has no store to export from"
        raise ExportError(msg, run=str(run_dir))
    try:
        lines = journal_records_after(store, 0)
    except CorruptRecordError as exc:
        msg = "the run's journal holds a record no store could have written"
        raise ExportError(msg, run=str(run_dir), reason=str(exc)) from exc
    latest = {line.node_id: line.payload for line in lines}
    return len(lines), latest


def _found(
    nodes: dict[str, dict[str, Any]], names: frozenset[str] = CONTRACT_NAMES
) -> tuple[dict[str, tuple[Any, str, tuple[str, ...]]], dict[str, tuple[str, ...]]]:
    """Each name of ``names`` the graph holds: its value, unit and nodes; and the disagreements."""
    held: dict[str, list[tuple[str, Any, str]]] = {}
    for node_id in sorted(nodes):
        for name, quantity in nodes[node_id].get("quantities", {}).items():
            if name in names:
                held.setdefault(name, []).append((node_id, quantity["value"], quantity["unit"]))
    found: dict[str, tuple[Any, str, tuple[str, ...]]] = {}
    conflicts: dict[str, tuple[str, ...]] = {}
    for name, rows in sorted(held.items()):
        ids = tuple(node_id for node_id, _, _ in rows)
        _, value, unit = rows[0]
        if any(v != value or u != unit for _, v, u in rows[1:]):
            conflicts[name] = ids
        else:
            found[name] = (value, unit, ids)
    return found, conflicts


def _lacking(fields: dict[str, bool], found: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(n for n, required in fields.items() if required and n not in found))


def _measures(fields: dict[str, bool], found: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": found[name][0], "unit": found[name][1]}
        for name in sorted(fields)
        if name in found
    }


def _event_bytes(run_dir: Path) -> bytes:
    """The run's event log, read once, never through a link."""
    path = run_dir / EVENTS_NAME
    try:
        fd = os.open(path, _READ_FLAGS)
    except OSError as exc:
        msg = f"the run has no event log to export from ({exc.strerror})"
        raise ExportError(msg, run=str(run_dir)) from exc
    try:
        with os.fdopen(fd, "rb") as handle:
            return handle.read()
    except OSError as exc:
        msg = f"the run's event log cannot be read ({exc.strerror})"
        raise ExportError(msg, run=str(run_dir)) from exc


def _finished(run_dir: Path) -> tuple[bool, tuple[str, ...]]:
    """Whether the run's event log records every module of its plan ended; those owing a sign-off.

    A module has ended with its completion line, or, in a run that records decisions and has
    ended (escalated), with its sign-off the one precondition of its completion open.
    """
    path = run_dir / EVENTS_NAME
    data = _event_bytes(run_dir)
    try:
        state = replay(parse_events(data, log=str(path)))
    except OrchestratorError as exc:
        msg = "the run's event log holds a line no run could have written"
        raise ExportError(msg, run=str(run_dir), reason=str(exc)) from exc
    modules = state.modules()
    owed = _sign_offs_owed(state, modules)
    return bool(modules) and all(m in state.completed or m in owed for m in modules), owed


def _sign_offs_owed(state: RunState, modules: list[str]) -> tuple[str, ...]:
    """The modules a run that records decisions ended with only their sign-off owed, in order.

    None in a run that acts, where a person's decision is what ends one, nor before the run has
    ended: until then a merge may still be under way. None either where integration's own
    subtask did not merge: the run ended, but not with the merge that declares what is complete.
    """
    if state.acts or state.next_step().kind != "escalated":
        return ()
    integration = state.completion_subtask
    if integration is None or state.subtasks[integration].status != "done":
        return ()
    return tuple(
        m
        for m in modules
        if m not in state.completed
        and [name for name, _ in open_preconditions(state, m)] == ["sign_off"]
    )


@dataclass(frozen=True)
class _LawSource:
    """The control module's law file as read: parsed, with its digest, commit and path."""

    file: law_module.LawFile
    sha256: str
    commit: str
    path: str


def _law_location(run_dir: Path) -> tuple[str, str] | None:
    """Where the control module's law file is, in the run's last merged commit, or ``None``.

    The path is the control module's directory (as the plan named it) and the file's name; the
    commit is the last merge the event log records.
    """
    path = run_dir / EVENTS_NAME
    events = parse_events(_event_bytes(run_dir), log=str(path))
    directory = next(
        (
            e.module_dir
            for e in events
            if isinstance(e, SubtaskPlanned) and e.assigned_role == CONTROL_ROLE
        ),
        None,
    )
    merges = [e.merge_commit for e in events if isinstance(e, Merged)]
    if directory is None or not merges:
        return None
    return f"{directory}/{LAW_FILE}", merges[-1]


def _git(repository: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """A read-only ``git`` command in ``repository``: nothing it runs writes to it."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(  # noqa: S603 - fixed arguments; a commit and a path as data
            ["git", "-C", str(repository), *args],  # noqa: S607
            capture_output=True,
            check=False,
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"the run's repository cannot be read ({exc})"
        raise ExportError(msg, repository=str(repository)) from exc


def _law_source(run_dir: Path, repository: Path) -> _LawSource | None:
    """The law file at the run's last merged commit, parsed; ``None`` where there is none.

    The file is read from the commit, never from a working copy, so what is read is what was
    merged; nothing is written to the repository.

    Raises:
        ExportError: the repository, or the commit in it, cannot be read.
        law_module.LawRefused: the file is too large, or is not a law.
    """
    location = _law_location(run_dir)
    if location is None:
        return None
    path, commit = location
    if _git(repository, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        msg = "the run's last merged commit is not in the repository given"
        raise ExportError(msg, repository=str(repository), commit=commit)
    kind = _git(repository, "cat-file", "-t", f"{commit}:{path}")
    if kind.returncode != 0:
        return None
    if kind.stdout.strip() != b"blob":
        msg = f"the law's path holds a {kind.stdout.strip().decode()}, not a file"
        raise law_module.LawRefused("malformed", msg)
    size = _git(repository, "cat-file", "-s", f"{commit}:{path}")
    if size.returncode != 0:
        return None
    if int(size.stdout.strip() or b"0") > law_module.MAX_FILE_BYTES:
        msg = f"the law file is larger than {law_module.MAX_FILE_BYTES} bytes"
        raise law_module.LawRefused("malformed", msg)
    blob = _git(repository, "cat-file", "blob", f"{commit}:{path}")
    if blob.returncode != 0:
        msg = f"the law file cannot be read at {commit}"
        raise ExportError(msg, repository=str(repository), commit=commit)
    return _LawSource(
        file=law_module.parse_file(blob.stdout, defer_scope=True),
        sha256=hashlib.sha256(blob.stdout).hexdigest(),
        commit=commit,
        path=path,
    )


def _quantity(
    source: law_module.Source,
    found: Mapping[str, tuple[Any, str, tuple[str, ...]]],
    what: str,
    unit: str,
) -> dict[str, Any]:
    """A loop quantity from the graph: a name as held, a rate's reciprocal, or a sum, in ``unit``.

    Nothing is converted: a reciprocal takes a rate in ``Hz`` to a time in ``s`` (the one
    identity between those units), and a sum needs every term in one unit.
    """
    if source.quantity is not None:
        value, held, _ = found[source.quantity]
    elif source.reciprocal_of is not None:
        rate, held_rate, _ = found[source.reciprocal_of]
        if held_rate != "Hz" or not rate > 0:
            msg = (
                f"{what} is the reciprocal of {source.reciprocal_of!r}, held as {rate} "
                f"{held_rate}; a rate in Hz above 0"
            )
            raise law_module.LawRefused("units_do_not_balance", msg)
        value, held = 1 / rate, "s"
    else:
        assert source.sum_of is not None
        units = {found[name][1] for name in source.sum_of}
        if len(units) != 1:
            msg = f"{what} adds quantities in different units ({', '.join(sorted(units))})"
            raise law_module.LawRefused("units_do_not_balance", msg)
        held = units.pop()
        value = sum(found[name][0] for name in source.sum_of)
    if law_module.dimension(held) != law_module.dimension(unit):
        msg = f"{what} is held in {held!r}; the loop takes it in {unit!r}"
        raise law_module.LawRefused("units_do_not_balance", msg)
    return {"value": value, "unit": held}


def _refusing(
    conflicts: dict[str, tuple[str, ...]], found: dict[str, Any]
) -> dict[str, tuple[str, ...]]:
    """The disagreements that refuse the answer: on a setting, or in a structure otherwise whole."""
    present = set(found) | set(conflicts)
    read = set(PARAMETERS)
    for fields in STRUCTURES.values():
        if all(name in present for name, required in fields.items() if required):
            read |= set(fields)
    return {name: nodes for name, nodes in conflicts.items() if name in read}


def _inside(out: Path, run_dir: Path) -> bool:
    """Whether ``out`` lies in the run's directory, by the filesystem's own say.

    Two spellings of one directory (a link, or another case on a case-insensitive filesystem)
    are told apart by the string a path resolves to, so the directory itself is compared: the
    nearest ancestor of ``out`` that exists, and each of its parents, against the run's.
    """
    if Path(os.path.realpath(out)).is_relative_to(Path(os.path.realpath(run_dir))):
        return True
    ancestor = Path(os.path.abspath(out))
    while not ancestor.exists():
        ancestor = ancestor.parent
    return any(_same_file(candidate, run_dir) for candidate in (ancestor, *ancestor.parents))


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False


def export_whole_run(
    run_dir: Path,
    out: Path,
    *,
    repository: Path | None = None,
    supplied: Mapping[str, tuple[float | int, str]] | None = None,
) -> Export:
    """The whole-run answer the finished run at ``run_dir`` left in its graph, written to ``out``.

    Nothing is written unless the export is ``exported``, and nothing in ``run_dir`` ever.

    **The control module's law.** Given the run's ``repository``, the export also looks for the
    control module's law file (:data:`LAW_FILE`, in its module directory) at the last merge the
    event log records, reading it from that commit and nothing else. A file that is there is the
    design's own statement of its law, and it is exported as the answer's controller, the
    coefficients taken from the graph as it holds them, only if its units balance and the law
    reproduces every test vector in the file with the graph's own numbers; a file that is refused
    is ``law_unverified``, by name, and never falls back to another structure. No file and no
    named structure whole is ``law_missing``. A file beside a named structure whole is
    ``ambiguous``, as two named structures are. Without ``repository`` nothing changes: the
    answer is the version 2 answer of a named structure, byte for byte.

    ``supplied`` gives, by the catalogue's name, a setting the graph does not hold (a value stated
    in a design note's prose, say); it is exported as given and the record says it was supplied.

    Raises:
        ExportError: ``out`` lies in the run's directory; the run has no store or no event
            log, or either holds a line no run could have written; or the answer cannot be
            written at ``out``, or something is already there.
    """
    if _inside(out, run_dir):
        msg = "the answer is never written inside the run it is exported from"
        raise ExportError(msg, run=str(run_dir), out=str(out))
    revision, nodes = _graph(run_dir)
    finished, owed = _finished(run_dir)
    if not finished:
        return Export(status="unfinished", revision=revision)
    source: _LawSource | None = None
    refusal: law_module.LawRefused | None = None
    if repository is not None:
        try:
            source = _law_source(run_dir, repository)
        except law_module.LawRefused as exc:
            refusal = exc
    found, conflicts = _found(nodes)
    lacking = {name: _lacking(fields, found) for name, fields in STRUCTURES.items()}
    complete = tuple(sorted(name for name, names in lacking.items() if not names))
    if refusal is not None:
        return Export(
            status="law_unverified",
            revision=revision,
            complete=complete,
            conflicts=conflicts,
            sign_offs_owed=owed,
            law_reason=refusal.code,
            law_detail=refusal.detail,
        )
    if _refusing(conflicts, found):
        return Export(
            status="ambiguous",
            revision=revision,
            complete=complete,
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    if len(complete) > 1:
        return Export(
            status="ambiguous",
            revision=revision,
            complete=complete,
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    if source is not None:
        if complete:
            return Export(
                status="ambiguous",
                revision=revision,
                complete=tuple(sorted((*complete, LAW_STRUCTURE))),
                conflicts=conflicts,
                sign_offs_owed=owed,
            )
        return _export_law(out, revision, nodes, owed, source, supplied or {})
    settings = _lacking(PARAMETERS, found)
    if not complete and repository is not None:
        return Export(
            status="law_missing",
            revision=revision,
            missing={**lacking, **({"parameters": settings} if settings else {})},
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    if not complete:
        missing = dict(lacking)
        if settings:
            missing["parameters"] = settings
        return Export(
            status="contract_lost",
            revision=revision,
            missing=missing,
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    structure = complete[0]
    if settings:
        return Export(
            status="contract_lost",
            revision=revision,
            structure=structure,
            complete=complete,
            missing={"parameters": settings},
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    read = set(STRUCTURES[structure]) | set(PARAMETERS)
    answer = {
        "form": _FORM,
        "version": _VERSION,
        "controller": {"structure": structure, **_measures(STRUCTURES[structure], found)},
        "parameters": _measures(PARAMETERS, found),
        "files": [],
    }
    raw = _json_bytes(answer)
    export = Export(
        status="exported",
        revision=revision,
        structure=structure,
        complete=complete,
        taken_from={name: found[name][2] for name in sorted(read) if name in found},
        conflicts=conflicts,
        left_out=tuple(sorted(set(found) - read)),
        sign_offs_owed=owed,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    _write_new(((record_path(out), _record_bytes(export, out)), (out, raw)))
    return export


def _export_law(
    out: Path,
    revision: int,
    nodes: dict[str, dict[str, Any]],
    owed: tuple[str, ...],
    source: _LawSource,
    supplied: Mapping[str, tuple[float | int, str]],
) -> Export:
    """The version 3 answer that states the control module's law, or the refusal that names why."""
    file = source.file
    names = frozenset(file.graph_names()) | frozenset(PARAMETERS_V3)
    found, conflicts = _found(nodes, names)
    taken = {"law_path": source.path, "law_sha256": source.sha256, "law_commit": source.commit}
    base = {"revision": revision, "sign_offs_owed": owed, **taken}
    read = frozenset(file.graph_names()) | frozenset(PARAMETERS_V3)
    if any(name in read for name in conflicts):
        return Export(
            status="ambiguous",
            revision=revision,
            complete=(LAW_STRUCTURE,),
            conflicts=conflicts,
            sign_offs_owed=owed,
        )
    unknown = sorted(set(supplied) - set(PARAMETERS_V3))
    held_too = sorted(set(supplied) & set(found))
    if unknown or held_too:
        msg = "a supplied setting is not a setting of the answer, or the graph already holds it"
        raise ExportError(msg, names=", ".join(unknown + held_too))
    for name, (value, unit) in sorted(supplied.items()):
        problem = setting_problem(name, value, unit)
        if problem is not None:
            msg = f"the supplied setting {name!r} is refused: {problem}"
            raise ExportError(msg, names=name)
    absent = tuple(n for n in file.graph_names() if n not in found)
    if absent:
        return Export(
            status="law_unverified",
            law_reason="coefficient_not_held",
            law_detail=f"the law names quantities the graph does not hold: {', '.join(absent)}",
            conflicts=conflicts,
            **base,  # type: ignore[arg-type]
        )
    # An out-of-scope term that has no weight with the graph's numbers cannot affect the command:
    # it is set aside, and the law is judged as it is.
    file = file.with_numbers(
        {name: found[quantity][0] for name, quantity in file.coefficients.items()}
    )
    settings = tuple(
        n
        for n, required in PARAMETERS_V3.items()
        if required and n not in found and n not in supplied
    )
    if settings:
        return Export(
            status="contract_lost",
            structure=LAW_STRUCTURE,
            complete=(LAW_STRUCTURE,),
            missing={"parameters": tuple(sorted(settings))},
            conflicts=conflicts,
            **base,  # type: ignore[arg-type]
        )
    try:
        result = _law_controller(file, found, supplied, nodes)
    except law_module.LawRefused as exc:
        return Export(
            status="law_unverified",
            law_reason=exc.code,
            law_detail=exc.detail,
            conflicts=conflicts,
            **base,  # type: ignore[arg-type]
        )
    parameters = _measures(PARAMETERS_V3, found)
    parameters.update({n: {"value": v, "unit": u} for n, (v, u) in sorted(supplied.items())})
    answer = {
        "form": _FORM,
        "version": _VERSION_3,
        "controller": result.controller,
        "parameters": dict(sorted(parameters.items())),
        "files": [],
    }
    raw = _json_bytes(answer)
    try:
        parse_answer(raw)
    except TaskFormatError as exc:
        # What the file and the graph make is not an answer the scorer can read (a number past
        # its bound, say): a mapping error, so a refusal here and never a fail there.
        return Export(
            status="law_unverified",
            law_reason="answer_not_valid",
            law_detail=str(exc),
            conflicts=conflicts,
            **base,  # type: ignore[arg-type]
        )
    read_names = sorted(set(file.graph_names()) | (set(PARAMETERS_V3) & set(found)))
    export = Export(
        status="exported",
        structure=LAW_STRUCTURE,
        complete=(LAW_STRUCTURE,),
        taken_from={name: found[name][2] for name in read_names},
        conflicts=conflicts,
        left_out=(),
        sha256=hashlib.sha256(raw).hexdigest(),
        vector_rows=result.verified.rows,
        law_signals=result.verified.signals,
        law_timing=result.timing,
        supplied={n: {"value": v, "unit": u} for n, (v, u) in sorted(supplied.items())},
        law_held_modes=result.held_modes,
        law_held_state_flags=result.held_state_flags,
        law_pins={key: pin.as_record() for key, pin in result.verified.pins.items()},
        law_set_aside=tuple(
            {"line": o.line, "term": o.index + 1, "code": o.code, "detail": o.detail}
            for o in file.set_aside
        ),
        **base,  # type: ignore[arg-type]
    )
    _write_new(((record_path(out), _record_bytes(export, out)), (out, raw)))
    return export


#: The roles that write the loop's own numbers: their copies of an interface quantity are not
#: the interface's statement.
INTERFACE_KIND = "interface"
#: The gate catalogue's names that give a floor: the gyro's rate (its age is the sensor delay)
#: and the duty the drive train allows (the command limit). The compute delay has no catalogue
#: name: only where its quantities come from is checked.
SENSOR_FLOOR_NAME = "output_data_rate"
LIMIT_FLOOR_NAME = "duty_cycle"
PERIOD_REFERENCE_NAME = "update_rate"
#: A relative slack for the one float comparison against an interface's number.
FLOOR_SLACK = 1e-12


def _interface_statements(
    nodes: Mapping[str, dict[str, Any]], name: str
) -> list[tuple[str, float, str]]:
    """What the run's interface nodes state under ``name``: node, value, unit.

    Only interface-kind nodes, and only a quantity not written by the control role: control's own
    copies are never the statement.
    """
    out = []
    for node_id in sorted(nodes):
        node = nodes[node_id]
        quantity = node.get("quantities", {}).get(name)
        if node.get("kind") != INTERFACE_KIND or quantity is None:
            continue
        writer = quantity.get("written_by") or node.get("owner_role")
        if writer != CONTROL_ROLE:
            out.append((node_id, quantity["value"], quantity["unit"]))
    return out


def _writers(nodes: Mapping[str, dict[str, Any]], name: str, ids: tuple[str, ...]) -> list[str]:
    return sorted(
        {
            nodes[i]["quantities"][name].get("written_by") or nodes[i].get("owner_role", "")
            for i in ids
        }
    )


#: A relative slack for the period against the interface's update rate: the spelling of a decimal.
PERIOD_SLACK = 1e-9
#: The units a time is held in, any of which makes a quantity time-valued.
TIME_UNITS = frozenset({"s", "ms", "us", "\u00b5s", "\u03bcs", "ns"})
#: The flags on the compute delay, each by its own name (apart from the no-statement flag).
OMITS_FLAG = "compute_delay_omits_interface_times"
NON_INTERFACE_FLAG = "compute_delay_names_a_non_interface_quantity"


def _compute_delay_flags(
    nodes: Mapping[str, dict[str, Any]], names: tuple[str, ...]
) -> tuple[list[str], list[str], list[str]]:
    """What is wrong with where the compute delay comes from: the flags, and what they name.

    The compute delay has no catalogue name to hold a number against, so it is held to where it
    comes from. It is flagged when it does not include every time-valued quantity (a quantity in a
    unit of time, not written by control) of every interface node of the run, whether the law
    draws on that node or not: a bound stated by one node and left out of the sum is as much
    left out as one of the node it draws on, and the answer says which. It is flagged too when it
    draws on a quantity that no interface node, apart from control's own copy, states. Returns
    ``(flags, left_out, not_the_interface's)``.
    """
    outside = sorted(n for n in names if not _interface_statements(nodes, n))
    named = set(names)
    omitted: set[str] = set()
    for node_id in sorted(nodes):
        node = nodes[node_id]
        if node.get("kind") != INTERFACE_KIND:
            continue
        for quantity_name, quantity in node.get("quantities", {}).items():
            writer = quantity.get("written_by") or node.get("owner_role")
            time_valued = writer != CONTROL_ROLE and quantity["unit"] in TIME_UNITS
            if time_valued and quantity_name not in named:
                omitted.add(quantity_name)
    flags = [OMITS_FLAG] if omitted else []
    if outside:
        flags.append(NON_INTERFACE_FLAG)
    return flags, sorted(omitted), outside


def _timing(
    file: law_module.LawFile,
    found: Mapping[str, tuple[Any, str, tuple[str, ...]]],
    nodes: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The loop's timing and limit from the graph, each held against the run's interface.

    Returns the answer's four quantities and the record of each: the graph names used, their
    nodes and writers, the value, the interface value it was held against (name, node, value)
    or the flag that the interface states nothing.

    The scored sensor delay may not be smaller than ``1/output_data_rate`` as an interface node
    (not written by control) states it, the scored command limit not larger than the interface's
    ``duty_cycle``; a larger delay and a smaller limit are pessimistic and allowed. The scored
    period is the reciprocal of the interface's ``update_rate`` where one is stated: a shorter
    period runs the loop faster than the interface says, a longer one is not the loop it runs.
    A copy of the interface's number in control's own node may be pointed at: it counts only if
    it equals the interface's. The compute delay has no catalogue name, so it is held to where it
    comes from and flagged by name (:func:`_compute_delay_flags`): it must include every
    time-valued quantity of every interface node of the run, and draw on no quantity that is not
    the interface's; the flag is on the answer, never a refusal. Where the interface states
    nothing, the answer is still exported, with the no-statement flag.

    Known difference: the named structures of version 2 read ``sensor_delay``, ``compute_delay``
    and ``command_limit`` by name from any node, unchecked against the interface; version 2 keeps
    its bytes and behaviour, so this floor is not applied there.

    Raises:
        law_module.LawRefused: ``delay_or_limit_not_stated_by_the_interface`` or
            ``period_is_not_the_interface_s``.
    """
    sources = {
        "period": (file.period, "the period", "s"),
        "sensor_delay": (file.sensor_delay, "the sensor delay", "s"),
        "compute_delay": (file.compute_delay, "the compute delay", "s"),
        "command_limit": (file.command_limit, "the command limit", "1"),
    }
    timing = {
        key: _quantity(source, found, what, unit) for key, (source, what, unit) in sources.items()
    }
    report: dict[str, dict[str, Any]] = {}
    for key, (source, what, _unit) in sources.items():
        names = source.names()
        ids = tuple(sorted({i for n in names for i in found[n][2]}))
        value = timing[key]["value"]
        held: dict[str, Any] | None = None
        refusal = ""
        code = "delay_or_limit_not_stated_by_the_interface"
        extra: dict[str, Any] = {}
        if key == "sensor_delay":
            rates = [s for s in _interface_statements(nodes, SENSOR_FLOOR_NAME) if s[2] == "Hz"]
            rates = [s for s in rates if s[1] > 0]
            if rates:
                node, rate, _ = min(rates, key=lambda s: s[1])
                held = {"name": SENSOR_FLOOR_NAME, "node": node, "value": 1 / rate}
                if value < held["value"] * (1 - FLOOR_SLACK):
                    refusal = f"is {value:g} s, below the interface's 1/{SENSOR_FLOOR_NAME}"
        elif key == "command_limit":
            limits = [s for s in _interface_statements(nodes, LIMIT_FLOOR_NAME) if s[2] == "1"]
            if limits:
                node, limit, _ = min(limits, key=lambda s: s[1])
                held = {"name": LIMIT_FLOOR_NAME, "node": node, "value": limit}
                if value > limit * (1 + FLOOR_SLACK):
                    refusal = f"is {value:g}, above the interface's {LIMIT_FLOOR_NAME}"
        elif key == "compute_delay":
            stated = [_interface_statements(nodes, n) for n in names]
            if all(any(u == "s" for _, _, u in s) for s in stated):
                total = sum(max(v for _, v, u in s if u == "s") for s in stated)
                node = ", ".join(sorted({n for s in stated for n, _, _ in s}))
                held = {"name": "+".join(names), "node": node, "value": total}
            flags, omitted, outside = _compute_delay_flags(nodes, names)
            extra = {
                "flags": flags,
                "omitted_interface_times": omitted,
                "not_the_interface_s": outside,
            }
        else:
            rates = [s for s in _interface_statements(nodes, PERIOD_REFERENCE_NAME) if s[2] == "Hz"]
            rates = [s for s in rates if s[1] > 0]
            if rates:
                held = {
                    "name": PERIOD_REFERENCE_NAME,
                    "node": rates[0][0],
                    "value": 1 / rates[0][1],
                }
                code = "period_is_not_the_interface_s"
                for _, rate, _ in rates:
                    if abs(value - 1 / rate) > PERIOD_SLACK * (1 / rate):
                        refusal = (
                            f"is {value:g} s, not the interface's 1/{PERIOD_REFERENCE_NAME} "
                            f"({1 / rate:g} s)"
                        )
                        break
        if refusal:
            msg = f"{what} {refusal}; a law file may not make it kinder than the run's interface"
            raise law_module.LawRefused(code, msg)
        report[key] = {
            "names": list(names),
            "nodes": list(ids),
            "writers": sorted({w for n in names for w in _writers(nodes, n, found[n][2])}),
            "value": value,
            "unit": timing[key]["unit"],
            "held_against": held,
            "no_interface_statement": held is None,
            **extra,
        }
    return timing, report


@dataclass(frozen=True)
class _LawResult:
    """What the law file and the graph make: the answer's controller, and what was found."""

    controller: dict[str, Any]
    verified: law_module.Verified
    timing: dict[str, dict[str, Any]]
    held_modes: tuple[dict[str, Any], ...]
    held_state_flags: tuple[str, ...]


def _law_controller(
    file: law_module.LawFile,
    found: Mapping[str, tuple[Any, str, tuple[str, ...]]],
    supplied: Mapping[str, tuple[float | int, str]],
    nodes: Mapping[str, dict[str, Any]],
) -> _LawResult:
    """The answer's controller from the law file and the graph, what its vectors verified, timing.

    Every check that can run on a law runs before the law is refused for a term out of scope, so
    that term is never the cover for another fault: the timing against the interface, a coefficient
    that divides by zero, the units of every line, and only then the scope. A law with such a term
    cannot be evaluated, so its vectors are not.

    Raises:
        law_module.LawRefused: the units do not balance, the timing is not the interface's, a term
            divides by zero, a term is out of scope, or a vector is not reproduced.
    """
    timing, report = _timing(file, found, nodes)
    coefficients = {
        name: {"value": found[quantity][0], "unit": found[quantity][1]}
        for name, quantity in sorted(file.coefficients.items())
    }
    values = {name: float(m["value"]) for name, m in coefficients.items()}
    divisors = law_module.zero_divisors(file, values)
    if divisors:
        raise law_module.zero_refusal(divisors[0])
    law_module.check(file, {name: m["unit"] for name, m in coefficients.items()})
    if file.outside:
        raise law_module.LawRefused(file.outside[0].code, file.outside[0].detail)
    period = float(timing["period"]["value"])
    verified = law_module.verify(
        file,
        values,
        file.vectors,
        period=period,
        limit=float(timing["command_limit"]["value"]),
        full_scale=float(
            found["pwm_full_scale"][0]
            if "pwm_full_scale" in found
            else supplied["pwm_full_scale"][0]
        ),
    )
    body = file.model_dump(
        mode="json", include={"memory", "lines", "command"}, exclude_defaults=True
    )
    flagged = sorted(key for key, row in report.items() if row["no_interface_statement"])
    compute = report["compute_delay"]
    held = law_module.held_report(file, values, period=period)
    return _LawResult(
        {
            "structure": LAW_STRUCTURE,
            **timing,
            "no_interface_statement": flagged,
            "compute_delay_flags": compute["flags"],
            "compute_delay_omitted": compute["omitted_interface_times"],
            "coefficients": coefficients,
            **body,
        },
        verified,
        report,
        tuple(mode.as_record() for mode in held),
        law_module.held_state_flags(held),
    )


def _json_bytes(body: dict[str, Any]) -> bytes:
    return (json.dumps(body, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _record_bytes(export: Export, out: Path) -> bytes:
    """The record written beside an exported answer: what the export found, and the digest."""
    # A record of an answer written from a named structure has no law fields: its bytes are what
    # they always were.
    law_fields = {
        "law_reason",
        "law_detail",
        "law_sha256",
        "law_commit",
        "law_path",
        "vector_rows",
        "law_signals",
        "law_timing",
        "supplied",
        "law_held_modes",
        "law_held_state_flags",
        "law_pins",
        "law_set_aside",
    }
    left = set() if export.structure == LAW_STRUCTURE else law_fields
    found = export.model_dump(mode="json", exclude={"sha256", "missing", *left})
    return _json_bytes(
        {
            **found,
            "answer": out.name,
            "answer_sha256": export.sha256,
            "sign_off": UNSIGNED if export.sign_offs_owed else None,
        }
    )


def _write_all(fd: int, raw: bytes) -> None:
    """Every byte of ``raw`` written to ``fd``."""
    view = memoryview(raw)
    while view:
        view = view[os.write(fd, view) :]


def _ours(out: Path, claim: os.stat_result) -> bool:
    """Whether ``out`` is still the file this export made there, its claim or what it put."""
    try:
        now = os.lstat(out)
    except OSError:
        return False
    return (now.st_dev, now.st_ino) == (claim.st_dev, claim.st_ino)


def _umask() -> int:
    """The process's file-creation mask, read without changing it."""
    mask = os.umask(0)
    os.umask(mask)
    return mask


def _claim(out: Path) -> int:
    """``out`` created empty and open, or an error that says what a refusal may mean."""
    try:
        return os.open(out, _CLAIM_FLAGS, 0o644)
    except FileExistsError as exc:
        msg = (
            f"the answer cannot be written where asked ({exc.strerror}); a name left empty with a "
            f"temporary beside it (named from the answer's) is what an earlier write that was "
            f"killed leaves, and both are removed by hand"
        )
        raise ExportError(msg, out=str(out)) from exc


def _write_new(files: tuple[tuple[Path, bytes], ...]) -> None:
    """Each ``raw`` at its ``out``, where nothing may be yet: all claimed, then each put there.

    They are put in the order given, so a file that must never stand alone comes last.

    Every ``out`` is claimed first by creating it empty, which fails if anything is at it, a
    link included, so no file is written unless every name is free. Each is then written whole
    to a new name :func:`tempfile.mkstemp` makes in the same directory, and renamed onto its
    claim only once every claim is still the file it made, so no name the export did not make
    is ever replaced. The harness makes no second name for a file, so nothing is linked into
    place. Whatever fails, every name the export made, and every file it put, is removed where it
    can be, so a failed write leaves nothing behind and the next export is not refused. A process
    killed outright (no chance to remove anything) between a claim and its rename leaves the empty
    claim and the temporary, and the next export is refused until both are removed by hand; the
    refusal says so. A file is put down with the mode a plain file made here would have. A removal
    that itself fails is passed over, and leaves only that file (a temporary beside the answer's
    name, which a person may delete).
    """
    # Held open to the end: while one is, the claimed file's inode cannot be freed and given
    # to another file at the same name, so the identity compared below is the claim's alone.
    claims: list[tuple[Path, int, os.stat_result]] = []
    temporaries: list[tuple[str, os.stat_result]] = []
    placed: list[tuple[Path, os.stat_result]] = []
    whole = False
    at = files[0][0]
    try:
        for out, _ in files:
            at = out
            out.parent.mkdir(parents=True, exist_ok=True)
            claimed = _claim(out)
            claims.append((out, claimed, os.fstat(claimed)))
        for out, raw in files:
            at = out
            fd, temporary = tempfile.mkstemp(prefix=f".{out.name}.", dir=out.parent)
            try:
                temporaries.append((temporary, os.fstat(fd)))
                os.fchmod(fd, 0o644 & ~_umask())
                _write_all(fd, raw)
                os.fsync(fd)
            finally:
                os.close(fd)
        for out, _, claim in claims:
            if not _ours(out, claim):
                msg = "the answer's name was taken by something else while it was written"
                raise ExportError(msg, out=str(out))
        for (out, _, _), (temporary, written) in zip(claims, temporaries, strict=True):
            os.replace(temporary, out)
            placed.append((out, written))
        whole = True
    except OSError as exc:
        msg = f"the answer cannot be written where asked ({exc.strerror})"
        raise ExportError(msg, out=str(at)) from exc
    finally:
        if not whole:
            # Each removal is made if it can be: one that cannot (a temporary left read-only, say)
            # does not stop the rest, and does not replace the error that brought us here.
            for temporary, _ in temporaries[len(placed) :]:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
            for out, written in placed:
                with contextlib.suppress(OSError):
                    if _ours(out, written):
                        os.unlink(out)
            for out, _, claim in claims[len(placed) :]:
                with contextlib.suppress(OSError):
                    if _ours(out, claim):
                        os.unlink(out)
        for _, claimed, _ in claims:
            os.close(claimed)
