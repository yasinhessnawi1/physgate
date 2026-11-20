"""The harness arm's whole-run answer, exported from the run's design-state graph.

A raw agent writes its whole-run answer by hand. A harness run's design lives in its graph,
spread over the nodes its roles wrote, so its answer is exported from the graph as the run
left it: the canonical store's journal at its newest revision, read without opening a store
(opening one runs recovery, which writes).

**By name, never by guess.** Each field of the answer is the quantity of exactly that name in
the graph, in whichever node holds it, copied as the graph holds it: its value and its unit,
unconverted. Both arms are told the same form in the same bytes, its names and its units
among it, so the harness is held to the names the raw agent is held to. A near name is not
the name (``sample_rate`` is not ``update_rate``), and a value in another unit is exported in
that unit, so the scorer refuses it exactly as it would refuse the raw agent's: an exporter
that chose which near name was meant, or converted a unit, would be judging its own guess, and
a guess made on the harness's side only would steer the comparison it feeds. The names are
taken from the answer's own schema (:mod:`physgate.evaluation.whole.answer`), so the two
cannot drift apart. A value is not checked against its bound either; the scorer does that.

**The structure** is the one of the closed list whose every required name the graph holds.
None is no answer (``contract_lost``); more than one is no answer either (``ambiguous``),
since nothing in the graph says which is the controller the firmware runs. A name the graph
holds in several nodes is taken when every node agrees on its value and unit, and the answer
is ``ambiguous`` when any two disagree, whichever structure reads it. Names of another
structure that the chosen one does not read are left out of the answer and listed in the
record.

**What is not exported.** No ``analysed_controller``: the graph holds one set of coefficients,
the one the run's analysis and its firmware are both held to, so there is no second one to
state. No ``files``: the answer names none. No simulation record: the answer states choices,
and where the graph read a quantity off a sealed record, the quantity's value is what is
exported, its record staying beside the run.

The answer is written to a name nothing is at yet, never through a link, so nothing left at
that name is overwritten or written through.
"""

from __future__ import annotations

import hashlib
import json
import os
import typing
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from physgate.evaluation.whole.answer import Controller, Parameters, WholeRun
from physgate.state.exceptions import CorruptRecordError
from physgate.state.store import journal_records_after

#: Where a run keeps its canonical store, as ``physgate run`` opens it: ``<run>/store``.
STORE_DIRNAME = "store"

#: How the export ended. ``contract_lost``: the graph holds no structure whole, or lacks a
#: setting. ``ambiguous``: two nodes disagree on a name, or the graph holds two structures
#: whole.
Status = Literal["exported", "contract_lost", "ambiguous"]

_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class ExportError(Exception):
    """The run has no graph to export from, or the answer cannot be written where asked."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class Export(BaseModel):
    """What the export found in the graph, and the digest of the answer it wrote, if any.

    ``taken_from``, each exported name with the nodes that hold it; ``missing``, by structure
    (or ``parameters``), the required names the graph lacks; ``conflicts``, each name two nodes
    disagree on, with the nodes that hold it; ``complete``, the structures the graph holds
    whole; ``left_out``, the names of the answer's form the graph holds that the chosen
    structure does not read.
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


def export_whole_run(run_dir: Path, out: Path) -> Export:
    """The whole-run answer the run at ``run_dir`` left in its graph, written to ``out``.

    Nothing is written unless the export is ``exported``.

    Raises:
        ExportError: the run has no store, its journal is not one a store could have written,
            or something is already at ``out``.
    """
    revision, nodes = _graph(run_dir)
    found, conflicts = _found(nodes)
    lacking = {name: _lacking(fields, found) for name, fields in STRUCTURES.items()}
    complete = tuple(sorted(name for name, names in lacking.items() if not names))
    if conflicts:
        return Export(status="ambiguous", revision=revision, complete=complete, conflicts=conflicts)
    if len(complete) > 1:
        return Export(status="ambiguous", revision=revision, complete=complete)
    settings = _lacking(PARAMETERS, found)
    if not complete:
        missing = dict(lacking)
        if settings:
            missing["parameters"] = settings
        return Export(status="contract_lost", revision=revision, missing=missing)
    (structure,) = complete
    if settings:
        return Export(
            status="contract_lost",
            revision=revision,
            structure=structure,
            complete=complete,
            missing={"parameters": settings},
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
        left_out=tuple(sorted(set(found) - read)),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _write_new(out: Path, raw: bytes) -> None:
    """``raw`` written to ``out``, where nothing may be yet, never through a link."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(out, _WRITE_FLAGS, 0o644)
    except OSError as exc:
        msg = f"the answer cannot be written where asked ({exc.strerror})"
        raise ExportError(msg, out=str(out)) from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
