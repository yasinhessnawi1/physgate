"""No session under test reads or writes another session's temporary directory.

Every session's own temporary directory lies directly beneath one parent, which is refused to the
session's every read and write: the file tools, a shell command, and the OS layer's sandbox. Only
the session's own directory beneath it stays open, matched exactly: as spelt and as resolved, never
case-folded, and never through a link. So no session reads the task output another session left
in its own directory, all of them running as the same user.

Every parent here is a stand-in under the test's own directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths, settings, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, build_config, install
from physgate.hooks.settings import current_installation as installation
from physgate.oslayer.policy import sandbox_policy

PROFILES = ("role", "baseline", "reviewer")
SID = "5a4b3c2d-a-session"
OWN = "a1a1a1a1a1"
OTHER = "b2b2b2b2b2"
OTHER_MARKER = "other-session-task-output-41c7"
OWN_MARKER = "own-session-task-output-8d02"


def _task_file(temp: Path, marker: str) -> Path:
    """A background command's output, where the binary writes one in a session's directory."""
    tasks = temp / f"claude-{os.getuid()}" / "-a-project" / SID / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    out = tasks / "b1k2m3n4p.output"
    out.write_text(marker + "\n")
    return out


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1").mkdir(parents=True)
    (base / "packet" / "worktree").mkdir(parents=True)
    parent = base / "temps"
    _task_file(parent / OWN, OWN_MARKER)
    _task_file(parent / OTHER, OTHER_MARKER)
    # The parent every session's own temporary directory is made in, as a stand-in.
    monkeypatch.setattr(settings, "session_temps_root", lambda: str(parent), raising=False)
    return base


def _fields(root: Path, profile: str, own: Path | None) -> dict[str, object]:
    sdir = root / "run" / "sessions" / SID
    reviewer = profile == "reviewer"
    fields: dict[str, object] = {
        "profile": profile,
        "role": "electrical" if profile == "role" else None,
        "worktree": str(root / "packet" / "worktree" if reviewer else root / "run" / "worktrees"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
    }
    if reviewer:
        # An allowance that holds every session's directory: the rule refuses them all the same.
        fields["read_roots"] = (str(root / "packet"), str(root / "temps"))
    else:
        fields["worktree"] = str(root / "run" / "worktrees" / "s1")
        fields["sessions_root"] = str(root / "run" / "sessions")
    if own is not None:
        fields["temp_dir"] = str(own)
    return fields


def _config(root: Path, profile: str) -> SessionConfig:
    request = InstallRequest.model_validate(_fields(root, profile, root / "temps" / OWN))
    return build_config(request, installation())


def _read(path: str, config: SessionConfig) -> str:
    hook_input = HookInput.model_validate(
        event(tool_name="Read", tool_input={"file_path": path}, cwd=config.worktree)
    )
    decision = paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _shell(command: str, config: SessionConfig) -> str:
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = shell_paths.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _other(root: Path) -> Path:
    (found,) = (root / "temps" / OTHER).rglob("*.output")
    return found


def _own(root: Path) -> Path:
    (found,) = (root / "temps" / OWN).rglob("*.output")
    return found


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_another_session_s_temporary_directory_is_refused(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    other = _other(root)
    for path in (other, other.parent, root / "temps" / OTHER, root / "temps"):
        assert _read(str(path), config) != "allow", path
        relative = os.path.relpath(path, config.worktree)
        assert _read(relative, config) != "allow", relative


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_shell_read_of_another_session_s_temporary_directory_is_refused(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    other = _other(root)
    relative = os.path.relpath(other, config.worktree)
    temps = root / "temps"
    for command in (f"cat {other}", f"head -c 9 {relative}", f"ls {temps}", f"cat {temps}/*/x"):
        assert _shell(command, config) != "allow", command


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_write_into_another_session_s_temporary_directory_is_refused(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    target = root / "temps" / OTHER / "planted.txt"
    assert paths.protection(str(target), config.worktree, config, writing=True) is not None
    assert _shell(f"echo x > {target}", config) != "allow"


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_the_session_s_own_directory_stays_open_to_it_exactly(root: Path, profile: str) -> None:
    config = _config(root, profile)
    own = _own(root)
    assert _read(str(own), config) == "allow"
    assert _shell(f"cat {own}", config) == "allow"
    assert (
        paths.protection(str(own.parent / "new.txt"), config.worktree, config, writing=True) is None
    )


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_link_in_the_session_s_own_directory_to_another_s_is_refused(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    own_dir = root / "temps" / OWN
    (own_dir / "file-link").symlink_to(_other(root))
    (own_dir / "dir-link").symlink_to(root / "temps" / OTHER)
    through = own_dir / "dir-link" / _other(root).relative_to(root / "temps" / OTHER)
    for path in (own_dir / "file-link", through):
        assert _read(str(path), config) != "allow", path
        assert _shell(f"cat {path}", config) != "allow", path


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_case_variant_of_the_session_s_own_directory_is_not_its_own(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    own = _own(root)
    variant = str(own).replace(f"/temps/{OWN}/", f"/temps/{OWN.upper()}/")
    assert variant != str(own)
    assert _read(variant, config) != "allow"


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_the_os_layer_denies_every_session_s_directory_but_its_own(
    root: Path, profile: str
) -> None:
    config = _config(root, profile)
    home = str(root / "run" / "sessions" / SID / "home")
    own = str(root / "temps" / OWN)
    fs = sandbox_policy(config, home=home, temp_dir=own).settings["sandbox"]["filesystem"]
    assert str(root / "temps") in fs["denyRead"], fs["denyRead"]
    assert own in fs["allowRead"], fs["allowRead"]
    assert not [a for a in fs["allowRead"] if Path(a).is_relative_to(root / "temps" / OTHER)]
    assert not [a for a in fs["allowWrite"] if Path(a).is_relative_to(root / "temps" / OTHER)]


@pytest.mark.parametrize("profile", PROFILES)
def test_a_temporary_directory_outside_the_one_parent_is_refused(root: Path, profile: str) -> None:
    for elsewhere in ("/tmp/pg-0123456789ab", str(root / "elsewhere" / OWN)):
        fields = _fields(root, profile, Path(elsewhere))
        with pytest.raises(ValueError, match="beneath"):
            install(InstallRequest.model_validate(fields), REGISTRY)
    assert not (root / "run" / "sessions" / SID / "session" / "settings.json").exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_the_parent_itself_is_never_a_session_s_own_directory(root: Path, profile: str) -> None:
    fields = _fields(root, profile, root / "temps")
    with pytest.raises(ValueError, match="beneath"):
        install(InstallRequest.model_validate(fields), REGISTRY)
