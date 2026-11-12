"""Under ``repair:N`` a plan its review did not pass is re-planned at most N times, each reviewed.

A round is a call, the start check of its plan and that plan's review. What follows a round
depends only on how it ended and on whether it is round N + 1: a verdict other than a pass re-plans
while rounds remain and no canary is in its findings, and is held as under ``on`` otherwise; a pass
starts the run; no verdict holds it; no plan records a failed decomposition; the instrument's
failure (of the call, of the start check's library or target, of the review) ends ``decompose``
with no run; a held-out exposure halts the run it starts.

Each round is written to the round journal when it ends, its plan to its own file, and the run's
opening carries every round's tokens and one review line per reviewed round, so whatever a later
round does, rounds 1 … j − 1 read as a shorter ``repair:`` run's do. A kill leaves the rounds that
ended, and the directory is refused.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, get_args

import pytest
from replan_rig import (
    BRIEF,
    CANARY,
    UNAVAILABLE,
    Ran,
    Step,
    Stopped,
    decompose,
    events,
    journal,
    plan_file,
    plan_of,
    round_dir,
    rounds_record,
    verdict,
)

from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.decompose import (
    FailureCause,
    replan_findings,
    replan_prompt,
    require_fresh,
)
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.plan import plan_sha256
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.trajectory import seal

ROLES = ["electrical"]
ITEM = "run-1-plan"
#: The plan call's causes that are the designer's: each a failed decomposition, never a re-plan.
NO_PLAN = {
    "no_structured_output",
    "invalid_plan",
    "schema_refused",
    "wall_clock",
    "turn_limit",
    "malformed_output",
    "context_exceeded",
    "refused",
}


def _reviews(run_dir: Path) -> list[dict[str, Any]]:
    return [one for one in events(run_dir) if one["kind"] == "design_review_ran"]


def _ended(run_dir: Path) -> list[dict[str, Any]]:
    return [one for one in journal(run_dir) if one["kind"] == "round_ended"]


def _one(found: list[Any]) -> Any:  # noqa: ANN401 - the one element
    assert len(found) == 1, found
    return found[0]


def _last(run_dir: Path) -> dict[str, Any]:
    lines = journal(run_dir)
    assert lines, "no round journal"
    return lines[-1]


def _held(ran: Ran) -> list[Any]:
    found = read_queue(ran.run_dir).open_items()
    return [i for i in found if getattr(i, "source", None) == "plan_review"]


@pytest.mark.parametrize("n", [1, 2, 3])
def test_repair_n_replans_at_most_n_times_then_holds_as_on(tmp_path: Path, n: int) -> None:
    ran = decompose(tmp_path, f"repair:{n}", [Step()] * (n + 2))
    assert ran.code == 0, ran.code
    assert len(ran.script.calls) == n + 1
    assert len(ran.script.seen) == n + 1
    log = events(ran.run_dir)
    assert log[0]["design_review"] == f"repair:{n}"
    reviews = _reviews(ran.run_dir)
    assert [r.get("held_item") for r in reviews] == [None] * n + [ITEM]
    assert [r["plan_sha256"] for r in reviews] == [plan_sha256(plan_of(k)) for k in range(1, n + 2)]
    decomposed = _one([one for one in log if one["kind"] == "decomposed"])
    assert decomposed["plan_sha256"] == plan_sha256(plan_of(n + 1))
    assert len(_held(ran)) == 1


def test_each_replan_is_reviewed_again(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:2", [Step(), Step(review="blocked"), Step(review="pass")])
    assert ran.code == 0, ran.code
    assert [call["workdir"] for call in ran.script.calls] == [
        round_dir(ran.run_dir, k) for k in (1, 2, 3)
    ]
    assert ran.script.calls[0].get("prompt") is None
    for k, kind in ((1, "fail"), (2, "blocked")):
        told = replan_prompt(BRIEF, ROLES, plan_of(k), replan_findings(verdict(k, kind)))
        assert ran.script.calls[k]["prompt"] == told
    for k, under in enumerate(ran.script.seen, start=1):
        stream = round_dir(ran.run_dir, k) / "stdout.jsonl"
        assert under.plan == plan_of(k)
        assert under.plan_sha256 == plan_sha256(plan_of(k))
        assert Path(under.stream) == stream
        # Each round's stream is its own, still the bytes its call wrote.
        assert f'"round": {k}' in stream.read_text()
        assert under.stream_seal == seal(stream.read_bytes())
    assert [r.get("held_item") for r in _reviews(ran.run_dir)] == [None, None, None]
    assert _held(ran) == []


@pytest.mark.parametrize("mode", ["on", "repair:3"])
def test_a_canary_in_a_finding_holds_the_plan_and_makes_no_call(tmp_path: Path, mode: str) -> None:
    ran = decompose(tmp_path, mode, [Step(review="canary"), Step()])
    assert ran.code == 0, ran.code
    assert len(ran.script.calls) == 1
    ended = _one(_ended(ran.run_dir))
    # Recorded under every reviewing mode, so a round's record names no N.
    assert ended["ending"]["canary"] == "held_out"
    assert ended["ending"]["review_cause"] == "fail"
    review = _one(_reviews(ran.run_dir))
    assert review["result"]["verdict"] == "fail"
    assert review.get("held_item") == ITEM
    assert all(CANARY not in str(call.get("prompt")) for call in ran.script.calls)


@pytest.mark.parametrize("cause", UNAVAILABLE)
def test_an_unavailable_review_holds_without_a_replan(tmp_path: Path, cause: str) -> None:
    ran = decompose(tmp_path, "repair:2", [Step(review=cause), Step()])
    assert ran.code == 0, ran.code
    assert len(ran.script.calls) == 1
    review = _one(_reviews(ran.run_dir))
    assert review["unavailable"]["cause"] == cause
    assert review.get("held_item") == ITEM
    assert len(_held(ran)) == 1


# A call refused by its schema is made once more first, and ends the run only when refused again:
# held in the rows of a decomposition refused by its schema.
@pytest.mark.parametrize("cause", ["invalid_plan", "wall_clock", "plan_refused"])
def test_a_no_plan_round_ends_the_run_without_a_replan(tmp_path: Path, cause: str) -> None:
    second = Step(refusal=cause) if cause == "plan_refused" else Step(call=cause)
    ran = decompose(tmp_path, "repair:3", [Step(), second, Step()])
    assert ran.code == 1, ran.code
    assert len(ran.script.calls) == 2
    log = events(ran.run_dir)
    assert log, "no run recorded"
    assert log[-1]["kind"] == "halted"
    assert log[-1]["reason"] == "decomposition_failed"
    assert log[-1]["detail"].startswith(f"{cause}: ")
    # The round before it is kept on the record, and nothing is held.
    assert len(_reviews(ran.run_dir)) == 1
    assert _held(ran) == []


def test_under_on_a_plan_refused_for_its_content_is_a_recorded_failed_run(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "on", [Step(refusal="plan_refused")])
    assert ran.code == 1, ran.code
    assert len(ran.script.seen) == 0
    log = events(ran.run_dir)
    assert [one["kind"] for one in log][-1:] == ["halted"]
    assert log[-1]["detail"].startswith("plan_refused: ")


@pytest.mark.parametrize(
    "cause", ["infrastructure", "unprepared", "invocation_error", "model_separation"]
)
@pytest.mark.parametrize("mode", ["on", "repair:2"])
def test_an_infrastructure_review_failure_is_never_an_item_nor_a_replan(
    tmp_path: Path, mode: str, cause: str
) -> None:
    ran = decompose(tmp_path, mode, [Step(review=cause), Step()])
    assert ran.code == 2, ran.code
    assert len(ran.script.calls) == 1
    assert not (ran.run_dir / "events.jsonl").exists()
    assert not (ran.run_dir / "queue.jsonl").exists()
    last = _last(ran.run_dir)
    assert last["kind"] == "rounds_ended"
    assert (last["round"], last["follows"], last["cause"]) == (1, "void", cause)
    assert last["ending_class"] == "infrastructure"


def test_observe_still_records_an_infrastructure_review_and_starts_the_run(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "observe", [Step(review="infrastructure")])
    assert ran.code == 0, ran.code
    review = _one(_reviews(ran.run_dir))
    assert review["unavailable"]["cause"] == "infrastructure"
    assert review.get("held_item") is None


# -- the injection matrix ---------------------------------------------------------------

_CALL_CAUSES = [f"call:{cause}" for cause in get_args(FailureCause)]
ENDINGS = [
    "pass",
    "fail",
    "blocked",
    *UNAVAILABLE,
    "infrastructure",
    "unprepared",
    "canary",
    "exposed",
    "invocation_error",
    "model_separation",
    *_CALL_CAUSES,
    "plan_refused",
    "library_refused",
    "accounting",
    "kill",
]


def _step(ending: str) -> Step:
    if ending.startswith("call:"):
        return Step(call=ending.removeprefix("call:"))
    if ending in ("plan_refused", "library_refused"):
        return Step(refusal=ending)
    if ending == "accounting":
        return Step(call="accounting")
    if ending == "kill":
        return Step(call="stop")
    return Step(review=ending)


def _expected(ending: str, k: int) -> tuple[int, str, str]:
    """The round a ``repair:3`` run ends on, what follows it, and the cause it is ended by."""
    cause = {
        "canary": "fail",
        "exposed": "held_out_exposed",
        "accounting": "accounting_mismatch",
    }.get(ending, ending.removeprefix("call:"))
    if ending in ("fail", "blocked"):
        return (k, "start", cause) if k == 4 else (k + 1, "start", "pass")
    if ending.startswith("call:") or ending == "plan_refused":
        return k, "fail_run" if cause in NO_PLAN | {"plan_refused"} else "void", cause
    if ending in ("pass", "canary", "exposed", *UNAVAILABLE):
        return k, "start", cause
    return k, "void", cause


@pytest.fixture(scope="module")
def shorter(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Ran]:
    """For each j, the run ending at round j − 1 on the same script: ``on``, then ``repair:j−2``."""
    found: dict[int, Ran] = {}
    for j in (2, 3, 4):
        mode = "on" if j == 2 else f"repair:{j - 2}"
        found[j] = decompose(tmp_path_factory.mktemp(f"shorter-{j}"), mode, [Step()] * (j - 1))
    return found


@pytest.mark.parametrize("ending", ENDINGS)
@pytest.mark.parametrize("j", [2, 3, 4])
def test_every_round_survives_what_comes_after_it(
    tmp_path: Path, shorter: dict[int, Ran], j: int, ending: str
) -> None:
    assert shorter[j].code == 0, shorter[j].code
    # A call refused by its schema is made once more, inside its round: the round ends refused
    # only when its second call is refused too.
    again = 2 if ending == "call:schema_refused" else 1
    ran = decompose(tmp_path, "repair:3", [*[Step()] * (j - 1), *[_step(ending)] * again])
    end, follows, cause = _expected(ending, j)
    started = ending != "kill" and follows != "void"
    # Rounds 1 … j − 1 are what the shorter run recorded, whatever round j did.
    assert rounds_record(ran.run_dir, j - 1, opening=started) == rounds_record(
        shorter[j].run_dir, j - 1, opening=started
    )
    for k in range(1, j):
        line = _one([one for one in _ended(ran.run_dir) if one["round"] == k])
        assert (
            hashlib.sha256(plan_file(ran.run_dir, k).read_bytes()).hexdigest()
            == (line["plan_sha256"])
        )
    last = _last(ran.run_dir)
    if ending == "kill":
        assert isinstance(ran.code, Stopped), ran.code
        assert (last["kind"], last["round"]) == ("round_started", j)
        assert not (ran.run_dir / "events.jsonl").exists()
        return
    # The run ends with a record that names how it ended, and at which round.
    assert last["kind"] == "rounds_ended"
    assert (last["round"], last["follows"], last["cause"]) == (end, follows, cause)
    assert len(ran.script.calls) == end + again - 1
    if follows == "void":
        assert ran.code == 2, ran.code
        assert not (ran.run_dir / "events.jsonl").exists()
        return
    reviews = _reviews(ran.run_dir)
    log = events(ran.run_dir)
    if follows == "fail_run":
        assert ran.code == 1, ran.code
        assert len(reviews) == end - 1
        assert (log[-1]["reason"], log[-1]["detail"].split(":")[0]) == (
            "decomposition_failed",
            cause,
        )
        assert _held(ran) == []
        return
    if ending == "exposed":
        assert ran.code == 1, ran.code
        assert [one["kind"] for one in log[-2:]] == ["incident", "halted"]
        assert len(reviews) == end - 1
        return
    assert ran.code == 0, ran.code
    assert len(reviews) == end
    holds = cause != "pass"
    assert [r.get("held_item") for r in reviews] == [None] * (end - 1) + [ITEM if holds else None]
    assert len(_held(ran)) == (1 if holds else 0)


# -- a kill, the journal, the token account, the prompt -----------------------------------


def _stop_on_second(real: Any) -> Any:  # noqa: ANN401 - the loop's function, wrapped
    made: list[int] = []

    def stopping(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        made.append(1)
        if len(made) == 2:
            raise Stopped
        return real(*args, **kwargs)

    return stopping


@pytest.mark.parametrize(
    ("point", "ended"),
    [("before_the_call", 1), ("after_the_call", 1), ("in_the_review", 1), ("after_its_line", 2)],
)
def test_a_killed_decompose_leaves_its_rounds_and_the_directory_is_refused(
    tmp_path: Path, point: str, ended: int
) -> None:
    import physgate.orchestrator.decompose as decompose_module

    second = {
        "before_the_call": Step(call="stop"),
        "after_the_call": Step(call="stop-after"),
        "in_the_review": Step(review="stop"),
        "after_its_line": Step(),
    }[point]
    patches = (
        {"replan_prompt": _stop_on_second(decompose_module.replan_prompt)}
        if point == "after_its_line"
        else None
    )
    ran = decompose(tmp_path, "repair:3", [Step(), second, Step()], loop_patches=patches)
    assert isinstance(ran.code, Stopped), ran.code
    lines = journal(ran.run_dir)
    assert [(one["kind"], one["round"]) for one in lines][: 2 * ended] == [
        (kind, k) for k in range(1, ended + 1) for kind in ("round_started", "round_ended")
    ]
    assert all(one["kind"] != "rounds_ended" for one in lines)
    assert not (ran.run_dir / "events.jsonl").exists()
    refused = None
    try:
        require_fresh(ran.run_dir)
    except RunStateError as exc:
        refused = exc
    assert refused is not None, "a directory holding a killed decomposition's rounds was taken"
    assert f"round {ended}" in str(refused), str(refused)


def test_every_journal_line_is_synced_where_it_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real = os.fsync

    def synced(fd: int) -> None:
        sizes.append(os.fstat(fd).st_size)
        real(fd)

    monkeypatch.setattr(os, "fsync", synced)
    ran = decompose(tmp_path, "repair:1", [Step(), Step()])
    assert ran.code == 0, ran.code
    raw = (ran.run_dir / "decomposition" / "rounds.jsonl").read_bytes().splitlines(keepends=True)
    assert len(raw) == 5, raw
    ends = [sum(len(line) for line in raw[: i + 1]) for i in range(len(raw))]
    # Each line was on disk, synced, when it had just been written: not only once at the end.
    assert all(end in sizes for end in ends), (ends, sizes)


def test_decomposition_invocations_equal_rounds(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:3", [Step()] * 4)
    assert ran.code == 0, ran.code
    account = TokenAccount.from_events(list(read_events(ran.run_dir / "events.jsonl")))
    assert account.decomposition_invocations() == 4
    account.assert_no_routing()
    assert sorted(a for a in account.by_attribution() if a.startswith("reviewer:")) == [
        f"reviewer:review-{k}" for k in (1, 2, 3, 4)
    ]


def test_the_round_three_prompt_equals_round_two_s_from_the_same_plan_and_findings(
    tmp_path: Path,
) -> None:
    once = decompose(tmp_path / "once", "repair:1", [Step(), Step()])
    thrice = decompose(tmp_path / "thrice", "repair:3", [Step(), Step(said=1), Step(review="pass")])
    assert once.code == 0 and thrice.code == 0, (once.code, thrice.code)
    assert len(once.script.calls) == 2 and len(thrice.script.calls) == 3
    at_two = once.script.calls[1]["prompt"]
    assert at_two == replan_prompt(BRIEF, ROLES, plan_of(1), replan_findings(verdict(1, "fail")))
    assert thrice.script.calls[2]["prompt"] == at_two


def test_off_writes_no_round_journal_and_observe_writes_one(tmp_path: Path) -> None:
    off = decompose(tmp_path / "off", "off", [Step()])
    assert off.code == 0, off.code
    assert not (off.run_dir / "decomposition" / "rounds.jsonl").exists()
    observed = decompose(tmp_path / "observe", "observe", [Step()])
    assert observed.code == 0, observed.code
    assert [one["kind"] for one in journal(observed.run_dir)] == [
        "round_started",
        "round_ended",
        "rounds_ended",
    ]
