"""The sentinel keeps what names a protected task apart from the session's own directory.

At a session's first hook the sentinel records every entry beneath its protected roots, those
beneath the roots no session reads (the held-out tier, the answer keys, the run's withheld
records) among them: each by its path, so a protected task's directory, which is its id, and
each file with its digest. A role session's own directory is kept from every session of its run,
but it can lie later where people and other sessions read. So where the session's configuration
names a place apart (the run's own, refused to every read and write of every layer), the part of
the record that names those entries is kept there, and the record in the session's own hook state
holds no protected path, file name or content digest. Every check reads both parts and catches
what it caught before; a part apart that is gone, or a record that holds it whole where a place
apart is named, refuses. A configuration that names no place, as one installed before the place
existed, keeps the record whole, as it always did.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from hook_helpers import SESSION, bash

from physgate.hooks import paths, sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

#: A protected task's id, its file's name and its bytes: nothing else in the rig holds them.
TASK_ID = "control.held-out-stand-in-5c1d7e"
FILE_NAME = "brief-9a2b4f.json"
BYTES = b'{"stand-in": "a held-out brief"}\n'
DIGEST = hashlib.sha256(BYTES).hexdigest()


@pytest.fixture
def root(tmp_path: Path) -> Path:
    task = tmp_path / "heldout" / TASK_ID
    task.mkdir(parents=True)
    (task / FILE_NAME).write_bytes(BYTES)
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / "README.md").write_text("readme\n")
    (tmp_path / "apart").mkdir()
    return tmp_path


def _fields(root: Path) -> dict[str, object]:
    return {
        "profile": "role",
        "role": "electrical",
        "worktree": str(root / "worktree"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(root / "outside" / "state"),
        "target_dir": str(root / "outside" / "session"),
        "claude_config_dir": str(root / "outside" / "cfg"),
        "user_home": str(root / "outside" / "home"),
        "token_ceiling": 1000,
        "held_out": (str(root / "heldout"),),
    }


def _apart_named() -> None:
    assert "sentinel_apart" in InstallRequest.model_fields, (
        "the installer names no place apart for the sentinel's record of the protected paths"
    )


def _config(root: Path, *, apart: bool = True, **changes: object) -> SessionConfig:
    fields = _fields(root) | changes
    if apart:
        _apart_named()
        fields.setdefault("sentinel_apart", str(root / "apart"))
    return build_config(InstallRequest(**fields), installation())  # type: ignore[arg-type]


def _check(root: Path, name: str = "PostToolUse", config: SessionConfig | None = None) -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=str(root / "worktree")) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, config or _config(root))
    return "allow" if decision.allow else decision.reason


def _holders(where: Path) -> list[str]:
    """Every file under ``where`` that names the protected task, its file or its digest."""
    found = []
    for path in sorted(where.rglob("*")):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if any(m.encode() in data for m in (TASK_ID, FILE_NAME, DIGEST)):
                found.append(str(path))
        if any(m in path.name for m in (TASK_ID, FILE_NAME)):
            found.append(str(path))
    return found


def _main(root: Path) -> Path:
    return root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "baseline.json"


def test_the_session_s_own_directory_names_no_protected_task_and_the_place_apart_does(
    root: Path,
) -> None:
    assert _check(root, "SessionStart") == "allow"
    assert _check(root) == "allow"
    assert _check(root, "SessionEnd") == "allow"
    assert _main(root).is_file(), "the sentinel took no record"
    assert _holders(root / "outside") == [], "the session's own directory names a protected task"
    # Not vacuous: the entries were recorded, apart.
    held = _holders(root / "apart")
    assert held, "the protected entries were recorded nowhere"
    assert all(Path(p).parent == root / "apart" for p in held), held
    record = json.loads(Path(held[0]).read_text())
    assert any(TASK_ID in p for p in record["revert"]), record.keys()


def test_a_changed_protected_file_is_still_caught_and_refuses_every_later_call(
    root: Path,
) -> None:
    assert _check(root, "SessionStart") == "allow"
    (root / "heldout" / TASK_ID / FILE_NAME).write_bytes(b"changed\n")
    reason = _check(root, "SessionEnd")
    assert "could not be put back" in reason, reason
    assert _check(root) == reason


def test_a_protected_directory_s_mode_is_put_back_from_the_place_apart(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    task = root / "heldout" / TASK_ID
    was = task.stat().st_mode & 0o777
    task.chmod(0o700 if was != 0o700 else 0o755)
    reason = _check(root)
    assert "were put back" in reason and TASK_ID in reason, reason
    assert task.stat().st_mode & 0o777 == was


def test_a_part_apart_that_is_gone_refuses(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    (kept,) = (root / "apart").iterdir()
    kept.unlink()
    with pytest.raises(OSError):  # the hook runtime makes every failure a refusal
        _check(root)


def test_a_record_held_whole_where_a_place_apart_is_named_refuses(root: Path) -> None:
    # Taken as a session installed with no place apart takes it: whole.
    assert _check(root, "SessionStart", _config(root, apart=False)) == "allow"
    assert TASK_ID in _main(root).read_text()
    with pytest.raises(ValueError, match="whole"):
        _check(root)


def test_a_configuration_that_names_no_place_keeps_the_record_whole_as_before(root: Path) -> None:
    config = _config(root, apart=False)
    assert _check(root, "SessionStart", config) == "allow"
    base = json.loads(_main(root).read_text())
    assert any(TASK_ID in p for p in base["sealed"]), base["sealed"]
    assert any(TASK_ID in p for p in base["revert"])
    (root / "heldout" / TASK_ID / FILE_NAME).write_bytes(b"changed\n")
    assert "could not be put back" in _check(root, "SessionEnd", config)


def test_the_place_apart_is_refused_to_every_read_and_write_and_never_put_back(
    root: Path,
) -> None:
    config = _config(root)
    (found,) = [r for r in config.protected_roots if r.path == str(root / "apart")]
    assert found.reads == "denied"
    assert found.watch == "none"
    assert paths.read_refused(str(root / "apart" / f"{SESSION}.json"), config)


@pytest.mark.parametrize(
    "inside", ["worktree", "outside/home", "outside/state", "outside/session", "outside/cfg"]
)
def test_a_place_apart_inside_the_session_s_own_places_is_refused(root: Path, inside: str) -> None:
    _apart_named()
    place = root / inside / "apart"
    with pytest.raises(ValueError, match="apart"):
        _config(root, sentinel_apart=str(place))


def test_a_place_apart_that_holds_the_session_s_own_directory_is_refused(root: Path) -> None:
    _apart_named()
    with pytest.raises(ValueError, match="apart"):
        _config(root, sentinel_apart=str(root / "outside"))


def test_the_session_s_id_names_its_part_apart(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    assert os.listdir(root / "apart") == [f"{SESSION}.json"]


def test_a_record_kept_apart_read_where_no_place_apart_is_named_refuses(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    with pytest.raises(ValueError, match="no place apart"):
        _check(root, config=_config(root, apart=False))


def test_a_record_that_no_longer_says_it_is_kept_apart_refuses(root: Path) -> None:
    assert _check(root, "SessionStart") == "allow"
    record = json.loads(_main(root).read_text())
    assert record.pop("kept_apart") is True
    _main(root).write_text(json.dumps(record, sort_keys=True))
    with pytest.raises(ValueError, match="whole"):
        _check(root)


def test_two_places_apart_refuse(root: Path) -> None:
    config = _config(root)
    (found,) = [r for r in config.protected_roots if r.path == str(root / "apart")]
    second = found.model_copy(update={"path": str(root / "apart-too")})
    doubled = config.model_copy(update={"protected_roots": (*config.protected_roots, second)})
    with pytest.raises(ValueError, match="more than one place apart"):
        _check(root, "SessionStart", doubled)


@pytest.mark.parametrize("tool", ["Read", "Write"])
def test_no_file_tool_of_the_session_reaches_the_place_apart(root: Path, tool: str) -> None:
    key = "file_path"
    target = str(root / "apart" / f"{SESSION}.json")
    hook_input = HookInput.model_validate(
        {
            "session_id": SESSION,
            "cwd": str(root / "worktree"),
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {key: target, "content": "x"},
        }
    )
    decision = paths.pre_tool_use(hook_input, _config(root))
    assert not decision.allow
    assert "protected paths" in decision.reason or "no session reads" in decision.reason
