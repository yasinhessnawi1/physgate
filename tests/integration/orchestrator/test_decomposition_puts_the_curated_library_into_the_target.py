"""Through ``physgate decompose``: the real curated library reaches the target's run branch.

The real binary against the scripted endpoint, with the library this checkout
actually holds, not the suite's fixture one. A plan of a control module and a
firmware module is decomposed; the run branch's specification commit must then
hold exactly the always-loaded files of those two roles, byte for byte what
this checkout holds, and nothing else of the library. Then the refusals: a
target already holding other bytes where a curated file goes, and a run that
could plan a role with no curated content, refused before its one model call
is spent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from git_rig import PARAMS, config, target_repo
from scripted_endpoint import DUMMY_KEY, Script, serving, tool

from physgate.cli import main
from physgate.knowledge import loader
from physgate.orchestrator.git import commit_all
from physgate.orchestrator.run_config import ModelStrings, harness_root

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

HARNESS = harness_root()
ROLES = ("control", "firmware")
INTERFACE: dict[str, Any] = {
    "id": "iface.balance.v1",
    "kind": "interface",
    "domain": "cross",
    "owner_role": "control",
    "quantities": {},
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:" + "0" * 64,
    "updated": "2026-10-02T00:00:00Z",
}
PLAN = {
    "modules": [
        {"name": "control", "role": "control", "module_dir": "modules/control", "spec": "x"},
        {"name": "firmware", "role": "firmware", "module_dir": "modules/firmware", "spec": "y"},
    ],
    "interface_nodes": [INTERFACE],
}


@pytest.fixture(autouse=True)
def _the_real_library(monkeypatch: pytest.MonkeyPatch) -> None:
    """This file tests the library this checkout holds, not the suite's fixture one."""
    monkeypatch.setattr("physgate.orchestrator.cli._library_root", harness_root)


def _decompose(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    roles: tuple[str, ...] = ROLES,
    prepare: Any = None,  # noqa: ANN401 - a callable on the target repository
) -> tuple[int, Any, Path, Path]:
    repo = target_repo(root)
    if prepare is not None:
        prepare(repo)
    params = config().model_dump(include=PARAMS)
    params["models"] = ModelStrings(
        decomposition="claude-sonnet-5",
        roles=dict.fromkeys(roles, "claude-sonnet-5"),
        reviewers=dict.fromkeys(roles, "claude-opus-5-5"),
    ).model_dump()
    (root / "params.json").write_text(json.dumps(params))
    (root / "brief.md").write_text("Balance the robot.\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    run_dir = root / "run"
    with serving(Script(main=[tool("StructuredOutput", **PLAN)])) as (api, url):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        code = main(
            [
                "decompose",
                str(root / "brief.md"),
                "--seed",
                "7",
                "--run-id",
                "run-1",
                "--params",
                str(root / "params.json"),
                "--target",
                str(repo),
                "--run-dir",
                str(run_dir),
            ]
        )
    return code, api, repo, run_dir


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def test_the_spec_commit_holds_exactly_the_planned_roles_curated_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert HARNESS is not None
    code, _, repo, _ = _decompose(tmp_path, monkeypatch)
    assert code == 0, capsys.readouterr().err
    branch = "physgate/run-1/run"
    tree = set(_git(repo, "ls-tree", "-r", "--name-only", branch).split())
    knowledge = {p for p in tree if p.startswith("knowledge/")}
    expected = {p.as_posix() for role in ROLES for p in loader.always_loaded(role)}
    assert knowledge == expected
    for relative in expected:
        shown = subprocess.run(
            ["git", "show", f"{branch}:{relative}"], cwd=repo, capture_output=True, check=True
        ).stdout
        assert shown == (HARNESS / relative).read_bytes(), relative
    message = _git(repo, "log", "-1", "--format=%B", branch)
    assert "curated library" in message


def test_a_target_holding_other_bytes_where_a_curated_file_goes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def own_standards(repo: Path) -> None:
        path = repo / "knowledge" / "control" / "standards.md"
        path.parent.mkdir(parents=True)
        path.write_text("the target's own, never promoted\n")
        commit_all(repo, "a standards file of the target's own\n")

    code, _, repo, run_dir = _decompose(tmp_path, monkeypatch, prepare=own_standards)
    assert code != 0
    assert "already holds a different file" in capsys.readouterr().err
    assert not (run_dir / "events.jsonl").exists()
    # Refused before anything was written: no run record, and no run branch in the target.
    assert not run_dir.exists() or not any((run_dir / n).exists() for n in ("run.json", "store"))
    assert "physgate/" not in _git(repo, "branch", "--list", "physgate/*")
    assert (repo / "knowledge" / "control" / "standards.md").read_text() == (
        "the target's own, never promoted\n"
    )


def test_a_run_that_could_plan_a_role_without_curated_content_spends_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, api, _, run_dir = _decompose(tmp_path, monkeypatch, roles=("control", "mechanical"))
    assert code != 0
    printed = capsys.readouterr().err
    assert "no curated file" in printed and "mechanical" in printed
    assert api.requests == []
    assert not (run_dir / "decomposition").exists()
