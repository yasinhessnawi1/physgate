"""The sentinel compares every protected path at every hook and puts back what moved.

Each attack below was measured against the stat signature when the design was
chosen; here each one is made against a real protected tree and the tree is
checked byte for byte afterwards.
"""

from __future__ import annotations

import fcntl
import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from hook_helpers import SESSION, bash

from physgate.hooks import sentinel
from physgate.hooks.config import ProtectedRoot, SessionConfig
from physgate.hooks.runtime import HookInput
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.state import LOG_NAME

FILES = {
    "worktree/src/physgate/gate/check.py": "CHECK = True\n",
    "worktree/src/physgate/gate/bounds/table.csv": "a,1\n",
    "worktree/src/physgate/electrical/driver.py": "x = 1\n",
    "worktree/experiments/R-OP-01/RESULT.md": "result\n",
    "worktree/experiments/R-OP-01/src/store.py": "measured code\n",
    "worktree/experiments/R-NEW-01/CRITERIA.md": "criteria\n",
    "worktree/experiments/R-NEW-01/notes.md": "notes\n",
    "store/journal.jsonl": '{"rev":1}\n',
    "store/nodes/electrical.motor.json": "{}\n",
    "outside/home/.claude/settings.json": "{}\n",
}
GATE = "worktree/src/physgate/gate"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for rel, content in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def _config(root: Path) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(root / "worktree"),
            own_branch=None,
            store_root=str(root / "store"),
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
        ),
        installation(),
    )


def _check(root: Path, config: SessionConfig | None = None, name: str = "PostToolUse") -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=str(root / "worktree")) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, config or _config(root))
    return "allow" if decision.allow else decision.reason


def _log(root: Path) -> list[dict[str, object]]:
    path = root / "outside" / "state" / LOG_NAME
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def _quarantine(root: Path) -> list[str]:
    q = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "quarantine"
    return sorted(p.name for p in q.iterdir()) if q.exists() else []


def _started(root: Path) -> None:
    assert _check(root, name="SessionStart") == "allow"


def test_nothing_changed_nothing_happens(root: Path) -> None:
    _started(root)
    assert _check(root) == "allow"
    assert _check(root, name="PreToolUse") == "allow"
    assert _log(root) == []


def test_the_first_hook_takes_the_record_when_session_start_never_ran(root: Path) -> None:
    assert _check(root, name="PreToolUse") == "allow"
    (root / GATE / "check.py").write_text("CHECK = False\n")
    assert "put back" in _check(root)
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"


def test_a_modified_gate_file_is_put_back_and_the_call_refused(root: Path) -> None:
    _started(root)
    (root / GATE / "check.py").write_text("CHECK = False\n")
    told = _check(root)
    assert "put back" in told and "check.py" in told
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"
    (event_,) = [e for e in _log(root) if e["hook"] == "sentinel"]
    assert event_["decision"] == "put back" and event_["profile"] == "role"


def test_a_write_that_restores_the_modification_time_is_still_caught(root: Path) -> None:
    _started(root)
    target = root / GATE / "check.py"
    before = os.stat(target)
    target.write_text("CHECK = Fals\n")  # same length
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert "put back" in _check(root)
    assert target.read_text() == "CHECK = True\n"


def test_a_new_file_is_moved_aside_not_deleted(root: Path) -> None:
    _started(root)
    (root / GATE / "planted.py").write_text("PASS = True\n")
    (root / GATE / "newdir" / "deep").mkdir(parents=True)
    (root / GATE / "newdir" / "deep" / "x.py").write_text("x\n")
    assert "put back" in _check(root)
    assert sorted(p.name for p in (root / GATE).iterdir()) == ["bounds", "check.py"]
    kept = _quarantine(root)
    assert any(n.endswith("planted.py") for n in kept) and any(n.endswith("newdir") for n in kept)
    q = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "quarantine"
    (planted,) = [p for p in q.iterdir() if p.name.endswith("planted.py")]
    assert planted.read_text() == "PASS = True\n"


def test_a_second_plant_of_the_same_name_does_not_overwrite_the_first(root: Path) -> None:
    _started(root)
    for content in ("first\n", "second\n"):
        (root / GATE / "planted.py").write_text(content)
        assert "put back" in _check(root)
    q = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "quarantine"
    assert sorted(p.read_text() for p in q.iterdir()) == ["first\n", "second\n"]


def test_a_deleted_tree_is_put_back(root: Path) -> None:
    _started(root)
    (root / GATE / "bounds" / "table.csv").unlink()
    (root / GATE / "bounds").rmdir()
    (root / GATE / "check.py").unlink()
    assert "put back" in _check(root)
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"
    assert (root / GATE / "bounds" / "table.csv").read_text() == "a,1\n"


def test_a_file_swapped_for_a_symlink_to_identical_bytes_is_put_back(root: Path) -> None:
    _started(root)
    decoy = root / "decoy.py"
    decoy.write_text("CHECK = True\n")
    (root / GATE / "check.py").unlink()
    (root / GATE / "check.py").symlink_to(decoy)
    assert "put back" in _check(root)
    assert not (root / GATE / "check.py").is_symlink()
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"


def test_the_gate_directory_swapped_for_a_symlink_is_put_back(root: Path) -> None:
    _started(root)
    copy = root / "copy"
    (root / GATE).rename(copy)
    (root / GATE).symlink_to(copy)
    assert "put back" in _check(root)
    assert (root / GATE).is_dir() and not (root / GATE).is_symlink()
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"


def test_a_mode_change_is_put_back(root: Path) -> None:
    _started(root)
    target = root / GATE / "check.py"
    mode = os.stat(target).st_mode & 0o777
    os.chmod(target, 0o777)
    assert "put back" in _check(root)
    assert os.stat(target).st_mode & 0o777 == mode


def test_a_hard_link_alias_is_broken_by_the_revert(root: Path) -> None:
    _started(root)
    alias = root / "alias.py"
    os.link(root / GATE / "check.py", alias)
    alias.write_text("CHECK = False\n")
    assert "put back" in _check(root)
    alias.write_text("CHECK = False, again\n")
    assert (root / GATE / "check.py").read_text() == "CHECK = True\n"


def test_a_touch_that_changes_no_bytes_is_not_a_change(root: Path) -> None:
    _started(root)
    os.utime(root / GATE / "check.py")
    assert _check(root) == "allow"


def test_frozen_experiment_files_are_put_back_and_the_rest_is_not(root: Path) -> None:
    _started(root)
    exp = root / "worktree" / "experiments"
    (exp / "R-OP-01" / "src" / "store.py").write_text("changed\n")
    (exp / "R-NEW-01" / "CRITERIA.md").write_text("moved threshold\n")
    (exp / "R-NEW-01" / "notes.md").write_text("more notes\n")
    told = _check(root)
    assert "store.py" in told and "CRITERIA.md" in told and "notes.md" not in told
    assert (exp / "R-OP-01" / "src" / "store.py").read_text() == "measured code\n"
    assert (exp / "R-NEW-01" / "CRITERIA.md").read_text() == "criteria\n"
    assert (exp / "R-NEW-01" / "notes.md").read_text() == "more notes\n"


def test_a_settings_file_planted_in_the_worktree_is_moved_aside(root: Path) -> None:
    _started(root)
    claude = root / "worktree" / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text('{"disableAllHooks": true}')
    assert "put back" in _check(root)
    assert not claude.exists()


def test_an_append_to_the_journal_is_left_to_the_store_and_a_rewrite_is_put_back(
    root: Path,
) -> None:
    _started(root)
    journal = root / "store" / "journal.jsonl"
    journal.write_text('{"rev":1}\n{"rev":2}\n')
    assert _check(root) == "allow", "an append is the orchestrator's, or the store's guard's"
    journal.write_text('{"rev":9}\n{"rev":2}\n')
    assert "journal.jsonl" in _check(root)
    assert journal.read_text() == '{"rev":1}\n{"rev":2}\n'
    journal.write_text("")
    assert "journal.jsonl" in _check(root)
    assert journal.read_text() == '{"rev":1}\n{"rev":2}\n'


def test_node_files_and_user_settings_are_logged_not_reverted(root: Path) -> None:
    _started(root)
    node = root / "store" / "nodes" / "electrical.motor.json"
    node.write_text('{"changed": true}\n')
    user = root / "outside" / "home" / ".claude" / "settings.json"
    user.write_text('{"hooks": {}}\n')
    assert _check(root) == "allow"
    assert node.read_text() == '{"changed": true}\n'
    (logged,) = [e for e in _log(root) if e["decision"] == "changed"]
    assert str(node) in logged["paths"] and str(user) in logged["paths"]  # type: ignore[operator]
    # The record advances, so the same change is not reported on every later call.
    assert _check(root) == "allow"
    assert len([e for e in _log(root) if e["decision"] == "changed"]) == 1


def test_the_sentinel_runs_on_every_event_including_a_failed_call() -> None:
    # A command that exits non-zero fires the failure event and not the ordinary
    # one (measured), so a sentinel wired only to the ordinary one would never
    # see the write a failing command made.
    assert set(sentinel.HOOK.handlers) == {
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "Stop",
        "SessionEnd",
    }


def test_the_record_is_read_and_written_under_an_exclusive_lock(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Tool calls can run in parallel, and so can their hooks. The property is
    # asserted by the call rather than by racing two threads, because a race
    # that happens not to collide proves nothing about the lock.
    order: list[str] = []
    real_flock = fcntl.flock
    real_load = sentinel._State.load

    def flock(fd: int, op: int) -> None:
        order.append("lock" if op == fcntl.LOCK_EX else "unlock")
        real_flock(fd, op)

    def load(self: sentinel._State) -> dict[str, object] | None:
        order.append("load")
        return real_load(self)

    monkeypatch.setattr(fcntl, "flock", flock)
    monkeypatch.setattr(sentinel._State, "load", load)
    _started(root)
    assert order == ["lock", "load", "unlock"]


def test_changed_hook_code_halts_the_session_for_good(root: Path, tmp_path: Path) -> None:
    code = tmp_path / "hookcode"
    code.mkdir()
    (code / "sentinel_probe_module.py").write_text("VALUE = 1\n")
    sys.path.insert(0, str(code))
    try:
        importlib.import_module("sentinel_probe_module")
        config = _config(root)
        config = config.model_copy(
            update={
                "protected_roots": (
                    *config.protected_roots,
                    ProtectedRoot(path=str(code), reason="hook code", watch="halt"),
                )
            }
        )
        assert _check(root, config, "SessionStart") == "allow"
        (code / "sentinel_probe_module.py").write_text("VALUE = 2  # tampered\n")
        assert "every call is refused" in _check(root, config)
        (code / "sentinel_probe_module.py").write_text("VALUE = 1\n")
        assert "every call is refused" in _check(root, config, "PreToolUse")
    finally:
        sys.path.remove(str(code))
        sys.modules.pop("sentinel_probe_module", None)


def test_the_record_holds_the_hook_code_actually_loaded(root: Path) -> None:
    _started(root)
    base = json.loads(
        (
            root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "baseline.json"
        ).read_text()
    )
    loaded = set(base["halt"])
    assert any(p.endswith("physgate/hooks/sentinel.py") for p in loaded)
    assert any("/pydantic/" in p for p in loaded)
    assert os.path.realpath(sys.executable) in loaded
