"""The harness arm's whole-run answer, exported from the run's design-state graph.

A raw agent writes its whole-run answer by hand. A harness run's design lives in its graph,
spread over the nodes its roles wrote, so its answer is exported from the graph as the run
left it: the canonical store's journal at its newest revision, read without opening a store
(opening one runs recovery, which writes), and nothing in the run's directory is written.

**Only a finished run.** The store cannot say, without being opened, which of its revisions a
merge kept: a role's nodes are applied before its merge, so a merge that then fails leaves them
in the journal. So the export asks the run's event log instead, read once and replayed: every
module of the plan must have its completion line, and the run must not have halted. A run
short of that is ``unfinished`` and has no answer.

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

**The write.** The answer is never written inside the run's directory. It is written whole to
a new name beside ``out`` and then linked to ``out``, which must not exist yet, so nothing left
at that name is overwritten or written through, and a write that fails leaves nothing behind.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import typing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.whole.answer import Controller, Parameters, WholeRun
from physgate.orchestrator.events import parse_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.replay import replay
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import journal_records_after

#: Where a run keeps its canonical store and its event log, as ``physgate run`` keeps them.
STORE_DIRNAME = "store"
EVENTS_NAME = "events.jsonl"

#: How the export ended. ``unfinished``: the run did not record every module complete, or
#: halted. ``contract_lost``: the graph holds no structure whole, or lacks a setting.
#: ``ambiguous``: two nodes disagree on a name that matters, or the graph holds two structures
#: whole.
Status = Literal["exported", "unfinished", "contract_lost", "ambiguous"]

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


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
    answer's form the graph holds that the chosen structure does not read.
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
    sha256: str | None = None


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
#: Every name of the answer's form the export reads from the graph.
CONTRACT_NAMES: frozenset[str] = frozenset(PARAMETERS).union(*STRUCTURES.values())
_FORM = _literal(WholeRun, "form")
_VERSION = _literal(WholeRun, "version")


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
    nodes: dict[str, dict[str, Any]],
) -> tuple[dict[str, tuple[Any, str, tuple[str, ...]]], dict[str, tuple[str, ...]]]:
    """Each name of the form the graph holds: its value, unit and nodes; and the disagreements."""
    held: dict[str, list[tuple[str, Any, str]]] = {}
    for node_id in sorted(nodes):
        for name, quantity in nodes[node_id].get("quantities", {}).items():
            if name in CONTRACT_NAMES:
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


def _finished(run_dir: Path) -> bool:
    """Whether the run's event log records every module of its plan complete, and no halt."""
    path = run_dir / EVENTS_NAME
    try:
        fd = os.open(path, _READ_FLAGS)
    except OSError as exc:
        msg = f"the run has no event log to export from ({exc.strerror})"
        raise ExportError(msg, run=str(run_dir)) from exc
    with os.fdopen(fd, "rb") as handle:
        data = handle.read()
    try:
        state = replay(parse_events(data, log=str(path)))
    except OrchestratorError as exc:
        msg = "the run's event log holds a line no run could have written"
        raise ExportError(msg, run=str(run_dir), reason=str(exc)) from exc
    modules = state.modules()
    return state.halted is None and bool(modules) and all(m in state.completed for m in modules)


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
    """Whether ``out``, as the filesystem resolves it, lies in the run's directory."""
    resolved = Path(os.path.realpath(out))
    return resolved.is_relative_to(Path(os.path.realpath(run_dir)))


def export_whole_run(run_dir: Path, out: Path) -> Export:
    """The whole-run answer the finished run at ``run_dir`` left in its graph, written to ``out``.

    Nothing is written unless the export is ``exported``, and nothing in ``run_dir`` ever.

    Raises:
        ExportError: ``out`` lies in the run's directory; the run has no store or no event
            log, or either holds a line no run could have written; or the answer cannot be
            written at ``out``, or something is already there.
    """
    if _inside(out, run_dir):
        msg = "the answer is never written inside the run it is exported from"
        raise ExportError(msg, run=str(run_dir), out=str(out))
    revision, nodes = _graph(run_dir)
    if not _finished(run_dir):
        return Export(status="unfinished", revision=revision)
    found, conflicts = _found(nodes)
    lacking = {name: _lacking(fields, found) for name, fields in STRUCTURES.items()}
    complete = tuple(sorted(name for name, names in lacking.items() if not names))
    if _refusing(conflicts, found):
        return Export(status="ambiguous", revision=revision, complete=complete, conflicts=conflicts)
    if len(complete) > 1:
        return Export(status="ambiguous", revision=revision, complete=complete, conflicts=conflicts)
    settings = _lacking(PARAMETERS, found)
    if not complete:
        missing = dict(lacking)
        if settings:
            missing["parameters"] = settings
        return Export(
            status="contract_lost", revision=revision, missing=missing, conflicts=conflicts
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
        )
    read = set(STRUCTURES[structure]) | set(PARAMETERS)
    answer = {
        "form": _FORM,
        "version": _VERSION,
        "controller": {"structure": structure, **_measures(STRUCTURES[structure], found)},
        "parameters": _measures(PARAMETERS, found),
        "files": [],
    }
    raw = (json.dumps(answer, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    _write_new(out, raw)
    return Export(
        status="exported",
        revision=revision,
        structure=structure,
        complete=complete,
        taken_from={name: found[name][2] for name in sorted(read) if name in found},
        conflicts=conflicts,
        left_out=tuple(sorted(set(found) - read)),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _write_all(fd: int, raw: bytes) -> None:
    """Every byte of ``raw`` written to ``fd``."""
    view = memoryview(raw)
    while view:
        view = view[os.write(fd, view) :]


def _write_new(out: Path, raw: bytes) -> None:
    """``raw`` at ``out``, where nothing may be yet: written whole beside it, then linked there.

    The new name is made by :func:`tempfile.mkstemp` in ``out``'s directory, so nothing was at
    it; the link fails if anything is at ``out`` by then, and never replaces it; the new name
    is removed whatever happens, so a failed write leaves nothing behind.
    """
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{out.name}.", dir=out.parent)
    except OSError as exc:
        msg = f"the answer's directory cannot be made or written ({exc.strerror})"
        raise ExportError(msg, out=str(out)) from exc
    try:
        try:
            _write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.link(temporary, out, follow_symlinks=False)
    except OSError as exc:
        msg = f"the answer cannot be written where asked ({exc.strerror})"
        raise ExportError(msg, out=str(out)) from exc
    finally:
        os.unlink(temporary)
