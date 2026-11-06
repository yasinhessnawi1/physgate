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
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

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
from physgate.series.reader import attempt_records
from physgate.series.seal import SeriesCheck
from physgate.series.tolerance import RELATIVE_TOLERANCE
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


def listing(context: Context, params: Mapping[str, str]) -> Response:
    """Every attempt one of whose sessions ended, from the run's event log alone.

    Attempts come in the order their first session ended. No record is opened.
    """
    run_dir = run_dir_of(context, params)
    events = read_events(context.allowlist.resolve(run_dir / EVENTS))
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
