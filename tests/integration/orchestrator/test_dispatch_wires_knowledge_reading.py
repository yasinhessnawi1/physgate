"""``dispatch.py``'s ``_install`` feeds ``loader.py``'s sets into a real session config.

No Claude Code binary needed: ``hooks install`` is a plain CLI that writes two
files and never checks the pinned binary version (that check is `.run()`'s
own, later). This checkout's own console script is used as ``install_bin`` —
the real code under test, not a copy — so this proves the wiring end to end
through the real installer, without the binary-version gate the rest of the
dispatch integration suite needs.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from git_rig import config, run_layout

from physgate.hooks.config import SessionConfig
from physgate.hooks.reading import outstanding
from physgate.hooks.token_ceiling import measure, session_start
from physgate.knowledge import loader
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.git import commit_all
from physgate.orchestrator.merge import RunGit
from physgate.orchestrator.ports import SessionRequest
from physgate.orchestrator.run_config import RunConfig
from physgate.state.store import Store

pytestmark = pytest.mark.integration

SPEC = ".physgate/specs/s1.md"
ROLE = "electrical"


def _dev_physgate_binary() -> Path:
    return Path(sys.executable).parent / "physgate"


def _layout(root: Path) -> tuple[RunGit, Path]:
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text("Size the driver.\n")
    for relative in loader.always_loaded(ROLE):
        path = run.integration / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative.name}\n\nFixture content for the wiring test.\n")
    commit_all(run.integration, "specifications and knowledge\n")
    store_root = run.run_dir / "store"
    store = Store(store_root)
    store.close()
    return run, store_root


def _request(cfg: RunConfig) -> SessionRequest:
    return SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role=ROLE,
        spec_path=SPEC,
        module_dir="modules/power",
        model="claude-sonnet-5",
        repair_instruction=None,
        bounds=cfg.bounds,
    )


@dataclass(frozen=True)
class _Input:
    """The one field the reading check reads from a hook's input: the session id."""

    session_id: str
    cwd: str = "/"
    hook_event_name: str = "PreToolUse"
    tool_name: str | None = "Bash"
    tool_input: dict[str, Any] | None = None
    tool_response: Any = None
    agent_id: str | None = None


def test_the_installed_session_config_carries_loaders_full_reading_set(tmp_path: Path) -> None:
    run, store_root = _layout(tmp_path)
    cfg = config()
    dispatcher = ClaudeDispatcher(
        config=cfg,
        run=run,
        store_root=store_root,
        install_bin=_dev_physgate_binary(),
        binary="unused-by-install",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy"),
    )
    request = _request(cfg)
    worktree = run.open_subtask(request.subtask_id)
    sdir = run.run_dir / "sessions" / "probe"
    installed = dispatcher._install(request, worktree, sdir)  # noqa: SLF001 - the thing under test

    written = SessionConfig.model_validate_json(Path(installed.config).read_text())
    expected_reading = {
        str(worktree / p)
        for p in loader.required_reading(request.assigned_role, Path(request.spec_path))
    }
    expected_always_loaded = {
        str(worktree / p) for p in loader.always_loaded(request.assigned_role)
    }

    assert set(written.required_reading) == expected_reading
    assert set(written.always_loaded) == expected_always_loaded
    assert expected_always_loaded < expected_reading  # the spec is required, never always-loaded
    assert measure(written).allow  # the fixture files are nowhere near the run's ceiling

    # The hook layer's own reading hook, unmodified: every one of loader's
    # files, and only those, is outstanding before any is read.
    hook_input = _Input(session_id="probe-session")
    assert set(outstanding(written, hook_input)) == expected_reading


def test_a_role_whose_always_loaded_set_is_over_the_ceiling_fails_a_session_start_naming_the_file(
    tmp_path: Path,
) -> None:
    """ARCH-023's other acceptance test: under the ceiling passes (above); over it fails, named."""
    run = run_layout(tmp_path)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text("Size the driver.\n")
    oversized = None
    for relative in loader.always_loaded(ROLE):
        path = run.integration / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative.name == "skill.md":
            path.write_text("x" * 5000)  # deliberately over the ceiling set below
            oversized = str(path).replace(str(run.integration), "")
        else:
            path.write_text(f"# {relative.name}\n\nFixture content.\n")
    commit_all(run.integration, "specifications and an oversized skill file\n")
    store_root = run.run_dir / "store"
    Store(store_root).close()

    cfg = config().model_copy(update={"token_ceiling": 1000})  # far below the 5000-byte skill file
    dispatcher = ClaudeDispatcher(
        config=cfg,
        run=run,
        store_root=store_root,
        install_bin=_dev_physgate_binary(),
        binary="unused-by-install",
        base_url=None,
        credential=Credential("api_key", "sk-ant-test-dummy"),
    )
    request = _request(cfg)
    worktree = run.open_subtask(request.subtask_id)
    sdir = run.run_dir / "sessions" / "probe-over-ceiling"
    installed = dispatcher._install(request, worktree, sdir)  # noqa: SLF001 - the thing under test
    written = SessionConfig.model_validate_json(Path(installed.config).read_text())

    assert oversized is not None, "the fixture never found its own skill.md path"
    decision = measure(written)
    assert not decision.allow
    assert "skill.md" in decision.reason and "not a reason to raise the ceiling" in decision.reason

    # The same refusal, through the real SessionStart hook this run would actually get.
    start_input = _Input(
        session_id="probe-over-ceiling", hook_event_name="SessionStart", tool_name=None
    )
    start_decision = session_start(start_input, written)
    assert not start_decision.allow
    assert "skill.md" in start_decision.reason
