"""The round journal is read back only as the rounds could have written it, line by line in context.

When an attempt is void no event log exists, and its rounds are kept only in the journal and the
plan files: so its reader is a boundary. Each line is held to what the rounds write given every
line before it: no round past the run's last, a plan's digest exactly where the round has a plan,
a review exactly where one ran, a re-plan only after a round that is re-planned, the terminal line
naming what its last round gives, and each round's own session. The reader says whether the
rounds ended. A run whose event log was started opens only over a journal whose rounds ended and
agree with the log's own record of them; a decomposition killed between the run's start and the
journal's terminal line is refused when the run is opened. Each plan file is synced before its
round's end line is written.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from replan_rig import Step, Stopped, decompose, outcome_of

from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.run_config import load_run_config

JOURNAL = ("decomposition", "rounds.jsonl")


def _journal(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in run_dir.joinpath(*JOURNAL).read_text().splitlines()]


def _write(run_dir: Path, lines: list[dict[str, Any]]) -> None:
    run_dir.joinpath(*JOURNAL).write_text("".join(json.dumps(one) + "\n" for one in lines))


def _read(run_dir: Path, last: int) -> Any:  # noqa: ANN401 - what was read, or the refusal
    from physgate.orchestrator import design_rounds

    return outcome_of(lambda: design_rounds.read_journal(run_dir, last=last))


def _ended(lines: list[dict[str, Any]], k: int) -> dict[str, Any]:
    return next(one for one in lines if one["kind"] == "round_ended" and one["round"] == k)


def _terminal(lines: list[dict[str, Any]]) -> dict[str, Any]:
    return next(one for one in lines if one["kind"] == "rounds_ended")


def _passed(one: dict[str, Any]) -> None:
    one["ending"]["review_cause"] = "pass"
    one["review"]["result"]["verdict"] = "pass"


def _verdict_terminal(lines: list[dict[str, Any]]) -> None:
    _terminal(lines).update(cause="pass", ending_class="verdict")


def _fail_run_terminal(lines: list[dict[str, Any]]) -> None:
    _terminal(lines)["follows"] = "fail_run"


def _plan_without_digest(lines: list[dict[str, Any]]) -> None:
    _ended(lines, 2)["plan_sha256"] = None


def _verdict_without_review(lines: list[dict[str, Any]]) -> None:
    _ended(lines, 2)["review"] = None


def _round_one_s_session(lines: list[dict[str, Any]]) -> None:
    first = _ended(lines, 1)["session_id"]
    for one in lines:
        if one.get("round") == 2 and "session_id" in one:
            one["session_id"] = first


def _a_round_past_the_last(lines: list[dict[str, Any]], run_dir: Path) -> None:
    terminal = _terminal(lines)
    lines.remove(terminal)
    started = next(one for one in lines if one["kind"] == "round_started" and one["round"] == 3)
    ended = _ended(lines, 3)
    session = str(uuid.uuid4())
    lines += [
        {**started, "round": 4, "session_id": session},
        {**ended, "round": 4, "session_id": session},
        {**terminal, "round": 4},
    ]
    four = run_dir / "decomposition" / "round-4"
    four.mkdir(parents=True)
    (four / "plan.json").write_bytes(
        (run_dir / "decomposition" / "round-3" / "plan.json").read_bytes()
    )


#: Each forgery the loop could not have written, the round it is on, and the check that names it.
FORGERIES: dict[str, tuple[Callable[..., None], int, str]] = {
    "an earlier round passed": (lambda lines, _: _passed(_ended(lines, 1)), 1, "follows"),
    "the terminal names a verdict its round did not give": (
        lambda lines, _: _verdict_terminal(lines),
        3,
        "terminal",
    ),
    "the terminal fails a run its round started": (
        lambda lines, _: _fail_run_terminal(lines),
        3,
        "terminal",
    ),
    "a plan with no digest": (lambda lines, _: _plan_without_digest(lines), 2, "pairing"),
    "a verdict with no review": (lambda lines, _: _verdict_without_review(lines), 2, "pairing"),
    "a round under an earlier round's session": (
        lambda lines, _: _round_one_s_session(lines),
        2,
        "session",
    ),
    "a round past the run's last": (_a_round_past_the_last, 4, "budget"),
}


@pytest.fixture
def three_fails(tmp_path: Path) -> Path:
    ran = decompose(tmp_path / "base", "repair:2", [Step(), Step(), Step()])
    assert ran.code == 0, ran.code
    return ran.run_dir


@pytest.mark.parametrize("name", list(FORGERIES))
def test_a_journal_the_rounds_could_not_have_written_is_refused(
    three_fails: Path, name: str
) -> None:
    forge, on, check = FORGERIES[name]
    lines = _journal(three_fails)
    forge(lines, three_fails)
    _write(three_fails, lines)
    found = _read(three_fails, 3)
    assert isinstance(found, RunStateError), f"{name}: read as {found!r}"
    assert found.context.get("round") == str(on), found.context
    assert found.context.get("check") == check, found.context


@pytest.mark.parametrize("name", [n for n, (_, on, _c) in FORGERIES.items() if on < 3])
def test_each_forgery_is_named_with_a_later_fault_present(three_fails: Path, name: str) -> None:
    # A later round's plan file that is not its digest: the reader names the first fault, by
    # the check that found it, never the later one.
    forge, on, check = FORGERIES[name]
    lines = _journal(three_fails)
    forge(lines, three_fails)
    _write(three_fails, lines)
    (three_fails / "decomposition" / "round-3" / "plan.json").write_text("{}")
    found = _read(three_fails, 3)
    assert isinstance(found, RunStateError), f"{name}: read as {found!r}"
    assert (found.context.get("round"), found.context.get("check")) == (str(on), check)


def test_the_unforged_journal_reads_and_says_its_rounds_ended(three_fails: Path) -> None:
    found = _read(three_fails, 3)
    assert not isinstance(found, Exception), found
    assert found.complete is True
    assert [one.kind for one in found.lines][-1] == "rounds_ended"


@pytest.mark.parametrize(
    ("edit", "cause"),
    [
        ("torn", "record_missing"),
        ("reordered", "record_missing"),
        ("two_terminals", "record_missing"),
        ("digest", "plan_digest_mismatch"),
    ],
)
def test_a_torn_reordered_doubled_or_mismatched_journal_is_refused(
    three_fails: Path, edit: str, cause: str
) -> None:
    lines = _journal(three_fails)
    path = three_fails.joinpath(*JOURNAL)
    if edit == "torn":
        _write(three_fails, lines)
        path.write_bytes(path.read_bytes()[:-9])
    elif edit == "reordered":
        lines[2], lines[3] = lines[3], lines[2]
        _write(three_fails, lines)
    elif edit == "two_terminals":
        _write(three_fails, [*lines, lines[-1]])
    else:
        (three_fails / "decomposition" / "round-2" / "plan.json").write_text("{}")
    found = _read(three_fails, 3)
    assert isinstance(found, RunStateError), f"{edit}: read as {found!r}"
    assert found.context.get("cause") == cause


#: Real journals of the loop's endings, each read back whole: (policy, steps, last round, ended).
ENDINGS = {
    "a pass": ("repair:2", [Step(review="pass")], 3, True),
    "re-planned to a pass": (
        "repair:2",
        [Step(), Step(review="blocked"), Step(review="pass")],
        3,
        True,
    ),
    "held at the last round": ("repair:1", [Step(), Step()], 2, True),
    "a no-plan round": ("repair:2", [Step(), Step(call="no_structured_output")], 3, True),
    "a refused plan": ("repair:2", [Step(), Step(refusal="plan_refused")], 3, True),
    "an unavailable review": ("repair:2", [Step(), Step(review="no_verdict")], 3, True),
    "a canary": ("repair:2", [Step(), Step(review="canary")], 3, True),
    "an exposure": ("repair:2", [Step(), Step(review="exposed")], 3, True),
    "a void review": ("repair:2", [Step(), Step(review="infrastructure")], 3, True),
    "a void call": ("repair:2", [Step(), Step(call="api_error")], 3, True),
    "a library refusal": ("repair:2", [Step(), Step(refusal="library_refused")], 3, True),
    "an invocation error": ("repair:2", [Step(), Step(review="invocation_error")], 3, True),
    "an accounting mismatch": ("repair:2", [Step(), Step(call="accounting")], 3, True),
    "a kill in the review": ("repair:2", [Step(), Step(review="stop")], 3, False),
    "on": ("on", [Step()], 1, True),
    "observe": ("observe", [Step()], 1, True),
}


@pytest.mark.parametrize("name", list(ENDINGS))
def test_every_ending_s_journal_reads_back_and_says_whether_its_rounds_ended(
    tmp_path: Path, name: str
) -> None:
    policy, steps, last, ended = ENDINGS[name]
    ran = decompose(tmp_path, policy, steps)
    found = _read(ran.run_dir, last)
    assert not isinstance(found, Exception), f"{name}: {found!r}"
    assert found.complete is ended


def _opened(run_dir: Path) -> Any:  # noqa: ANN401 - the record, or the refusal
    from physgate.orchestrator.record import RunRecord

    config = load_run_config(run_dir / "run.json")

    def open_it() -> Any:  # noqa: ANN401
        record = RunRecord(config, run_dir)
        record.close()
        return record

    return outcome_of(open_it)


def test_a_reviewed_run_whose_rounds_ended_opens(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(), Step(review="pass")])
    assert ran.code == 0, ran.code
    assert not isinstance(_opened(ran.run_dir), Exception)


def _killed_after_the_start(tmp_path: Path) -> Path:
    from physgate.orchestrator import design_rounds

    real = design_rounds.start_run

    def start_then_stop(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        real(*args, **kwargs).close()
        raise Stopped

    ran = decompose(
        tmp_path,
        "repair:1",
        [Step(), Step(review="pass")],
        loop_patches={"start_run": start_then_stop},
    )
    assert isinstance(ran.code, Stopped), ran.code
    assert (ran.run_dir / "events.jsonl").exists()
    assert _journal(ran.run_dir)[-1]["kind"] == "round_ended"
    return ran.run_dir


def test_a_decomposition_killed_after_the_run_started_is_refused_when_opened(
    tmp_path: Path,
) -> None:
    found = _opened(_killed_after_the_start(tmp_path))
    assert isinstance(found, RunStateError), found
    assert "killed" in str(found)


@pytest.mark.parametrize("edit", ["missing", "cut", "void", "another_session"])
def test_a_reviewed_run_over_a_journal_that_is_not_its_rounds_is_refused_when_opened(
    tmp_path: Path, edit: str
) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(), Step(review="pass")])
    assert ran.code == 0, ran.code
    lines = _journal(ran.run_dir)
    if edit == "missing":
        ran.run_dir.joinpath(*JOURNAL).unlink()
    elif edit == "cut":
        _write(ran.run_dir, lines[:-1])
    elif edit == "void":
        _write(ran.run_dir, [*lines[:-1], {**lines[-1], "follows": "void"}])
    else:
        session = str(uuid.uuid4())
        for one in lines:
            if one.get("round") == 2 and "session_id" in one:
                one["session_id"] = session
        _write(ran.run_dir, lines)
    found = _opened(ran.run_dir)
    assert isinstance(found, RunStateError), f"{edit}: opened as {found!r}"


def test_each_plan_file_is_synced_before_its_round_s_end_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[tuple[int, int, int]] = []
    real = os.fsync
    journal = tmp_path / "run" / "decomposition" / "rounds.jsonl"

    def sync(fd: int) -> None:
        stat = os.fstat(fd)
        written = journal.stat().st_size if journal.exists() else 0
        synced.append((stat.st_ino, stat.st_size, written))
        real(fd)

    monkeypatch.setattr(os, "fsync", sync)
    ran = decompose(tmp_path, "repair:1", [Step(), Step()])
    assert ran.code == 0, ran.code
    raw = journal.read_bytes().splitlines(keepends=True)
    for k in (1, 2):
        plan = ran.run_dir / "decomposition" / f"round-{k}" / "plan.json"
        before = sum(
            len(line)
            for line in raw[
                : next(
                    i
                    for i, line in enumerate(raw)
                    if json.loads(line)["kind"] == "round_ended" and json.loads(line)["round"] == k
                )
            ]
        )
        stat = plan.stat()
        hits = [w for ino, size, w in synced if (ino, size) == (stat.st_ino, stat.st_size)]
        assert hits, f"round {k}'s plan file was never synced"
        assert min(hits) <= before, f"round {k}'s plan file was synced only after its end line"
