"""The gate the orchestrator calls: runs the registered checks and folds them into a verdict.

The runner is the only place an observation becomes a record. It stamps each one
with the check's number, the scope it ran at, whether a failure there blocks
(read from the architecture's table, never from the check), and the mode the gate
was asked to run in. A mode it does not recognise, or none, is refused before any
check runs: a record without its mode would let an observed failure be counted as
a gated one, and the catch accounting would no longer mean anything.

A law of the closed-form laws check blocks only where that check blocks **and** the
law is out of probation. The check reports each law's failure the same way whatever
the law's state; the runner looks the law up in the table the gate was built with and
stamps a probation law's failure as a warning, in ``on`` mode as in ``observe``. The
check never decides whether its own failure blocks, and neither does a law. Each law
is stamped as a check of its own at each scope, so its reach is always on the record:
its own pass record with its count where it failed nowhere, its count on its failing
records where it failed, and its unchecked records where it judged nothing.

The verdict is not chosen here either. It follows from the records by the rule
the result shape itself enforces: it fails exactly when a check failed where its
failure blocks. Under ``observe`` the verdict is the same; the loop decides not to
act on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from physgate.gate.bounds_table import Bounds, load_bounds
from physgate.gate.catalogue import catalogue_digest
from physgate.gate.context import CheckContext
from physgate.gate.equilibrium import EquilibriumSolver
from physgate.gate.exceptions import GateModeError, LawRecordError, NothingCheckedError
from physgate.gate.graph import ChangeHistory, GraphView
from physgate.gate.laws import LawTable, load_laws
from physgate.gate.registry import CADENCE, REGISTRY, OnFailure, RegisteredCheck
from physgate.gate.result import CheckRun, Observation
from physgate.orchestrator.protocols import (
    CHECK_NUMBERS,
    Artefact,
    CheckName,
    CheckRecord,
    GateResult,
    IntegrationArtefact,
    LawDetails,
    LawStatus,
    PassDetails,
    QuantityRef,
    RunningGateMode,
    Scope,
    UncheckedDetails,
)

#: The order the scopes are checked in, narrowest first.
SCOPE_ORDER: tuple[Scope, ...] = ("subtask", "module", "system")
RUNNING_MODES: frozenset[str] = frozenset({"on", "observe"})


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
        self,
        registry: tuple[RegisteredCheck, ...] = REGISTRY,
        bounds: Bounds | None = None,
        solver: EquilibriumSolver | None = None,
        laws: LawTable | None = None,
    ) -> None:
        """Run the checks in ``registry`` against ``bounds`` and ``laws``; real unless a test says.

        Each law's probation state comes from ``laws``, the table the gate is built with, and
        decides whether a law's failure blocks; the catalogue digest on every result names it.

        Raises:
            BoundsTableError: the bounds table does not load; no gate is built without it.
            LawTableError: the law table does not load; no gate is built without it.
        """
        self._registry = registry
        self._bounds = bounds if bounds is not None else load_bounds()
        self._laws = laws if laws is not None else load_laws()
        self._catalogue_sha256 = catalogue_digest(self._laws)
        self._solver = solver
        self._law_status: Mapping[str, LawStatus] = MappingProxyType(dict(self._laws.statuses()))

    @property
    def catalogue_sha256(self) -> str:
        """The digest of the catalogue and the law table this gate was built with."""
        return self._catalogue_sha256

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        """Check one attempt's artefact.

        Raises:
            GateModeError: ``mode`` is not one in which a gate runs.
            NothingCheckedError: no registered check runs at the attempt's scopes.
            CorruptRecordError, DesignStateError: the graph cannot be read.
        """
        running = require_running_mode(mode)
        view = GraphView.read(Path(artefact.graph_root), base_revision=artefact.base_revision)
        return self.run(view, artefact.scopes, running)

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        """Check the integrated design at system scope, over the canonical graph.

        Every node is in scope; the store is read from its journal and never opened.
        The artefact's change history goes with it, for the propagation check.

        Raises:
            ChangeHistoryError: the history does not describe the store's journal.
            GateModeError: ``mode`` is not one in which a gate runs.
            NothingCheckedError: no registered check runs at system scope.
            CorruptRecordError, DesignStateError: the graph cannot be read.
        """
        running = require_running_mode(mode)
        history = ChangeHistory(
            baseline=artefact.baseline_revision, change_sets=artefact.change_sets
        )
        view = GraphView.read(Path(artefact.graph_root), base_revision=0, history=history)
        return self.run(view, ("system",), running)

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
                ran = entry.run(
                    CheckContext(
                        view=view,
                        scope=scope,
                        bounds=self._bounds,
                        solver=self._solver,
                        laws=self._laws,
                    )
                )
                if entry.name == "laws":
                    stamped, failing = _stamp_laws(
                        scope, on_failure, running, ran, self._law_status
                    )
                else:
                    _require_no_law(entry.name, ran)
                    stamped = _stamp(entry.name, scope, on_failure, running, ran)
                    failing = _failing(ran) if on_failure == "block" else []
                records.extend(stamped)
                failing_quantities.extend(failing)
        if not records:
            msg = "no registered check runs at the scopes asked for"
            raise NothingCheckedError(msg, scopes=",".join(wanted) or "none")
        return _fold(records, running, tuple(failing_quantities[:3]), self._catalogue_sha256)


def _ordered(observations: Iterable[Observation]) -> list[Observation]:
    """Observations in a stable order, so the same graph gives the same records."""
    return sorted(observations, key=lambda o: (o.node or "", o.module or "", o.outcome, o.message))


def _failing(ran: CheckRun) -> list[QuantityRef]:
    """The quantities of the failures in ``ran``, in record order."""
    return [q for o in _ordered(ran.observations) if o.outcome == "fail" for q in o.quantities]


def _law_of(observation: Observation) -> str | None:
    """The law an observation is about, if it names one."""
    details = observation.details
    if isinstance(details, LawDetails | UncheckedDetails | PassDetails):
        return details.law_id
    return None


def _require_no_law(name: CheckName, ran: CheckRun) -> None:
    """Refuse a law reported by any check but the laws check.

    Raises:
        LawRecordError: ``ran`` counts a law, or an observation in it names one.
    """
    if ran.law_evaluated or any(_law_of(o) is not None for o in ran.observations):
        msg = "only the laws check reports a law"
        raise LawRecordError(msg, check=name)


def _stamp_laws(
    scope: Scope,
    on_failure: OnFailure,
    mode: RunningGateMode,
    ran: CheckRun,
    statuses: Mapping[str, LawStatus],
) -> tuple[list[CheckRecord], list[QuantityRef]]:
    """The laws check's records, each law stamped as a check of its own, in law-id order.

    A law blocks here only if the check blocks here and the law is out of probation, as the
    table the gate was built with says. Returns the records and the quantities of the failures
    that block.

    Raises:
        LawRecordError: a law the table does not hold, a law without its count, a failure at
            another status than the table's or with another count than the law's, or an
            observation that names no law.
    """
    counts = {c.law_id: c.evaluated for c in ran.law_evaluated}
    by_law: dict[str, list[Observation]] = {}
    for observation in ran.observations:
        law_id = _law_of(observation)
        if law_id is None:
            msg = "a laws observation names no law"
            raise LawRecordError(msg, node=observation.node or "")
        by_law.setdefault(law_id, []).append(observation)
    if not counts and not by_law:
        if ran.evaluated:
            msg = "the laws check counted instances without naming their laws"
            raise LawRecordError(msg, evaluated=str(ran.evaluated))
        return _stamp("laws", scope, on_failure, mode, ran), []
    records: list[CheckRecord] = []
    failing: list[QuantityRef] = []
    for law_id in sorted(set(counts) | set(by_law)):
        status = statuses.get(law_id)
        if status is None:
            msg = "a law the check reported is not in the table the gate was built with"
            raise LawRecordError(msg, law=law_id)
        if law_id not in counts:
            msg = "a law was reported without its count"
            raise LawRecordError(msg, law=law_id)
        observations = tuple(by_law.get(law_id, ()))
        for o in observations:
            if isinstance(o.details, LawDetails) and o.details.law_status != status:
                msg = "a law was reported at another status than the table's"
                raise LawRecordError(msg, law=law_id, reported=o.details.law_status, table=status)
            if isinstance(o.details, LawDetails) and o.details.evaluated != counts[law_id]:
                msg = "a law's failing record does not carry the law's count"
                raise LawRecordError(msg, law=law_id)
        blocks = on_failure == "block" and status == "block"
        one = CheckRun(tool=ran.tool, evaluated=counts[law_id], observations=observations)
        records.extend(_stamp("laws", scope, "block" if blocks else "warn", mode, one, law_id))
        if blocks:
            failing.extend(_failing(one))
    return records, failing


def _stamp(
    name: CheckName,
    scope: Scope,
    on_failure: OnFailure,
    mode: RunningGateMode,
    ran: CheckRun,
    law_id: str | None = None,
) -> list[CheckRecord]:
    """Every record one check's run produces, each carrying the mode and the scope.

    ``law_id`` names the law, for one law of the laws check; its pass record names it too.
    """
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
    # A check that judged nothing and left something unchecked writes no pass: "found
    # nothing wrong (0 evaluated)" beside an unchecked record would read as a pass of what
    # was not read. A check with nothing in its scope at all still records its empty pass.
    judged_nothing_unchecked = ran.evaluated == 0 and any(
        o.outcome == "unchecked" for o in ran.observations
    )
    if not any(o.outcome == "fail" for o in ran.observations) and not judged_nothing_unchecked:
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
                message=(
                    f"the {law_id} law found nothing wrong ({ran.evaluated} evaluated)"
                    if law_id is not None
                    else f"the {name} check found nothing wrong ({ran.evaluated} evaluated)"
                ),
                gate_mode=mode,
                details=PassDetails(evaluated=ran.evaluated, law_id=law_id),
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
