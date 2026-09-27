"""Fake-session runs over real git, a real store and the real loop, for the observability tests.

A run here is what ``physgate run`` produces with its session dispatcher swapped for
a stand-in: the plan is started as decomposition starts it (from a fixed plan, no
model call), and the real loop drives it with the real change checker, merger and
store keeper. The stand-in session writes its module file and one node proposal
into the real worktree and the orchestrator's own template commits it. No binary,
no installation, no endpoint. What differs between two such runs is what differs
by construction: session ids, commit times, timestamps.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.cli import _harness_root
from physgate.orchestrator.decompose import Outcome, Plan, PlannedModule, mint_id, start_run
from physgate.orchestrator.git import head_of
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest
from physgate.orchestrator.protocols import (
    Artefact,
    CheckRecord,
    GateResult,
    IntegrationArtefact,
    MagnitudeDetails,
    MessageUsage,
    NumericOutput,
    PassDetails,
    ReviewResult,
    RunningGateMode,
    Usage,
)
from physgate.orchestrator.run_config import (
    ModelStrings,
    RunBounds,
    RunConfig,
    endpoint_of,
    harness_state,
)
from physgate.orchestrator.trajectory import seal
from physgate.state.schema import Node

#: The harness as the command measures it, once at import.
HARNESS = harness_state(_harness_root())
ENDPOINT = "http://127.0.0.1:9"
MODULES = ("s1", "s2")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def target_repo(root: Path) -> Path:
    """A target repository with one commit."""
    repo = root / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "README.md").write_text("target\n")
    (repo / "modules" / "keep.txt").write_text("x\n")
    git(repo, "init", "-q", "-b", "master")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "add", "-A")
    git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "i")
    return repo


def config(run_id: str, repo: Path, **overrides: Any) -> RunConfig:  # noqa: ANN401
    """A complete configuration for a fake-session run against ``repo``."""
    fields: dict[str, Any] = {
        "run_id": run_id,
        "seed": 1,
        "brief_sha256": "a" * 64,
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"electrical": "claude-sonnet-5"},
            reviewers={"electrical": "claude-opus-5-5"},
        ),
        "bounds": RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=120.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        "token_ceiling": 100_000,
        "claude_version": "2.1.272",
        "target_head": head_of(repo, "master"),
        "endpoint": endpoint_of(ENDPOINT),
        "auth": "api_key",
        "reportable": False,
        "harness": HARNESS,
        "effort": "high",
        "max_output_tokens": 64000,
    }
    fields.update(overrides)
    return RunConfig(**fields)


def node(node_id: str, kind: str = "component") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "i": {"value": 1.5, "unit": "A", "source": "datasheet", "written_by": "electrical"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-26T00:00:00Z",
    }


@dataclass
class FakeSession:
    """Writes its module file and one proposal, then the orchestrator commits the attempt."""

    layout: RunGit
    #: Per call: the value the module file holds, to make one run differ from another.
    content: dict[int, str] = field(default_factory=dict)
    calls: int = 0

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[Leftover]:
        return []

    def run(self, request: SessionRequest) -> SessionReport:
        self.calls += 1
        worktree = self.layout.open_subtask(request.subtask_id)
        module = worktree / request.module_dir
        module.mkdir(parents=True, exist_ok=True)
        (module / "impl.py").write_text(self.content.get(self.calls, "x = 1\n"))
        node_id = f"electrical.node_{request.subtask_id.replace('-', '_')}"
        proposal = worktree / ".physgate" / "proposals" / f"{node_id}.json"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text(json.dumps(node(node_id)))
        sid = f"fake-{uuid.uuid4().hex[:12]}"
        stream = self.layout.run_dir / "sessions" / sid / "stdout.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        stream.write_text(json.dumps({"type": "result", "session_id": sid}) + "\n")
        commit = commit_attempt(worktree, request.subtask_id, request.attempt, sid)
        usage = Usage(
            input_tokens=10 * self.calls,
            output_tokens=3,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=5,
        )
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=commit,
            trajectory=str(stream),
            trajectory_seal=seal(stream.read_bytes()),
            worktree=str(worktree),
            reading_verified=True,
            node_files_halted=False,
            usage=(MessageUsage(message_id=f"msg-{uuid.uuid4().hex[:8]}", usage=usage),),
        )


def _record(mode: RunningGateMode, *, failed: bool) -> CheckRecord:
    amps = NumericOutput(value=3.4, unit="A")
    details: PassDetails | MagnitudeDetails = (
        MagnitudeDetails(
            value=amps,
            low=NumericOutput(value=0.36, unit="A"),
            high=NumericOutput(value=2.0, unit="A"),
            source="a test table",
            table_sha256="0" * 64,
        )
        if failed
        else PassDetails(evaluated=1)
    )
    return CheckRecord(
        check=2,
        name="magnitude",
        scope="subtask",
        outcome="fail" if failed else "pass",
        blocking=True,
        node="motor.left" if failed else None,
        module=None,
        value=amps if failed else None,
        expected=None,
        tool="test",
        message="the stall current is too high" if failed else "in range",
        gate_mode=mode,
        details=details,
    )


@dataclass
class Gate:
    """A test gate: passes, unless told to fail a given call."""

    fail_on: set[int] = field(default_factory=set)
    calls: int = 0

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.calls += 1
        failed = self.calls in self.fail_on
        return GateResult(
            verdict="fail" if failed else "pass",
            mode=mode,
            finding="the stall current is too high" if failed else "checked",
            failing_check="magnitude" if failed else None,
            numeric_output=NumericOutput(value=3.4, unit="A") if failed else None,
            quantities=(),
            checks=(_record(mode, failed=failed),),
            catalogue_sha256="c" * 64,
        )

    def check_integration(
        self, artefact: IntegrationArtefact, *, mode: RunningGateMode
    ) -> GateResult:
        return GateResult(
            verdict="pass",
            mode=mode,
            finding="checked",
            failing_check=None,
            numeric_output=None,
            quantities=(),
            checks=(_record(mode, failed=False),),
            catalogue_sha256="c" * 64,
        )


@dataclass
class Reviewer:
    model: str = "claude-opus-5-5"
    calls: int = 0

    def review(self, artefact: Artefact) -> ReviewResult:
        self.calls += 1
        return ReviewResult(
            verdict="pass",
            finding="sound",
            reviewer_model=self.model,
            session_id=f"rev-{uuid.uuid4().hex[:8]}",
            usage=(
                MessageUsage(
                    message_id=f"r-{uuid.uuid4().hex[:8]}",
                    usage=Usage(
                        input_tokens=40,
                        output_tokens=9,
                        cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,
                    ),
                ),
            ),
        )


def start(root: Path, run_id: str, repo: Path, **overrides: Any) -> RunConfig:  # noqa: ANN401
    """Start a run from the fixed plan, as decomposition would (no model call)."""
    cfg = config(run_id, repo, **overrides)
    plan = Plan(
        modules=tuple(
            PlannedModule(
                name=name,
                role="electrical",
                module_dir=f"modules/{mint_id(cfg.seed, i, name)}",
                spec=f"Build {name}.",
            )
            for i, name in enumerate(MODULES)
        ),
        interface_nodes=(Node.model_validate(node("iface.bus", kind="interface")),),
    )
    outcome = Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model="claude-sonnet-5",
        num_turns=1,
    )
    start_run(outcome, config=cfg, run_dir=root / run_id, target_repo=repo).close()
    return cfg


def drive(
    root: Path,
    cfg: RunConfig,
    repo: Path,
    *,
    gate: Gate | None = None,
    session_content: dict[int, str] | None = None,
    resume: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> str:
    """Drive a started run with the real loop and ports; return the step it ended on."""
    run_dir = root / cfg.run_id
    run = RunGit(repo=repo, run_dir=run_dir, run_id=cfg.run_id)
    keeper = StoreKeeper(run, run_dir / "store")
    modules = {
        mint_id(cfg.seed, i, name): f"modules/{mint_id(cfg.seed, i, name)}"
        for i, name in enumerate(MODULES)
    }
    loop = Loop(
        config=cfg,
        run_dir=run_dir,
        gate=gate or Gate(),
        reviewers={role: Reviewer(model=m) for role, m in cfg.models.reviewers.items()},
        dispatcher=FakeSession(run, content=session_content or {}),
        changes=GitChangeChecker(run, run_dir / "store", modules),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        sleep=lambda _: None,
        **({"clock": clock} if clock is not None else {}),
    )
    try:
        step = loop.resume() if resume else loop.run()
    finally:
        loop.close()
        keeper.close()
    return step.kind


def fake_run(root: Path, run_id: str, repo: Path, **kwargs: Any) -> Path:  # noqa: ANN401
    """Start and drive one fake-session run to its end; return its run directory."""
    overrides = kwargs.pop("overrides", {})
    cfg = start(root, run_id, repo, **overrides)
    drive(root, cfg, repo, **kwargs)
    return root / run_id
