"""The hook layer's own records of a session are read by no tool of that session.

The sentinel keeps, in the session's hook state directory, what it needs to put a protected path
back; beside it are the hooks' log and, in the api_key mode, the credential's helper. A session's
working directory lies beneath the run directory, and so does that state directory, so a file tool
could reach it by a path computed from the session's own home. So the state directory is refused
to every read: the file tools, a shell command, and the OS layer's sandbox. The hooks themselves
read and write it in their own processes, which run outside every tool call and outside the
sandbox.

Behind that, the sentinel keeps no byte of a file the session may not read (the held-out tier, a
withheld run record). Such a file is written by no session on any layer, so it never needs putting
back: a change to it is found by its digest, nothing is put back, and every later call is refused.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import paths, sentinel, shell_paths
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.shell import parse
from physgate.oslayer.policy import sandbox_policy

CANARY = "cd" * 16
#: The held-out stand-in's bytes: nothing else in the tree holds them.
HELD_BYTES = b"held-out stand-in 5c1e0b7a, scenario one\n"
#: An ordinary protected file's bytes, which a session may read: the sentinel still keeps them.
OPEN_BYTES = b"an ordinary protected file 9a41d2\n"
PROFILES = ("role", "baseline")
SESSION = "sess-1"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path.resolve()
    (base / "run" / "worktrees" / "s1").mkdir(parents=True)
    (base / "run" / "run.json").write_text('{"held_out_canaries": ["' + CANARY + '"]}\n')
    (base / "run" / "series").mkdir()
    (base / "run" / "series" / "sealed.json").write_bytes(OPEN_BYTES)
    (base / "tiers" / "v1").mkdir(parents=True)
    (base / "tiers" / "v1" / "scenario.json").write_bytes(HELD_BYTES)
    return base


def _config(root: Path, profile: str = "role") -> SessionConfig:
    return build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="electrical" if profile == "role" else None,
            worktree=str(root / "run" / "worktrees" / "s1"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "run" / "sessions" / SESSION / "state"),
            target_dir=str(root / "run" / "sessions" / SESSION / "session"),
            claude_config_dir=str(root / "run" / "sessions" / SESSION / "config"),
            user_home=str(root / "run" / "sessions" / SESSION / "home"),
            token_ceiling=1000,
            held_out=(str(root / "tiers" / "v1"),),
            extra_protected=(str(root / "run" / "run.json"), str(root / "run" / "series")),
            withheld=(str(root / "run" / "run.json"),),
        ),
        installation(),
    )


def _hook(root: Path, config: SessionConfig, event: str = "PreToolUse") -> str:
    """The sentinel's answer to one hook of the session: ``allow`` or the reason it refused."""
    hook_input = HookInput.model_validate(
        bash("true", cwd=config.worktree, session_id=SESSION) | {"hook_event_name": event}
    )
    decision = sentinel.check(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _started(root: Path, profile: str = "role") -> SessionConfig:
    """A session whose sentinel has taken its record, as at the session's first hook."""
    config = _config(root, profile)
    for d in ("session", "config", "home"):
        (root / "run" / "sessions" / SESSION / d).mkdir(parents=True, exist_ok=True)
    assert _hook(root, config, "SessionStart") == "allow"
    return config


def _state_files(config: SessionConfig) -> list[Path]:
    return sorted(p for p in Path(config.state_dir).rglob("*") if p.is_file())


def _packs(config: SessionConfig) -> list[Path]:
    return [p for p in _state_files(config) if p.name.startswith("pack-")]


@pytest.mark.parametrize("profile", PROFILES)
def test_a_file_tool_read_of_anything_in_the_state_directory_is_refused(
    root: Path, profile: str
) -> None:
    config = _started(root, profile)
    files = _state_files(config)
    # Not vacuous: the sentinel's record, its kept bytes and their index are there.
    assert _packs(config), files
    assert {"baseline.json", "index.json"} <= {p.name for p in files}, files
    wt = config.worktree
    for path in (*files, Path(config.state_dir)):
        assert paths.protection(str(path), wt, config, writing=False) is not None, path
        # As a session reaches it from its own working directory.
        relative = os.path.relpath(path, wt)
        assert paths.protection(relative, wt, config, writing=False) is not None, relative


@pytest.mark.parametrize("profile", PROFILES)
def test_a_shell_read_of_the_state_directory_is_refused(root: Path, profile: str) -> None:
    config = _started(root, profile)
    (pack, *_) = _packs(config)
    relative = os.path.relpath(pack, config.worktree)
    for command in (f"cat {pack}", f"head -c 99 {relative}", f"ls {config.state_dir}"):
        assert shell_paths.check(parse(command)[0], config.worktree, config) is not None, command


@pytest.mark.parametrize("profile", PROFILES)
def test_the_os_layer_denies_every_read_of_the_state_directory(root: Path, profile: str) -> None:
    config = _started(root, profile)
    (pack, *_) = _packs(config)
    home = str(root / "run" / "sessions" / SESSION / "home")
    policy = sandbox_policy(config, home=home, temp_dir="/tmp/pg-state")
    deny = policy.settings["sandbox"]["filesystem"]["denyRead"]
    allow = policy.settings["sandbox"]["filesystem"]["allowRead"]

    def covered(path: str, listed: list[str]) -> bool:
        return any(path == d or path.startswith(d.rstrip("/") + "/") for d in listed)

    assert covered(str(pack), deny), deny
    assert not covered(str(pack), allow), allow


@pytest.mark.parametrize("profile", PROFILES)
def test_the_sentinel_keeps_no_byte_of_a_file_the_session_may_not_read(
    root: Path, profile: str
) -> None:
    config = _started(root, profile)
    kept = b"".join(p.read_bytes() for p in _state_files(config))
    assert HELD_BYTES not in kept
    assert CANARY.encode() not in kept
    # The bytes of a protected file the session may read are kept still, to put it back.
    assert OPEN_BYTES in kept


@pytest.mark.parametrize("profile", PROFILES)
def test_a_withheld_record_that_changes_is_not_put_back_and_every_call_is_refused(
    root: Path, profile: str
) -> None:
    config = _started(root, profile)
    record = root / "run" / "run.json"
    record.write_text('{"held_out_canaries": []}\n')
    said = _hook(root, config)
    assert said != "allow"
    assert str(record) in said and "could not be put back" in said
    # Nothing was put back from anywhere: the sentinel holds no copy to put back.
    assert record.read_text() == '{"held_out_canaries": []}\n'
    assert _hook(root, config) != "allow", "a later call was allowed"


@pytest.mark.parametrize("profile", PROFILES)
def test_a_held_out_file_that_is_removed_is_not_put_back_and_every_call_is_refused(
    root: Path, profile: str
) -> None:
    config = _started(root, profile)
    held = root / "tiers" / "v1" / "scenario.json"
    held.unlink()
    said = _hook(root, config)
    assert said != "allow"
    assert str(held) in said and "could not be put back" in said
    assert not held.exists()


@pytest.mark.parametrize("profile", PROFILES)
def test_a_protected_file_the_session_may_read_is_still_put_back(root: Path, profile: str) -> None:
    config = _started(root, profile)
    sealed = root / "run" / "series" / "sealed.json"
    sealed.write_bytes(b"rewritten\n")
    said = _hook(root, config)
    assert said != "allow" and "put back" in said and "could not" not in said
    assert sealed.read_bytes() == OPEN_BYTES
    assert _hook(root, config) == "allow"
