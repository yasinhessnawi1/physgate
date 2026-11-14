"""Through the real binary: under ``hooks: off`` the discipline is gone and every protection holds.

A role session of an ablation run's ``hooks: off`` arm is not held to the harness's design
discipline: no reading is required before its first call, a proposal is not checked before it is
written, and it may write its worktree's own gate source, hook source and knowledge tree. Every
other root still refuses a write, through the same hook as in a full harness session, and nothing
of the target appears. Each case asserts on the hook layer's decision log and on the files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fake_messages_api import Script, text, tool
from hook_session import SessionRun, run_session

from physgate.hooks import graph, paths
from physgate.hooks.settings import InstallRequest

pytestmark = pytest.mark.integration

DOC = "A line of required reading.\n" * 12

#: Every root the arm keeps that a test can aim a write at, each as a new file beneath it.
#: ``@W`` is the worktree, ``@O`` the directory outside it. The hook installation is left out
#: here (a write there that landed would change the code under test); the enumeration of the
#: configuration holds it, as every other root.
KEPT = {
    "the series writer": "@W/.physgate/lib/writer.py",
    "the series outbox": "@W/.physgate/series/record.json",
    "the secrets": "@W/.env",
    "the worktree's Claude settings": "@W/.claude/planted.json",
    "the worktree's answer keys": "@W/corpora/answers.json",
    "a criteria file": "@W/experiments/R-NEW-01/CRITERIA.md",
    "the session's settings": "@O/session/planted.json",
    "the hooks' state": "@O/state/planted.json",
    "the session's Claude configuration": "@O/claude-config/planted.json",
    "git's user configuration": "@O/home/.gitconfig",
    "the user's Claude state": "@O/home/.claude.json",
    "the graph store": "@O/store/journal.jsonl",
    "the held-out tier": "@O/heldout/scenario_02.json",
    "every session's directory": "@O/sessions/another/stream.jsonl",
    "a run record": "@O/run/decomposition/plan.json",
    "a held run record": "@O/run/events.jsonl",
    "the withheld run configuration": "@O/run/run.json",
    "the harness checkout": "@O/harness/src/physgate/gate/planted.py",
}

#: The roots the arm drops: the worktree's own copies of what the harness runs from elsewhere.
DROPPED = {
    "the worktree's gate source": "@W/src/physgate/gate/planted.py",
    "the worktree's hook source": "@W/src/physgate/hooks/planted.py",
    "the worktree's knowledge tree": "@W/knowledge/electrical/standards.md",
}


def _placed(path: str, root: Path) -> str:
    return path.replace("@W", str(root / "worktree")).replace("@O", str(root / "outside"))


def _prepare_harness(root: Path) -> None:
    (root / "outside" / "harness" / "src").mkdir(parents=True, exist_ok=True)


def _session(root: Path, steps: list[dict[str, Any]], hooks: str, **fields: Any) -> SessionRun:  # noqa: ANN401
    _prepare_harness(root)
    outside = root / "outside"
    return run_session(
        root,
        Script(main=[*steps, text("end")]),
        hooks=hooks,
        held_out=(str(outside / "heldout"),),
        extra_protected=(str(outside / "run" / "decomposition"),),
        extra_protected_record=(str(outside / "run" / "events.jsonl"),),
        withheld=(str(outside / "run" / "run.json"),),
        harness_root=str(outside / "harness"),
        **fields,
    )


def _refusals(run: SessionRun) -> list[tuple[str, str]]:
    return [
        (e["hook"], e["reason"])
        for e in run.hook_log
        if e.get("decision") == "refuse" and e.get("tool") is not None
    ]


def _wired(run: SessionRun) -> set[str]:
    names: set[str] = set()
    for groups in run.settings["hooks"].values():
        command = groups[0]["hooks"][0]["command"].split()
        names |= set(command[command.index("--hooks") + 1].split(","))
    return names


def _the_arm_exists() -> None:
    assert "hooks" in InstallRequest.model_fields, "no role session can be installed hooks off"


def test_every_kept_root_refuses_a_write_through_the_same_hook(tmp_path: Path) -> None:
    _the_arm_exists()
    writes = [tool("Write", file_path=_placed(p, tmp_path), content="x\n") for p in KEPT.values()]
    run = _session(tmp_path, writes, "off")
    assert not {"graph", "reading", "token_ceiling"} & _wired(run)
    landed = [what for what, p in KEPT.items() if Path(_placed(p, tmp_path)).exists()]
    assert landed == []
    refusals = _refusals(run)
    assert [hook for hook, _ in refusals] == ["paths"] * len(KEPT)
    assert any(paths.FROZEN_CRITERIA in reason for _, reason in refusals)


def test_the_dropped_roots_take_a_write_that_a_full_session_refuses(tmp_path: Path) -> None:
    _the_arm_exists()
    for hooks, refused in (("on", len(DROPPED)), ("off", 0)):
        root = tmp_path / hooks
        writes = [
            tool("Write", file_path=_placed(p, root), content="x\n") for p in DROPPED.values()
        ]
        run = _session(root, writes, hooks)
        assert [hook for hook, _ in _refusals(run)] == ["paths"] * refused, hooks
        landed = {what for what, p in DROPPED.items() if Path(_placed(p, root)).exists()}
        assert landed == (set() if refused else set(DROPPED)), hooks


def test_no_reading_is_required_before_the_first_call(tmp_path: Path) -> None:
    _the_arm_exists()
    for hooks, ran in (("on", False), ("off", True)):
        root = tmp_path / hooks
        doc = root / "outside" / "docs" / "standards.md"
        run = _session(
            root,
            [tool("Bash", command="echo ran > marker.txt", description="x")],
            hooks,
            outside_files={"docs/standards.md": DOC},
            required_reading=(str(doc),),
            always_loaded=(str(doc),),
        )
        assert (run.worktree / "marker.txt").exists() is ran, hooks
        assert [hook for hook, _ in _refusals(run)] == ([] if ran else ["reading"]), hooks


def test_a_proposal_is_not_checked_before_it_is_written(tmp_path: Path) -> None:
    _the_arm_exists()
    bare = {
        "id": "electrical.driver",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {"stall_current": 2.4},
    }
    for hooks, lands in (("on", False), ("off", True)):
        root = tmp_path / hooks
        target = root / "worktree" / graph.PROPOSALS_DIR / "electrical.driver.json"
        run = _session(
            root, [tool("Write", file_path=str(target), content=json.dumps(bare))], hooks
        )
        assert target.exists() is lands, hooks
        assert [hook for hook, _ in _refusals(run)] == ([] if lands else ["graph"]), hooks
