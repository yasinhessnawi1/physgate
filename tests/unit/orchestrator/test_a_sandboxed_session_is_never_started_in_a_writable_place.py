"""The dispatcher starts no sandboxed session whose worktree lies where the layer lets all write.

Two sandboxed sessions whose worktrees share an ancestor in a writable place (``/tmp``,
the per-user temporary directory) abort each other's commands on Linux. Where the OS
layer runs, the dispatcher refuses such a worktree before anything of the session
exists, with the reason; where the layer does not run, or the worktree lies elsewhere,
the session starts as before.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config

from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import WorktreeMisplacedError
from physgate.orchestrator.ports import SessionRequest
from physgate.oslayer.probe import Absent, Present

PRESENT = Present(mechanism="bubblewrap", claude_version="2.1.301")
ABSENT = Absent(reason="stand-in: no layer")


def _attempt(
    monkeypatch: pytest.MonkeyPatch, worktree: Path, run_dir: Path, layer: Present | Absent
) -> list[Path]:
    """Dispatch one attempt in ``worktree``; return the session directories it reached."""
    config = make_config()
    started: list[Path] = []

    def run_session(  # noqa: ANN401
        _self: Any, _request: Any, _worktree: Path, sdir: Path, *_a: Any, **_k: Any
    ) -> str:
        started.append(sdir)
        return "started"

    monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
    monkeypatch.setattr(dispatch, "empty_outbox", lambda *_a: ())
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: layer)
    monkeypatch.setattr(ClaudeDispatcher, "_run_session", run_session)
    dispatcher = ClaudeDispatcher(
        config=config,
        run=SimpleNamespace(open_subtask=lambda _s: worktree, run_dir=run_dir),  # type: ignore[arg-type]
        store_root=run_dir / "store",
        install_bin=run_dir / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=run_dir / "reviews",
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/power",
        model=config.models.roles["electrical"],
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    dispatcher.run(request)
    return started


def test_a_sandboxed_session_in_the_shared_temporary_directory_is_refused_before_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = Path("/tmp/pg-run-never-made")
    with pytest.raises(WorktreeMisplacedError, match="a place the OS layer makes writable") as e:
        _attempt(monkeypatch, run_dir / "worktrees" / "s1", run_dir, PRESENT)
    assert e.value.context == {"subtask_id": "s1"}
    assert not run_dir.exists()  # nothing of the session was made


def test_without_the_layer_the_same_worktree_starts_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = Path("/tmp/pg-run-never-made")
    assert len(_attempt(monkeypatch, run_dir / "worktrees" / "s1", run_dir, ABSENT)) == 1


def test_a_sandboxed_session_outside_every_writable_place_starts(
    monkeypatch: pytest.MonkeyPatch, outside_tmp: Path
) -> None:
    started = _attempt(monkeypatch, outside_tmp / "worktrees" / "s1", outside_tmp, PRESENT)
    assert len(started) == 1
