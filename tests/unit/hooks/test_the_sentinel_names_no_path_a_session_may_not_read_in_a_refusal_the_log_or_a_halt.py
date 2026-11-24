"""The sentinel names no path a session may not read in a refusal, its log or a halt it keeps.

When the sentinel finds a protected entry changed, or a held-out or answer-key file with a second
name, it refuses the call, writes a line to the hook log, and keeps the halt in the session's own
record, which every later call returns. The refusal goes to the session; the log and the record
lie in the session's own directory, which can lie later where people and other sessions read. So
a path no tool of the session may read (a held-out task's directory is its id), or one beneath a
held-out or answer-key root, is named in none of them: each is given a label in its place, the
kind of protection and a digest of the path keyed by a key the session cannot read, the same for
one path on every call. Two entries are told apart by their labels; what the sentinel found
(gone, a second name, its count) is kept as it was. The operator finds the path from the key and
the record the sentinel keeps apart. A path the session may read is named as before.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from hook_helpers import SESSION, bash

from physgate.hooks import sentinel
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation
from physgate.hooks.state import LOG_NAME

TASK_ID = "control.held-out-stand-in-8d2e41"
OTHER_ID = "control.held-out-stand-in-1b7f03"
FILE_NAME = "brief-4c9e0d.json"
BYTES = b'{"stand-in": "a held-out brief"}\n'
DIGEST = hashlib.sha256(BYTES).hexdigest()
#: What a label looks like: the kind of protection, then twelve hex digits.
LABEL = re.compile(r"held-out entry [0-9a-f]{12}")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for task in (TASK_ID, OTHER_ID):
        (tmp_path / "heldout" / task).mkdir(parents=True)
        (tmp_path / "heldout" / task / FILE_NAME).write_bytes(BYTES)
    (tmp_path / "worktree" / ".claude").mkdir(parents=True)
    (tmp_path / "worktree" / ".claude" / "settings.json").write_text("{}\n")
    (tmp_path / "apart").mkdir(mode=0o700)
    (tmp_path / "apart").chmod(0o700)
    return tmp_path


def _config(root: Path, *, apart: bool = True) -> SessionConfig:
    fields: dict[str, object] = {
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
    if apart:
        fields["sentinel_apart"] = str(root / "apart")
    return build_config(InstallRequest(**fields), installation())  # type: ignore[arg-type]


def _check(root: Path, config: SessionConfig, name: str = "PostToolUse") -> str:
    hook_input = HookInput.model_validate(
        bash("x", cwd=str(root / "worktree")) | {"hook_event_name": name}
    )
    decision = sentinel.check(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _needles(root: Path) -> tuple[str, ...]:
    """What says where the protected material is: its root, a task's id, a file's name, a digest."""
    return (str(root / "heldout"), TASK_ID, OTHER_ID, FILE_NAME, DIGEST)


def _named(text: str, root: Path) -> list[str]:
    return [n for n in _needles(root) if n in text]


def _log(root: Path) -> str:
    path = root / "outside" / "state" / LOG_NAME
    return path.read_text() if path.exists() else ""


def _halt(root: Path) -> str:
    record = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "baseline.json"
    return str(json.loads(record.read_text()).get("halted") or "")


def _held_to_labels(root: Path, reason: str) -> None:
    assert reason != "allow", "nothing was refused"
    assert _named(reason, root) == [], (
        f"the refusal names where the protected material is: {reason}"
    )
    assert LABEL.search(reason), f"the refusal says nothing an operator can find: {reason}"
    log = _log(root)
    assert log, "the sentinel logged nothing"
    assert _named(log, root) == [], f"the hook log names where the protected material is: {log}"
    assert LABEL.search(log), log


@pytest.mark.parametrize("apart", [True, False], ids=["place-apart", "no-place-apart"])
def test_a_changed_held_out_file_is_refused_with_no_path_in_the_refusal_the_log_or_the_halt(
    root: Path, apart: bool
) -> None:
    config = _config(root, apart=apart)
    assert _check(root, config, "SessionStart") == "allow"
    (root / "heldout" / TASK_ID / FILE_NAME).write_bytes(b"changed\n")
    reason = _check(root, config)
    assert "could not be put back" in reason, reason
    _held_to_labels(root, reason)
    assert _named(_halt(root), root) == [], _halt(root)
    # The halt kept, and returned on every later call, word for word.
    assert _check(root, config) == reason


def test_a_held_out_directory_put_back_is_named_by_its_label(root: Path) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    task = root / "heldout" / TASK_ID
    was = task.stat().st_mode & 0o777
    task.chmod(0o700 if was != 0o700 else 0o755)
    reason = _check(root, config)
    assert "were put back" in reason, reason
    assert task.stat().st_mode & 0o777 == was, "the directory's mode was not put back"
    _held_to_labels(root, reason)


def test_a_held_out_file_with_a_second_name_at_the_start_is_refused_with_no_path(
    root: Path,
) -> None:
    (root / "elsewhere").mkdir()
    os.link(root / "heldout" / TASK_ID / FILE_NAME, root / "elsewhere" / "copy")
    config = _config(root)
    reason = _check(root, config, "SessionStart")
    assert "has more than one name (2)" in reason, reason
    _held_to_labels(root, reason)
    assert _named(_halt(root), root) == [], _halt(root)


def test_a_held_out_file_gone_at_the_end_is_refused_with_no_path(root: Path) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    (root / "heldout" / TASK_ID / FILE_NAME).unlink()
    reason = _check(root, config, "SessionEnd")
    _held_to_labels(root, reason)


def test_two_changed_entries_have_two_labels_and_each_keeps_its_own_on_every_call(
    root: Path,
) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    for task in (TASK_ID, OTHER_ID):
        task_dir = root / "heldout" / task
        task_dir.chmod(0o700 if task_dir.stat().st_mode & 0o777 != 0o700 else 0o755)
    first = _check(root, config)
    labels = sorted(set(LABEL.findall(first)))
    assert len(labels) == 2, f"two entries put back, not told apart: {first}"
    (root / "heldout" / TASK_ID).chmod(0o711)
    again = _check(root, config)
    found = LABEL.findall(again)
    assert len(found) == 1, f"one entry put back, not one label: {again}"
    assert found[0] in labels, f"the entry's label changed between two calls: {first} / {again}"


def test_a_path_the_session_may_read_is_still_named_where_it_was_put_back(root: Path) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    settings = root / "worktree" / ".claude" / "settings.json"
    settings.write_text('{"hooks": {}}\n')
    reason = _check(root, config)
    assert "were put back" in reason and str(settings) in reason, reason


def test_the_label_is_keyed_and_the_operator_finds_the_path_from_the_place_apart(
    root: Path,
) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    task = root / "heldout" / TASK_ID
    task.chmod(0o700 if task.stat().st_mode & 0o777 != 0o700 else 0o755)
    reason = _check(root, config)
    # No plain digest of the path: a reader holding a guess cannot confirm it.
    for spelling in (str(task), os.path.realpath(task)):
        assert hashlib.sha256(spelling.encode()).hexdigest()[:12] not in reason, reason
    label_of = getattr(sentinel, "label_of", None)
    key_in = getattr(sentinel, "label_key", None)
    assert label_of is not None and key_in is not None, "the operator has no way to find a label"
    key = key_in(str(root / "apart"))
    assert label_of(str(task), "held-out", key) in reason, reason
    expected = hashlib.blake2b(str(task).encode(), digest_size=6, key=key).hexdigest()
    assert f"held-out entry {expected}" in reason, reason
    # The key lies in the place apart, nowhere in the session's own directory.
    assert all(key.hex() not in p.read_text(errors="replace") for p in _files(root / "outside"))


def _files(where: Path) -> list[Path]:
    return [p for p in sorted(where.rglob("*")) if p.is_file() and not p.is_symlink()]


def test_a_record_made_before_the_labels_refuses_as_it_did_and_labels_what_it_finds_next(
    root: Path,
) -> None:
    """A whole record with no key, as a session installed before the place apart keeps it."""
    config = _config(root, apart=False)
    assert _check(root, config, "SessionStart") == "allow"
    record = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "baseline.json"
    base = json.loads(record.read_text())
    base.pop("label_key", None)
    record.write_text(json.dumps(base, sort_keys=True))
    assert _check(root, config) == "allow", "a record made before the labels was refused"
    (root / "heldout" / TASK_ID / FILE_NAME).write_bytes(b"changed\n")
    reason = _check(root, config)
    assert "could not be put back" in reason, reason
    _held_to_labels(root, reason)


def test_a_halt_kept_by_a_record_made_before_the_labels_is_returned_as_it_was_kept(
    root: Path,
) -> None:
    config = _config(root, apart=False)
    assert _check(root, config, "SessionStart") == "allow"
    record = root / "outside" / "state" / "sessions" / SESSION / "sentinel" / "baseline.json"
    base = json.loads(record.read_text())
    kept = f"A protected path changed and could not be put back ({root}/heldout/x); every call"
    base["halted"] = kept
    record.write_text(json.dumps(base, sort_keys=True))
    assert _check(root, config) == kept
