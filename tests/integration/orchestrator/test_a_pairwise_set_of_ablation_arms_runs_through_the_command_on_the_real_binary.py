"""A pairwise set of ablation arms, each run through the ``physgate`` command on the real binary.

The scripted matrix (the unit suite's) runs every combination of the switches on stand-in
sessions. Here the switches whose value changes what a real session is given, or whether one is
spawned, are run on the real binary against the scripted endpoint, no model called: the gate
(whether an attempt is refused and repaired in a second session), the role reviewers (a reviewer
session with the paired rubric or its generalist, or none), the skill library (whether the role
session's worktree and reading hold the skill file) and hook enforcement (which hooks its
settings wire). Every pair of their values is in at least one row; each row is an ablation run,
the only kind that admits every value, reviewing its plan under ``observe``.

Each row is ``physgate decompose`` then ``physgate run``, with the command's own requirements, an
OS layer measured where the run is, and the reviewer factory the command registers. Two parts
are stand-ins, as in the other rows that drive the command: the physics gate (it refuses each
subtask's first attempt) and the plan's reviewer (it passes the plan), since neither is a session
of the role's work. The harness is measured as its own commit, clean, at both commands alike, as
the review-arm rows do (the pinned binary's rig leaves files in the checkout on one pin).

Where the OS layer cannot run, a measured run is refused at its configuration, so the rows skip,
or fail where the job is meant to have the layer.
"""

from __future__ import annotations

import itertools
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from gate_run import BRIEF, INTERFACE
from git_rig import Gate, run_params, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool
from test_a_run_is_reviewed_by_the_claude_reviewer_through_the_command import (
    _config,
    _library,
    _reading,
    _verdict,
    install,
)

from physgate.cli import main
from physgate.hooks.settings import DISCIPLINE_HOOKS
from physgate.knowledge import loader
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator import cli
from physgate.orchestrator.cli import Registrations
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.events import ReviewRan, read_events
from physgate.orchestrator.invocation import claude_binary, session_search_path
from physgate.orchestrator.protocols import MessageUsage, ReviewResult, Usage
from physgate.orchestrator.run_config import HarnessState, harness_state, load_run_config
from physgate.oslayer.probe import Present, judge_here
from physgate.reviewers.claude import claude_reviewers
from physgate.reviewers.packet import WORKTREE_NAME
from physgate.reviewers.rubric import NOT_IN_REVIEW, generalist_of, load_rubric

__all__ = ["install"]

#: Whether this machine has a Claude Code binary to run the rows on.
NO_BINARY = not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude"))
#: Set in a job that is meant to run these rows: a missing binary or OS layer then fails them.
REQUIRED = bool(os.environ.get("PHYSGATE_REQUIRE_OS_LAYER"))

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(NO_BINARY and not REQUIRED, reason="no Claude Code binary on this machine"),
]

ROLE = "electrical"
#: The switches whose value reaches a real session, with every value each takes.
FACTORS: dict[str, tuple[str, ...]] = {
    "gate_mode": ("on", "observe", "off"),
    "reviewers": ("paired", "generalist", "off"),
    "skills": ("on", "off"),
    "hooks": ("on", "off"),
}
KEPT_HOOKS = {"sentinel", "tools", "paths", "shell_paths", "git_ops", "os_abort", "survivors"}
SKILL = f"knowledge/{ROLE}/skill.md"


def _pairs(row: dict[str, str]) -> set[tuple[str, str, str, str]]:
    return {(a, row[a], b, row[b]) for a, b in itertools.combinations(FACTORS, 2)}


def pairwise() -> list[dict[str, str]]:
    """Rows that hold every pair of the factors' values, chosen greedily in a fixed order."""
    every = [
        dict(zip(FACTORS, values, strict=True)) for values in itertools.product(*FACTORS.values())
    ]
    left = set().union(*map(_pairs, every))
    rows: list[dict[str, str]] = []
    while left:
        best = max(every, key=lambda row: len(_pairs(row) & left))
        rows.append(best)
        left -= _pairs(best)
    return rows


ROWS = pairwise()


def test_the_rows_hold_every_pair_of_values() -> None:
    every = {
        (a, x, b, y)
        for a, b in itertools.combinations(FACTORS, 2)
        for x in FACTORS[a]
        for y in FACTORS[b]
    }
    assert set().union(*map(_pairs, ROWS)) == every
    assert len(ROWS) == 9


@pytest.fixture
def layer() -> None:
    """Skip unless the OS layer runs here; fail instead where the job is meant to have it."""
    if NO_BINARY:
        # Only reached where the rows are required: elsewhere the module is skipped.
        pytest.fail("this job is meant to run these rows, and it has no Claude Code binary")
    # As the command judges it for a new run.
    found = judge_here(
        claude_version=binary_version(), search_path=session_search_path(claude_binary())
    )
    if isinstance(found, Present):
        return
    if REQUIRED:
        pytest.fail("this job is meant to run the OS layer, and the layer cannot run here")
    pytest.skip("the OS layer cannot run here, and a measured run is refused without it")


class PlanReviewer:
    """The plan's reviewer: it passes the plan."""

    model = "claude-sonnet-5"

    def review_plan(self, under: Any) -> ReviewResult:  # noqa: ANN401
        usage = Usage(
            input_tokens=5,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return ReviewResult(
            verdict="pass",
            finding="the plan allocates every criterion",
            reviewer_model=self.model,
            session_id="design-review-session-1",
            usage=(MessageUsage(message_id="r1", usage=usage),),
        )

    def factory(self, setup: Any, config: Any) -> PlanReviewer:  # noqa: ANN401
        return self


def _role_steps(skills: str) -> list[dict[str, Any]]:
    """A role session: read what it must, write its proposal, stop."""
    given = loader.session_reading(
        ROLE, Path(".physgate/specs/x.md"), skills="off" if skills == "off" else "on"
    )
    node: dict[str, Any] = {
        "id": f"{ROLE}.supply",
        "kind": "component",
        "domain": ROLE,
        "owner_role": ROLE,
        "quantities": {
            "current_draw": {"value": 0.5, "unit": "A", "source": "datasheet", "written_by": ROLE}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-11-20T00:00:00Z",
    }
    return [
        *(tool("Read", file_path=f"{{cwd}}/{path.as_posix()}") for path in given.always_loaded),
        tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
        tool("Read", file_path=f"{{cwd}}/.physgate/interfaces/{INTERFACE['id']}.json"),
        tool(
            "Write",
            file_path=f"{{cwd}}/.physgate/proposals/{node['id']}.json",
            content=json.dumps(node),
        ),
        text("done"),
    ]


def _drive(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    row: dict[str, str],
) -> tuple[int, Path, Path, list[str]]:
    library, _ = _library(tmp_path / "lib")
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", lambda: library)
    measured = harness_state(cli._harness_root())
    clean = HarnessState(commit=measured.commit, clean=True, uncommitted_sha256=None)
    monkeypatch.setattr(cli, "harness_state", lambda _root: clean)
    repo = target_repo(tmp_path)
    run_dir = tmp_path / "run"
    models = _config().models
    arm = _config().model_copy(
        update={
            **row,
            "ablation": True,
            "design_review": "observe",
            "os_layer_absent": "refuse",
            "models": models.model_copy(
                update={"reviewers": {**models.reviewers, "design": "claude-sonnet-5"}}
            ),
        }
    )
    (tmp_path / "params.json").write_text(json.dumps(run_params(arm)))
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    plan = {
        "modules": [
            {"name": "power", "role": ROLE, "module_dir": "modules/power", "spec": "Size."}
        ],
        "interface_nodes": [INTERFACE],
    }
    role_steps = _role_steps(row["skills"])
    reviewed: list[str] = []

    def step(_thread: str, cwd: str, done: int) -> dict[str, Any]:
        if not cwd.endswith(f"/read/{WORKTREE_NAME}"):
            return role_steps[done] if done < len(role_steps) else text("done")
        reviewed.append(cwd)
        verdict = _verdict("accept")
        if NOT_IN_REVIEW in (Path(cwd).parent / "rubric.md").read_text():
            verdict["items"] = {
                k: v for k, v in verdict["items"].items() if k.startswith(("AC-", "RH-"))
            }
        steps = [tool("Read", file_path=p) for p in _reading(cwd)]
        steps.append(tool("StructuredOutput", review=verdict))
        return steps[done] if done < len(steps) else text("done")

    places = ["--install", str(install), "--review-root", str(tmp_path / "rs")]
    with serving(Script(main=[tool("StructuredOutput", **plan)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        args = ["--seed", "7", "--run-id", "run-1", "--params", str(tmp_path / "params.json")]
        where = ["--target", str(repo), "--run-dir", str(run_dir)]
        decompose = main(
            ["decompose", str(tmp_path / "brief.md"), *args, *where, *places],
            Registrations(plan_reviewer_factory=PlanReviewer().factory),
        )
        assert decompose == 0, capsys.readouterr().err
        capsys.readouterr()
        api.script = Script(main=[])
        api.on_request = step
        registrations = Registrations(
            gate=Gate(verdicts=["fail"]), reviewer_factory=claude_reviewers
        )
        code = main(["run", *where, *places], registrations)
    return code, run_dir, library, reviewed


def _wired(settings: Path) -> set[str]:
    names: set[str] = set()
    for groups in json.loads(settings.read_text())["hooks"].values():
        argv = shlex.split(groups[0]["hooks"][0]["command"])
        names |= set(argv[argv.index("--hooks") + 1].split(","))
    return names


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("row", ROWS, ids=["-".join(row.values()) for row in ROWS])
def test_the_arm_runs_to_completion_and_each_switch_does_what_it_says(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    row: dict[str, str],
) -> None:
    code, run_dir, library, reviewed = _drive(tmp_path, install, monkeypatch, capsys, row)
    out = capsys.readouterr()
    assert code == 0, out.err
    assert json.loads(out.out)["step"] == "done", out.out
    lines = [json.loads(raw) for raw in (run_dir / "events.jsonl").read_text().splitlines()]
    kinds = [line["kind"] for line in lines]
    assert not {"halted", "incident", "escalated", "subtask_rejected"} & set(kinds), kinds
    (merged,) = [line for line in lines if line["kind"] == "merged"]
    config = load_run_config(run_dir / "run.json")
    for name, value in row.items():
        assert getattr(config, name) == value, name
    assert config.ablation

    # The gate: refused and repaired under on, recorded and let through under observe, skipped.
    gated = [line for line in lines if line["kind"] in ("gate_ran", "gate_skipped")]
    rejected = [line["attempt"] for line in lines if line["kind"] == "attempt_rejected"]
    if row["gate_mode"] == "on":
        assert [g["result"]["verdict"] for g in gated] == ["fail", "pass"]
        assert (merged["attempt"], rejected) == (2, [1])
    elif row["gate_mode"] == "observe":
        observed = [(g["result"]["verdict"], g["result"]["mode"]) for g in gated]
        assert observed == [("fail", "observe")]
        assert (merged["attempt"], rejected) == (1, [])
    else:
        assert [g["kind"] for g in gated] == ["gate_skipped"]
        assert (merged["attempt"], rejected) == (1, [])

    # The role reviewers: no reviewer session under off, else one with the arm's rubric.
    ran = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, ReviewRan)]
    skipped = [line for line in lines if line["kind"] == "review_skipped"]
    if row["reviewers"] == "off":
        assert (ran, reviewed) == ([], [])
        assert [s["attempt"] for s in skipped] == [merged["attempt"]]
    else:
        paired = load_rubric(library / KNOWLEDGE_ROOT, ROLE)
        rubric = paired if row["reviewers"] == "paired" else generalist_of(paired)
        (review,) = ran
        found = (review.result.rubric_kind, review.result.rubric_sha256)
        assert found == (row["reviewers"], rubric.sha256)
        assert skipped == [] and reviewed

    # Every role session's settings wire the run's hooks: the discipline's three only under on.
    sessions = [line["session_id"] for line in lines if line["kind"] == "session_ended"]
    assert len(sessions) == merged["attempt"], sessions
    for sid in sessions:
        wired = _wired(run_dir / "sessions" / sid / "session" / "settings.json")
        assert wired >= KEPT_HOOKS, sorted(wired)
        assert bool(set(DISCIPLINE_HOOKS) & wired) == (row["hooks"] == "on"), sorted(wired)

    # The run branch holds the role's skill file under on, and nothing of it under off.
    files = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", merged["merge_commit"]],
        cwd=tmp_path / "target",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert (SKILL in files) == (row["skills"] == "on"), files
