"""A hard link to a run's records: refused in a run root withheld whole, as before in the worktree.

A file of a run's ``decomposition/`` carries what its plan was written from, and a hard link to it
is a second name for the same bytes. The tripwire holds withheld files, not that directory (the
harness keeps a link there), so a second name made elsewhere was read past the denial wherever no
other root covered it: in an earlier run's directory beside the session's own, nothing did. With
the run root withheld whole, by rule, a second name anywhere in it but the worktree is refused to
every route. Inside the worktree a Read of a second name for a file of the run's records is
refused, as it was (now by the root the file lies in, matched first); a shell reads it there by
its path, as it did, where the OS layer opens the worktree: unchanged, and no worse. Nor is the
tripwire asked more: a root withheld whole is not one it walks.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.hooks import paths, shell_paths, withheld
from physgate.hooks.config import SessionConfig
from physgate.hooks.paths import HARD_LINKED_READ
from physgate.hooks.reasons import WITHHELD_WHOLE_REASON
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.shell import parse


@pytest.fixture
def rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    run = root / "runs" / "run-b"
    for d in ("worktrees/m1", "decomposition/round-1", "sessions/s1/home", "sessions/s1/state"):
        (run / d).mkdir(parents=True)
    for d in ("session", "config"):
        (run / "sessions" / "s1" / d).mkdir()
    (run / "decomposition" / "round-1" / "plan.json").write_text("written from the brief\n")
    earlier = root / "runs" / "run-a" / "decomposition"
    earlier.mkdir(parents=True)
    (earlier / "plan.json").write_text("an earlier run's plan, from its brief\n")
    return root


def _config(root: Path, *, whole: bool) -> SessionConfig:
    run = root / "runs" / "run-b"
    sdir = run / "sessions" / "s1"
    fields: dict[str, object] = {
        "profile": "role",
        "role": "control",
        "worktree": str(run / "worktrees" / "m1"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sdir / "state"),
        "target_dir": str(sdir / "session"),
        "claude_config_dir": str(sdir / "config"),
        "user_home": str(sdir / "home"),
        "token_ceiling": 1000,
        "sessions_root": str(run / "sessions"),
        "withheld": (str(run / "decomposition"),),
        "temp_dir": str(root / "temps" / "own"),
        "session_temps": str(root / "temps"),
        "shared_claude_temp": (str(root / "claude-temp"),),
    }
    if whole:
        fields |= {"withheld_whole": (str(root / "runs"),), "own_place": str(run)}
    return build_config(InstallRequest(**fields), installation())  # type: ignore[arg-type]


def _reads(config: SessionConfig, target: Path) -> bool:
    by_tool = paths.protection(str(target), config.worktree, config, writing=False) is None
    by_shell = not shell_paths.check(parse(f"cat {target}")[0], config.worktree, config)
    return by_tool or by_shell


def test_a_second_name_in_an_earlier_run_beside_the_session_s_own_is_refused(rig: Path) -> None:
    plan = rig / "runs" / "run-b" / "decomposition" / "round-1" / "plan.json"
    second = rig / "runs" / "run-a" / "plan-again.json"
    os.link(plan, second)
    # Without the run root withheld whole, nothing covers the earlier run's directory.
    assert _reads(_config(rig, whole=False), second)
    assert not _reads(_config(rig, whole=True), second)


def test_an_earlier_run_s_own_plan_is_refused(rig: Path) -> None:
    earlier = rig / "runs" / "run-a" / "decomposition" / "plan.json"
    assert _reads(_config(rig, whole=False), earlier)
    assert not _reads(_config(rig, whole=True), earlier)


@pytest.mark.parametrize("whole", [False, True], ids=["before", "with the root withheld whole"])
def test_a_second_name_inside_the_worktree_is_refused_to_a_read_as_before(
    rig: Path, whole: bool
) -> None:
    plan = rig / "runs" / "run-b" / "decomposition" / "round-1" / "plan.json"
    second = rig / "runs" / "run-b" / "worktrees" / "m1" / "notes.json"
    os.link(plan, second)
    config = _config(rig, whole=whole)
    reason = paths.protection(str(second), config.worktree, config, writing=False)
    # Refused as a second name before; with the root withheld whole the name is matched to the
    # file it names, which lies in the root, and refused by that root first.
    assert reason == (WITHHELD_WHOLE_REASON if whole else HARD_LINKED_READ), reason


def test_the_tripwire_walks_no_root_withheld_whole(rig: Path) -> None:
    before = withheld.roots_of(_config(rig, whole=False))
    after = withheld.roots_of(_config(rig, whole=True))
    assert after == before and str(rig / "runs") not in after, after
