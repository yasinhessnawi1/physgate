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
  since the server starts no process.

A trajectory's path is never taken from the record. The record is written on the machine
that ran the session, and a forged log could name any file in the run directory, a running
session's credential among them. The path is built from the session id, the one way the
dispatcher names it.

The record lists and the ledger are sent as JSON lines, byte for byte what the command line
prints; the rest as JSON.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from physgate.evaluation.observe.cost import KNOWN_SHEETS, load_price_sheet, price_events
from physgate.evaluation.observe.manifest import manifest_id_of
from physgate.gate.graph import GraphView
from physgate.orchestrator.common import render_jsonl
from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.gate_events import recorded_gate_events
from physgate.orchestrator.replay import recorded_ledger
from physgate.orchestrator.run_config import load_run_config
from physgate.orchestrator.trajectory import read_sealed
from physgate.state.store import JOURNAL_NAME
from physgate.ui.exceptions import NotFoundError
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


def _run_dir(context: Context, params: Mapping[str, str]) -> Path:
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
    run_dir = _run_dir(context, params)
    recorded = load_run_config(_file(context, run_dir, RUN_CONFIG))
    return json_response(
        {"manifest_id": recorded.sha256(), "config": recorded.model_dump(mode="json")}
    )


def events(context: Context, params: Mapping[str, str]) -> Response:
    """The run's event log, one record per line, as the package reads it back."""
    run_dir = _run_dir(context, params)
    return _lines(render_jsonl(read_events(_file(context, run_dir, EVENTS))))


def ledger(context: Context, params: Mapping[str, str]) -> Response:
    """The task ledger, byte for byte what ``physgate ledger`` prints."""
    run_dir = _run_dir(context, params)
    held = recorded_ledger(_file(context, run_dir, EVENTS), _file(context, run_dir, LEDGER))
    return _lines(render_jsonl(held))


def gate_events(context: Context, params: Mapping[str, str]) -> Response:
    """The gate events, byte for byte what ``physgate gate-events`` prints."""
    run_dir = _run_dir(context, params)
    found = recorded_gate_events(
        _file(context, run_dir, EVENTS), _file(context, run_dir, RUN_CONFIG)
    )
    return _lines(render_jsonl(found))


def graph(context: Context, params: Mapping[str, str]) -> Response:
    """Every node at its latest revision, with its revision, from the run's journal."""
    run_dir = _run_dir(context, params)
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
    run_dir = _run_dir(context, params)
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
    run_dir = _run_dir(context, params)
    log = read_events(_file(context, run_dir, EVENTS))
    recorded = load_run_config(_file(context, run_dir, RUN_CONFIG))
    line = price_events(
        recorded, manifest_id_of(run_dir, log), log, load_price_sheet(params["date"])
    )
    return json_response(line.model_dump(mode="json"))
