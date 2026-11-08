"""What the author's watch could not hold, or what saw the held-out tier, is never pooled.

The checkpoint runs on a thread of the watch, and a call of it that hangs outlives the stop
of the session: once the session is over, it changes nothing the runner then reads (what is
held, what lies in the work directory). A session the watch could not hold to its cap (its
reading or checkpoint failed, it stalled, its stream never appeared) was not counted as the
watch meant it to be, so the runner pools none of its tasks; it still keeps the session's
stream inside the protected root and removes the work. The same holds for a session whose
stream showed a held-out canary, however it ended: what it wrote may hold what it saw.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from test_the_task_author_s_session_is_staged_held_and_split_blind import (
    FakeSession,
    _plan,
    _setup,
    _tasks,
    _write_task,
)

from physgate.evaluation.per_role import author_session
from physgate.evaluation.per_role.author_session import (
    AuthorProgress,
    author,
    held_out_tier,
    pool_dir,
)
from physgate.evaluation.per_role.authoring import AuthoringError
from physgate.evaluation.per_role.validate import sound

#: A canary flag the record does not carry at all.
ABSENT = "absent"
#: Long enough for every wait in this file, which all end within a second.
WITHIN_S = 30.0


def _listed(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []


def test_a_checkpoint_call_still_running_when_the_session_is_over_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree, scratch = tmp_path / "worktree", tmp_path / "checks"
    worktree.mkdir()
    progress = AuthorProgress(worktree, scratch, cap=8_000_000, per_task=1_000_000)
    _write_task(worktree / "control.t00", 0)
    assert progress.check(0) is None and progress.held == {"control.t00"}

    # The next call hangs in the scorer, past the end of the session.
    _write_task(worktree / "control.t01", 1)
    real = sound
    entered, release = threading.Event(), threading.Event()

    def hung(tier: Path) -> list[str]:
        entered.set()
        release.wait(WITHIN_S)
        return real(tier)

    monkeypatch.setattr(author_session, "sound", hung)
    caller = threading.Thread(target=progress.check, args=(0,), daemon=True)
    caller.start()
    try:
        assert entered.wait(WITHIN_S)
        close: Any = getattr(progress, "close", None)
        assert close is not None, "nothing tells the checkpoint that its session is over"
        held_then = close()
        left = _listed(scratch)
    finally:
        release.set()
    caller.join(WITHIN_S)
    assert not caller.is_alive()
    assert held_then == 1
    assert progress.held == {"control.t00"}, "a call that outlived the session changed the count"
    assert _listed(scratch) == left, "a call that outlived the session wrote or removed a copy"

    # A call after the close looks at nothing: a task gone is still counted as it was then,
    # and a task written is never copied.
    monkeypatch.setattr(author_session, "sound", real)
    shutil.rmtree(worktree / "control.t00")
    assert progress.check(0) is None and progress.held == {"control.t00"}
    _write_task(worktree / "control.t02", 2)
    assert progress.check(0) is None and progress.held == {"control.t00"}
    assert _listed(scratch) == left, "a call after the session was over wrote a copy"


def test_a_checkpoint_call_that_fails_after_the_session_is_over_leaves_its_copy_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree, scratch = tmp_path / "worktree", tmp_path / "checks"
    worktree.mkdir()
    progress = AuthorProgress(worktree, scratch, cap=8_000_000, per_task=1_000_000)
    _write_task(worktree / "control.t00", 0)
    entered, release = threading.Event(), threading.Event()

    def failing(_tier: Path) -> list[str]:
        entered.set()
        release.wait(WITHIN_S)
        raise RuntimeError("the scorer failed")

    raised: list[BaseException] = []

    def call() -> None:
        try:
            progress.check(0)
        except RuntimeError as exc:
            raised.append(exc)

    monkeypatch.setattr(author_session, "sound", failing)
    caller = threading.Thread(target=call, daemon=True)
    caller.start()
    try:
        assert entered.wait(WITHIN_S)
        progress.close()
        left = _listed(scratch)
    finally:
        release.set()
    caller.join(WITHIN_S)
    assert not caller.is_alive() and len(raised) == 1
    assert left and _listed(scratch) == left, "a failing call removed a copy after the session"


class _Keeping(FakeSession):
    """The scripted session, keeping the checkpoint it was given."""

    def __call__(
        self,
        prompt: str,
        setup: Any,  # noqa: ANN401
        work: Path,
        *,
        cap: int,
        files: Any = None,  # noqa: ANN401
        check: Any = None,  # noqa: ANN401
    ) -> dict[str, Any]:
        self.kept = check
        return super().__call__(prompt, setup, work, cap=cap, files=files, check=check)


def test_the_runner_closes_the_checkpoint_before_it_looks_at_what_the_session_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Keeping(_tasks(2))
    closed_then: list[object] = []
    real = author_session.stage

    def staging(worktree: Path, into: Path, only: Any = None) -> int:  # noqa: ANN401
        if only is None:  # the runner's own staging, not the checkpoint's copy
            closed_then.append(getattr(getattr(fake.kept, "__self__", None), "closed", None))
        return real(worktree, into, only)

    monkeypatch.setattr(author_session, "run_session", fake)
    monkeypatch.setattr(author_session, "stage", staging)
    (tmp_path / "scratch").mkdir()
    summary = author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert closed_then == [True], "the runner read what the session left with its checkpoint open"
    assert summary["held_while_running"] == 2


class _Ending(FakeSession):
    """The scripted session, ending as ``end`` says; ``seen`` is its canary flag, or absent."""

    def __init__(self, write: Any, end: str, seen: bool | str | None = False) -> None:  # noqa: ANN401
        super().__init__(write, checking=False)
        self.end, self.seen = end, seen

    def __call__(
        self,
        prompt: str,
        setup: Any,  # noqa: ANN401
        work: Path,
        *,
        cap: int,
        files: Any = None,  # noqa: ANN401
        check: Any = None,  # noqa: ANN401
    ) -> dict[str, Any]:
        record = super().__call__(prompt, setup, work, cap=cap, files=files, check=check)
        record = {**record, "end": self.end, "held_out_seen": self.seen}
        if self.seen == ABSENT:
            del record["held_out_seen"]
        return record


def _refused(tmp_path: Path) -> str | None:
    """Run the author; the refusal's text and context, after checking nothing was taken."""
    plan = _plan(tmp_path)
    (tmp_path / "scratch").mkdir()
    refused: str | None = None
    try:
        author(plan, _setup(tmp_path / "private"))
    except AuthoringError as exc:
        refused = f"{exc} {exc.context}"
    if refused is not None:
        assert _listed(pool_dir(plan.held_out_root, "control")) == []
        assert not held_out_tier(plan.held_out_root, "control").exists()
        assert not plan.visible.exists()
        # The stream is still secured and the work removed.
        assert list((plan.held_out_root / "control.author").glob("*/stdout.jsonl"))
        assert not plan.work.exists()
    return refused


@pytest.mark.parametrize(
    ("end", "seen"),
    [("ended", True), ("budget_exhausted", True), ("task_cap", True), ("ended", ABSENT)],
)
def test_a_session_whose_stream_showed_a_held_out_canary_pools_none_of_its_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, end: str, seen: bool | str
) -> None:
    # However it ended, and when the record cannot say it saw none: nothing is taken.
    monkeypatch.setattr(author_session, "run_session", _Ending(_tasks(16), end, seen))
    staged: list[Any] = []
    stage = author_session.stage

    def staging(*args: Any) -> int:  # noqa: ANN401
        staged.append(args)
        return stage(*args)

    monkeypatch.setattr(author_session, "stage", staging)
    refused = _refused(tmp_path)
    assert refused is not None, f"the tasks of a session that saw a canary ({end}) were taken"
    assert "held_out_seen" in refused
    assert staged == [], "what a session that saw a canary wrote was staged"


@pytest.mark.parametrize("end", ["watch_failed", "watch_stalled", "no_stream"])
def test_a_session_its_watch_could_not_hold_pools_none_of_its_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, end: str
) -> None:
    monkeypatch.setattr(author_session, "run_session", _Ending(_tasks(16), end))
    plan = _plan(tmp_path)
    (tmp_path / "scratch").mkdir()
    refused: str | None = None
    try:
        author(plan, _setup(tmp_path / "private"))
    except AuthoringError as exc:
        refused = str(exc)
    assert refused is not None, f"the tasks of a session that ended {end} were taken"
    assert end in refused
    assert _listed(pool_dir(plan.held_out_root, "control")) == []
    assert not held_out_tier(plan.held_out_root, "control").exists()
    assert not plan.visible.exists()
    # The stream is still secured and the work removed.
    assert list((plan.held_out_root / "control.author").glob("*/stdout.jsonl"))
    assert not plan.work.exists()


def test_a_session_stopped_at_its_cap_pools_what_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The cap is the watch holding the session, not failing to: its tasks are pooled.
    monkeypatch.setattr(author_session, "run_session", _Ending(_tasks(3), "budget_exhausted"))
    (tmp_path / "scratch").mkdir()
    summary = author(_plan(tmp_path), _setup(tmp_path / "private"))
    assert summary["status"] == "pooled" and summary["pooled"] == 3
