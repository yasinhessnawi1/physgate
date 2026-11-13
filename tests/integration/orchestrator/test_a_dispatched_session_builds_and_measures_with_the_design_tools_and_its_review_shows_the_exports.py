"""Through the dispatcher: a role session builds and measures with the CAD tools, and is reviewed.

The path a mechanical role takes in a run, from end to end, with the real binary against the
scripted endpoint inside the OS layer with no network: the run names a provisioned tool
environment; the session finds its interpreter as ``python3`` and its first-use places in its
own temporary directory, all from the environment's own file, with nothing set by hand. It
writes two scripts into its module and runs them: one builds the chassis fixture's parts and
writes their results and exports through the environment's helper; the other reads the
published Balboa model from the environment's ``reference/`` folder and writes what it measured.
The published model cannot be written. The attempt the dispatcher commits holds the scripts,
their results and the exports; the commit-time rule admits the six exports, and the diff a
reviewer reads names each on one line with its size, digest and free-text count, never its
bytes. The environment is as it was.

``PHYSGATE_TOOL_ENVIRONMENT`` names a provisioned environment (``toolenv/provision.py``).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from design_fixtures import CHASSIS, GEOMETRY_HASH
from git_rig import config, run_layout
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

from physgate.knowledge import loader
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.git import commit_all, git
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.merge import RunGit, admitted_exports
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunBounds, RunConfig, write_run_config
from physgate.orchestrator.tool_environment import measure_named
from physgate.oslayer.probe import Present, judge_here
from physgate.reviewers import packet
from physgate.state.store import Store
from physgate.toolenv.manifest import scan

try:
    import design_reference
except ImportError:  # the red rows run before the script exists
    design_reference = None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

PROVISIONED = os.environ.get("PHYSGATE_TOOL_ENVIRONMENT", "")
ROLE = "mechanical"
MODULE = "modules/chassis"
SPEC = ".physgate/specs/s1.md"
PARTS = ("plate", "motor_mount", "battery_holder")
ALWAYS_LOADED = loader.always_loaded(ROLE)


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def _layout(root: Path) -> tuple[RunGit, Path]:
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text("Build the chassis and measure the published robot.\n")
    for relative in ALWAYS_LOADED:
        path = run.integration / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative.name}\n\nFixture content for the dispatch tests.\n")
    commit_all(run.integration, "specifications\n")
    store_root = run.run_dir / "store"
    Store(store_root).close()
    return run, store_root


def _dispatch(
    root: Path, install_bin: Path, steps: list[dict[str, Any]], cfg: RunConfig
) -> tuple[Any, Any, RunGit]:
    run, store_root = _layout(root)
    write_run_config(run.run_dir / "run.json", cfg)
    with serving(Script(main=steps)) as (api, url):
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            credential=Credential("api_key", DUMMY_KEY),
            review_root=Path("/nonexistent/review-scratch"),
        )
        report = dispatcher.run(
            SessionRequest(
                subtask_id="s1",
                attempt=1,
                assigned_role=ROLE,
                spec_path=SPEC,
                module_dir=MODULE,
                model="claude-sonnet-5",
                repair_instruction=None,
                bounds=cfg.bounds,
            )
        )
    return api, report, run


def _built_append(path: Path) -> dict[str, Any]:
    """A command that appends to ``path`` by a name it builds as it runs."""
    whole = str(path)
    half = len(whole) // 2
    return tool(
        "Bash",
        command=(
            f"p=$(printf %s '{whole[:half]}')$(printf %s '{whole[half:]}'); "
            '(echo changed >> "$p") 2>/dev/null && echo REF-WRITTEN || echo REF-DENIED'
        ),
    )


def test_a_session_builds_measures_and_exports_and_its_review_names_each_export_on_one_line(
    tmp_path: Path, install_bin: Path
) -> None:
    assert design_reference is not None, "no recorded script measures the published model"
    if not PROVISIONED:
        pytest.skip("no provisioned tool environment named")
    path = f"{Path(claude_binary()).parent}:/usr/bin:/bin:/usr/sbin:/sbin"
    layer = judge_here(claude_version=config().claude_version, search_path=path)
    if not isinstance(layer, Present):
        pytest.skip("the OS layer cannot run here")
    root = Path(PROVISIONED)
    reference = root / "reference" / design_reference.BALBOA_FILE
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    named = {"interpreter": str(root / "venv" / "bin" / "python3"), "roots": [str(root)]}
    cfg = config().model_copy(
        update={
            "tool_environment": measure_named(named, forbidden={}),
            "network": "none",
            "network_enforced": True,
            "os_layer": layer,
            "bounds": RunBounds(
                binary_max_retries=0,
                session_wall_clock_s=1500.0,
                session_max_turns=30,
                infra_retry_delays_s=(),
            ),
        }
    )
    before = scan([root])
    worktree = tmp_path / "run" / "worktrees" / "s1"
    module = worktree / MODULE
    helpers = root / "helpers"
    steps = [
        *[tool("Read", file_path=str(worktree / relative)) for relative in ALWAYS_LOADED],
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Write", file_path=str(module / "chassis.py"), content=CHASSIS),
        tool("Write", file_path=str(module / "balboa.py"), content=design_reference.BALBOA),
        tool("Bash", command="echo CACHE=$XDG_CACHE_HOME; echo DATA=$XDG_DATA_HOME"),
        tool("Bash", command=f"cd {module} && python3 chassis.py {helpers} | cut -c1-120"),
        tool(
            "Bash",
            command=f"cd {module} && python3 balboa.py {helpers} | cut -c1-120",
            timeout=1200000,
        ),
        _built_append(reference),
        text("done"),
    ]
    api, report, run = _dispatch(tmp_path, install_bin, steps, cfg)
    assert report.end.outcome == "completed", report
    told = "\n".join(r.last_user for r in api.requests if r.thread == "main")
    lines = told.splitlines()
    # The first-use places are the session's own, from the environment's file alone.
    places = [line.split("=", 1)[1] for line in lines if line.startswith(("CACHE=", "DATA="))]
    assert len(places) == 2 and all(places), told[-2000:]
    for place in places:
        assert place.startswith(("/var/tmp/pgs/", "/private/var/tmp/pgs/")), place
    assert "REF-DENIED" in lines and "REF-WRITTEN" not in lines, told[-2000:]
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == digest
    # The attempt holds the scripts, their results and the exports, and nothing else.
    assert report.attempt_commit is not None
    commit = report.attempt_commit
    committed = git(run.repo, "ls-tree", "-r", "--name-only", commit).splitlines()
    mine = sorted(p for p in committed if p.startswith(f"{MODULE}/"))
    results = [f"{name}.result.json" for name in PARTS]
    results += [f"plate-motor_mount-{case}.result.json" for case in ("resting", "pushed-in")]
    results += ["plate-motor_mount-lifted.result.json", "mount-arm.result.json"]
    results += ["deck.result.json", design_reference.BALBOA_RESULT]
    exported = [f"exports/{name}.{kind}" for name in PARTS for kind in ("step", "stl")]
    expected = ["chassis.py", "balboa.py", *results, *exported]
    assert mine == sorted(f"{MODULE}/{name}" for name in expected), mine
    for name in PARTS:
        found = json.loads(git(run.repo, "show", f"{commit}:{MODULE}/{name}.result.json"))
        assert found["geometry_hash"] == GEOMETRY_HASH[name], name
    measured = json.loads(
        git(run.repo, "show", f"{commit}:{MODULE}/{design_reference.BALBOA_RESULT}")
    )
    assert measured["kind"] == "reference_measurement"
    assert measured["reference"]["sha256"] == digest
    assert measured["reference"]["file"] == f"reference/{design_reference.BALBOA_FILE}"
    # The commit-time rule admits each export, and the review names each on one line.
    base = git(run.repo, "rev-parse", f"{commit}^")
    admitted = admitted_exports(run.repo, base, commit, MODULE)
    assert sorted(a.path for a in admitted) == sorted(f"{MODULE}/{p}" for p in exported)
    diff = packet._diff(run.repo, base, commit, frozenset((a.path, a.sha256) for a in admitted))
    shown = diff.decode("utf-8", errors="replace").splitlines()
    assert shown.count(packet.EXPORTS_HEADER) == 1
    named = [line for line in shown if line.startswith("exported file ")]
    assert len(named) == len(exported), named
    for line in named:
        assert ": added, " in line and "sha256 " in line, line
        assert "free text 0 bytes" in line, line
    assert "ISO-10303-21" not in "\n".join(shown)
    assert not [line for line in shown if line.startswith("diff --git") and "/exports/" in line]
    assert scan([root]) == before
