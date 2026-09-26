"""The dispatcher, with the real 2.1.272 binary against the scripted endpoint.

A session runs in its subtask's worktree under settings generated from the
read-only installation, with the key through a helper and not in its
environment. Its reading is read back from the hook layer's own records; the
wall clock and the turn limit are infrastructure outcomes with their cause; a
binary that no longer reports the recorded version is refused before any spawn.
No real model is called.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, run_layout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from fake_messages_api import DUMMY_KEY, Script, serving, text, tool  # noqa: E402

from physgate.orchestrator.dispatch import ClaudeDispatcher  # noqa: E402
from physgate.orchestrator.exceptions import InvocationError  # noqa: E402
from physgate.orchestrator.git import commit_all, git  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.merge import RunGit  # noqa: E402
from physgate.orchestrator.ports import SessionRequest  # noqa: E402
from physgate.orchestrator.run_config import RunConfig  # noqa: E402
from physgate.state.store import Store  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

SPEC = ".physgate/specs/s1.md"
PROPOSAL: dict[str, Any] = {
    "id": "electrical.driver",
    "kind": "component",
    "domain": "electrical",
    "owner_role": "electrical",
    "quantities": {
        "current": {"value": 1.5, "unit": "A", "source": "datasheet", "written_by": "electrical"}
    },
    "requirements": [],
    "constrains": [],
    "model": None,
    "geometry_hash": "sha256:0",
    "updated": "2026-09-26T00:00:00Z",
}


@pytest.fixture(scope="module")
def install_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = Path(__file__).resolve().parents[3]
    return prepare_install(tmp_path_factory.mktemp("install") / "hooks", root)


def layout(root: Path) -> tuple[RunGit, Path]:
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text("Size the driver.\n")
    commit_all(run.integration, "specifications\n")
    store_root = run.run_dir / "store"
    store = Store(store_root)
    store.close()
    return run, store_root


def request(cfg: RunConfig) -> SessionRequest:
    return SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        spec_path=SPEC,
        module_dir="modules/power",
        model="claude-sonnet-4-5",
        repair_instruction=None,
        bounds=cfg.bounds,
    )


def dispatch(
    root: Path, install_bin: Path, steps: list[dict[str, Any]], cfg: RunConfig | None = None
) -> tuple[Any, Any, RunGit]:
    run, store_root = layout(root)
    cfg = cfg or config()
    with serving(Script(main=steps)) as (api, url):
        dispatcher = ClaudeDispatcher(
            config=cfg,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=url,
            api_key=DUMMY_KEY,
        )
        report = dispatcher.run(request(cfg))
        facts = dispatcher.environment()
    return api, (report, facts), run


def read_spec(run: RunGit) -> dict[str, Any]:
    return tool("Read", file_path=str(run.subtask_worktree("s1") / SPEC))


def test_a_session_reads_works_and_proposes_under_the_generated_settings(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command="env > modules/power/env.txt; echo 'x = 2' > modules/power/a.py"),
        tool(
            "Write",
            file_path=str(worktree / ".physgate" / "proposals" / "electrical.driver.json"),
            content=json.dumps(PROPOSAL),
        ),
        text("done"),
    ]
    api, (report, facts), run = dispatch(tmp_path, install_bin, steps)
    assert report.end.outcome == "completed", report
    assert report.reading_verified and not report.node_files_halted
    files = git(run.repo, "show", "--name-only", "--format=", str(report.attempt_commit)).split()
    assert "modules/power/a.py" in files
    assert ".physgate/proposals/electrical.driver.json" in files
    env_seen = (worktree / "modules" / "power" / "env.txt").read_text()
    assert "ANTHROPIC_API_KEY" not in env_seen and DUMMY_KEY not in env_seen
    # Through the helper the binary sends the key in both headers (measured: both
    # carry the helper's key), so the scripted endpoint's "other credential" flag,
    # which is any Authorization header, is set; the key itself is the dummy one,
    # and nothing else could supply one: no key in the environment, a scratch home.
    assert all(r.carried_dummy_key for r in api.requests)
    trajectory = Path(str(report.trajectory))
    assert trajectory.exists() and DUMMY_KEY not in trajectory.read_text()
    sdir = trajectory.parent
    assert not (sdir / "state" / "key").exists() and not (sdir / "state" / "key-helper.sh").exists()
    assert json.loads((sdir / "process.json").read_text())["session_id"] == report.session_id
    assert len({u.message_id for u in report.usage}) == len(report.usage) == len(api.requests)
    assert facts.files_with_write_bits == 0 and facts.files_with_second_links == 0
    assert facts.owner_is_session_user  # the same user could make it writable again


def test_the_first_tool_but_read_is_refused_until_the_reading_is_done(
    tmp_path: Path, install_bin: Path
) -> None:
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Bash", command="echo early > modules/power/early.py"),
        tool("Read", file_path=str(worktree / SPEC)),
        text("done"),
    ]
    api, (report, _), run = dispatch(tmp_path, install_bin, steps)
    assert report.reading_verified
    assert not (worktree / "modules" / "power" / "early.py").exists()
    assert "Required reading is not complete" in api.requests[1].last_user


def test_a_session_that_never_reads_is_reported_as_unread(
    tmp_path: Path, install_bin: Path
) -> None:
    _, (report, _), _ = dispatch(tmp_path, install_bin, [text("done without reading")])
    assert report.end.outcome == "completed" and not report.reading_verified


def test_the_wall_clock_stops_a_session_and_is_its_cause(tmp_path: Path, install_bin: Path) -> None:
    cfg = config()
    cfg = cfg.model_copy(
        update={"bounds": cfg.bounds.model_copy(update={"session_wall_clock_s": 4.0})}
    )
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [
        tool("Read", file_path=str(worktree / SPEC)),
        tool("Bash", command="sleep 30"),
        text("x"),
    ]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg)
    assert report.end.outcome == "infrastructure" and report.end.cause == "wall_clock"
    assert report.attempt_commit is None


def test_the_turn_limit_is_an_infrastructure_outcome(tmp_path: Path, install_bin: Path) -> None:
    cfg = config()
    cfg = cfg.model_copy(update={"bounds": cfg.bounds.model_copy(update={"session_max_turns": 1})})
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text("x")]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps, cfg)
    assert report.end.cause == "turn_limit"


def test_a_binary_that_is_not_the_recorded_version_is_refused_before_any_spawn(
    tmp_path: Path, install_bin: Path
) -> None:
    cfg = config().model_copy(update={"claude_version": "2.1.271"})
    with pytest.raises(InvocationError, match="not the version this run recorded"):
        dispatch(tmp_path, install_bin, [text("never")], cfg)
    assert not (tmp_path / "run" / "sessions").exists()


def test_a_key_that_reaches_the_stream_anyway_is_redacted_before_anything_reads_it(
    tmp_path: Path, install_bin: Path
) -> None:
    # The helper keeps the key out of the environment; this is the second layer,
    # for a key that reaches the stream some other way, here in the model's words.
    worktree = tmp_path / "run" / "worktrees" / "s1"
    steps = [tool("Read", file_path=str(worktree / SPEC)), text(f"the key is {DUMMY_KEY}")]
    _, (report, _), _ = dispatch(tmp_path, install_bin, steps)
    captured = Path(str(report.trajectory)).read_text()
    assert DUMMY_KEY not in captured and "[redacted: the API key]" in captured
