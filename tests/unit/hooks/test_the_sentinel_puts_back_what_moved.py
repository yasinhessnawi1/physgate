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
from hook_helpers import SESSION, bash, make_store, node

from physgate.hooks import sentinel
from physgate.hooks.config import HookInput, ProtectedRoot, SessionConfig
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
    "outside/home/.claude/settings.json": "{}\n",
}
GATE = "worktree/src/physgate/gate"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for rel, content in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    make_store(tmp_path / "store")
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
    original = journal.read_bytes()
    journal.write_bytes(original + b'{"not": "a record"}\n')
    assert _check(root) == "allow", "an append is the orchestrator's, or the store's guard's"
    appended = journal.read_bytes()
    journal.write_bytes(b"x" + appended[1:])
    assert "journal.jsonl" in _check(root)
    assert journal.read_bytes() == appended
    journal.write_bytes(b"")
    assert "journal.jsonl" in _check(root)
    assert journal.read_bytes() == appended


def test_user_settings_are_logged_not_reverted(root: Path) -> None:
    _started(root)
    user = root / "outside" / "home" / ".claude" / "settings.json"
    user.write_text('{"hooks": {}}\n')
    assert _check(root) == "allow"
    assert user.read_text() == '{"hooks": {}}\n'
    (logged,) = [e for e in _log(root) if e["decision"] == "changed"]
    assert logged["paths"] == [str(user)]
    # The record advances, so the same change is not reported on every later call.
    assert _check(root) == "allow"
    assert len([e for e in _log(root) if e["decision"] == "changed"]) == 1


NODE = "store/nodes/electrical.motor.json"


def test_a_node_file_that_differs_from_the_journal_halts_and_nothing_is_written(
    root: Path,
) -> None:
    _started(root)
    tampered = (root / NODE).read_bytes().replace(b"2.4", b"9.9")
    (root / NODE).write_bytes(tampered)
    told = _check(root)
    assert "does not hold what the journal says" in told
    assert (root / NODE).read_bytes() == tampered, "the sentinel must write nothing to the store"
    assert "does not hold what the journal says" in _check(root, name="PreToolUse")
    (logged,) = [e for e in _log(root) if e["decision"] == "node mismatch"]
    assert logged["paths"] == [str(root / NODE)]


def test_a_node_file_the_journal_never_named_halts(root: Path) -> None:
    _started(root)
    (root / "store" / "nodes" / "electrical.planted.json").write_text("{}\n")
    assert "electrical.planted.json" in _check(root)


def test_the_orchestrators_legitimate_write_is_not_a_finding(root: Path) -> None:
    _started(root)
    make_store(root / "store", node(quantities={}))
    assert _check(root) == "allow"


def test_a_check_inside_the_orchestrators_write_window_is_not_a_finding(root: Path) -> None:
    # The store appends the journal line, then writes the node file. A check
    # landing between the two sees a file that matches the previous revision
    # and a journal that is newer than the last check saw.
    _started(root)
    before = (root / NODE).read_bytes()
    make_store(root / "store", node(quantities={}))
    after = (root / NODE).read_bytes()
    assert after != before
    (root / NODE).write_bytes(before)  # the file as it stood before the store wrote it
    assert _check(root) == "allow", "the journal is newer than the record: a write in progress"
    (root / NODE).write_bytes(after)  # the store finishes its write
    assert _check(root) == "allow"


def test_a_file_left_behind_after_the_window_closed_is_a_finding(root: Path) -> None:
    # The window excuses a file only while its node's newest line is newer than
    # the last check. Once the check has seen that line, a stale file is stale.
    _started(root)
    before = (root / NODE).read_bytes()
    make_store(root / "store", node(quantities={}))
    (root / NODE).write_bytes(before)
    assert _check(root) == "allow"
    os.utime(root / NODE)
    assert "does not hold what the journal says" in _check(root)


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


def test_loaded_code_is_found_as_if_every_file_were_resolved_whole(
    root: Path, tmp_path: Path
) -> None:
    # The sentinel resolves each directory once rather than each file. That must
    # name the same files, including a module that is itself a link and one
    # reached through a linked directory, both pointing into the watched code.
    code = tmp_path / "hookcode"
    (code / "real").mkdir(parents=True)
    (code / "real" / "sentinel_probe_direct.py").write_text("VALUE = 1\n")
    (code / "real" / "sentinel_probe_target.py").write_text("VALUE = 2\n")
    (code / "real" / "sentinel_probe_through.py").write_text("VALUE = 3\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "sentinel_probe_link.py").symlink_to(code / "real" / "sentinel_probe_target.py")
    (tmp_path / "linked-dir").symlink_to(code / "real")
    names = ("sentinel_probe_direct", "sentinel_probe_link", "sentinel_probe_through")
    for entry in (code / "real", elsewhere, tmp_path / "linked-dir"):
        sys.path.insert(0, str(entry))
    try:
        importlib.import_module("sentinel_probe_direct")
        importlib.import_module("sentinel_probe_link")
        sys.path.remove(str(code / "real"))
        importlib.invalidate_caches()
        importlib.import_module("sentinel_probe_through")
        assert "linked-dir" in str(sys.modules["sentinel_probe_through"].__file__)
        config = _config(root)
        config = config.model_copy(
            update={
                "protected_roots": (
                    *config.protected_roots,
                    ProtectedRoot(path=str(code), reason="hook code", watch="halt"),
                )
            }
        )
        found = set(sentinel._loaded_code(config))
        halt_roots = [os.path.realpath(r.path) for r in config.protected_roots if r.watch == "halt"]
        files = [getattr(m, "__file__", None) for m in list(sys.modules.values())]
        whole = {os.path.realpath(sys.executable)} | {os.path.realpath(f) for f in files if f}
        expected = {
            f for f in whole if any(f == r or f.startswith(r.rstrip("/") + "/") for r in halt_roots)
        }
        assert expected <= found
        assert found - expected == {f for f in found if f.endswith(".pth")}
        real = os.path.realpath(code / "real")
        for name in ("direct", "target", "through"):
            assert os.path.join(real, f"sentinel_probe_{name}.py") in found
    finally:
        for entry in (code / "real", elsewhere, tmp_path / "linked-dir"):
            if str(entry) in sys.path:
                sys.path.remove(str(entry))
        for name in names:
            sys.modules.pop(name, None)


def _sentinel_dir(root: Path) -> Path:
    return root / "outside" / "state" / "sessions" / SESSION / "sentinel"


def test_the_first_record_keeps_every_byte_in_one_pack_and_an_index(root: Path) -> None:
    # One file per protected file cost the first hook a create and a rename
    # apiece; on a network filesystem that alone was over the hook's budget.
    _started(root)
    blobs = _sentinel_dir(root) / "blobs"
    packs = sorted(p.name for p in blobs.iterdir() if p.name.startswith("pack-"))
    index = json.loads((blobs / "index.json").read_text())
    assert len(index) >= 5
    # The protected trees in one pack, the graph journal in a second.
    assert len(packs) == 2
    assert {entry[0] for entry in index.values()} == set(packs)
    assert sorted(p.name for p in blobs.iterdir()) == sorted([*packs, "index.json"])


def test_kept_bytes_that_no_longer_match_their_digest_are_never_put_back(root: Path) -> None:
    _started(root)
    blobs = _sentinel_dir(root) / "blobs"
    for pack in blobs.glob("pack-*"):
        data = bytearray(pack.read_bytes())
        data[:] = bytes(len(data))
        pack.write_bytes(bytes(data))
    (root / GATE / "check.py").write_text("CHECK = False\n")
    with pytest.raises(OSError, match="do not match"):
        _check(root)
    assert (root / GATE / "check.py").read_text() == "CHECK = False\n"


def test_the_interpreter_is_recorded_by_signature_and_any_move_of_it_halts(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code = tmp_path / "interp"
    code.mkdir()
    binary = code / "python3.12"
    binary.write_bytes(b"\x7fELF not really an interpreter\n")
    monkeypatch.setattr(sys, "executable", str(binary))
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
    base = json.loads((_sentinel_dir(root) / "baseline.json").read_text())
    sig, digest = base["halt"][os.path.realpath(binary)]
    assert digest is None
    assert _check(root, config) == "allow"
    # The same bytes, touched: there is no digest to excuse it, so it is a change.
    os.utime(binary, ns=(1, 1))
    assert "every call is refused" in _check(root, config)


def test_every_append_to_the_journal_is_recorded_with_its_call_and_byte_range(
    root: Path,
) -> None:
    # An append cannot be told from the orchestrator's own here, so it is let
    # through, and it is recorded: the call it was seen after, the profile and
    # the exact bytes, for the orchestrator to match against its own writes.
    _started(root)
    journal = root / "store" / "journal.jsonl"
    before = journal.stat().st_size
    extra = b'{"rev": 99}\n'
    with journal.open("ab") as handle:
        handle.write(extra)
    assert _check(root) == "allow"
    (event_,) = [e for e in _log(root) if e.get("decision") == "journal append"]
    assert event_["paths"] == [str(journal)]
    assert event_["bytes"] == [before, before + len(extra)]
    assert (event_["tool"], event_["profile"], event_["role"]) == ("Bash", "role", "electrical")
    assert event_["tool_input"] == {"command": "x", "description": "x"}
    # Seen once: the next call has nothing new to record.
    assert _check(root) == "allow"
    assert len([e for e in _log(root) if e.get("decision") == "journal append"]) == 1
