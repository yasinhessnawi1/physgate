"""Against the real binary: a reviewer reads only its allowance, and no role reads a rubric.

The same method as the bypass suite: each attempt is a real Claude Code tool call
driven by the scripted endpoint, so no model can decline it, and it is judged by
what the session was told and by the hook layer's own log.

A stand-in harness checkout sits beside the worktree, holding a corpus and a
reviewer's rubric, each with a marker line. A reviewer whose allowance is its own
worktree is refused the corpus by absolute path, by a relative path, through a
symlink planted in its allowance, and through a hard link planted there; it reads
its own files. A role session in the same worktree is refused the rubric by the
Read tool and by the shell, and reads the role's own standards file as the
control.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

from physgate.hooks.reasons import OUTSIDE_REVIEW_REASON, REVIEW_MATERIAL_REASON

pytestmark = pytest.mark.integration

CORPUS_MARKER = "a line only the harness corpus holds"
RUBRIC_MARKER = "a line only the reviewer rubric holds"
STANDARDS_MARKER = "a line the role standards hold"
CORPUS = "harness/corpora/set/a01.json"
RUBRIC = "harness/knowledge/reviewers/control/rubric.md"
STANDARDS = "harness/knowledge/control/standards.md"


def _stand_in(root: Path) -> Path:
    for rel, body in (
        (CORPUS, CORPUS_MARKER),
        (RUBRIC, RUBRIC_MARKER),
        (STANDARDS, STANDARDS_MARKER),
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n")
    return root / "harness"


def _session(tmp_path: Path, profile: str, steps: list[dict[str, Any]], prepare: Any = None) -> Any:  # noqa: ANN401
    harness = _stand_in(tmp_path)
    fields: dict[str, Any] = {"profile": profile, "harness_root": str(harness)}
    if profile == "reviewer":
        fields |= {"role": None, "own_branch": None, "read_roots": (str(tmp_path / "worktree"),)}
    return run_session(tmp_path, Script(main=[*steps, text("end")]), prepare=prepare, **fields)


def _refused_by(run: Any, hook: str) -> int:  # noqa: ANN401
    return sum(1 for e in run.hook_log if e.get("decision") == "refuse" and e.get("hook") == hook)


def test_a_reviewer_is_refused_the_harness_corpus_by_every_spelling(tmp_path: Path) -> None:
    def plant(worktree: Path) -> None:
        (worktree / "alias").symlink_to(tmp_path / "harness" / "corpora")
        os.link(tmp_path / CORPUS, worktree / "twin.json")

    steps = [
        tool("Read", file_path=str(tmp_path / CORPUS)),
        tool("Read", file_path="../" + CORPUS),
        tool("Read", file_path=str(tmp_path / "worktree" / "alias" / "set" / "a01.json")),
        tool("Read", file_path=str(tmp_path / "worktree" / "twin.json")),
        tool("Read", file_path=str(tmp_path / "worktree" / "README.md")),
    ]
    run = _session(tmp_path, "reviewer", steps, prepare=plant)
    told = [run.told_after(n) for n in range(1, len(steps) + 1)]
    assert all(CORPUS_MARKER not in t for t in told), "the reviewer was shown the corpus"
    assert all(OUTSIDE_REVIEW_REASON in t for t in told[:3]), told[:3]
    assert "more than one name" in told[3], told[3]
    assert "a worktree" in told[4], "the reviewer could not read its own allowance"
    assert _refused_by(run, "paths") == 4


def test_a_role_session_is_refused_its_reviewer_s_rubric(tmp_path: Path) -> None:
    steps = [
        tool("Read", file_path=str(tmp_path / RUBRIC)),
        tool("Bash", command="cat " + str(tmp_path / RUBRIC), description="attempt"),
        tool("Read", file_path=str(tmp_path / STANDARDS)),
    ]
    run = _session(tmp_path, "role", steps)
    told = [run.told_after(n) for n in range(1, len(steps) + 1)]
    assert all(RUBRIC_MARKER not in t for t in told), "the role session was shown the rubric"
    assert REVIEW_MATERIAL_REASON in told[0] and REVIEW_MATERIAL_REASON in told[1], told[:2]
    assert STANDARDS_MARKER in told[2], "the control read was refused too"
    assert _refused_by(run, "paths") == 1 and _refused_by(run, "shell_paths") == 1
