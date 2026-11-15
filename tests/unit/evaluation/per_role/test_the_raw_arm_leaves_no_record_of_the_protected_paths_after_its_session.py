"""The raw arm leaves no record of the protected paths once its session has been checked.

The hook sentinel takes, at a session's first hook, a record of every entry beneath the
session's withheld roots: each by its path (so a protected task's directory, which is its id),
with its size, times and the digest of its bytes. That record lies in the session's own hook
state, which no tool of the session reads; its last reader is the end check after the stop. A
visible trial's directory is moved where people and later tools read it, so the record goes
with the credential, in the same cleanup, on every path out of the session, reached through
descriptors with no link followed. A cleanup that cannot remove it is recorded and refuses the
result, as one that cannot remove the credential does.

The stand-in session writes the record where the sentinel would, since the stand-in binary runs
no hook; the real binary's rows hold the same of the sentinel's own record.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from task_fixtures import own_task
from test_the_raw_arm_s_credential_is_handled_as_a_role_session_s import _script, _setup

from physgate.evaluation.per_role.arms import raw
from physgate.evaluation.tiers.task import parse_task

TASK = parse_task(json.dumps(own_task()).encode())
#: What the record names of a protected task: nothing else the session writes holds it.
PROTECTED_ID = "control.held-out-stand-in-7f3a09"

#: A session that does what the sentinel's first hook does: it writes the record of the
#: protected paths, and a file beside it that is no record of them, in its own session's
#: hook state, then ends.
RECORDING = f"""
id=""; prev=""
for a in "$@"; do [ "$prev" = "--session-id" ] && id="$a"; prev="$a"; done
dir="../session/state/sessions/$id/sentinel"
mkdir -p "$dir/blobs"
printf '%s' '{{"revert": {{"/store/control/v1/held_out/{PROTECTED_ID}/task.json": []}}}}' \\
  > "$dir/baseline.json"
printf '%s' '{{"sealed": ["{PROTECTED_ID}"]}}' > "$dir/.baseline.json.tmp"
printf '%s' '{{}}' > "$dir/blobs/index.json"
echo '{{"type":"result","subtype":"success","usage":{{}}}}'
"""


def _linked(outside: Path) -> str:
    """A session whose own directory in the hook state is a link to ``outside``."""
    return f"""
id=""; prev=""
for a in "$@"; do [ "$prev" = "--session-id" ] && id="$a"; prev="$a"; done
mkdir -p ../session/state/sessions
ln -s '{outside}' "../session/state/sessions/$id"
echo '{{"type":"result","subtype":"success","usage":{{}}}}'
"""


def _holders(root: Path) -> list[str]:
    return [
        str(p)
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink() and PROTECTED_ID.encode() in p.read_bytes()
    ]


def _sentinel_dirs(work: Path) -> list[Path]:
    return sorted((work / "session" / "state" / "sessions").glob("*/sentinel"))


def test_after_the_session_no_file_of_it_names_a_protected_path(tmp_path: Path) -> None:
    work = tmp_path / "work"
    raw.run_raw(TASK, _setup(tmp_path, _script(tmp_path / "claude", RECORDING)), work, cap=10**9)
    # Not vacuous: the session made its record where the sentinel keeps it.
    (sentinel,) = _sentinel_dirs(work)
    assert _holders(work) == [], "a file the session left names a protected path"
    assert not (sentinel / "baseline.json").exists()
    assert not (sentinel / ".baseline.json.tmp").exists()
    # Only the record goes: what lies beside it names no protected path and stays.
    assert (sentinel / "blobs" / "index.json").read_text() == "{}"


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("await_session", RuntimeError("the process table could not be read")),
        ("await_session", KeyboardInterrupt()),
        ("check_after_stop", RuntimeError("the end check could not be run")),
    ],
    ids=["an error while it runs", "killed while it runs", "an end check that fails"],
)
def test_the_record_is_removed_on_every_path_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str, error: BaseException
) -> None:
    real = getattr(raw, step)

    def after_the_session(*a: object, **k: object) -> object:
        real(*a, **k)  # the session runs and writes its record; then the step fails
        raise error

    monkeypatch.setattr(raw, step, after_the_session)
    work = tmp_path / "work"
    binary = _script(tmp_path / "claude", RECORDING)
    outcome: BaseException | None = None
    try:
        raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    except BaseException as exc:  # noqa: BLE001 - the row holds what was raised
        outcome = exc
    assert type(outcome) is type(error), outcome
    assert _sentinel_dirs(work), "the session left no record to remove"
    assert _holders(work) == [], "a file the session left names a protected path"


def test_a_link_in_the_way_is_never_followed_and_refuses_the_result(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "sentinel").mkdir(parents=True)
    kept = outside / "sentinel" / "baseline.json"
    kept.write_text('{"not": "the session\'s"}')
    work = tmp_path / "work"
    outcome: BaseException | None = None
    try:
        binary = _script(tmp_path / "claude", _linked(outside))
        raw.run_raw(TASK, _setup(tmp_path, binary), work, cap=10**9)
    except BaseException as exc:  # noqa: BLE001 - the row holds what was raised
        outcome = exc
    assert isinstance(outcome, raw.RawArmError), outcome
    assert "sentinel's record" in str(outcome), outcome
    # Nothing outside the session's own directory was removed through the link.
    assert kept.read_text() == '{"not": "the session\'s"}'
    record = json.loads((work / "cleanup.json").read_text())
    assert "link" in record["error"], record
    assert not (work / "raw.json").exists()
