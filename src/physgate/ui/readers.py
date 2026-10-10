"""The operator UI's read routes over one run: each a direct call into the reader the CLI uses.

No record format is parsed here. Every file a handler reads is first made real and held to
the allowlist, then handed to the package's own reader for that format:

- the run configuration: ``load_run_config``, with its digest as the manifest id;
- the event log: ``read_events``;
- the task ledger: ``recorded_ledger``, read without writing and held to the log's projection,
  exactly what ``physgate ledger`` prints;
- the gate events: ``recorded_gate_events``, exactly what ``physgate gate-events`` prints;
- the graph: ``GraphView.read``, the gate's own read-only view of the journal;
- a session's trajectory: ``read_sealed``, held to the seal its session's end recorded;
- the cost: ``price_events`` at a recorded price sheet, without the manifest's git checks,
  since the server starts no process;
- the trace: ``read_traces``, exactly what ``physgate trace`` prints;
- the run's decisions: ``decisions``, the sequence a rerun is compared by;
- where the run stands: ``replay(...).next_step()``, the loop's own answer;
- the tokens: ``TokenAccount``, per attribution, per kind and in total;
- the gate checks with what each said: ``recorded_gate_checks``, the same events
  ``physgate gate-events`` prints, each beside its record's bound, message and details;
- the graph at a revision, one node's history and the change list between two revisions:
  ``graph_at``, ``node_history`` and ``journal_diff``, read from the journal without opening a
  store, the change list through the store's own selection;
- the approval queue: ``queue_listing``, exactly what ``physgate queue list`` prints, read
  without writing; and one item as a person is shown it, ``item_view``, with its line's digest
  and every trajectory held to its seal, which is what a decision on it sends back.

A trajectory's path is never taken from the record. The record is written on the machine
that ran the session, and a forged log could name any file in the run directory, a running
session's credential among them. The path is built from the session id, the one way the
dispatcher names it.

The record lists and the ledger are sent as JSON lines, byte for byte what the command line
prints; the rest as JSON.
"""

from __future__ import annotations

import errno
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from physgate.evaluation.observe.cost import KNOWN_SHEETS, load_price_sheet, price_events
from physgate.evaluation.observe.manifest import manifest_id_of
from physgate.evaluation.observe.sequence import decisions as decision_sequence
from physgate.evaluation.observe.trace import read_traces
from physgate.gate.graph import GraphView
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.common import render_jsonl
from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.gate_events import recorded_gate_checks, recorded_gate_events
from physgate.orchestrator.queue import item_view, queue_files, queue_listing, read_stream
from physgate.orchestrator.replay import recorded_ledger, replay
from physgate.orchestrator.run_config import load_run_config
from physgate.orchestrator.trajectory import read_sealed
from physgate.state.schema import validate_node
from physgate.state.store import (
    JOURNAL_NAME,
    JournalLine,
    RevisionNotFoundError,
    graph_at,
    journal_diff,
    journal_records_after,
    node_history,
)
from physgate.ui.exceptions import NotFoundError, PathRefusedError
from physgate.ui.routes import Context, Response, json_response, run_directories

#: How the run's files are named in its directory.
EVENTS = "events.jsonl"
LEDGER = "ledger.jsonl"
RUN_CONFIG = "run.json"
STORE = "store"
SESSIONS = "sessions"
STREAM = "stdout.jsonl"

#: The media type of a body that is one JSON record per line.
JSON_LINES = "application/x-ndjson; charset=utf-8"

#: A session id as the event log's own model accepts it.
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def run_dir_of(context: Context, params: Mapping[str, str]) -> Path:
    """The run directory a request names by its root's position and its name."""
    wanted = (int(params["root"]), params["name"])
    for position, name, path in run_directories(context.allowlist):
        if (position, name) == wanted:
            return path
    msg = "no run of that name under that root"
    raise NotFoundError(msg, root=params["root"], name=params["name"])


def _file(context: Context, run_dir: Path, *parts: str) -> Path:
    return context.allowlist.resolve(run_dir.joinpath(*parts))


def _lines(body: str) -> Response:
    return Response(200, body.encode(), JSON_LINES)


def config(context: Context, params: Mapping[str, str]) -> Response:
    """The run's recorded configuration and its manifest id."""
    run_dir = run_dir_of(context, params)
    recorded = load_run_config(_file(context, run_dir, RUN_CONFIG))
    return json_response(
        {"manifest_id": recorded.sha256(), "config": recorded.model_dump(mode="json")}
    )


def events(context: Context, params: Mapping[str, str]) -> Response:
    """The run's event log, one record per line, as the package reads it back."""
    run_dir = run_dir_of(context, params)
    return _lines(render_jsonl(read_events(_file(context, run_dir, EVENTS))))


def ledger(context: Context, params: Mapping[str, str]) -> Response:
    """The task ledger, byte for byte what ``physgate ledger`` prints."""
    run_dir = run_dir_of(context, params)
    held = recorded_ledger(_file(context, run_dir, EVENTS), _file(context, run_dir, LEDGER))
    return _lines(render_jsonl(held))


def gate_events(context: Context, params: Mapping[str, str]) -> Response:
    """The gate events, byte for byte what ``physgate gate-events`` prints."""
    run_dir = run_dir_of(context, params)
    found = recorded_gate_events(
        _file(context, run_dir, EVENTS), _file(context, run_dir, RUN_CONFIG)
    )
    return _lines(render_jsonl(found))


def graph(context: Context, params: Mapping[str, str]) -> Response:
    """Every node at its latest revision, with its revision, from the run's journal."""
    run_dir = run_dir_of(context, params)
    store = _file(context, run_dir, STORE)
    _file(context, run_dir, STORE, JOURNAL_NAME)
    view = GraphView.read(store, 0)
    return json_response(
        {
            "head_revision": max(view.revisions.values(), default=0),
            "nodes": {
                node_id: {"revision": view.revisions[node_id], "node": node.model_dump(mode="json")}
                for node_id, node in sorted(view.nodes.items())
            },
        }
    )


def trajectory(context: Context, params: Mapping[str, str]) -> Response:
    """A session's captured stream, held to the seal its end recorded."""
    run_dir = run_dir_of(context, params)
    session_id = params["session"]
    ended = [
        event
        for event in read_events(_file(context, run_dir, EVENTS))
        if isinstance(event, SessionEnded) and event.session_id == session_id
    ]
    sealed = next((event for event in ended if event.trajectory_seal is not None), None)
    if sealed is None or sealed.trajectory_seal is None:
        msg = "the run records no sealed trajectory for that session"
        raise NotFoundError(msg, session=session_id)
    path = _file(context, run_dir, SESSIONS, session_id, STREAM)
    return Response(200, read_sealed(path, sealed.trajectory_seal), JSON_LINES)


def prices(context: Context, params: Mapping[str, str]) -> Response:
    """The dates of the recorded price sheets a cost can be read at."""
    return json_response({"prices": sorted(KNOWN_SHEETS)})


def cost(context: Context, params: Mapping[str, str]) -> Response:
    """The run's cost at the price sheet of the date named, as ``physgate cost`` prices it."""
    run_dir = run_dir_of(context, params)
    log = read_events(_file(context, run_dir, EVENTS))
    recorded = load_run_config(_file(context, run_dir, RUN_CONFIG))
    line = price_events(
        recorded, manifest_id_of(run_dir, log), log, load_price_sheet(params["date"])
    )
    return json_response(line.model_dump(mode="json"))


class _Record(Protocol):
    """A record the package's readers return: it serialises itself as the CLI prints it."""

    def model_dump_json(self) -> str: ...


def _model(model: _Record) -> object:
    """A model as the command line prints it: its JSON, read back."""
    return json.loads(model.model_dump_json())


def _line(event: _Record) -> dict[str, Any]:
    """An event as its log line holds it, which is the form the decision sequence reads."""
    line: dict[str, Any] = json.loads(event.model_dump_json())
    return line


def trace(context: Context, params: Mapping[str, str]) -> Response:
    """The run's trace, exactly what ``physgate trace`` prints."""
    run_dir = run_dir_of(context, params)
    _file(context, run_dir, EVENTS)
    _file(context, run_dir, RUN_CONFIG)
    return json_response(_model(read_traces(run_dir)))


def decisions(context: Context, params: Mapping[str, str]) -> Response:
    """The run's decisions in log order, each with the sequence number that made it."""
    run_dir = run_dir_of(context, params)
    log = read_events(_file(context, run_dir, EVENTS))
    return json_response({"decisions": decision_sequence([_line(e) for e in log])})


def status(context: Context, params: Mapping[str, str]) -> Response:
    """Where the run stands: what the loop would do next, and why it halted, if it did."""
    run_dir = run_dir_of(context, params)
    state = replay(read_events(_file(context, run_dir, EVENTS)))
    step = state.next_step()
    halted = state.halted
    return json_response(
        {
            "next_step": {
                "kind": step.kind,
                "subtask_id": step.subtask_id,
                "attempt": step.attempt,
                "point": step.point,
            },
            "halted": None
            if halted is None
            else {"seq": halted.seq, "reason": halted.reason, "detail": halted.detail},
        }
    )


def tokens(context: Context, params: Mapping[str, str]) -> Response:
    """The token account: per attribution, per kind of spender, and the run's total."""
    run_dir = run_dir_of(context, params)
    account = TokenAccount.from_events(read_events(_file(context, run_dir, EVENTS)))

    def dumped(by: Mapping[str, _Record]) -> dict[str, object]:
        return {key: _model(usage) for key, usage in by.items()}

    return json_response(
        {
            "by_attribution": dumped(account.by_attribution()),
            "by_kind": dumped(account.by_kind()),
            "total": _model(account.total()),
        }
    )


def gate_checks(context: Context, params: Mapping[str, str]) -> Response:
    """Every gate event with its record's bound, message and details, one per line."""
    run_dir = run_dir_of(context, params)
    found = recorded_gate_checks(
        _file(context, run_dir, EVENTS), _file(context, run_dir, RUN_CONFIG)
    )
    return _lines(render_jsonl(found))


def _journal(context: Context, run_dir: Path) -> Path:
    """The run's graph directory, with its journal held to the allowlist first."""
    store = _file(context, run_dir, STORE)
    _file(context, run_dir, STORE, JOURNAL_NAME)
    return store


def _revision(params: Mapping[str, str], name: str) -> int:
    return int(params[name])


def _node_of(line: JournalLine) -> object:
    return validate_node(line.payload).model_dump(mode="json")


def graph_at_revision(context: Context, params: Mapping[str, str]) -> Response:
    """Every node as it stood at a journal revision, each with the revision it was written at."""
    run_dir = run_dir_of(context, params)
    store = _journal(context, run_dir)
    revision = _revision(params, "revision")
    try:
        at = graph_at(store, revision)
    except RevisionNotFoundError as exc:
        raise NotFoundError(str(exc), **exc.context) from None
    return json_response(
        {
            "revision": revision,
            "head_revision": len(journal_records_after(store, 0)),
            "nodes": {
                node_id: {"revision": line.rev, "node": _node_of(line)}
                for node_id, line in at.items()
            },
        }
    )


def history(context: Context, params: Mapping[str, str]) -> Response:
    """One node's every revision, oldest first, each with the attempt that wrote it.

    A revision at or below the head decomposition recorded is the given design's; any
    other belongs to the merged attempt whose writes the event log names.
    """
    run_dir = run_dir_of(context, params)
    store = _journal(context, run_dir)
    node_id = params["node"]
    lines = node_history(store, node_id)
    if not lines:
        msg = "the run's journal holds no such node"
        raise NotFoundError(msg, node=node_id)
    baseline, change_sets = change_history(read_events(_file(context, run_dir, EVENTS)))
    writer = {
        revision: {"subtask_id": change.subtask_id, "attempt": change.attempt}
        for change in change_sets
        for revision in change.revisions
    }
    return json_response(
        {
            "node_id": node_id,
            "baseline": baseline,
            "history": [
                {
                    "revision": line.rev,
                    "op": line.op,
                    "version": line.version,
                    "written_by": "decomposition" if line.rev <= baseline else writer.get(line.rev),
                    "node": _node_of(line),
                }
                for line in lines
            ],
        }
    )


def diff(context: Context, params: Mapping[str, str]) -> Response:
    """The store's change list between two revisions, and each changed node at both."""
    run_dir = run_dir_of(context, params)
    store = _journal(context, run_dir)
    since, until = _revision(params, "from"), _revision(params, "to")
    if since > until:
        msg = "a diff runs from an earlier revision to a later one"
        raise NotFoundError(msg, revision_from=str(since), revision_to=str(until))
    try:
        changes = journal_diff(store, since, until)
        before, after = graph_at(store, since), graph_at(store, until)
    except RevisionNotFoundError as exc:
        raise NotFoundError(str(exc), **exc.context) from None
    changed = sorted({change.node_id for change in changes})

    def at(found: Mapping[str, JournalLine], node_id: str) -> object:
        line = found.get(node_id)
        return None if line is None else {"revision": line.rev, "node": _node_of(line)}

    return json_response(
        {
            "from": since,
            "to": until,
            "changes": [
                {
                    "revision": change.revision,
                    "node_id": change.node_id,
                    "version": change.version,
                    "op": change.op,
                }
                for change in changes
            ],
            "nodes": {
                node_id: {"before": at(before, node_id), "after": at(after, node_id)}
                for node_id in changed
            },
        }
    )


def _queue_files(context: Context, run_dir: Path) -> None:
    """Hold the queue's files and the event log to the allowlist before anything reads them."""
    for path in queue_files(run_dir):
        context.allowlist.resolve(path)


def queue(context: Context, params: Mapping[str, str]) -> Response:
    """The open items and every decision with its mark, byte for byte ``physgate queue list``."""
    run_dir = run_dir_of(context, params)
    _queue_files(context, run_dir)
    return json_response(queue_listing(run_dir))


def queue_item(context: Context, params: Mapping[str, str]) -> Response:
    """One item as a person is shown it: open or not, its digest, each trajectory's seal status.

    A trajectory's path is built from the session id its link names, never taken as recorded.
    """
    run_dir = run_dir_of(context, params)
    _queue_files(context, run_dir)

    def stream(session_id: str) -> bytes | None:
        try:
            path = _file(context, run_dir, SESSIONS, session_id, STREAM)
        except PathRefusedError as exc:
            # A stream the allowlist refuses (a link out of the run, a second name) is not read;
            # it is reported as tampered, which is what the decision's own check finds as well.
            raise OSError(errno.EPERM, str(exc)) from None
        return read_stream(path)

    view = item_view(run_dir, int(params["position"]), read_stream=stream)
    if view is None:
        msg = "the run's queue holds no item at that position"
        raise NotFoundError(msg, position=params["position"])
    return json_response(view.model_dump(mode="json"))
