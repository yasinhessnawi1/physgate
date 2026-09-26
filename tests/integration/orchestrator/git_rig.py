"""A real git repository and run layout for the orchestrator's git tests."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from physgate.orchestrator.budget import SessionEnd
from physgate.orchestrator.git import head_of
from physgate.orchestrator.managed import EMPTY_OVERRIDE_SHA256
from physgate.orchestrator.merge import RunGit, commit_attempt, write_scope_violations
from physgate.orchestrator.ports import ChangeCheck, SessionReport, SessionRequest
from physgate.orchestrator.protocols import (
    Artefact,
    GateResult,
    MessageUsage,
    NumericOutput,
    ReviewResult,
    RunningGateMode,
    Usage,
)
from physgate.orchestrator.record import PlanEntry
from physgate.orchestrator.run_config import ModelStrings, RunBounds, RunConfig

GITENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    "HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=GITENV, capture_output=True, text=True, check=True
    ).stdout


def target_repo(root: Path) -> Path:
    """A target repository with one commit: a README and two module directories."""
    repo = root / "target"
    (repo / "modules" / "power").mkdir(parents=True)
    (repo / "modules" / "control").mkdir(parents=True)
    (repo / "README.md").write_text("target\n")
    (repo / "modules" / "power" / "base.py").write_text("x = 1\n")
    (repo / "modules" / "control" / "base.py").write_text("y = 1\n")
    sh(repo, "init", "-q", "-b", "master")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "initial")
    return repo


def run_layout(root: Path) -> RunGit:
    repo = target_repo(root)
    run = RunGit(repo=repo, run_dir=root / "run", run_id="run-1")
    run.open_run_branch(head_of(repo, "master"))
    return run


@dataclass
class GitDispatcher:
    """A session stand-in that writes into the real worktree and lets the orchestrator commit."""

    run: RunGit
    outside: set[int] = field(default_factory=set)
    repair: set[int] = field(default_factory=set)
    #: Per call: node proposals to write, by node id.
    proposals: dict[int, dict[str, dict[str, Any]]] = field(default_factory=dict)
    #: Per call: something done while the session runs, before the orchestrator commits.
    during: dict[int, Callable[[Path], None]] = field(default_factory=dict)
    #: Per call: something done to the worktree after the orchestrator committed.
    after_commit: dict[int, Callable[[Path], None]] = field(default_factory=dict)
    halted: set[int] = field(default_factory=set)
    requests: list[SessionRequest] = field(default_factory=list)

    def __call__(self, request: SessionRequest) -> SessionReport:
        self.requests.append(request)
        call = len(self.requests)
        worktree = self.run.open_subtask(request.subtask_id)
        seen = sorted(p.name for p in (worktree / request.module_dir).iterdir())
        target = worktree / request.module_dir / f"attempt{request.attempt}.py"
        target.write_text(f"# attempt {request.attempt}; saw {','.join(seen)}\n")
        if call in self.outside:
            (worktree / "README.md").write_text("changed outside the module\n")
        if call in self.repair:
            (worktree / "README.md").write_text("target\n")
        for node_id, payload in self.proposals.get(call, {}).items():
            path = worktree / ".physgate" / "proposals" / f"{node_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
        if call in self.during:
            self.during[call](worktree)
        sid = f"sess-{call}"
        commit = commit_attempt(worktree, request.subtask_id, request.attempt, sid)
        if call in self.after_commit:
            self.after_commit[call](worktree)
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=commit,
            trajectory=f"sessions/{sid}/stdout.jsonl",
            worktree=str(worktree),
            reading_verified=True,
            node_files_halted=call in self.halted,
            usage=(
                MessageUsage(
                    message_id=f"m{call}",
                    usage=Usage(
                        input_tokens=5,
                        output_tokens=1,
                        cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,
                    ),
                ),
            ),
        )


class DispatchPort:
    """Adapts ``GitDispatcher`` to the loop's ``Dispatcher`` Protocol."""

    def __init__(self, inner: GitDispatcher) -> None:
        self.inner = inner

    def environment(self) -> None:
        return None

    def stop_leftovers(self) -> list[tuple[str, int, int]]:
        return []

    def run(self, request: SessionRequest) -> SessionReport:
        return self.inner(request)


@dataclass
class ScopeChecker:
    """The write-scope half of the change check, over the real repository."""

    run: RunGit
    module_dirs: dict[str, str]

    def check(self, subtask_id: str, attempt_commit: str, role: str) -> ChangeCheck:
        base = sh(self.run.repo, "merge-base", self.run.run_branch, attempt_commit).strip()
        found = write_scope_violations(
            self.run.repo, base, attempt_commit, self.module_dirs[subtask_id]
        )
        if found:
            reason = "the attempt changed paths outside its module: " + "; ".join(found)
            return ChangeCheck(refused_by="write_scope", reason=reason, graph_root="graph")
        return ChangeCheck(refused_by=None, reason=None, graph_root="graph")


@dataclass
class Gate:
    verdicts: list[str] = field(default_factory=list)
    calls: int = 0

    def check(self, artefact: Artefact, *, mode: RunningGateMode) -> GateResult:
        self.calls += 1
        verdict = self.verdicts[self.calls - 1] if self.calls <= len(self.verdicts) else "pass"
        return GateResult(
            verdict=verdict,  # type: ignore[arg-type]
            mode=mode,
            finding="checked" if verdict == "pass" else "the stall current is too high",
            failing_check=None if verdict == "pass" else "bounds",
            numeric_output=None if verdict == "pass" else NumericOutput(value=3.4, unit="A"),
            quantities=(),
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
            session_id=f"rev-{self.calls}",
            usage=(),
        )


class EmptyGraph:
    """A graph port with an empty journal and no proposals."""

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
        return ()

    def reopen(self) -> tuple[int, tuple[str, ...]]:
        return 0, ()


def config(run_id: str = "run-1") -> RunConfig:
    return RunConfig(
        run_id=run_id,
        seed=1,
        brief_sha256="a" * 64,
        gate_mode="on",
        models=ModelStrings(
            decomposition="claude-sonnet-5",
            roles={"electrical": "claude-sonnet-5"},
            reviewers={"electrical": "claude-opus-5-5"},
        ),
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=120.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        token_ceiling=100_000,
        claude_version="2.1.272",
        target_head="b" * 40,
        endpoint="default",
        auth="api_key",
        managed_override_sha256=EMPTY_OVERRIDE_SHA256,
    )


def plan_entry(subtask_id: str, module_dir: str) -> PlanEntry:
    return PlanEntry(
        subtask_id=subtask_id,
        spec_path=f".physgate/specs/{subtask_id}.md",
        assigned_role="electrical",
        module_dir=module_dir,
    )
