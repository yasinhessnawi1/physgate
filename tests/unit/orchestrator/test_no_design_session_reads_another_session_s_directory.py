"""No role or baseline session reads the run's session directories, but for its own reading.

Every session of a run has a directory under the run's ``sessions/``: its Claude Code configuration
(in the subscription mode, the login), its captured stream, its settings and its hook state. A
session's working directory lies beneath the run directory, so a file tool could reach a sibling's
directory by a path from its own. So the whole of ``sessions/`` is refused to every read of a role
or baseline session: the file tools, a shell command, and the OS layer's sandbox. The hooks refuse
the session's own home too; what stays open to them is what it is given to read there, and the OS
layer opens the home to its commands. Its own binary reads its configuration itself, not through a
tool, so that is not refused.
"""

from __future__ import annotations

import contextlib
import hashlib
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
from physgate.orchestrator.protocols import IssuedState
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "baseline")
#: A sibling session's login, as the subscription mode writes it.
TOKEN = "login-stand-in-0c9d"
SID = "7a6b5c4d-own-session"
ISSUED = b"# Integration's issued state\n\nThe stand-in.\n"


def _argv(base: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The installer's argv, as the dispatcher builds it for a session in ``run/sessions/<sid>``."""
    seen: list[list[str]] = []
    real_run = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if list(argv[1:3]) == ["hooks", "install"]:
            seen.append(list(argv))
            out = '{"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}'
            return subprocess.CompletedProcess(argv, 0, out, "")
        return real_run(argv, **kw)

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
            # Integration's issued state: the one file a session reads in its own directory.
            issued_state=IssuedState(
                text=ISSUED.decode(),
                sha256=hashlib.sha256(ISSUED).hexdigest(),
                length=len(ISSUED),
            ),
        )
        worktree = base / "run" / "worktrees" / "s1"
        worktree.mkdir(parents=True, exist_ok=True)
        dispatcher._install(
            request,
            worktree,
            base / "run" / "sessions" / SID,
            None,
            own_temp=Path("/var/tmp/pgs/0123456789"),
        )
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
    # The run.json named here is never written; the recorded-hooks rule has its own rows.
    monkeypatch.setattr(hooks_cli, "_hooks_refusal", lambda _args: None)
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


def _issued(base: Path) -> Path:
    (found,) = (base / "run" / "sessions" / SID / "issued").iterdir()
    return found


@pytest.mark.parametrize("profile", PROFILES)
def test_a_session_still_reads_what_it_is_given_in_its_own_directory(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    issued = _issued(base)
    assert issued.read_bytes() == ISSUED
    assert paths.protection(str(issued), config.worktree, config, writing=False) is None


@pytest.mark.parametrize("profile", PROFILES)
def test_nothing_else_of_its_own_directory_is_read_not_even_its_home(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    own = base / "run" / "sessions" / SID
    note = own / "home" / "notes.txt"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("mine\n")
    for path in (note, own / "config", own / "issued"):
        assert paths.protection(str(path), config.worktree, config, writing=False) is not None, path


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("kind", ["symlink", "hard link"])
def test_a_link_in_its_own_directory_to_a_sibling_s_login_is_refused(
    base: Path, monkeypatch: pytest.MonkeyPatch, profile: str, kind: str
) -> None:
    config = _installed(base, monkeypatch, profile)
    login, _ = _sibling(base)
    home = base / "run" / "sessions" / SID / "home"
    home.mkdir(parents=True, exist_ok=True)
    issued = _issued(base)
    issued.unlink()
    # In its home, and in the very place of the file it is given to read.
    for link in (home / "login.json", issued):
        if kind == "symlink":
            link.symlink_to(login)
        else:
            os.link(login, link)
        assert paths.protection(str(link), config.worktree, config, writing=False) is not None, link
        command = parse(f"cat {link}")[0]
        assert shell_paths.check(command, config.worktree, config) is not None, link


def test_the_dispatcher_s_install_names_the_run_s_sessions(
    base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The installer is told, by the dispatcher, where the run keeps every session's directory.
    argv = _argv(base, monkeypatch)
    named = [argv[i + 1] for i, a in enumerate(argv) if a == "--sessions-root"]
    assert named == [str(base / "run" / "sessions")], argv


@pytest.mark.parametrize("profile", PROFILES)
def test_a_search_path_from_its_interpreter_s_directory_reads_nothing_and_is_not_refused(
    base: Path, profile: str
) -> None:
    # The run's named interpreter is linked in the session's own directory, where no command of
    # the session writes, and its search path starts there: ``$PATH`` expanded names no file.
    from physgate.hooks.settings import InstallRequest, build_config, current_installation

    own = base / "run" / "sessions" / SID
    (own / "bin").mkdir(parents=True)
    worktree = base / "run" / "worktrees" / "s1"
    worktree.mkdir(parents=True)
    config = build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(own / "state"),
            target_dir=str(own / "session"),
            claude_config_dir=str(own / "config"),
            user_home=str(own / "home"),
            token_ceiling=1000,
            os_layer_readable=(str(own / "bin"), str(own / "home" / "bin")),
            sessions_root=str(base / "run" / "sessions"),
        ),
        current_installation(),
    )
    wt = str(worktree)
    for allowed in (f"{own / 'bin'}:/usr/bin:/bin", str(own / "bin" / "absent")):
        assert paths.protection(allowed, wt, config, writing=False) is None, allowed
    # Never in its home, where its commands write: what is absent there now can be made there.
    for refused in (own / "home" / "bin" / "absent", own / "home" / "absent", own / "absent"):
        assert paths.protection(str(refused), wt, config, writing=False) is not None, refused


@pytest.mark.parametrize("profile", PROFILES)
def test_a_symlinked_directory_inside_an_allowance_does_not_open_a_sibling_s_directory(
    base: Path, profile: str
) -> None:
    # An allowance is held on the path as resolved too: a directory linked inside the
    # interpreter's directory to a sibling session's directory is not the interpreter's.
    from physgate.hooks.settings import InstallRequest, build_config, current_installation

    own = base / "run" / "sessions" / SID
    (own / "bin").mkdir(parents=True)
    worktree = base / "run" / "worktrees" / "s1"
    worktree.mkdir(parents=True)
    login, _ = _sibling(base)
    (own / "bin" / "sub").symlink_to(login.parent)
    config = build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="control" if profile == "role" else None,
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(own / "state"),
            target_dir=str(own / "session"),
            claude_config_dir=str(own / "config"),
            user_home=str(own / "home"),
            token_ceiling=1000,
            os_layer_readable=(str(own / "bin"),),
            sessions_root=str(base / "run" / "sessions"),
        ),
        current_installation(),
    )
    through = own / "bin" / "sub" / login.name
    assert through.read_text() == login.read_text()
    wt = str(worktree)
    assert paths.protection(str(through), wt, config, writing=False) is not None
    assert shell_paths.check(parse(f"cat {through}")[0], wt, config) is not None
