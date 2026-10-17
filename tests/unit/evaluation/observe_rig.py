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

import hashlib
import json
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from harness_pin import measured_harness
from knowledge_fixture import build_fixture_library

from physgate.evaluation.observe.rerun import MEASURED, RerunPlan
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.decompose import Outcome, Plan, PlannedModule, mint_id, start_run
from physgate.orchestrator.escalation import bind
from physgate.orchestrator.git import head_of, object_format, verified_git_dir
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.ports import Leftover, SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import (
    Artefact,
    CheckRecord,
    GateResult,
    IntegrationArtefact,
    MagnitudeDetails,
    MessageUsage,
    NumericOutput,
    PassDetails,
    QuantityRef,
    ReviewResult,
    RunningGateMode,
    Usage,
)
from physgate.orchestrator.run_config import (
    ModelStrings,
    RunBounds,
    RunConfig,
    endpoint_of,
)
from physgate.orchestrator.trajectory import seal
from physgate.series.collect import collect as collect
from physgate.series.collect import empty_outbox
from physgate.series.seal import SessionSeries, SetAside
from physgate.state.schema import Node

#: The harness as the command measures it, once at import.
HARNESS = measured_harness()
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


def config(run_id: str, repo: Path, role: str = "electrical", **overrides: Any) -> RunConfig:  # noqa: ANN401
    """A complete configuration for a fake-session run against ``repo``, every module ``role``'s."""
    fields: dict[str, Any] = {
        "run_id": run_id,
        "seed": 1,
        "brief_sha256": "a" * 64,
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition="claude-sonnet-5",
            roles={role: "claude-sonnet-5"},
            reviewers={role: "claude-opus-5-5"},
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
        "thinking_display": "summarized",
        "role_python": None,
        "git_binary": None,
        "escalation_backend": "rules",
        "held_out": (),
        "held_out_canaries": (),
        "network": "open",
        "network_enforced": None,
        "os_layer": None,
    }
    fields.update(overrides)
    return RunConfig(**fields)


def node(
    node_id: str, kind: str = "component", *, bare: bool = False, role: str = "electrical"
) -> dict[str, Any]:
    """A node proposal; ``bare`` writes its quantity as a bare number, a schema error."""
    quantity: Any = (
        1.5 if bare else {"value": 1.5, "unit": "A", "source": "datasheet", "written_by": role}
    )
    return {
        "id": node_id,
        "kind": kind,
        "domain": role,
        "owner_role": role,
        "quantities": {"i": quantity},
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-26T00:00:00Z",
    }


#: A stand-in simulation: no physics, numbers made up and labelled so, recorded by the writer.
RECORDING_SCRIPT = """import os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer
seed = int(os.environ["STAND_IN_SEED"])
series_writer.record("step", title="Stand-in step, not a simulation", axis="time",
    x=("time", "s", [0.0, 0.01, 0.02]), traces=[("position", "m", [0.0, 0.01 * seed, 0.05])],
    inputs={"seed": (seed, "dimensionless")})
"""


@dataclass
class FakeSession:
    """Writes its module file and one proposal, then the orchestrator commits the attempt."""

    layout: RunGit
    #: Per call: the value the module file holds, to make one run differ from another.
    content: dict[int, str] = field(default_factory=dict)
    #: The calls whose proposal writes a bare number.
    bare: set[int] = field(default_factory=set)
    #: The result event each session's stream ends in, from its id and usage; by default a
    #: bare result that records no usage. The stream is sealed as written, as a real end is.
    result: Callable[[str, Usage], dict[str, Any]] | None = None
    #: When set, each session runs a script under its module that records one series with
    #: this seed, and its outbox is collected before the commit, as the dispatcher does.
    records: int | None = None
    #: When set, the proposed node also carries this quantity, which names the record.
    linked: dict[str, Any] | None = None
    #: The role the session plays; the node it proposes is that role's.
    role: str = "electrical"
    #: The recording script to run in place of the one-record stand-in. When it prints a JSON
    #: object of quantities (each a value, a unit and the record it was read off), the proposed
    #: node carries them, as a session reporting what it read off its own records would.
    script: str = RECORDING_SCRIPT
    #: Per call: the recording script that call writes, in place of ``script``.
    scripts: dict[int, str] = field(default_factory=dict)
    #: The calls that write their script but never run it, so they record nothing.
    unrun: set[int] = field(default_factory=set)
    #: The calls that end for infrastructure (an API error) after recording: nothing is
    #: committed, and the loop retries the attempt in a fresh session.
    infra: set[int] = field(default_factory=set)
    calls: int = 0

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[Leftover]:
        return []

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        self.calls += 1
        worktree = self.layout.open_subtask(request.subtask_id)
        module = worktree / request.module_dir
        module.mkdir(parents=True, exist_ok=True)
        (module / "impl.py").write_text(self.content.get(self.calls, "x = 1\n"))
        node_id = f"{self.role}.node_{request.subtask_id.replace('-', '_')}"
        proposal = worktree / ".physgate" / "proposals" / f"{node_id}.json"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        payload = node(node_id, bare=self.calls in self.bare, role=self.role)
        if self.linked is not None:
            payload["quantities"]["step_peak"] = {
                "source": "read off the stand-in step",
                "written_by": self.role,
                **self.linked,
            }
        sid = f"fake-{uuid.uuid4().hex[:12]}"
        usage = Usage(
            input_tokens=10 * self.calls,
            output_tokens=3,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=5,
        )
        stream = self.layout.run_dir / "sessions" / sid / "stdout.jsonl"
        stream.parent.mkdir(parents=True, exist_ok=True)
        ended = (
            {"type": "result", "session_id": sid}
            if self.result is None
            else self.result(sid, usage)
        )
        stream.write_text(json.dumps(ended) + "\n")
        series = SessionSeries()
        if self.records is not None:
            # As the dispatcher does: whatever an earlier session left is moved aside first.
            left = empty_outbox(worktree, self.layout.run_dir, sid)
            reported: dict[str, Any]
            if self.calls in self.unrun:
                script = worktree / request.module_dir / "sim.py"
                script.write_text(self.scripts.get(self.calls, self.script))
                series, reported = SessionSeries(discarded=left), {}
            else:
                series, reported = self._record(worktree, request, sid, self.records, left)
            for name, quantity in reported.items():
                payload["quantities"][name] = {
                    "source": "read off the session's own record",
                    "written_by": self.role,
                    **quantity,
                }
        proposal.write_text(json.dumps(payload))
        if self.calls in self.infra:
            return SessionReport(
                session_id=sid,
                end=SessionEnd(outcome="infrastructure", cause="api_error"),
                attempt_commit=None,
                trajectory=str(stream),
                trajectory_seal=seal(stream.read_bytes()),
                worktree=str(worktree),
                reading_verified=False,
                node_files_halted=False,
                usage=(),
                series=series,
            )
        commit = commit_attempt(
            worktree, request.subtask_id, request.attempt, sid, repo=self.layout.repo
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
            series=series,
        )

    def _record(
        self,
        worktree: Path,
        request: SessionRequest,
        sid: str,
        seed: int,
        left: tuple[SetAside, ...],
    ) -> tuple[SessionSeries, dict[str, Any]]:
        """Run a recording script in the module, then collect the outbox as dispatch does.

        Returns what was collected, and the quantities the script reported, if any.
        """
        script = worktree / request.module_dir / "sim.py"
        script.write_text(self.scripts.get(self.calls, self.script))
        done = subprocess.run(
            [sys.executable, "-E", "-s", str(script)],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(self.layout.run_dir / "home"),
                # The seed reaches the script from outside it, so two runs with different
                # seeds commit the same script and differ only in what it recorded.
                "STAND_IN_SEED": str(seed),
            },
        )
        assert done.returncode == 0, done.stderr
        reported: dict[str, Any] = json.loads(done.stdout) if done.stdout.strip() else {}
        collected = collect(
            worktree,
            module_dir=request.module_dir,
            run_dir=self.layout.run_dir,
            subtask_id=request.subtask_id,
            attempt=request.attempt,
            session_id=sid,
            object_format=object_format(verified_git_dir(self.layout.repo, linked=False)),
            discarded_before=left,
        )
        return collected, reported


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
    #: The quantities a failing call cites, as a real gate's finding does; none by default.
    cited: tuple[QuantityRef, ...] = ()

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.calls += 1
        failed = self.calls in self.fail_on
        return GateResult(
            verdict="fail" if failed else "pass",
            mode=mode,
            finding="the stall current is too high" if failed else "checked",
            failing_check="magnitude" if failed else None,
            numeric_output=NumericOutput(value=3.4, unit="A") if failed else None,
            quantities=self.cited if failed else (),
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
    #: The prefix of its message ids, to make one run's differ from another's.
    ids: str = "r"
    calls: int = 0
    #: Every attempt it was asked to review, as the loop handed it over.
    seen: list[Artefact] = field(default_factory=list)

    def review(self, artefact: Artefact) -> ReviewResult:
        self.calls += 1
        self.seen.append(artefact)
        return ReviewResult(
            verdict="pass",
            finding="sound",
            reviewer_model=self.model,
            session_id=f"rev-{uuid.uuid4().hex[:8]}",
            usage=(
                MessageUsage(
                    # Numbered per call, as the scripted endpoint numbers its messages.
                    message_id=f"{self.ids}-{self.calls}",
                    usage=Usage(
                        input_tokens=40,
                        output_tokens=9,
                        cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,
                    ),
                ),
            ),
        )


def start(
    root: Path,
    run_id: str,
    repo: Path,
    role: str = "electrical",
    **overrides: Any,  # noqa: ANN401
) -> RunConfig:
    """Start a run from the fixed plan, as decomposition would (no model call)."""
    cfg = config(run_id, repo, role, **overrides)
    plan = Plan(
        modules=tuple(
            PlannedModule(
                name=name,
                role=role,
                module_dir=f"modules/{mint_id(cfg.seed, i, name)}",
                spec=f"Build {name}.",
            )
            for i, name in enumerate(MODULES)
        ),
        interface_nodes=(Node.model_validate(node("iface.bus", kind="interface", role=role)),),
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
    start_run(
        outcome,
        config=cfg,
        run_dir=root / run_id,
        target_repo=repo,
        library=build_fixture_library(root / "library"),
    ).close()
    return cfg


def drive(
    root: Path,
    cfg: RunConfig,
    repo: Path,
    *,
    gate: Gate | None = None,
    session_content: dict[int, str] | None = None,
    bare: set[int] | None = None,
    reviewer_ids: str = "r",
    resume: bool = False,
    clock: Callable[[], datetime] | None = None,
    session_result: Callable[[str, Usage], dict[str, Any]] | None = None,
    records: int | None = None,
    linked: dict[str, Any] | None = None,
    role: str = "electrical",
    script: str = RECORDING_SCRIPT,
    reviewers: dict[str, Reviewer] | None = None,
    session: dict[str, Any] | None = None,
) -> str:
    """Drive a started run with the real loop and ports; return the step it ended on.

    ``reviewers``, when given, are the reviewers the loop asks, so a test can see what each
    was handed. ``session`` sets further fields of the stand-in session.
    """
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
        reviewers=reviewers
        or {name: Reviewer(model=m, ids=reviewer_ids) for name, m in cfg.models.reviewers.items()},
        dispatcher=FakeSession(
            run,
            content=session_content or {},
            bare=bare or set(),
            result=session_result,
            records=records,
            linked=linked,
            role=role,
            script=script,
            **(session or {}),
        ),
        changes=GitChangeChecker(run, run_dir / "store", modules),
        merger=GitMerger(run, removal_timeout_s=60.0),
        graph=keeper,
        escalation=bind("rules"),
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
    cfg = start(root, run_id, repo, kwargs.get("role", "electrical"), **overrides)
    drive(root, cfg, repo, **kwargs)
    return root / run_id


def fake_driver(root: Path, repo: Path, **drive_kwargs: Any) -> Callable[[RerunPlan], None]:  # noqa: ANN401
    """Drives a rerun as ``decompose`` then ``run`` would, with the stand-in session."""

    def drive_it(plan: RerunPlan) -> None:
        # The parameters as recorded; what decompose measures, measured again.
        fields = {k: getattr(plan.recorded, k) for k in RunConfig.model_fields if k not in MEASURED}
        fields |= {
            "seed": plan.recorded.seed,
            "brief_sha256": hashlib.sha256(plan.brief.read_bytes()).hexdigest(),
        }
        cfg = start(root, plan.run_id, repo, drive_kwargs.get("role", "electrical"), **fields)
        drive(root, cfg, repo, **drive_kwargs)

    return drive_it
