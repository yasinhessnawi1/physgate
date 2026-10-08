"""No implementation that passes work ships in ``src/``.

A gate that passes everything "for now" would turn every downstream test green
while enforcing nothing. The loop calls a gate and a reviewer through Protocols.
This scans every class in the source tree for a method with the Protocols'
shape, ``check`` or ``review`` taking an artefact, and allows exactly two: the
physics gate's runner and the Claude reviewer. Each is held by what it does
rather than by where it is: the gate, with nothing to check, gives no verdict at
all, so it cannot pass work it did not check; the reviewer, without the attempt's
sealed trajectory, gives no verdict and spawns no session, so it cannot pass work
it did not read.
"""

from __future__ import annotations

import ast
import stat
from pathlib import Path

import pytest
from orch_helpers import make_config

import physgate
from physgate.gate.exceptions import NothingCheckedError
from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.protocols import Artefact
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric

SRC = Path(physgate.__file__).parent
PROTOCOLS = SRC / "orchestrator" / "protocols.py"


#: The implementations allowed: the physics gate's runner and the Claude reviewer.
PHYSICS_GATE = "gate/runner.py:PhysicsGate.check"
CLAUDE_REVIEWER = "reviewers/claude.py:ClaudeReviewer.review"


def _where(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def implementations(root: Path) -> list[str]:
    """Classes under ``root`` that define the gate's or the reviewer's method."""
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path == PROTOCOLS:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if bases & {"Gate", "Reviewer"}:
                found.append(f"{_where(path, root)}:{node.name} subclasses a Protocol")
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name in {"check", "review"}:
                    names = {a.arg for a in item.args.args + item.args.kwonlyargs}
                    if "artefact" in names:
                        found.append(f"{_where(path, root)}:{node.name}.{item.name}")
    return found


def test_the_source_tree_is_scanned() -> None:
    assert PROTOCOLS.exists()
    assert len(list(SRC.rglob("*.py"))) > 20


def test_the_only_implementations_in_src_are_the_physics_gate_and_the_claude_reviewer() -> None:
    assert implementations(SRC) == [PHYSICS_GATE, CLAUDE_REVIEWER]


def test_the_physics_gate_gives_no_verdict_when_it_has_nothing_to_check(tmp_path: Path) -> None:
    empty = GraphView.read(tmp_path / "graph", base_revision=0)
    with pytest.raises(NothingCheckedError):
        PhysicsGate(()).run(empty, ["subtask", "module", "system"], "on")


def test_the_claude_reviewer_gives_no_verdict_on_a_trajectory_it_cannot_read_whole(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "calls.txt"
    binary = tmp_path / "claude"
    binary.write_text(f'#!/bin/sh\necho "$@" >> {calls}\necho "2.1.272 (Claude Code)"\n')
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    reviewer = ClaudeReviewer(
        role="electrical",
        rubric=Rubric(role="electrical", text="r", sha256="0" * 64),
        setup=ReviewerSetup.of_run(
            make_config(),
            review_root=tmp_path / "rs",
            repo=tmp_path,
            install_bin=tmp_path / "physgate",
            binary=str(binary),
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            library=tmp_path,
        ),
    )
    unsealed = Artefact(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        attempt_commit="a" * 40,
        worktree=str(tmp_path),
        graph_root=str(tmp_path),
        trajectory=str(tmp_path / "stdout.jsonl"),
        scopes=("subtask",),
        base_revision=0,
        base_commit="b" * 40,
    )
    with pytest.raises(ReviewUnavailableError) as raised:
        reviewer.review(unsealed)
    assert raised.value.cause == "unprepared"
    assert calls.read_text() == "--version\n"


def test_the_scan_sees_an_implementation_when_one_is_there(tmp_path: Path) -> None:
    (tmp_path / "passing.py").write_text(
        "class PassEverything:\n    def check(self, artefact, *, mode):\n        return None\n"
        "class Nodding(Reviewer):\n    pass\n"
    )
    assert implementations(tmp_path) == [
        "passing.py:PassEverything.check",
        "passing.py:Nodding subclasses a Protocol",
    ]
