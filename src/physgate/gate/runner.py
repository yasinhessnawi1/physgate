"""The gate the orchestrator calls: runs the registered checks and folds them into a verdict.

The runner is the only place an observation becomes a record. It stamps each one
with the check's number, the scope it ran at, whether a failure there blocks
(read from the architecture's table, never from the check), and the mode the gate
was asked to run in. A mode it does not recognise, or none, is refused before any
check runs: a record without its mode would let an observed failure be counted as
a gated one, and the catch accounting would no longer mean anything.

The verdict is not chosen here either. It follows from the records by the rule
the result shape itself enforces: it fails exactly when a check failed where its
failure blocks. Under ``observe`` the verdict is the same; the loop decides not to
act on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from physgate.gate.bounds_table import Bounds, load_bounds
from physgate.gate.catalogue import catalogue_digest
from physgate.gate.context import CheckContext
from physgate.gate.exceptions import GateModeError, NothingCheckedError
from physgate.gate.graph import GraphView
from physgate.gate.registry import CADENCE, REGISTRY, OnFailure, RegisteredCheck
from physgate.gate.result import CheckRun, Observation
from physgate.orchestrator.protocols import (
    CHECK_NUMBERS,
    Artefact,
    CheckName,
    CheckRecord,
    GateResult,
    PassDetails,
    QuantityRef,
    RunningGateMode,
    Scope,
)

#: The order the scopes are checked in, narrowest first.
SCOPE_ORDER: tuple[Scope, ...] = ("subtask", "module", "system")
RUNNING_MODES: frozenset[str] = frozenset({"on", "observe"})


def scopes_and_base(artefact: Artefact) -> tuple[tuple[Scope, ...], int]:
    """The scopes an attempt is checked at, and the journal head before it.

    A bridge, and a temporary one: the orchestrator's artefact does not yet say
    which scopes apply or where the attempt's own writes begin. Until it does, an
    attempt is checked at subtask scope only, and every node counts as its own.
    Once the artefact carries both, they are read from it, and this function is
    removed with a test asserting it is gone.
    """
    scopes: tuple[Scope, ...] | None = getattr(artefact, "scopes", None)
    base: int | None = getattr(artefact, "base_revision", None)
    return (scopes if scopes is not None else ("subtask",), base if base is not None else 0)


def require_running_mode(mode: object) -> RunningGateMode:
    """Return ``mode`` if it is one in which the gate runs.

    Raises:
        GateModeError: it is ``off``, or anything else. Under ``off`` the gate is
            not called at all, so a call in that mode is a caller's mistake.
    """
    if mode == "on":
        return "on"
    if mode == "observe":
        return "observe"
    msg = "the gate runs only in mode 'on' or 'observe'"
    raise GateModeError(msg, mode=repr(mode))


class PhysicsGate:
    """The physics gate: every registered check, at the scopes it is asked for."""

    def __init__(
        self, registry: tuple[RegisteredCheck, ...] = REGISTRY, bounds: Bounds | None = None
    ) -> None:
        """Run the checks in ``registry`` against ``bounds``: the real ones unless a test says.

        Raises:
            BoundsTableError: the bounds table does not load; no gate is built without it.
        """
        self._registry = registry
        self._bounds = bounds if bounds is not None else load_bounds()
        self._catalogue_sha256 = catalogue_digest()

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        """Check one attempt's artefact.

        Raises:
            GateModeError: ``mode`` is not one in which a gate runs.
            NothingCheckedError: no registered check runs at the attempt's scopes.
            CorruptRecordError, DesignStateError: the graph cannot be read.
        """
        running = require_running_mode(mode)
        scopes, base = scopes_and_base(artefact)
        view = GraphView.read(Path(artefact.graph_root), base_revision=base)
        return self.run(view, scopes, running)

    def run(self, view: GraphView, scopes: Iterable[Scope], mode: RunningGateMode) -> GateResult:
        """Run every registered check at each of ``scopes`` over ``view``.

        Raises:
            GateModeError: ``mode`` is not one in which a gate runs.
            NothingCheckedError: no registered check runs at any of ``scopes``.
        """
        running = require_running_mode(mode)
        asked = set(scopes)
        wanted = [s for s in SCOPE_ORDER if s in asked]
        records: list[CheckRecord] = []
        failing_quantities: list[QuantityRef] = []
        for entry in self._registry:
            for scope in wanted:
                on_failure = CADENCE[entry.name].get(scope)
                if on_failure is None:
                    continue
                ran = entry.run(CheckContext(view=view, scope=scope, bounds=self._bounds))
                stamped = _stamp(entry.name, scope, on_failure, running, ran)
                records.extend(stamped)
                if on_failure == "block":
                    failing_quantities.extend(
                        q
                        for o in _ordered(ran.observations)
                        if o.outcome == "fail"
                        for q in o.quantities
                    )
        if not records:
            msg = "no registered check runs at the scopes asked for"
            raise NothingCheckedError(msg, scopes=",".join(wanted) or "none")
        return _fold(records, running, tuple(failing_quantities[:3]), self._catalogue_sha256)


def _ordered(observations: Iterable[Observation]) -> list[Observation]:
    """Observations in a stable order, so the same graph gives the same records."""
    return sorted(observations, key=lambda o: (o.node or "", o.module or "", o.outcome, o.message))


def _stamp(
    name: CheckName,
    scope: Scope,
    on_failure: OnFailure,
    mode: RunningGateMode,
    ran: CheckRun,
) -> list[CheckRecord]:
    """Every record one check's run produces, each carrying the mode and the scope."""
    blocking = on_failure == "block"
    records = [
        CheckRecord(
            check=CHECK_NUMBERS[name],
            name=name,
            scope=scope,
            outcome="warn" if o.outcome == "fail" and not blocking else o.outcome,
            blocking=blocking,
            node=o.node,
            module=o.module,
            value=o.value,
            expected=o.expected,
            tool=ran.tool,
            message=o.message,
            gate_mode=mode,
            details=o.details,
        )
        for o in _ordered(ran.observations)
    ]
    if not any(o.outcome == "fail" for o in ran.observations):
        records.insert(
            0,
            CheckRecord(
                check=CHECK_NUMBERS[name],
                name=name,
                scope=scope,
                outcome="pass",
                blocking=blocking,
                node=None,
                module=None,
                value=None,
                expected=None,
                tool=ran.tool,
                message=f"the {name} check found nothing wrong ({ran.evaluated} evaluated)",
                gate_mode=mode,
                details=PassDetails(evaluated=ran.evaluated),
            ),
        )
    return records


def _fold(
    records: list[CheckRecord],
    mode: RunningGateMode,
    quantities: tuple[QuantityRef, ...],
    catalogue_sha256: str,
) -> GateResult:
    """The verdict and the finding the records add up to."""
    blocking = [r for r in records if r.outcome == "fail" and r.blocking]
    warnings = [r for r in records if r.outcome == "warn"]
    if blocking:
        first = blocking[0]
        more = len(blocking) - 1
        finding = first.message + (
            f" ({more} more blocking finding(s) in the record)" if more else ""
        )
        return GateResult(
            verdict="fail",
            mode=mode,
            finding=finding,
            failing_check=first.name,
            numeric_output=first.value,
            quantities=quantities,
            checks=tuple(records),
            catalogue_sha256=catalogue_sha256,
        )
    finding = "every check passed"
    if warnings:
        finding += f", with {len(warnings)} warning(s): " + "; ".join(w.message for w in warnings)
    return GateResult(
        verdict="pass",
        mode=mode,
        finding=finding,
        failing_check=None,
        numeric_output=None,
        quantities=(),
        checks=tuple(records),
        catalogue_sha256=catalogue_sha256,
    )
