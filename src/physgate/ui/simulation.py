"""The operator UI's read routes over a run's simulation records.

A role's script records each run of a simulation, and the session's end seals what it recorded,
by digest and length, on its line in the run's event log (``physgate.series``). These routes
show the operator that evidence and only that.

**The listing reads the event log alone.** For each attempt it lists:

- the records its sessions sealed, found by the reader's own rule (``attempt_records``, which the
  change check and the review packet use), so a later session's record of an id supersedes an
  earlier one's exactly as there;
- the records a later session superseded;
- every file a session's collector set aside, with its reason;
- every graph quantity the change check held to a record, as the check recorded it.

It opens no record and never looks in the run's series directory. A file there that no session's
end seals (a writer's leftover, a planted file, the collector's own tree of what it refused) is
never named.

**A gate column that shows only what a gate record says about the quantity.** Each checked
quantity is joined, by its name, to the gate records of the same subtask and attempt:

- an unchecked record on the quantity's node that names it;
- or a failing record the gate's finding names it in, matched to the quantity by node, value and
  unit, with the range it was held to.

A failing finding that names the quantity but matches no failing record, or more than one, is
said to be unmatched, and no record is picked. A gate record that names other quantities says
nothing about this one, and a pass names no quantity at all, so neither is ever a verdict on it.
Where no gate record names the quantity, the answer says that instead, and it also says when the
gate did not run: its mode was off, the attempt was refused before it, or the attempt has not
reached it yet. The gate's mode is read off the records themselves, never from the run's
configuration.

**Numbers as the records hold them.** Values go out as JSON numbers, which Python writes in the
shortest form that reads back as the same double. An integer larger than a browser's number holds
exactly goes out as its decimal numeral, so the page shows the integer the record holds.

**One record, as its seal names it.** The record route finds the record as the attempt route
does, reads it once through the reader's checked read, has the format's one parser admit those
bytes, and answers with exactly them: never a re-encoding of what was parsed, so the page draws
what the session sealed. A record that cannot be served as sealed is refused with the seal it
was held to and what the reader found, named by its place in the run and never by where the run
lies on disk, exactly as the attempt route's row for it says.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from physgate.orchestrator.budget import ATTEMPT_LIMIT
from physgate.orchestrator.events import (
    AttemptRejected,
    Event,
    GateRan,
    GateSkipped,
    Merged,
    ProposalsChecked,
    SessionEnded,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.protocols import (
    CheckRecord,
    MagnitudeDetails,
    NumericOutput,
    UncheckedDetails,
)
from physgate.series.exceptions import RecordRefusedError, RecordTamperedError
from physgate.series.extract import MAGNITUDE_TRACE, PHASE_TRACE
from physgate.series.reader import (
    SERIES_DIR,
    SealedEntry,
    attempt_records,
    read_record,
    read_sealed_bytes,
)
from physgate.series.record import Column, Record, parse_record
from physgate.series.seal import SeriesCheck
from physgate.series.summary import column_summary
from physgate.series.tolerance import RELATIVE_TOLERANCE
from physgate.ui.exceptions import NotFoundError, PathRefusedError, UIError
from physgate.ui.readers import EVENTS, run_dir_of
from physgate.ui.routes import Context, Response, json_response

#: The largest integer a browser's number holds exactly (2**53 - 1).
SAFE_INTEGER = 9_007_199_254_740_991

#: What the gate column says when no gate record of the attempt can be shown for a quantity.
NOT_NAMED = "not_named"
UNMATCHED = "unmatched"
GATE_OFF = "gate_off"
REFUSED_BEFORE_GATE = "refused_before_gate"
GATE_NOT_RUN = "gate_not_run"


def _number(value: float | int) -> float | int | str:
    """``value`` as sent: a number, or the numeral of an integer a browser cannot hold exactly."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > SAFE_INTEGER:
        return str(value)
    return value


def _quantity(output: NumericOutput) -> dict[str, Any]:
    return {"value": _number(output.value), "unit": output.unit}


def _of(event: Event, key: tuple[str, int]) -> bool:
    """Whether ``event`` names the subtask and attempt ``key``."""
    subtask = getattr(event, "subtask_id", None)
    attempt = getattr(event, "attempt", None)
    return (subtask, attempt) == key


def _entry(line: GateRan, record: CheckRecord) -> dict[str, Any]:
    """One gate record as the listing shows it, with its range when it is a magnitude record."""
    ranged = record.details if isinstance(record.details, MagnitudeDetails) else None
    return {
        "seq": line.seq,
        "check": record.check,
        "name": record.name,
        "outcome": record.outcome,
        "gate_mode": record.gate_mode,
        "blocking": record.blocking,
        "expected": record.expected,
        "low": None if ranged is None else _quantity(ranged.low),
        "high": None if ranged is None else _quantity(ranged.high),
    }


def _naming(check: SeriesCheck, line: GateRan) -> list[dict[str, Any]] | None:
    """The records of ``line`` that name ``check``'s quantity, in order; ``None`` if unmatched.

    A record names the quantity when it is an unchecked record on the quantity's node that
    lists its name, or when the gate's finding names the quantity and exactly one failing
    record has its node, its value and its unit.
    """
    records = line.result.checks
    chosen: set[int] = set()
    for index, record in enumerate(records):
        if (
            record.outcome == "unchecked"
            and record.node == check.node_id
            and isinstance(record.details, UncheckedDetails)
            and check.quantity in record.details.quantities
        ):
            chosen.add(index)
    for ref in line.result.quantities:
        if (ref.node_id, ref.name) != (check.node_id, check.quantity):
            continue
        matches = [
            index
            for index, record in enumerate(records)
            if record.outcome == "fail"
            and record.node == ref.node_id
            and record.value is not None
            and record.value.value == ref.value
            and record.value.unit == ref.unit
        ]
        if len(matches) != 1:
            return None
        chosen.add(matches[0])
    return [_entry(line, records[index]) for index in sorted(chosen)]


def _gate(
    check: SeriesCheck, refused: bool, gated: Sequence[GateRan], skipped: bool
) -> list[dict[str, Any]] | str:
    """What the gate column shows for ``check``, from the attempt's lines after its check."""
    if refused and not gated:
        return REFUSED_BEFORE_GATE
    if gated:
        found: list[dict[str, Any]] = []
        for line in gated:
            named = _naming(check, line)
            if named is None:
                return UNMATCHED
            found += named
        return found or NOT_NAMED
    return GATE_OFF if skipped else GATE_NOT_RUN


def _check(check: SeriesCheck, gate: list[dict[str, Any]] | str) -> dict[str, Any]:
    shown: dict[str, Any] = check.model_dump(mode="json")
    shown["declared_value"] = _number(check.declared_value)
    shown["gate"] = gate
    return shown


def _attempt(events: list[Event], key: tuple[str, int], owner: str | None) -> dict[str, Any]:
    """Everything the listing says about one attempt, each piece from its own lines."""
    subtask, attempt = key
    ended = [e for e in events if isinstance(e, SessionEnded) and _of(e, key)]
    sealed = attempt_records(events, subtask, attempt)
    kept = {(entry.record.record_id, entry.session_id) for entry in sealed}
    position = {id(event): at for at, event in enumerate(events)}
    checked = [e for e in events if isinstance(e, ProposalsChecked) and _of(e, key)]
    last = checked[-1] if checked else None
    after = -1 if last is None else position[id(last)]
    gated = [
        e for e in events if isinstance(e, GateRan) and _of(e, key) and position[id(e)] > after
    ]
    skipped = any(
        isinstance(e, GateSkipped) and _of(e, key) and position[id(e)] > after for e in events
    )
    refused = last is not None and last.refused_by is not None
    return {
        "subtask_id": subtask,
        "attempt": attempt,
        "owner_role": owner,
        "merged": any(isinstance(e, Merged) and _of(e, key) for e in events),
        "rejected": any(isinstance(e, AttemptRejected) and _of(e, key) for e in events),
        "refused_by": None if last is None else last.refused_by,
        "sessions": [
            {
                "session_id": session.session_id,
                "outcome": session.outcome,
                "attempt_commit": session.attempt_commit,
            }
            for session in ended
        ],
        "records": [
            {
                "record_id": entry.record.record_id,
                "session_id": entry.session_id,
                "sha256": entry.record.sha256,
                "length": entry.record.length,
                "script": entry.record.script,
                "script_sha256": entry.record.script_sha256,
            }
            for entry in sealed
        ],
        "superseded": [
            {"record_id": record.record_id, "session_id": session.session_id}
            for session in ended
            for record in session.series.records
            if (record.record_id, session.session_id) not in kept
        ],
        "set_aside": [
            {
                "session_id": session.session_id,
                "kind": kind,
                "name": entry.name,
                "reason": entry.reason,
            }
            for session in ended
            for kind, entries in (
                ("refused", session.series.refused),
                ("discarded", session.series.discarded),
            )
            for entry in entries
        ],
        "checks": []
        if last is None
        else [_check(check, _gate(check, refused, gated, skipped)) for check in last.series_checks],
    }


def _events(context: Context, run_dir: Path, params: Mapping[str, str]) -> list[Event]:
    """The run's event log, read through the allowlist; a run with none yet is not found.

    Raises:
        NotFoundError: the run has no event log yet.
    """
    log = context.allowlist.resolve(run_dir / EVENTS)
    if not log.is_file():
        msg = "the run has no event log yet, so no session of it has ended"
        raise NotFoundError(msg, root=params["root"], name=params["name"])
    return read_events(log)


def listing(context: Context, params: Mapping[str, str]) -> Response:
    """Every attempt one of whose sessions ended, from the run's event log alone.

    Attempts come in the order their first session ended. No record is opened.
    """
    run_dir = run_dir_of(context, params)
    events = _events(context, run_dir, params)
    owners: dict[str, str] = {}
    order: dict[tuple[str, int], None] = {}
    for event in events:
        if isinstance(event, SubtaskPlanned):
            owners.setdefault(event.subtask_id, event.assigned_role)
        if isinstance(event, SessionEnded):
            order.setdefault((event.subtask_id, event.attempt), None)
    return json_response(
        {
            "tolerance": f"{float(RELATIVE_TOLERANCE):g}",
            "attempts": [_attempt(events, key, owners.get(key[0])) for key in order],
        }
    )


#: A digest as the reader reports one it found, beside a length, which is all digits.
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _summary(column: Column) -> dict[str, Any]:
    """One column as the review's listing summarises it, by the listing's own function."""
    shown = column_summary(column)
    return {
        "name": column.name,
        "unit": shown.unit,
        "samples": shown.samples,
        "first": shown.first,
        "last": shown.last,
        "smallest": shown.smallest,
        "largest": shown.largest,
    }


def _shown(record: Record, entry: SealedEntry, commit: str | None) -> dict[str, Any]:
    """A record read as sealed: what it is, how it was produced, and each column's summary."""
    blobs = {code.path: code.blob for code in entry.record.loaded}
    names = {trace.name for trace in record.traces}
    return {
        "title": record.title,
        "group": record.group,
        "axis": record.axis,
        # Drawn as a loop's frequency response exactly when the harness's own extractors would
        # read it as one: a frequency record carrying both of the loop's traces.
        "loop": record.axis == "frequency" and {MAGNITUDE_TRACE, PHASE_TRACE} <= names,
        "x": _summary(record.x),
        "traces": [_summary(trace) for trace in record.traces],
        "inputs": {
            name: {"value": _number(given.value), "unit": given.unit}
            for name, given in record.inputs.items()
        },
        "producer": {
            "script": {
                "path": record.producer.script.path,
                "sha256": record.producer.script.sha256,
                "blob": entry.record.script_blob,
            },
            "loaded": [
                {"path": code.path, "sha256": code.sha256, "blob": blobs.get(code.path)}
                for code in record.producer.loaded
            ],
        },
        "environment": [
            {"path": code.path, "sha256": code.sha256} for code in entry.record.environment
        ],
        "attempt_commit": commit,
    }


def _refused(entry: SealedEntry, kind: str, error: Exception) -> dict[str, Any]:
    """A record that could not be read as sealed: why, its seal, and what the reader found.

    The record is named by its path relative to the run, never by where the run lies on disk,
    and nothing of its bytes is sent.
    """
    row: dict[str, Any] = {
        "record": "/".join(
            (
                SERIES_DIR,
                entry.subtask_id,
                str(entry.attempt),
                entry.session_id,
                f"{entry.record.record_id}.json",
            )
        ),
        "refused": kind,
        "error": str(error),
        "sealed_sha256": entry.record.sha256,
        "sealed_length": entry.record.length,
    }
    found = getattr(error, "context", {}).get("found")
    if isinstance(found, str) and _DIGEST.fullmatch(found):
        row["found_sha256"] = found
    elif isinstance(found, str) and found.isdigit():
        row["found_length"] = int(found)
    return row


def _row(context: Context, run_dir: Path, entry: SealedEntry, commit: str | None) -> dict[str, Any]:
    """One sealed record, read through its seal, or the reason it could not be."""
    base = {
        "record_id": entry.record.record_id,
        "session_id": entry.session_id,
        "sha256": entry.record.sha256,
        "length": entry.record.length,
    }
    try:
        path = entry.path(run_dir)
        # Held to the allowlist first, then read by the path as built: the reader refuses a
        # path that is not its own real path, so a link is never followed to what it names.
        context.allowlist.resolve(path)
        record = read_record(path, entry.seal())
    except PathRefusedError as exc:
        return {**base, **_refused(entry, "seal", exc)}
    except RecordTamperedError as exc:
        return {**base, **_refused(entry, "seal", exc)}
    except RecordRefusedError as exc:
        return {**base, **_refused(entry, "format", exc)}
    return {**base, **_shown(record, entry, commit)}


def attempt(context: Context, params: Mapping[str, str]) -> Response:
    """One attempt's sealed records, each read through its seal; a refused one is its own row.

    Raises:
        NotFoundError: the run is not there, has no event log, has no such attempt, or the
            attempt sealed no record.
    """
    run_dir = run_dir_of(context, params)
    subtask, number = params["subtask"], int(params["attempt"])
    if number > ATTEMPT_LIMIT:
        msg = f"no such attempt: a subtask has at most {ATTEMPT_LIMIT} attempts"
        raise NotFoundError(msg, subtask=subtask, attempt=params["attempt"])
    events = _events(context, run_dir, params)
    sealed = attempt_records(events, subtask, number)
    if not sealed:
        msg = "this attempt sealed no simulation record"
        raise NotFoundError(msg, subtask=subtask, attempt=params["attempt"])
    commits = {
        event.session_id: event.attempt_commit
        for event in events
        if isinstance(event, SessionEnded)
    }
    return json_response(
        {
            "subtask_id": subtask,
            "attempt": number,
            "records": [
                _row(context, run_dir, entry, commits.get(entry.session_id)) for entry in sealed
            ],
        }
    )


class SeriesRefusedError(UIError):
    """A sealed record the record route will not serve: it changed, or this version cannot read it.

    Its context names the record by its place in the run, the seal it was held to, the reader's
    reason, and what the reader found, as the attempt route's row for the same record does.
    """


#: What a refusal of the record route says it is: the record is not the sealed bytes, or it is
#: but they are not a record this version reads.
BROKEN = "broken"
HELD = "held"


def _not_served(entry: SealedEntry, seal: str, error: Exception) -> SeriesRefusedError:
    """The refusal of ``entry``, said as the attempt route's row says it; no absolute path."""
    row = _refused(entry, "seal" if seal == BROKEN else "format", error)
    context = {key: str(value) for key, value in row.items() if key not in ("refused", "error")}
    msg = (
        "the record is not what its session sealed, so it is not served"
        if seal == BROKEN
        else "the record is sealed, but this version cannot read it"
    )
    return SeriesRefusedError(msg, seal=seal, reason=row["error"], **context)


def record(context: Context, params: Mapping[str, str]) -> Response:
    """One sealed record, as the very bytes its seal names, once the format's parser admits them.

    Raises:
        NotFoundError: the run is not there, has no event log, has no such attempt, or the
            attempt sealed no record of that id.
        PathRefusedError: the allowlist refuses the record's path; named relative to the run.
        SeriesRefusedError: the record is not the sealed bytes, or is not one this version reads.
    """
    run_dir = run_dir_of(context, params)
    subtask, number, wanted = params["subtask"], int(params["attempt"]), params["record"]
    if number > ATTEMPT_LIMIT:
        msg = f"no such attempt: a subtask has at most {ATTEMPT_LIMIT} attempts"
        raise NotFoundError(msg, subtask=subtask, attempt=params["attempt"])
    events = _events(context, run_dir, params)
    found = [
        entry
        for entry in attempt_records(events, subtask, number)
        if entry.record.record_id == wanted
    ]
    if not found:
        msg = "this attempt sealed no record of that id"
        raise NotFoundError(msg, subtask=subtask, attempt=params["attempt"], record=wanted)
    (entry,) = found
    try:
        path = entry.path(run_dir)
        # Held to the allowlist first, then read by the path as built, as the attempt route does.
        context.allowlist.resolve(path)
        data = read_sealed_bytes(path, entry.seal())
        # Admitted by the format's one parser; the bytes it admitted are the ones served.
        parse_record(data)
    except PathRefusedError as exc:
        # The allowlist's own refusal names the absolute path; the client gets the relative one.
        raise PathRefusedError(str(exc), record=_refused(entry, "seal", exc)["record"]) from None
    except RecordTamperedError as exc:
        raise _not_served(entry, BROKEN, exc) from None
    except RecordRefusedError as exc:
        raise _not_served(entry, HELD, exc) from None
    return Response(200, data, "application/json")
