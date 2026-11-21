"""Every role and review session is installed with a temporary directory of its own.

Without one, Claude Code keeps the session's temporary files in the directory every session of the
user on the machine shares, which the hook layer refuses to the session's tools. So the dispatcher
gives each role session one, with the OS layer or without it, and each review session gets one
too. Each is short enough for the binary to take, exists while the session is installed, and is
removed when the session is over.

The installer itself is stood in for: what is asserted is what each spawner asks of it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config

from physgate.hooks.settings import OS_LAYER_TEMP_LIMIT
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.ports import SessionRequest
from physgate.oslayer.probe import Absent, Present

ABSENT = Absent(reason="stand-in: no sandbox here")
PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")


def _value(argv: list[str], flag: str) -> str | None:
    found = [argv[i + 1] for i, arg in enumerate(argv) if arg == flag]
    assert len(found) <= 1, argv
    return found[0] if found else None


def _installer(seen: list[tuple[list[str], dict[str, bool]]]) -> Any:  # noqa: ANN401
    """A stand-in installer that records its argv and whether each temporary directory exists."""
    real_run = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if list(argv[1:3]) == ["hooks", "install"]:
            temps = {
                v: Path(v).is_dir()
                for flag in ("--temp", "--os-layer-temp")
                if (v := _value(argv, flag)) is not None
            }
            seen.append((list(argv), temps))
            return subprocess.CompletedProcess(argv, 2, "", "stood in: no session is started")
        return real_run(argv, **kw)

    return run


def _dispatch(
    monkeypatch: pytest.MonkeyPatch, run_dir: Path, layer: Present | Absent
) -> tuple[list[str], dict[str, bool]]:
    """One attempt dispatched up to its installer, which refuses it: what that was asked."""
    config = make_config(os_layer_absent="allow" if isinstance(layer, Absent) else "refuse")
    seen: list[tuple[list[str], dict[str, bool]]] = []
    monkeypatch.setattr(subprocess, "run", _installer(seen))
    monkeypatch.setattr(dispatch, "binary_version", lambda _binary: config.claude_version)
    monkeypatch.setattr(dispatch, "empty_outbox", lambda *_a: ())
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    monkeypatch.setattr(dispatch, "harness_protection", lambda: [])
    # The stand-in run has no repository: its git directory is no one's to make anything in.
    monkeypatch.setattr(dispatch, "common_dir", lambda repo: repo / "no-git-directory")
    monkeypatch.setattr(ClaudeDispatcher, "os_layer", lambda _self: layer)
    monkeypatch.setattr(
        ClaudeDispatcher, "environment", lambda _self: SimpleNamespace(system_managed=())
    )

    def open_subtask(subtask_id: str, reopen: int = 0) -> Path:
        worktree = run_dir / "worktrees" / subtask_id
        worktree.mkdir(parents=True, exist_ok=True)
        return worktree

    dispatcher = ClaudeDispatcher(
        config=config,
        run=SimpleNamespace(  # type: ignore[arg-type]
            open_subtask=open_subtask,
            run_dir=run_dir,
            repo=run_dir,
            subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}",
        ),
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
    with pytest.raises(InvocationError, match="installer refused"):
        dispatcher.run(request)
    ((argv, temps),) = seen
    return argv, temps


#: The one parent of every session's own temporary directory, which every session is refused
#: but for its own child: outside every place the OS layer makes writable.
SESSION_TEMPS = "/var/tmp/pgs"


def _own(temps: dict[str, bool]) -> Path:
    """The one temporary directory the install was given: there then, gone now, short enough.

    It lies directly beneath the one parent, where no other session reads or writes it.
    """
    assert len(temps) == 1, temps
    ((path, existed),) = temps.items()
    assert existed, f"{path} did not exist when the session was installed"
    assert len(path) <= OS_LAYER_TEMP_LIMIT, path
    assert not Path(path).exists(), f"{path} outlived its session"
    assert os.path.realpath(Path(path).parent) == os.path.realpath(SESSION_TEMPS), path
    return Path(path)


def test_a_role_session_without_the_os_layer_gets_a_temporary_directory_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    argv, temps = _dispatch(monkeypatch, tmp_path / "run", ABSENT)
    assert _value(argv, "--temp") is not None, argv
    assert _value(argv, "--os-layer-temp") is None, argv
    assert _own(temps).name


def test_a_role_session_inside_the_os_layer_gets_its_layer_s_directory_and_no_second(
    monkeypatch: pytest.MonkeyPatch, outside_tmp: Path
) -> None:
    argv, temps = _dispatch(monkeypatch, outside_tmp / "run", PRESENT)
    assert _value(argv, "--os-layer-temp") is not None, argv
    assert _value(argv, "--temp") is None, argv
    assert _own(temps).name


def test_a_review_session_gets_a_temporary_directory_of_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from physgate.reviewers import claude
    from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
    from physgate.reviewers.rubric import Rubric

    seen: list[tuple[list[str], dict[str, bool]]] = []
    monkeypatch.setattr(subprocess, "run", _installer(seen))
    monkeypatch.setattr(claude, "harness_protection", lambda: [])
    config = make_config()
    monkeypatch.setattr(claude, "binary_version", lambda _binary: config.claude_version)
    review = tmp_path / "rs" / "review"
    read = review / "read"
    (read / "worktree").mkdir(parents=True)
    packet = SimpleNamespace(read_root=str(read), required_reading=(), indicators=())
    monkeypatch.setattr(claude, "review_dir", lambda _root, _sid: review)
    monkeypatch.setattr(ClaudeReviewer, "_prepare", lambda _self, _review, _a, _sid: packet)
    setup = ReviewerSetup.of_run(
        config,
        review_root=tmp_path / "rs",
        repo=tmp_path / "target",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=tmp_path / "harness",
    )
    reviewer = ClaudeReviewer(
        role="electrical", setup=setup, rubric=Rubric(role="electrical", text="r", sha256="0" * 64)
    )
    with pytest.raises(InvocationError, match="installer refused"):
        reviewer.review(SimpleNamespace())  # type: ignore[arg-type]
    ((argv, temps),) = seen
    assert _value(argv, "--temp") is not None, argv
    assert _own(temps).name
