"""A trial's record for the report, built from what the arm and its scorer left.

Each piece is read from the record that already holds it, never re-derived: the outcome
from the scorer's record, the gate's and reviewers' work from the run's events through
the catch accounting every other count uses, the cost from the run's cost line or, for the
raw arm's one session, from its stream at the same price sheet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from physgate.evaluation.observe.calls import read_call
from physgate.evaluation.observe.cost import CostLine, DatedSheet
from physgate.evaluation.observe.exceptions import PriceSheetError
from physgate.evaluation.per_role.report import (
    ControlFlags,
    Cost,
    FirmwareRuns,
    GateCatches,
    Outcome,
    ReportError,
    ReviewCatches,
)
from physgate.evaluation.per_role.task import Task
from physgate.orchestrator.catches import catches
from physgate.orchestrator.dispatch import read_captured
from physgate.orchestrator.events import Event, ReviewRan
from physgate.orchestrator.gate_events import GateEvent
from physgate.orchestrator.protocols import Usage

#: The firmware standings that are final; ``retry`` is not.
_FINAL = ("pass", "fail", "flaky", "unscored")


def control_trial(task: Task, score: Mapping[str, Any]) -> tuple[Outcome, ControlFlags]:
    """A control score's outcome and flags.

    On a task with a secondary view (secondary specs bounding the gain margin), each
    reading passes when the headline passes and every secondary spec of that reading does:
    the gain margin as a ratio or in dB, and every other secondary spec in both.
    """
    passed = bool(score["passed"])
    flags = score.get("flags") or {}
    secondary = [s for s in task.specs if s.counts == "secondary"]
    if not secondary:
        return ("pass" if passed else "fail"), ControlFlags(
            no_gain_crossover=bool(flags.get("no_gain_crossover", False))
        )
    held = {row["name"]: bool(row["passed"]) for row in score.get("specs", [])}

    def reading(skip: str) -> bool:
        return passed and all(held.get(s.name, False) for s in secondary if s.metric != skip)

    return ("pass" if passed else "fail"), ControlFlags(
        no_gain_crossover=bool(flags.get("no_gain_crossover", False)),
        full_view_ratio=reading("gain_margin_db"),
        full_view_db=reading("gain_margin_ratio"),
    )


def firmware_trial(
    standing: str, executions: Sequence[Mapping[str, Any]], *, infrastructure_ends: int
) -> tuple[Outcome, FirmwareRuns]:
    """A firmware answer's final standing and how its executions went.

    Each execution is the emulator's own record: whether one of its limits ended it
    (``limit``) and how many bytes its sandbox runtime wrote to its error stream
    (``sandbox_stderr_bytes``). ``unscored`` stays unscored here; the report counts it as
    the arm's fail.

    Raises:
        ReportError: the standing is not final, or an execution's record lacks a field.
    """
    if standing not in _FINAL:
        msg = f"the standing {standing!r} is not final; an answer to retry is not reported"
        raise ReportError(msg)
    try:
        failed = sum(int(e["sandbox_stderr_bytes"]) > 0 for e in executions)
        limits = sum(bool(e["limit"]) for e in executions)
    except KeyError as exc:
        msg = f"an execution's record holds no {exc.args[0]!r}"
        raise ReportError(msg) from None
    return cast(Outcome, standing), FirmwareRuns(
        executions=len(executions),
        sandbox_failed=failed,
        limit_hits=limits,
        infrastructure_ends=infrastructure_ends,
    )


def gate_and_reviews(
    gate: Sequence[GateEvent], events: Sequence[Event]
) -> tuple[GateCatches, ReviewCatches]:
    """The gate's catches over every check, and the reviews' verdicts, in one run."""
    every = [row for row in catches(gate) if row.name == "all"]
    reviews = [e for e in events if isinstance(e, ReviewRan)]
    return (
        GateCatches(
            checks_run=sum(r.checks_run for r in every),
            artefacts_caught=sum(r.artefacts_caught for r in every),
            caught_after_reviewer_passed=sum(r.caught_after_reviewer_passed for r in every),
        ),
        ReviewCatches(
            reviews=len(reviews),
            failed=sum(e.result.verdict == "fail" for e in reviews),
            blocked=sum(e.result.verdict == "blocked" for e in reviews),
        ),
    )


def cost_of_line(line: CostLine) -> Cost:
    """A harness run's cost, as its cost line priced it."""
    return Cost(
        tokens=sum(row.tokens.total() for row in line.rows),
        usd=line.usd,
        basis=line.basis,
        lower_bound=line.lower_bound or line.partial,
    )


def raw_cost(
    stream: Path, session_id: str, model: str, prices: DatedSheet, *, subscription: bool
) -> Cost:
    """The raw session's cost: its stream's usage at the sheet's prices for its model.

    Its cache writes are split as its result records them, on a sheet that prices per
    call; where the result is absent or records no split, every write is priced at the
    five-minute rate and the figure is marked a lower bound, as a run's cost line is.

    Raises:
        ReportError: the sheet has no price for the model.
    """
    captured = read_captured(stream)
    counts = {
        name: sum(getattr(m.usage, name) for m in captured.usage)
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    }
    usage = Usage(**counts)
    price = prices.sheet.usd_per_mtok.get(model)
    if price is None:
        msg = f"the price sheet of {prices.sheet.date} has no price for {model!r}"
        raise ReportError(msg)
    recorded = read_call(stream, session_id)
    writes = recorded.cache_writes if recorded is not None else None
    split = writes if prices.sheet.cache_write_ttl == "per_call" else None
    try:
        usd = price.usd(usage, split)
    except PriceSheetError as exc:
        raise ReportError(str(exc)) from exc
    unread = usage.cache_creation_input_tokens > 0 and split is None
    return Cost(
        tokens=usage.total(),
        usd=usd,
        basis="list_price_estimate" if subscription else "list_price",
        lower_bound=unread or captured.result is None,
    )
