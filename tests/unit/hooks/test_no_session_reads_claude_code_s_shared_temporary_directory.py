"""No session under test reads the temporary directory every Claude Code session of the user shares.

Claude Code keeps its temporary files under ``/tmp/claude-<uid>`` (``/private/tmp/claude-<uid>`` on
macOS) unless ``CLAUDE_CODE_TMPDIR`` names another directory: every session of the same user on the
machine writes its background commands' output there, the operator's own sessions among them. So
each role, baseline and reviewer session is given a temporary directory of its own, its binary is
pointed at it, and the shared directory is refused to every read and write of the session: the file
tools, a shell command, and the OS layer's sandbox. The session's own temporary directory stays
open to it.

Every shared directory here is a stand-in under the test's own directory, holding a file the test
planted; nothing of the real one is read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from hook_helpers import bash, event
from pydantic import ValidationError

from physgate.hooks import paths, settings, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, build_config, install
from physgate.hooks.settings import current_installation as installation
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "baseline", "reviewer")
SID = "4f3e2d1c-a-session"
#: What the operator's own session printed, as a stand-in: no other file holds it.
SHARED_MARKER = "operator-task-output-7e21"
OWN_MARKER = "own-task-output-3b90"
OWN_TEMP = "/tmp/pg-0123456789ab"


def _uid_dir() -> str:
    return f"claude-{os.getuid()}"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1").mkdir(parents=True)
    (base / "packet" / "worktree").mkdir(parents=True)
    return base


def _task_file(top: Path, marker: str) -> Path:
    """A background command's output, where the binary writes one under ``top``."""
    tasks = top / _uid_dir() / "-a-project" / SID / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    out = tasks / "b1k2m3n4p.output"
    out.write_text(marker + "\n")
    return out


@pytest.fixture
def shared(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the shared directory, with another session's task output planted in it."""
    top = root / "shared-tmp"
    _task_file(top, SHARED_MARKER)
    monkeypatch.setattr(settings, "claude_temp_dirs", lambda: (str(top / _uid_dir()),))
    return top / _uid_dir()


def _fields(root: Path, profile: str, **extra: object) -> dict[str, object]:
    sdir = root / "run" / "sessions" / SID
    reviewer = profile == "reviewer"
    worktree = root / "packet" / "worktree" if reviewer else root / "run" / "worktrees" / "s1"
    fields: dict[str, object] = {
        "profile": profile,
        "role": "electrical" if profile == "role" else None,
        "worktree": str(worktree),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
    }
    if reviewer:
        # An allowance that holds the shared directory: the rule refuses it all the same.
        fields["read_roots"] = (str(root / "packet"), str(root / "shared-tmp"))
    else:
        fields["sessions_root"] = str(root / "run" / "sessions")
    fields.update(extra)
    return fields


def _request(root: Path, profile: str, **extra: object) -> InstallRequest:
    """The request, or the test's failure where the request cannot say what is asked of it."""
    try:
        return InstallRequest.model_validate(_fields(root, profile, **extra))
    except ValidationError as exc:
        pytest.fail(f"the install request cannot carry this: {exc}")


def _config(root: Path, profile: str) -> SessionConfig:
    return build_config(InstallRequest.model_validate(_fields(root, profile)), installation())


def _read(path: str, config: SessionConfig) -> str:
    """The file-tool hook's answer to a Read of ``path``: ``allow`` or the reason it refused."""
    hook_input = HookInput.model_validate(
        event(tool_name="Read", tool_input={"file_path": path}, cwd=config.worktree)
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _shell(command: str, config: SessionConfig) -> str:
    """The shell hook's answer to a Bash call: ``allow`` or the reason it refused."""
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = shell_paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_another_session_s_task_output_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    config = _config(root, profile)
    (planted,) = shared.rglob("*.output")
    for path in (planted, planted.parent, shared):
        assert _read(str(path), config) != "allow", path
        relative = os.path.relpath(path, config.worktree)
        assert _read(relative, config) != "allow", relative


@pytest.mark.parametrize("profile", PROFILES)
def test_a_read_through_another_spelling_of_the_shared_directory_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    # As /tmp is /private/tmp on macOS: the directory reached through a link to its parent.
    link = root / "tmp-link"
    link.symlink_to(shared.parent)
    config = _config(root, profile)
    (planted,) = shared.rglob("*.output")
    other = link / planted.relative_to(shared.parent)
    assert other.read_text().strip() == SHARED_MARKER  # the same file, by another name
    assert _read(str(other), config) != "allow", other


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_shell_read_of_another_session_s_task_output_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    config = _config(root, profile)
    (planted,) = shared.rglob("*.output")
    relative = os.path.relpath(planted, config.worktree)
    for command in (f"cat {planted}", f"head -c 99 {relative}", f"ls {shared}", f"cat {shared}/*"):
        assert _shell(command, config) != "allow", command


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_write_into_the_shared_directory_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    config = _config(root, profile)
    target = shared / "-a-project" / "planted.txt"
    assert paths.protection(str(target), config.worktree, config, writing=True) is not None
    assert _shell(f"echo x > {target}", config) != "allow"


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_the_os_layer_denies_the_shared_directory_both_ways_from_the_configuration(
    root: Path, shared: Path, profile: str
) -> None:
    # From the session's configuration alone: no separate list handed to the policy.
    config = _config(root, profile)
    home = str(root / "run" / "sessions" / SID / "home")
    fs = sandbox_policy(config, home=home, temp_dir=OWN_TEMP).settings["sandbox"]["filesystem"]
    assert str(shared) in fs["denyRead"], fs["denyRead"]
    assert str(shared) in fs["denyWrite"], fs["denyWrite"]
    assert not [a for a in fs["allowRead"] if Path(a).is_relative_to(shared)]


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_the_session_s_own_temporary_directory_stays_open_to_it(
    root: Path, shared: Path, profile: str
) -> None:
    # A reviewer has no shell, so no command of its own writes there, and it reads only its
    # allowance.
    config = _config(root, profile)
    own = _task_file(root / "own-tmp", OWN_MARKER)
    assert _read(str(own), config) == "allow"
    assert _shell(f"cat {own}", config) == "allow"


@pytest.mark.parametrize("profile", PROFILES)
def test_an_install_names_claude_code_s_own_shared_directory_by_default(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    shared = f"/tmp/claude-{os.getuid()}"
    named = {r.path: r for r in config.protected_roots}
    assert shared in named, sorted(named)
    assert named[shared].reads == "denied"
    assert _read(f"{shared}/-a-project/{SID}/tasks/x.output", config) != "allow"
    if sys.platform == "darwin":
        assert _read(f"/private{shared}/-a-project/{SID}/tasks/x.output", config) != "allow"


@pytest.mark.parametrize("profile", PROFILES)
def test_the_binary_is_pointed_at_the_session_s_own_temporary_directory_without_the_layer(
    root: Path, shared: Path, profile: str
) -> None:
    done = install(_request(root, profile, temp_dir=OWN_TEMP), REGISTRY)
    assert done.spawn_env["CLAUDE_CODE_TMPDIR"] == OWN_TEMP


@pytest.mark.parametrize("profile", PROFILES)
def test_a_session_without_a_temporary_directory_of_its_own_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    with pytest.raises(ValueError, match="temporary directory of its own"):
        install(InstallRequest.model_validate(_fields(root, profile)), REGISTRY)
    assert not (root / "run" / "sessions" / SID / "session" / "settings.json").exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_a_temporary_directory_too_long_for_the_binary_is_refused_without_the_layer_too(
    root: Path, shared: Path, profile: str
) -> None:
    # A longer one is replaced by the shared directory itself.
    request = _request(root, profile, temp_dir="/tmp/pg-" + "0" * 40)
    with pytest.raises(ValueError, match="longer than"):
        install(request, REGISTRY)


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_role_or_baseline_install_without_the_session_directories_is_refused(
    root: Path, shared: Path, profile: str
) -> None:
    fields = _fields(root, profile)
    del fields["sessions_root"]
    with pytest.raises(ValueError, match="session directories"):
        install(InstallRequest.model_validate(fields), REGISTRY)
    assert not (root / "run" / "sessions" / SID / "session" / "settings.json").exists()
