"""The run's recorded configuration is withheld from every session that does design work.

``run.json`` records the held-out tier's canaries: the strings the stream scan looks for to
tell that a session read the held-out tier. A session that could read the list could read the
tier and print nothing the scan knows. A role session's worktree lies beneath the run
directory, so the file is two levels up from it.

So the dispatcher installs every role session with ``run.json`` withheld, and the hook layer
keeps a withheld path from every read: the file tools, a shell command, and the OS layer's
sandbox, for the role and the baseline profiles alike. Writes stay refused, and the file is
still put back if it changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from test_the_held_out_tier_and_the_network_reach_every_session import _install_argv, _values

from physgate.hooks import paths, shell_paths
from physgate.hooks.config import SessionConfig
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

CANARY = "cd" * 16
PROFILES = ("role", "baseline")


def _session(base: Path, profile: str) -> tuple[SessionConfig, Path, Path]:
    """A session of ``profile`` installed as the dispatcher installs one: its config, run.json."""
    wt = base / "run" / "worktrees" / "s1"
    wt.mkdir(parents=True)
    run_json = base / "run" / "run.json"
    run_json.write_text('{"held_out_canaries": ["' + CANARY + '"]}\n')
    for d in ("outside/state", "outside/session", "outside/config", "outside/home", "harness"):
        (base / d).mkdir(parents=True, exist_ok=True)
    held = base / "tiers" / "v1"
    held.mkdir(parents=True)
    request = InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(wt),
        own_branch=None,
        store_root=str(base / "run" / "store"),
        state_dir=str(base / "outside" / "state"),
        target_dir=str(base / "outside" / "session"),
        claude_config_dir=str(base / "outside" / "config"),
        user_home=str(base / "outside" / "home"),
        token_ceiling=40960,
        held_out=(str(held),),
        extra_protected=(str(run_json),),
        withheld=(str(run_json),),
        harness_root=str(base / "harness"),
    )
    return build_config(request, current_installation()), wt, run_json


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return tmp_path.resolve()


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_the_run_s_configuration_is_refused(base: Path, profile: str) -> None:
    config, wt, run_json = _session(base, profile)
    assert paths.protection(str(run_json), str(wt), config, writing=False) is not None
    assert paths.protection("../../run.json", str(wt), config, writing=False) is not None


@pytest.mark.parametrize("profile", PROFILES)
def test_a_shell_read_of_the_run_s_configuration_is_refused(base: Path, profile: str) -> None:
    config, wt, run_json = _session(base, profile)
    for command in (f"cat {run_json}", "grep canaries ../../run.json", "head -c 99 ../../run.json"):
        assert shell_paths.check(parse(command)[0], str(wt), config) is not None, command


@pytest.mark.parametrize("profile", PROFILES)
def test_the_os_layer_denies_every_read_of_the_run_s_configuration(
    base: Path, profile: str
) -> None:
    config, _, run_json = _session(base, profile)
    policy = sandbox_policy(config, home=str(base / "outside" / "home"), temp_dir="/tmp/pg-wh")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    assert any(str(run_json) == d or str(run_json).startswith(d.rstrip("/") + "/") for d in deny), (
        deny
    )


def test_every_role_session_is_installed_with_the_run_s_configuration_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_json = str(tmp_path / "run" / "run.json")
    for temp in (None, Path("/tmp/pg-0123456789ab")):
        argv = _install_argv(tmp_path, monkeypatch, temp=temp)
        assert _values(argv, "--withheld") == [run_json], argv
