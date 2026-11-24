"""The sentinel names no path of the protected material in a refusal, its log or a halt it keeps.

When the sentinel finds a protected entry changed, or a held-out or answer-key file with a second
name, it refuses the call, writes a line to the hook log, and keeps the halt in the session's own
record, which every later call returns. The refusal goes to the session; the log and the record
lie in the session's own directory, which can lie later where people and other sessions read. So
a path of the protected material (beneath a held-out or answer-key root, a withheld run record;
a held-out task's directory is its id) is named in none of them: each is given a label in its
place, the kind of protection and a digest of the path keyed by a key the session cannot read,
the same for one path on every call. Two entries are told apart by their labels; what the
sentinel found (gone, a second name, its count) is kept as it was. The operator finds the path
from the key and the record the sentinel keeps apart. Any other path is named as before.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
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


def _request(root: Path, *, apart: bool = True) -> dict[str, object]:
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
    return fields


def _config(root: Path, *, apart: bool = True, **changes: object) -> SessionConfig:
    fields = _request(root, apart=apart) | changes
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


def test_a_second_name_made_during_the_session_is_refused_at_its_end_with_no_path(
    root: Path,
) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    (root / "elsewhere").mkdir()
    os.link(root / "heldout" / TASK_ID / FILE_NAME, root / "elsewhere" / "copy")
    reason = _check(root, config, "SessionEnd")
    assert "has more than one name (2)" in reason, reason
    _held_to_labels(root, reason)


def test_with_no_place_apart_one_path_keeps_one_label_on_every_call(root: Path) -> None:
    config = _config(root, apart=False)
    assert _check(root, config, "SessionStart") == "allow"
    task = root / "heldout" / TASK_ID
    labels = []
    for mode in (0o700, 0o711):
        task.chmod(mode if task.stat().st_mode & 0o777 != mode else 0o755)
        labels += LABEL.findall(_check(root, config))
    assert len(labels) == 2 and labels[0] == labels[1], f"one entry, two labels: {labels}"


@pytest.mark.parametrize(
    ("field", "kind"), [("answer_keys", "answer-key"), ("withheld", "withheld-record")]
)
def test_an_answer_key_or_a_withheld_record_changed_is_named_by_its_kind_and_label(
    root: Path, field: str, kind: str
) -> None:
    where = root / "kept" / "record-5e0a.json"
    where.parent.mkdir()
    where.write_text('{"kept": true}\n')
    value = str(where.parent) if field == "answer_keys" else str(where)
    fields = _request(root) | {field: (value,)}
    config = build_config(InstallRequest(**fields), installation())  # type: ignore[arg-type]
    assert _check(root, config, "SessionStart") == "allow"
    where.write_text('{"kept": false}\n')
    reason = _check(root, config)
    assert f"{kind} entry " in reason, reason
    assert str(where) not in reason and where.name not in reason, reason
    assert where.name not in _log(root), _log(root)


def _key_file(root: Path) -> Path:
    return root / "apart" / sentinel.LABEL_KEY_NAME


def _put_back_one(root: Path, config: SessionConfig) -> tuple[Path, str]:
    """A held-out task directory's mode changed and put back: the directory, and the refusal."""
    task = root / "heldout" / TASK_ID
    task.chmod(0o700 if task.stat().st_mode & 0o777 != 0o700 else 0o755)
    return task, _check(root, config)


def test_the_key_is_this_user_s_alone_with_one_name(root: Path) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    _put_back_one(root, config)
    held = _key_file(root).stat()
    assert held.st_mode & 0o777 == 0o600, oct(held.st_mode)
    assert held.st_nlink == 1 and held.st_uid == os.geteuid()
    assert re.fullmatch(r"[0-9a-f]{64}", _key_file(root).read_text())


def test_a_hook_killed_while_it_makes_the_key_leaves_no_key_and_the_next_makes_a_whole_one(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Killed after the key's file was made and before it was whole: no key half there."""
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    real = os.urandom

    def killed(n: int) -> bytes:
        monkeypatch.setattr(os, "urandom", real)
        raise SystemExit(137)

    monkeypatch.setattr(os, "urandom", killed)
    with pytest.raises(SystemExit):
        _put_back_one(root, config)
    assert not _key_file(root).exists(), "a key half made was left at the key's name"
    task, reason = _put_back_one(root, config)
    assert re.fullmatch(r"[0-9a-f]{64}", _key_file(root).read_text())
    label = sentinel.label_of(str(task), "held-out", sentinel.label_key(str(root / "apart")))
    assert f"put back: {label}." in reason or f"{label}," in reason, reason


@pytest.mark.parametrize(
    "kept", [b"", b"ab" * 16, b"zz" * 32, b"ab" * 33], ids=["empty", "short", "not hex", "long"]
)
def test_a_key_that_is_no_key_is_a_refusal_that_says_what_to_do_and_the_put_back_is_kept(
    root: Path, kept: bytes
) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    _key_file(root).write_bytes(kept)
    _key_file(root).chmod(0o600)
    task = root / "heldout" / TASK_ID
    was = task.stat().st_mode & 0o777
    _, reason = _put_back_one(root, config)
    assert task.stat().st_mode & 0o777 == was, "the directory's mode was not put back"
    # It says so, and what a person does, naming no protected path and not the place's.
    assert "labels.key" in reason and "removes" in reason, reason
    assert "were put back" in reason and "(one-off key)" in reason, reason
    assert str(root / "apart") not in reason and _named(reason, root) == [], reason
    # What was done on disk is on record before the refusal, as without the labels.
    decisions = [json.loads(line)["decision"] for line in _log(root).splitlines()]
    assert decisions[:1] == ["put back"], decisions
    # The record was saved: the put-back is not done or said again.
    assert _check(root, config) == "allow"


def test_a_key_open_to_others_is_no_key(root: Path) -> None:
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    _key_file(root).write_text("ab" * 32)
    _key_file(root).chmod(0o644)
    _, reason = _put_back_one(root, config)
    assert "labels.key" in reason and "(one-off key)" in reason, reason


def test_a_key_with_a_second_name_is_no_key(root: Path) -> None:
    """A second name is a way to read the key from somewhere else: such a key is not used."""
    config = _config(root)
    assert _check(root, config, "SessionStart") == "allow"
    _key_file(root).write_text("ab" * 32)
    _key_file(root).chmod(0o600)
    os.link(_key_file(root), root / "key-elsewhere")
    _, reason = _put_back_one(root, config)
    assert "labels.key" in reason and "(one-off key)" in reason, reason


def test_two_sessions_that_make_the_key_at_once_take_the_same_key(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The place is locked while the key is made: the second maker waits and reads the first's."""
    real = os.urandom

    def slow(n: int) -> bytes:
        # Wide enough that, unlocked, a second maker meets the first's key half made.
        time.sleep(0.05)
        return real(n)

    monkeypatch.setattr(os, "urandom", slow)
    makers = 4
    start = threading.Barrier(makers)
    taken: list[bytes] = []
    failed: list[BaseException] = []

    def make() -> None:
        start.wait()
        try:
            taken.append(sentinel.label_key(str(root / "apart")))
        except BaseException as exc:  # noqa: BLE001 - every maker's failure is the row's
            failed.append(exc)

    threads = [threading.Thread(target=make) for _ in range(makers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failed == [], failed
    assert len(taken) == makers and len(set(taken)) == 1, taken
    assert bytes.fromhex(_key_file(root).read_text()) == taken[0]


def _whole_config(root: Path) -> SessionConfig:
    """A configuration with every kind of protected place: a root withheld whole among them."""
    store = root / "store"
    (store / "trial" / "wt").mkdir(parents=True)
    (store / "other").mkdir()
    (root / "material").mkdir()
    return _config(
        root,
        worktree=str(store / "trial" / "wt"),
        withheld_whole=(str(store),),
        own_place=str(store / "trial"),
        extra_review_material=(str(root / "material"),),
    )


@pytest.mark.parametrize(
    ("where", "kind"),
    [
        ("store/other/x.json", "withheld-root"),
        ("apart/x.json", "sentinel-record"),
        ("material/x.json", "review-material"),
        ("heldout/x.json", "held-out"),
    ],
)
def test_the_orchestrator_s_label_and_the_sentinel_s_are_one_where_both_use_the_place_s_key(
    root: Path, where: str, kind: str
) -> None:
    config = _whole_config(root)
    path = str(root / where)
    key = sentinel.label_key(str(root / "apart"))
    expected = sentinel.label_of(path, kind, key)
    assert sentinel.labeller(config)(path) == expected
    assert sentinel._namer(config, str(root / "apart"), {})(path) == expected


def test_the_orchestrator_names_a_path_it_cannot_judge_by_a_label_never_as_it_is(
    root: Path,
) -> None:
    config = _config(root)
    unjudged = str(root / "heldout" / TASK_ID) + "\0" + FILE_NAME
    named = sentinel.labeller(config)(unjudged)
    assert TASK_ID not in named and FILE_NAME not in named, named
    assert named.startswith("protected entry "), named


def test_labels_the_orchestrator_makes_with_a_key_for_one_record_alone_say_so(root: Path) -> None:
    config = _config(root)
    (root / "apart").chmod(0o755)
    named = sentinel.labeller(config)(str(root / "heldout" / TASK_ID))
    assert named.startswith("held-out entry ") and named.endswith(" (one-off key)"), named
