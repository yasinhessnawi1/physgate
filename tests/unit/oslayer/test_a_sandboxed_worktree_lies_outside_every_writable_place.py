"""A sandboxed session is refused a worktree inside a place the OS layer makes writable.

On Linux the sandbox lays placeholders in every ancestor of the working directory that
lies inside a writable place; two sessions under one such ancestor remove each other's,
and bubblewrap aborts their commands before they run (measured on an ARM Linux VM).
So the hook installer refuses any sandboxed session, a role's or the raw agent's, a
worktree in the shared temporary directories, in Claude Code's own temporary directory,
or in the session's own writable places; a worktree anywhere else is installed as before.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
from pathlib import Path

import pytest

from physgate.hooks.config import Profile
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install
from physgate.oslayer.placement import machine_writable, placement_refusal
from physgate.oslayer.probe import claude_temp_dirs, shared_temp_dirs

TEMP = "/tmp/pg-0123456789ab"


def _request(root: Path, worktree: Path, *, profile: Profile = "role") -> InstallRequest:
    worktree.mkdir(parents=True, exist_ok=True)
    out = root / "outside"
    return InstallRequest(
        profile=profile,
        role="electrical" if profile == "role" else None,
        worktree=str(worktree),
        own_branch="subtask/e-1" if profile == "role" else None,
        store_root=str(out / "store") if profile == "role" else None,
        state_dir=str(out / "state"),
        target_dir=str(out / "session"),
        claude_config_dir=str(out / "config"),
        user_home=str(out / "home"),
        token_ceiling=1000,
        os_layer_temp_dir=TEMP,
    )


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_sandboxed_session_in_the_shared_temporary_directory_is_refused(
    profile: Profile,
) -> None:
    root = Path("/tmp") / f"pg-placement-{secrets.token_hex(6)}"
    try:
        with pytest.raises(ValueError, match="a place the OS layer makes writable"):
            install(_request(root, root / "run" / "worktrees" / "s1", profile=profile), REGISTRY)
        assert not (root / "outside" / "session").exists()  # nothing was installed
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("profile", ["role", "baseline"])
def test_a_sandboxed_session_outside_every_writable_place_is_installed(
    outside_tmp: Path, profile: Profile
) -> None:
    done = install(_request(outside_tmp, outside_tmp / "worktree", profile=profile), REGISTRY)
    assert json.loads(done.settings_path.read_text())["sandbox"]["enabled"] is True


def test_a_session_without_the_layer_may_lie_anywhere() -> None:
    root = Path("/tmp") / f"pg-placement-{secrets.token_hex(6)}"
    try:
        request = _request(root, root / "worktree").model_copy(update={"os_layer_temp_dir": None})
        done = install(request, REGISTRY)
        assert "sandbox" not in json.loads(done.settings_path.read_text())
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_worktree_in_the_session_s_own_home_is_refused(outside_tmp: Path) -> None:
    request = _request(outside_tmp, outside_tmp / "outside" / "home" / "worktree")
    with pytest.raises(ValueError, match="home"):
        install(request, REGISTRY)


@pytest.mark.parametrize(
    "where", ["/tmp/x", "/tmp", "/private/tmp/x", "shared-per-user", "claude-temp"]
)
def test_every_spelling_of_a_machine_wide_writable_place_is_refused(where: str) -> None:
    places = {
        "shared-per-user": f"{shared_temp_dirs()[-1]}/x",
        "claude-temp": f"{claude_temp_dirs()[0]}/x",
    }
    if where.startswith("/private") and not os.path.isdir("/private/tmp"):
        pytest.skip("no /private/tmp here")
    assert placement_refusal(Path(places.get(where, where)), machine_writable()) is not None


def test_a_worktree_reached_through_a_link_into_a_writable_place_is_refused(
    outside_tmp: Path,
) -> None:
    target = Path("/tmp") / f"pg-link-{secrets.token_hex(6)}"
    target.mkdir()
    try:
        link = outside_tmp / "link"
        link.symlink_to(target)
        assert placement_refusal(link / "worktrees" / "s1", machine_writable()) is not None
    finally:
        shutil.rmtree(target, ignore_errors=True)


def test_a_worktree_under_the_user_s_scratch_area_is_accepted() -> None:
    root = Path.home() / "physgate-scratch" / "runs" / "r1" / "worktrees" / "s1"
    assert placement_refusal(root, machine_writable()) is None
