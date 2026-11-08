"""No role or baseline session reads the run's session directories, but for its own reading.

Every session of a run has a directory under the run's ``sessions/``: its Claude Code configuration
(in the subscription mode, the login), its captured stream, its settings and its hook state. A
session's working directory lies beneath the run directory, so a file tool could reach a sibling's
directory by a path from its own. So the whole of ``sessions/`` is refused to every read of a role
or baseline session: the file tools, a shell command, and the OS layer's sandbox. What stays open
is the session's own home and what it is given to read there. Its own binary reads its
configuration itself, not through a tool, so that is not refused.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from orch_helpers import SCRIPTED_BOUNDS, make_config

from physgate.hooks import cli as hooks_cli
from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.shell import parse
from physgate.orchestrator import dispatch
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.ports import SessionRequest
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "baseline")
#: A sibling session's login, as the subscription mode writes it.
TOKEN = "sk-ant-oat01-not-a-credential-0c9d"
SID = "7a6b5c4d-own-session"


def _argv(base: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The installer's argv, as the dispatcher builds it for a session in ``run/sessions/<sid>``."""
    seen: list[list[str]] = []
    real_run = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if list(argv[1:3]) == ["hooks", "install"]:
            seen.append(list(argv))
            out = '{"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}'
            return subprocess.CompletedProcess(argv, 0, out, "")
        return real_run(argv, **kw)  # type: ignore[call-overload,no-any-return]

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        patch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
        patch.setattr(dispatch, "harness_protection", lambda: [])
        dispatcher = dispatch.ClaudeDispatcher(
            config=make_config(),
            run=SimpleNamespace(  # type: ignore[arg-type]
                subtask_branch=lambda subtask, _reopen=0: f"b/{subtask}", run_dir=base / "run"
            ),
            store_root=base / "store",
            install_bin=base / "install" / "bin" / "physgate",
            binary="claude",
            base_url=None,
            credential=Credential(mode="api_key", secret="not-a-key"),
            review_root=base / "reviews",
        )
        request = SessionRequest(
            subtask_id="s1",
            attempt=1,
            assigned_role="control",
            spec_path=".physgate/specs/s1.md",
            module_dir="modules/control",
            model="claude-opus-5-5",
            repair_instruction=None,
            bounds=SCRIPTED_BOUNDS,
        )
        worktree = base / "run" / "worktrees" / "s1"
        worktree.mkdir(parents=True, exist_ok=True)
        dispatcher._install(request, worktree, base / "run" / "sessions" / SID, None)
    (argv,) = seen
    return argv


def _installed(base: Path, monkeypatch: pytest.MonkeyPatch, profile: str) -> SessionConfig:
    """A session installed with the argv the dispatcher builds, as ``profile``."""
    argv = _argv(base, monkeypatch)
    if profile != "role":
        i = argv.index("--role")
        argv = argv[:i] + argv[i + 2 :]
        argv[argv.index("--profile") + 1] = profile
    # The installer is run in this process; whether the OS layer may be absent is its own
    # question, not this row's.
    monkeypatch.setattr(hooks_cli, "_os_layer_refusal", lambda _args: None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert hooks_cli.main(argv[1:]) == 0
    printed = out.getvalue()
    config_path = Path(printed[printed.index('"config": "') + 11 :].split('"', 1)[0])
    return SessionConfig.model_validate_json(config_path.read_bytes())


def _sibling(tmp_path: Path) -> tuple[Path, Path]:
    """A sibling session's login and stream, as an earlier session of the run left them."""
    sibling = tmp_path / "run" / "sessions" / "0b1c2d3e-sibling"
    (sibling / "config").mkdir(parents=True)
    login = sibling / "config" / ".credentials.json"
    login.write_text('{"claudeAiOauth": {"accessToken": "' + TOKEN + '"}}\n')
    stream = sibling / "stdout.jsonl"
    stream.write_text('{"type": "result"}\n')
    return login, stream


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_a_sibling_session_s_directory_is_refused(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    login, stream = _sibling(base)
    wt = config.worktree
    for path in (login, login.parent, stream):
        assert paths.protection(str(path), wt, config, writing=False) is not None, path
        relative = os.path.relpath(path, wt)
        assert paths.protection(relative, wt, config, writing=False) is not None, relative


@pytest.mark.parametrize("profile", PROFILES)
def test_a_shell_read_of_a_sibling_session_s_directory_is_refused(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    login, _ = _sibling(base)
    relative = os.path.relpath(login, config.worktree)
    for command in (f"cat {login}", f"cat {relative}", f"ls {login.parent.parent}"):
        assert shell_paths.check(parse(command)[0], config.worktree, config) is not None, command


@pytest.mark.parametrize("profile", PROFILES)
def test_the_os_layer_denies_every_read_of_a_sibling_session_s_directory(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    login, _ = _sibling(base)
    home = base / "run" / "sessions" / SID / "home"
    fs = sandbox_policy(config, home=str(home), temp_dir="/tmp/pg-sib").settings["sandbox"][
        "filesystem"
    ]

    def covered(path: str, listed: list[str]) -> bool:
        return any(path == d or path.startswith(d.rstrip("/") + "/") for d in listed)

    assert covered(str(login), fs["denyRead"]), fs["denyRead"]
    assert not covered(str(login), fs["allowRead"]), fs["allowRead"]


@pytest.mark.parametrize("profile", PROFILES)
def test_a_session_still_reads_its_own_home(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    home = base / "run" / "sessions" / SID / "home"
    note = home / "notes.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("mine\n")
    assert paths.protection(str(note), config.worktree, config, writing=False) is None
    assert shell_paths.check(parse(f"cat {note}")[0], config.worktree, config) is None


def test_the_dispatcher_s_install_names_the_run_s_sessions(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The installer is told, by the dispatcher, where the run keeps every session's directory.
    argv = _argv(base, monkeypatch)
    named = [argv[i + 1] for i, a in enumerate(argv) if a == "--sessions-root"]
    assert named == [str(base / "run" / "sessions")], argv
