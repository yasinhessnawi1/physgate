"""A shared temporary directory holding a place of the session's own is still refused around it.

The machine's shared temporary directories are refused to every role, baseline and reviewer
session both ways. Where one of the session's own places lies in one (a unit rig's tree, a
session without the OS layer: the installer refuses a sandboxed one a worktree there), the
directory is still named whole and only the session's own places are opened again there: a
neighbour beside them is refused, by the file tools' hook, the shell hook and the OS layer's
policy alike. Here a stand-in directory plays the shared one.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import protection
from physgate.hooks.reasons import SHARED_TEMP_REASON
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.oslayer.policy import sandbox_policy


def _config(shared: Path, profile: str = "role") -> SessionConfig:
    run = shared / "run"
    worktree = run / "worktrees" / "s1"
    sdir = run / "sessions" / "s1"
    for d in (worktree, sdir / "home", sdir / "state", sdir / "session", sdir / "config"):
        d.mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(worktree),
        own_branch=None,
        store_root=None,
        state_dir=str(sdir / "state"),
        target_dir=str(sdir / "session"),
        claude_config_dir=str(sdir / "config"),
        user_home=str(sdir / "home"),
        token_ceiling=1000,
        shared_temps=(str(shared),),
        shared_claude_temp=(),
    )
    return build_config(request, current_installation())


@pytest.fixture
def shared(outside_tmp: Path) -> Path:
    made = Path(os.path.realpath(outside_tmp)) / "shared-tmp"
    (made / "another-trial").mkdir(parents=True)
    (made / "another-trial" / "notes.txt").write_text("another trial's\n")
    return made


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_the_file_tools_and_the_shell_are_refused_a_neighbour_and_given_their_own(
    shared: Path, profile: str
) -> None:
    config = _config(shared, profile)
    worktree = config.worktree
    neighbour = str(shared / "another-trial" / "notes.txt")
    for writing in (False, True):
        for shell in (False, True):
            said = protection(neighbour, worktree, config, writing=writing, shell=shell)
            assert said == SHARED_TEMP_REASON, (writing, shell, said)
    own = os.path.join(worktree, "a.py")
    assert protection(own, worktree, config, writing=False) is None
    assert protection(own, worktree, config, writing=True) is None
    root = next(r for r in config.protected_roots if r.path == str(shared))
    assert root.reads == "denied"
    assert worktree in root.read_exceptions and worktree in root.exceptions


def test_the_os_layer_refuses_a_worktree_there_and_opens_a_home_there_alone(
    shared: Path,
) -> None:
    # A sandboxed session's worktree in a shared directory is refused, by the policy as by the
    # installer's placement rule: the layer would deny the session its own work.
    with pytest.raises(ValueError, match="worktree .* is inside a read-denied path"):
        sandbox_policy(
            _config(shared),
            home=str(shared / "run" / "sessions" / "s1" / "home"),
            temp_dir="/var/tmp/pgs/0123456789",
        )
    # A home there, the worktree elsewhere: the directory is denied, the home alone opened.
    elsewhere = shared.parent / "elsewhere"
    worktree = elsewhere / "worktree"
    worktree.mkdir(parents=True)
    home = shared / "home"
    home.mkdir()
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(worktree),
        own_branch=None,
        store_root=None,
        state_dir=str(elsewhere / "state"),
        target_dir=str(elsewhere / "session"),
        claude_config_dir=str(elsewhere / "config"),
        user_home=str(home),
        token_ceiling=1000,
        shared_temps=(str(shared),),
        shared_claude_temp=(),
    )
    config = build_config(request, current_installation())
    fs = sandbox_policy(config, home=str(home), temp_dir="/var/tmp/pgs/0123456789").settings[
        "sandbox"
    ]["filesystem"]
    assert str(shared) in fs["denyRead"]
    assert str(shared) not in fs["allowRead"] and str(shared) not in fs["allowWrite"]
    assert str(home) in fs["allowRead"] and str(home) in fs["allowWrite"]
