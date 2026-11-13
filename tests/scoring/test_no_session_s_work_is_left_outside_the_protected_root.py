"""No session's work is left outside the protected root unnoticed.

An authoring session and the blind check work outside every protected root, since the session
must read and write there: the author's tasks before they are pooled, the check's copy of the
held-out tasks it is given. Their work is kept inside the root and removed when they end. A
runner stopped before that (killed, or its cleanup failed) leaves it where any session can
read it, with no canary in the check's copy. So each records, inside the protected root,
that its work is out before the session starts, and clears the record only once the work is
secured; while such a record stands, no further author or check on that root starts, and the
refusal says which work to look at.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _held_tier,
    _plan,
    _setup,
    _tasks,
    check_setup,
    check_work,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import (
    QUESTIONS,
    author,
    blind_check,
)
from physgate.evaluation.tiers.authoring import AuthoringError
from physgate.evaluation.tiers.canaries import root_canaries


class _Stopped(BaseException):
    """The runner stopped from outside before it secured the session's work."""


def _answers(worktree: Path) -> None:
    keys = list(json.loads((worktree / "tasks.json").read_text()))
    (worktree / "answers.json").write_text(
        json.dumps({k: dict.fromkeys(QUESTIONS, True) for k in keys})
    )


def _check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, work: str, version: str) -> Any:  # noqa: ANN401
    plan = _plan(tmp_path)
    fake = FakeSession(_answers, session_id=f"s-{work}")
    monkeypatch.setattr(author_session, "run_session", fake)
    setup = check_setup(plan.store, _setup(tmp_path / "private"), work)
    # The tier asked for, whether or not a version is there: the refusal looked for is
    # the work left, not the tier.
    tier = str(plan.root / version / "held_out")
    setup = dataclasses.replace(
        setup,
        held_out=tuple(dict.fromkeys((*setup.held_out, tier))),
        held_out_canaries=root_canaries(plan.root),
    )
    try:
        out = blind_check(
            plan.store,
            plan.role,
            version,
            setup,
            check_work(plan.store, work),
            implementer_model="claude-opus-5-5",
            cap=500_000,
        )
    except AuthoringError as exc:
        return fake, exc.context
    except Exception as exc:  # noqa: BLE001 - anything but the named refusal fails the row
        return fake, {"raised": repr(exc)}
    return fake, out


def _stopped_before_securing(monkeypatch: pytest.MonkeyPatch) -> None:
    def stopping(*_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise _Stopped

    monkeypatch.setattr(author_session, "_keep_evidence", stopping)


def test_a_check_stopped_before_its_work_was_secured_stops_the_next_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = _held_tier(tmp_path, monkeypatch)
    with monkeypatch.context() as patched:
        _stopped_before_securing(patched)
        with pytest.raises(_Stopped):
            _check(tmp_path, patched, "check", version)
    assert (check_work(_plan(tmp_path).store) / "worktree" / "tasks.json").is_file()
    fake, refused = _check(tmp_path, monkeypatch, "check-2", version)
    assert isinstance(refused, dict) and refused.get("refused_because") == "work_left", (
        f"a check ran while another's copy of the tier lay outside the root: {refused}"
    )
    assert fake.calls == []
    assert str(check_work(_plan(tmp_path).store)) in refused.get("work", "")


def test_an_author_stopped_before_its_work_was_secured_stops_the_next_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scratch").mkdir()
    with monkeypatch.context() as patched:
        _stopped_before_securing(patched)
        patched.setattr(author_session, "run_session", FakeSession(_tasks(2)))
        with pytest.raises(_Stopped):
            author(_plan(tmp_path), _setup(tmp_path / "private"))
    fake = FakeSession(_tasks(2))
    monkeypatch.setattr(author_session, "run_session", fake)
    try:
        out = author(
            _plan(tmp_path, work=tmp_path / "scratch" / "work2"), _setup(tmp_path / "private")
        )
    except AuthoringError as exc:
        out = exc.context
    except Exception as exc:  # noqa: BLE001 - anything but the named refusal fails the row
        out = {"raised": repr(exc)}
    assert out.get("refused_because") == "work_left", (
        f"an author ran while another's tasks lay outside the root: {out}"
    )
    assert fake.calls == []
    # The refusal names the work to look at, not only that some work is left.
    assert str(tmp_path / "scratch" / "work") in out.get("work", "")


def test_a_check_whose_cleanup_failed_stops_the_next_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = _held_tier(tmp_path, monkeypatch)
    with monkeypatch.context() as patched:
        patched.setattr(author_session, "_remove", lambda path: f"{path}: still there")
        _, first = _check(tmp_path, patched, "check", version)
    assert isinstance(first, dict) and "left" in first, f"the failed cleanup passed: {first}"
    _, refused = _check(tmp_path, monkeypatch, "check-2", version)
    assert isinstance(refused, dict) and refused.get("refused_because") == "work_left", refused


def test_checks_whose_work_was_secured_follow_one_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Control: the record is cleared once the work is secured, so the next one runs.
    _, version = _held_tier(tmp_path, monkeypatch)
    for work in ("check", "check-2"):
        fake, out = _check(tmp_path, monkeypatch, work, version)
        assert len(fake.calls) == 1 and out.get("answered"), out
    root = _plan(tmp_path).root
    assert not [p for p in root.iterdir() if p.is_file()], "a record was left in the root"


def test_a_check_does_not_start_while_an_author_s_work_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scratch").mkdir()
    with monkeypatch.context() as patched:
        _stopped_before_securing(patched)
        patched.setattr(author_session, "run_session", FakeSession(_tasks(2)))
        with pytest.raises(_Stopped):
            author(_plan(tmp_path), _setup(tmp_path / "private"))
    # The check is refused on the work left, before it looks for any version.
    fake, refused = _check(tmp_path, monkeypatch, "check", "f" * 64)
    assert isinstance(refused, dict) and refused.get("refused_because") == "work_left", (
        f"a check ran while an author's tasks lay outside the root: {refused}"
    )
    assert fake.calls == []


def _another_role_s_work_left(tmp_path: Path) -> Path:
    """A record that another role's session has its work out of that role's root."""
    record = tmp_path / "private" / "store" / "firmware" / "check.working"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"work": str(tmp_path / "scratch" / "firmware-check")}) + "\n")
    return record


def test_an_author_does_not_start_while_another_role_s_work_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "scratch").mkdir()
    _another_role_s_work_left(tmp_path)
    fake = FakeSession(_tasks(2))
    monkeypatch.setattr(author_session, "run_session", fake)
    try:
        out = author(_plan(tmp_path), _setup(tmp_path / "private"))
    except AuthoringError as exc:
        out = exc.context
    except Exception as exc:  # noqa: BLE001 - anything but the named refusal fails the row
        out = {"raised": repr(exc)}
    assert out.get("refused_because") == "work_left", (
        f"an author ran while another role's work lay outside its root: {out}"
    )
    assert fake.calls == []


def test_a_check_does_not_start_while_another_role_s_work_is_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = _held_tier(tmp_path, monkeypatch)
    _another_role_s_work_left(tmp_path)
    fake, refused = _check(tmp_path, monkeypatch, "check", version)
    assert isinstance(refused, dict) and refused.get("refused_because") == "work_left", (
        f"a check ran while another role's work lay outside its root: {refused}"
    )
    assert fake.calls == []
