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

import hashlib
import itertools
import json
import os
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of
from replan_rig import Step, Stopped, decompose, events

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


#: A wall-clock time other than any the rounds took.
STEPPED = "2001-01-01T00:00:00.000000Z"


def _started(lines: list[dict[str, Any]], k: int) -> dict[str, Any]:
    return next(one for one in lines if one["kind"] == "round_started" and one["round"] == k)


def _elapsed(one: dict[str, Any]) -> dict[str, Any]:
    assert "elapsed" in one, f"round {one['round']}'s end line records no monotonic times"
    elapsed: dict[str, Any] = one["elapsed"]
    return elapsed


def _reviewed_by(one: dict[str, Any], session: str) -> None:
    one["review"]["session_id"] = session
    one["review"]["result"]["session_id"] = session


def _void_after_a_replanned_round(lines: list[dict[str, Any]]) -> None:
    # Round 2 ended fail and is re-planned; the journal ends there with a void naming no round's
    # own ending, as if the loop had raised after it.
    terminal = _terminal(lines)
    del lines[4:]
    void = {"follows": "void", "ending_class": "infrastructure", "cause": "RunStateError"}
    lines.append({**terminal, "round": 2, **void})


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
    "a void terminal after a round that is re-planned": (
        lambda lines, _: _void_after_a_replanned_round(lines),
        2,
        "terminal",
    ),
    "a planned round that spent nothing": (
        lambda lines, _: _ended(lines, 2).update(usage=[]),
        2,
        "spent",
    ),
    "a planned round of no turns": (
        lambda lines, _: _ended(lines, 2).update(num_turns=0),
        2,
        "spent",
    ),
    "a review under its round's own call session": (
        lambda lines, _: _reviewed_by(_ended(lines, 1), _ended(lines, 1)["session_id"]),
        1,
        "session",
    ),
    "a review under an earlier round's review session": (
        lambda lines, _: _reviewed_by(_ended(lines, 2), _ended(lines, 1)["review"]["session_id"]),
        2,
        "session",
    ),
    "a review with no start": (
        lambda lines, _: _ended(lines, 2).update(review_started=None),
        2,
        "pairing",
    ),
    "a call that ends before it starts": (
        lambda lines, _: _elapsed(_ended(lines, 1)).update(
            started=2.0, call_ended=1.0, review_started=3.0, ended=4.0
        ),
        1,
        "time",
    ),
    "a review that starts before its call ends": (
        lambda lines, _: _elapsed(_ended(lines, 1)).update(
            started=1.0, call_ended=3.0, review_started=2.0, ended=4.0
        ),
        1,
        "time",
    ),
    "a review that ends before it starts": (
        lambda lines, _: _elapsed(_ended(lines, 1)).update(
            started=1.0, call_ended=2.0, review_started=4.0, ended=3.0
        ),
        1,
        "time",
    ),
    "a review with no start on the monotonic clock": (
        lambda lines, _: _elapsed(_ended(lines, 2)).update(review_started=None),
        2,
        "time",
    ),
    "a round that starts before the round before it ended": (
        lambda lines, _: _elapsed(_ended(lines, 1)).update(ended=10.0**6),
        2,
        "time",
    ),
    "an end line whose start is not its start line's": (
        lambda lines, _: _ended(lines, 2).update(started=STEPPED),
        2,
        "time",
    ),
    "round 1's start line names no arm": (
        lambda lines, _: _started(lines, 1).update(design_review=None),
        1,
        "arm",
    ),
    "a later round's start line names the arm": (
        lambda lines, _: _started(lines, 2).update(
            design_review="repair:2", decomposition_model="claude-sonnet-5"
        ),
        2,
        "arm",
    ),
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

    real = getattr(design_rounds, "start_run")  # noqa: B009 - the module's own import

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
        # A void the rounds could have written (the start raised after the round ended), so only
        # the open's own rule refuses it: a started run is never over a void attempt's journal.
        void = {"follows": "void", "ending_class": "infrastructure", "cause": "RunStateError"}
        _write(ran.run_dir, [*lines[:-1], {**lines[-1], **void}])
        assert not isinstance(_read(ran.run_dir, 2), Exception)
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


@pytest.mark.parametrize(
    ("kind", "name"),
    [
        ("round_started", "started"),
        ("round_ended", "started"),
        ("round_ended", "call_ended"),
        ("round_ended", "review_started"),
        ("round_ended", "ended"),
    ],
)
def test_a_journal_time_that_is_not_a_timestamp_is_refused(
    three_fails: Path, kind: str, name: str
) -> None:
    lines = _journal(three_fails)
    next(one for one in lines if one["kind"] == kind and one["round"] == 1)[name] = "yesterday"
    _write(three_fails, lines)
    found = _read(three_fails, 3)
    assert isinstance(found, RunStateError), f"{kind}.{name}: read as {found!r}"
    assert found.context.get("cause") == "record_missing"


def test_every_round_s_times_are_kept_on_a_clock_no_step_moves_and_in_order(
    three_fails: Path,
) -> None:
    ended = [one for one in _journal(three_fails) if one["kind"] == "round_ended"]
    assert len(ended) == 3
    after = 0.0
    for one in ended:
        at = _elapsed(one)
        times = [after, at["started"], at["call_ended"], at["review_started"], at["ended"]]
        assert times == sorted(times), f"round {one['round']}: {times}"
        after = at["ended"]


def test_a_clock_stepped_back_in_every_round_refuses_nothing(tmp_path: Path) -> None:
    from physgate.orchestrator.common import utc_now

    origin, ticks = utc_now(), itertools.count()

    def stepping_back() -> datetime:
        return origin - timedelta(minutes=next(ticks))

    ran = decompose(
        tmp_path,
        "repair:2",
        [Step(), Step(review="blocked"), Step(review="pass")],
        loop_patches={"utc_now": stepping_back},
    )
    assert ran.code == 0, ran.code
    starts = [one["started"] for one in _journal(ran.run_dir) if one["kind"] == "round_ended"]
    assert len(set(starts)) == 3 and starts == sorted(starts, reverse=True), "no step back"
    assert not isinstance(_read(ran.run_dir, 3), Exception)
    assert not isinstance(_opened(ran.run_dir), Exception)


def test_a_start_time_for_a_review_that_never_ran_is_refused(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(), Step(call="no_structured_output")])
    lines = _journal(ran.run_dir)
    assert _ended(lines, 2)["review"] is None
    _ended(lines, 2)["review_started"] = _ended(lines, 2)["call_ended"]
    _write(ran.run_dir, lines)
    found = _read(ran.run_dir, 2)
    assert isinstance(found, RunStateError), f"read as {found!r}"
    assert (found.context.get("round"), found.context.get("check")) == ("2", "pairing")


@pytest.mark.parametrize(
    ("policy", "steps", "starts"),
    [
        ("repair:2", [Step(), Step(review="pass")], True),
        ("repair:2", [Step(), Step(review="infrastructure")], False),
        ("on", [Step(review="pass")], True),
        ("observe", [Step()], True),
    ],
)
def test_round_one_names_the_run_s_mode_and_designer_and_no_later_round_does(
    tmp_path: Path, policy: str, steps: list[Step], starts: bool
) -> None:
    ran = decompose(tmp_path, policy, steps)
    # A void attempt starts no run: its journal alone says what arm it was.
    assert (ran.run_dir / "run.json").exists() is starts
    started = [one for one in _journal(ran.run_dir) if one["kind"] == "round_started"]
    assert started, "no round started"
    assert started[0].get("design_review") == policy, started[0]
    assert started[0].get("decomposition_model") == "claude-sonnet-5", started[0]
    for one in started[1:]:
        assert one.get("design_review") is None and one.get("decomposition_model") is None


@pytest.fixture
def two_rounds(tmp_path: Path) -> Path:
    ran = decompose(tmp_path / "two", "repair:3", [Step(), Step(review="pass")])
    assert ran.code == 0, ran.code
    assert not isinstance(_opened(ran.run_dir), Exception)
    return ran.run_dir


def _review_of(lines: list[dict[str, Any]], k: int, **fields: Any) -> None:  # noqa: ANN401
    _ended(lines, k)["review"]["result"].update(fields)
    if "session_id" in fields:
        _ended(lines, k)["review"]["session_id"] = fields["session_id"]


def _blocked(lines: list[dict[str, Any]]) -> None:
    _ended(lines, 1)["ending"]["review_cause"] = "blocked"
    blocking = [{"finding": "the brief gives no supply voltage", "blocking": True}]
    _review_of(lines, 1, verdict="blocked", spec_defects=blocking)


def _replanned_file(lines: list[dict[str, Any]], run_dir: Path) -> None:
    # The round's plan file and its digest changed together: the journal reads, the log disagrees.
    plan = run_dir / "decomposition" / "round-1" / "plan.json"
    plan.write_bytes(plan.read_bytes() + b" ")
    _ended(lines, 1)["plan_sha256"] = hashlib.sha256(plan.read_bytes()).hexdigest()


def _restarted(lines: list[dict[str, Any]]) -> None:
    _started(lines, 1)["started"] = _ended(lines, 1)["started"] = STEPPED


def _spent_more(one: dict[str, Any]) -> None:
    one["usage"]["input_tokens"] += 1


def _log_edited(run_dir: Path, kind: str, at: int, **fields: Any) -> None:  # noqa: ANN401
    log = events(run_dir)
    line = [one for one in log if one["kind"] == kind][at]
    line.update(fields)
    (run_dir / "events.jsonl").write_text("".join(json.dumps(one) + "\n" for one in log))


#: Each edit of a completed run's journal (or its log) that the journal's own reader accepts, and
#: what the open names as disagreeing with the log: the arm, a call, a review or the tokens.
OPEN_EDITS: dict[str, tuple[Callable[[list[dict[str, Any]], Path], None], str]] = {
    "round 1's mode": (lambda lines, _: _started(lines, 1).update(design_review="repair:1"), "arm"),
    "round 1's designer": (
        lambda lines, _: _started(lines, 1).update(decomposition_model="claude-fable-5-1"),
        "arm",
    ),
    "a call's model": (lambda lines, _: _ended(lines, 1).update(model="claude-fable-5-1"), "calls"),
    "a call's turns": (lambda lines, _: _ended(lines, 1).update(num_turns=7), "calls"),
    "a call's start": (lambda lines, _: _restarted(lines), "calls"),
    "a call's end": (lambda lines, _: _ended(lines, 1).update(call_ended=STEPPED), "calls"),
    "a round's digest and its plan file": (_replanned_file, "calls"),
    "an earlier proposal's turns, in the log": (
        lambda _, run_dir: _log_edited(run_dir, "plan_proposed", 0, num_turns=7),
        "calls",
    ),
    "an earlier proposal's start, in the log": (
        lambda _, run_dir: _log_edited(run_dir, "plan_proposed", 0, started=STEPPED),
        "calls",
    ),
    "a review's session": (lambda lines, _: _review_of(lines, 1, session_id="review-x"), "reviews"),
    "a review's verdict": (lambda lines, _: _blocked(lines), "reviews"),
    "a review's start": (
        lambda lines, _: _ended(lines, 1).update(review_started=STEPPED),
        "reviews",
    ),
    "a review's end": (lambda lines, _: _ended(lines, 1).update(ended=STEPPED), "reviews"),
    "a call's usage": (lambda lines, _: _spent_more(_ended(lines, 2)["usage"][0]), "tokens"),
    "a review's usage": (
        lambda lines, _: _spent_more(_ended(lines, 1)["review"]["usage"][0]),
        "tokens",
    ),
}


@pytest.mark.parametrize(
    ("name", "second"),
    [(name, False) for name in OPEN_EDITS]
    + [(name, True) for name, (_, what) in OPEN_EDITS.items() if what != "tokens"],
)
def test_a_journal_that_disagrees_with_its_log_is_refused_when_opened_naming_what(
    two_rounds: Path, name: str, second: bool
) -> None:
    # With ``second``, a later comparison's fault too (round 2's call tokens): the first
    # disagreement in the open's order is the one named.
    edit, what = OPEN_EDITS[name]
    lines = _journal(two_rounds)
    edit(lines, two_rounds)
    if second:
        _spent_more(_ended(lines, 2)["usage"][0])
    _write(two_rounds, lines)
    assert not isinstance(_read(two_rounds, 4), Exception), f"{name}: the journal is not read"
    found = _opened(two_rounds)
    assert isinstance(found, RunStateError), f"{name}: opened as {found!r}"
    assert found.context.get("disagrees") == what, found.context


#: Honest endings that start a run, under every reviewing mode: each opens.
HONEST = {
    "observe, a failed plan call": ("observe", [Step(call="api_error")]),
    "observe, a refused plan": ("observe", [Step(refusal="plan_refused")]),
    "observe, an infrastructure review": ("observe", [Step(review="infrastructure")]),
    "observe, a fail": ("observe", [Step()]),
    "on, no plan": ("on", [Step(call="no_structured_output")]),
    "on, an exposure": ("on", [Step(review="exposed")]),
    "repair:1, an exposure at round 2": ("repair:1", [Step(), Step(review="exposed")]),
    "repair:2, a canary at round 2": ("repair:2", [Step(), Step(review="canary")]),
    "repair:2, no verdict at round 3": ("repair:2", [Step(), Step(), Step(review="no_verdict")]),
    "repair:1, held at the last round": ("repair:1", [Step(), Step()]),
    "repair:2, a refused plan at round 2": ("repair:2", [Step(), Step(refusal="plan_refused")]),
}


@pytest.mark.parametrize("name", list(HONEST))
def test_every_honest_ending_that_starts_a_run_opens(tmp_path: Path, name: str) -> None:
    policy, steps = HONEST[name]
    ran = decompose(tmp_path, policy, steps)
    assert (ran.run_dir / "events.jsonl").exists(), f"{name}: no run was started ({ran.code!r})"
    found = _opened(ran.run_dir)
    assert not isinstance(found, Exception), f"{name}: {found!r}"
