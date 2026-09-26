"""Scripted stand-ins for the loop's ports, recording every call."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orch_helpers import make_config, ticking_clock

from physgate.orchestrator.budget import InfraCause, SessionEnd
from physgate.orchestrator.common import GateMode
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import ChangeCheck, SessionReport, SessionRequest
from physgate.orchestrator.protocols import (
    Artefact,
    GateResult,
    MessageUsage,
    NumericOutput,
    QuantityRef,
    ReviewResult,
    RunningGateMode,
    Usage,
)
from physgate.state.task_ledger import TaskLedger


def sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()  # noqa: S324 - a stand-in commit id


def usage(n: int) -> Usage:
    return Usage(
        input_tokens=n, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0
    )


class KilledError(Exception):
    """Stands in for the orchestrator being killed inside a port call."""


@dataclass
class FakeDispatcher:
    """Completes every session, unless told to fail or be killed on a given call."""

    infra: dict[int, InfraCause] = field(default_factory=dict)
    unread: set[int] = field(default_factory=set)
    halted: set[int] = field(default_factory=set)
    kill_on: int | None = None
    requests: list[SessionRequest] = field(default_factory=list)

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[tuple[str, int, int]]:
        return []

    def run(self, request: SessionRequest) -> SessionReport:
        self.requests.append(request)
        call = len(self.requests)
        if call == self.kill_on:
            raise KilledError
        sid = f"sess-{call}"
        if call in self.infra:
            return SessionReport(
                session_id=sid,
                end=SessionEnd(outcome="infrastructure", cause=self.infra[call]),
                attempt_commit=None,
                trajectory=None,
                worktree=None,
                reading_verified=False,
                node_files_halted=False,
                usage=(MessageUsage(message_id=f"m{call}", usage=usage(3)),),
            )
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=sha(f"{request.subtask_id}-{request.attempt}-{call}"),
            trajectory=f"sessions/{sid}/stdout.jsonl",
            worktree=f"worktrees/{request.subtask_id}",
            reading_verified=call not in self.unread,
            node_files_halted=call in self.halted,
            usage=(
                MessageUsage(message_id=f"m{call}a", usage=usage(10)),
                MessageUsage(message_id=f"m{call}a", usage=usage(10)),
                MessageUsage(message_id=f"m{call}b", usage=usage(20)),
            ),
        )


@dataclass
class FakeChanges:
    refuse: dict[int, tuple[str, str]] = field(default_factory=dict)
    calls: int = 0

    def check(self, subtask_id: str, attempt_commit: str, role: str) -> ChangeCheck:
        self.calls += 1
        refused = self.refuse.get(self.calls)
        return ChangeCheck(
            refused_by=refused[0] if refused else None,  # type: ignore[arg-type]
            reason=refused[1] if refused else None,
            graph_root="scratch/graph",
        )


def failing_gate_result(mode: RunningGateMode) -> GateResult:
    return GateResult(
        verdict="fail",
        mode=mode,
        finding="the stall current exceeds the driver's rating",
        failing_check="bounds",
        numeric_output=NumericOutput(value=3.4, unit="A"),
        quantities=(QuantityRef(node_id="motor.left", name="stall_current", value=3.4, unit="A"),),
    )


@dataclass
class FakeGate:
    verdicts: list[str] = field(default_factory=list)
    seen: list[Artefact] = field(default_factory=list)

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.seen.append(artefact)
        verdict = (
            self.verdicts[len(self.seen) - 1] if len(self.seen) <= len(self.verdicts) else "pass"
        )
        if verdict == "fail":
            return failing_gate_result(mode)
        return GateResult(
            verdict="pass",
            mode=mode,
            finding="every check passed",
            failing_check=None,
            numeric_output=None,
            quantities=(),
        )


@dataclass
class FakeReviewer:
    model: str = "claude-opus-5"
    verdicts: list[str] = field(default_factory=list)
    seen: list[Artefact] = field(default_factory=list)
    kill_on: int | None = None

    def review(self, artefact: Artefact) -> ReviewResult:
        self.seen.append(artefact)
        if len(self.seen) == self.kill_on:
            raise KilledError
        n = len(self.seen)
        verdict = self.verdicts[n - 1] if n <= len(self.verdicts) else "pass"
        return ReviewResult(
            verdict=verdict,  # type: ignore[arg-type]
            finding="the change is sound" if verdict == "pass" else "the gain changed silently",
            reviewer_model=self.model,
            session_id=f"rev-{n}",
            usage=(MessageUsage(message_id=f"r{n}", usage=usage(7)),),
        )


@dataclass
class FakeMerger:
    ledger_path: Path | None = None
    merges: list[tuple[str, int, str]] = field(default_factory=list)
    ledger_at_merge: list[Any] = field(default_factory=list)

    messages: list[str] = field(default_factory=list)

    def merge(self, subtask_id: str, attempt: int, attempt_commit: str, message: str) -> str:
        self.messages.append(message)
        if self.ledger_path is not None:
            fresh = TaskLedger(self.ledger_path)
            self.ledger_at_merge.append(fresh.find(subtask_id))
            fresh.close()
        if (subtask_id, attempt, attempt_commit) not in self.merges:
            self.merges.append((subtask_id, attempt, attempt_commit))
        return sha(f"merge-{attempt_commit}")

    def artefact_diff(self, attempt_commit: str) -> str:
        return f"diff --git a/x b/x\n+ attempt {attempt_commit[:8]}\n"


@dataclass
class FakeGraph:
    """A graph port with an empty journal, reporting divergences on chosen diff calls."""

    divergent: dict[int, tuple[str, ...]] = field(default_factory=dict)
    calls: list[tuple[int, str]] = field(default_factory=list)
    reopened: int = 0

    def records_after(self, revision: int) -> list[Any]:
        return []

    def hold(self) -> None:
        return None

    def commit(self, message: str) -> None:
        return None

    def proposals(self, subtask_id: str, attempt_commit: str) -> list[dict[str, Any]]:
        return []

    def write(self, payload: dict[str, Any], role: str) -> int:
        raise AssertionError("no proposal, so nothing is written")

    def divergences(self, since: int, acting_role: str) -> tuple[str, ...]:
        self.calls.append((since, acting_role))
        return self.divergent.get(len(self.calls), ())

    def reopen(self) -> tuple[int, tuple[str, ...]]:
        self.reopened += 1
        return 0, ()


@dataclass
class Rig:
    """A loop over fakes in one run directory, rebuildable as a fresh process would."""

    run_dir: Path
    gate_mode: GateMode = "on"
    gate: FakeGate | None = field(default_factory=FakeGate)
    reviewer: FakeReviewer = field(default_factory=FakeReviewer)
    dispatcher: FakeDispatcher = field(default_factory=FakeDispatcher)
    changes: FakeChanges = field(default_factory=FakeChanges)
    merger: FakeMerger = field(default_factory=FakeMerger)
    diff: FakeGraph = field(default_factory=FakeGraph)
    delays: tuple[float, ...] = ()
    slept: list[float] = field(default_factory=list)
    config_overrides: dict[str, Any] = field(default_factory=dict)

    def open(self) -> Loop:
        from orch_helpers import SCRIPTED_BOUNDS

        self.merger.ledger_path = self.run_dir / "ledger.jsonl"
        bounds = SCRIPTED_BOUNDS.model_copy(update={"infra_retry_delays_s": self.delays})
        config = make_config(gate_mode=self.gate_mode, bounds=bounds, **self.config_overrides)
        sleeper: Callable[[float], None] = self.slept.append
        return Loop(
            config=config,
            run_dir=self.run_dir,
            gate=self.gate,
            reviewers={"electrical": self.reviewer},
            dispatcher=self.dispatcher,
            changes=self.changes,
            merger=self.merger,
            graph=self.diff,
            sleep=sleeper,
            clock=ticking_clock(),
        )


def plan(*ids: str) -> list[dict[str, str]]:
    return [
        {
            "subtask_id": i,
            "spec_path": f"specs/{i}.md",
            "assigned_role": "electrical",
            "module_dir": f"modules/{i}",
        }
        for i in ids
    ]
