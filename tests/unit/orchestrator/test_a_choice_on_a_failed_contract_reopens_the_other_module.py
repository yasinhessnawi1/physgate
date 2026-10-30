"""A person's choice on a failed contract's item keeps one module's work and reopens the other.

The chosen position is the module whose merged work stands. The other module reopens to conform to
the interface, which is fixed at decomposition, when only it deviates, its planning subtask has an
attempt or its one fix left, and the integration call is not on the record; otherwise the choice
records only, and the item says why. The decision line names the subtask it reopens, and the next
line about any subtask is the reopen, bound to the decision: replay refuses one no decision
explains. The reopened attempt spends the subtask's own budget, starts in a fresh worktree from the
run head, and is told the interface's values by a code-built order, never a session's words. The
earlier merge stays on the record, the pair is retested and never marked first, and completion
reads each pair's latest result. In a run that acts, the closing pass and the system gate wait for
an undecided contract item; a run that records only never waits.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, KilledError, Rig, seal
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    ITEM,
    escaped,
    item_of,
    kinds,
    lines,
    refusal,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    BUDGET,
    CLOSING,
    DRIVE,
    FW,
    INTEG,
    P_BACK,
    P_FW,
    comparable,
    hooked,
    node,
    rig_for,
    start,
)
from test_a_queue_decision_acts_at_a_boundary import _layer
from test_every_merge_path_git_call_is_pinned_or_in_the_store import _git, _target

from physgate import roles
from physgate.evaluation.observe.sequence import decisions
from physgate.orchestrator import decisions as deciding
from physgate.orchestrator.declaration import Declaration
from physgate.orchestrator.dispatch import role_prompt
from physgate.orchestrator.events import Event, read_events
from physgate.orchestrator.merge import GitMerger, RunGit, commit_attempt
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.replay import replay
from physgate.oslayer.probe import Present
from physgate.reviewers.packet import person_order_text

ACTS = {
    "queue_decisions": "act",
    "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
}
DECLARED = (DRIVE, FW)
BOTH = ("iface.drive", "iface.tilt")
#: fw's node as the interface holds it, which a reopened fw writes.
MENDED_FW = node("fw.main", "firmware", *BOTH, v=12, period=10)
MENDED_DRIVE = node("drive.motor", "control", *BOTH, v=12, period=10)
LEAD = (
    'The interface contract of module "drive" (producer, subtask "drive-0a1b2c") to module "fw" '
    '(consumer, subtask "fw-3d4e5f") failed after both merged. The interfaces are fixed at '
    "decomposition, and no run changes them. "
)
CHOOSE = "Decide whose merged work stands: choose producer or choose consumer. "


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def mend(rig: Rig, payloads: dict[str, dict[str, Any]]) -> None:
    """Each subtask in ``payloads`` writes its payload from its second attempt's commit on."""
    graph = rig.diff
    first: dict[str, str] = {}
    original = graph.proposals  # type: ignore[attr-defined]

    def proposals(subtask_id: str, attempt_commit: str, role: str) -> list[dict[str, Any]]:
        seen = first.setdefault(subtask_id, attempt_commit)
        if subtask_id in payloads and attempt_commit != seen:
            return [payloads[subtask_id]]
        return list(original(subtask_id, attempt_commit, role))

    graph.proposals = proposals  # type: ignore[attr-defined]


def opened(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    acts: bool = True,
    sizing: bool = False,
    mended: dict[str, dict[str, Any]] | None = None,
    writes: dict[str, list[dict[str, Any]]] | None = None,
    declared: Sequence[str] = DECLARED,
    kill: Callable[[Event, list[Event]], bool] | None = None,
    **fields: Any,  # noqa: ANN401 - the rig's own
) -> Rig:
    """The contract rig, run until it stops; fw deviates on ``v`` unless ``fw_volts`` says else."""
    fields.setdefault("fw_volts", 11)
    fields.setdefault("dispatcher", FakeDispatcher(trajectories=tmp_path / "run" / "sessions"))
    rig = rig_for(tmp_path, **fields)
    if acts:
        rig.config_overrides.update(ACTS)
    rig.diff.writes.update(writes or {})  # type: ignore[attr-defined]
    mend(rig, {FW: MENDED_FW} if mended is None else mended)
    loop = rig.open()
    hooked(monkeypatch, loop, declared=declared, kill=kill)
    start(loop, sizing=sizing)
    if acts:
        _layer(loop)
    with contextlib.suppress(KilledError):
        loop.run()
    loop.close()
    return rig


def again(
    rig: Rig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kill: Callable[[Event, list[Event]], bool] | None = None,
    declared: Sequence[str] = DECLARED,
) -> str:
    """A fresh process resumes the run; the step it stopped at, or ``killed``."""
    loop = rig.open()
    hooked(monkeypatch, loop, declared=declared, kill=kill)
    if rig.config_overrides.get("queue_decisions") == "act":
        _layer(loop)
    try:
        return loop.resume().kind
    except KilledError:
        return "killed"
    finally:
        loop.close()


def choose(run_dir: Path, position: str, note: str | None = None, item_id: str = ITEM) -> None:
    view = read_queue(run_dir)
    assert item_id in view.digests, "the item is not listed"
    shown = ShownItem(
        item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
    )
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(verb="choose", note=note, position=position),  # type: ignore[arg-type]
        resolved_by="yasin",
        shown=shown,
    )


def chosen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    position: str = "producer",
    *,
    note: str | None = None,
    kill: Callable[[Event, list[Event]], bool] | None = None,
    **kw: Any,  # noqa: ANN401 - opened's own
) -> Rig:
    rig = opened(tmp_path, monkeypatch, **kw)
    choose(rig.run_dir, position, note)
    again(rig, monkeypatch, kill=kill, declared=kw.get("declared", DECLARED))
    return rig


def of(rows: Sequence[dict[str, Any]], kind: str, **match: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    return [r for r in rows if r["kind"] == kind and all(r.get(k) == v for k, v in match.items())]


def requests_of(rig: Rig, subtask: str) -> list[Any]:
    return [r for r in rig.dispatcher.requests if r.subtask_id == subtask]


CONFORM = (
    "A person kept the other module's work on the failed interface contract of queue item "
    '"run-1-contract-1", and reopened this module, merged at attempt 1, to conform to the '
    "interface. The interfaces are fixed at decomposition. Write each value below into this "
    "module's node, as the interface holds it.\n"
    "\n"
    "The clauses this module fails:\n"
    "<<<\n"
    'Interface "iface.drive", quantity "v": the interface holds 12 "volt" (fixed at '
    'decomposition, revision 1); node "fw.main" holds 11 "volt" (revision 4, written by subtask '
    '"fw-3d4e5f" in role "firmware").\n'
    ">>>\n"
    "The specification as issued otherwise still governs."
)


# --- the deciding rule, and what the item says ---------------------------------------------------


def test_choosing_a_position_reopens_the_other_module_with_the_interfaces_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch)
    item = item_of(rig)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "reopen", "consumer": "record_only"}
    assert item.decision_required == (
        f"{LEAD}The consumer's nodes deviate from the interface. {CHOOSE}"
        'Choosing the producer keeps its work and reopens module "fw" for one more attempt '
        "(attempt 2), told the interface's values. Choosing the consumer records only: its own "
        "nodes break the contract."
    )
    choose(rig.run_dir, "producer")
    assert again(rig, monkeypatch) == "done"
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken")
    assert (taken["effect"], taken["acts"], taken["why_not"]) == ("reopen", True, None)
    assert taken.get("reopens") == FW
    at = rows.index(taken)
    reopened = rows[at + 1]
    assert reopened["kind"] == "subtask_reopened"
    merged = of(rows, "merged", subtask_id=FW)
    assert len(merged) == 2
    assert {k: reopened.get(k) for k in ("subtask_id", "item_id", "attempt", "merge_commit")} == {
        "subtask_id": FW,
        "item_id": ITEM,
        "attempt": 2,
        "merge_commit": merged[0]["merge_commit"],
    }
    assert reopened.get("shown_sha256") == taken["shown_sha256"]
    # The reopened attempt is told the interface's values, by code, and nothing else.
    fw = requests_of(rig, FW)
    assert [(r.attempt, r.kind) for r in fw] == [(1, "attempt"), (2, "attempt")]
    assert fw[1].repair_instruction == CONFORM
    seen = [a for a in rig.reviewer.seen if a.subtask_id == FW]
    assert len(seen) == 2
    order = seen[1].ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == ("contract_conform", ITEM, 1)
    told = person_order_text(order).decode()
    assert told.startswith(
        "This attempt reopens a merged module, ordered by a person on queue item "
        f"{ITEM} to conform to the interface's values."
    )
    # Only the reopened attempt: drive is never dispatched again.
    assert len(requests_of(rig, DRIVE)) == 1
    assert refusal(rows) is None


def test_a_position_whose_module_breaks_the_contract_records_only_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The producer deviates: choosing it records only; choosing the consumer reopens drive.
    low = node("drive.motor", "control", *BOTH, v=11, period=10)
    rig = opened(
        tmp_path, monkeypatch, fw_volts=12, writes={DRIVE: [low]}, mended={DRIVE: MENDED_DRIVE}
    )
    item = item_of(rig)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "record_only", "consumer": "reopen"}
    assert item.decision_required == (
        f"{LEAD}The producer's nodes deviate from the interface. {CHOOSE}"
        "Choosing the producer records only: its own nodes break the contract. Choosing the "
        'consumer keeps its work and reopens module "drive" for one more attempt (attempt 2), '
        "told the interface's values."
    )
    choose(rig.run_dir, "producer")
    again(rig, monkeypatch)
    rows = lines(rig)
    (taken,) = of(rows, "decision_taken")
    assert (taken["effect"], taken["acts"], taken["why_not"]) == (
        "none",
        False,
        "record_only_source",
    )
    assert "reopens" not in taken
    assert "subtask_reopened" not in kinds(rows)
    assert len(requests_of(rig, DRIVE)) == 1
    # A line that says the choice reopens is refused, for either module.
    at = rows.index(taken)
    for target in (DRIVE, FW):
        forged = taken | {"effect": "reopen", "acts": True, "why_not": None, "reopens": target}
        why = refusal([*rows[:at], forged])
        assert why is not None and "does other than the record allows" in why, why


def test_both_sides_deviating_records_only_and_names_the_interface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    low = node("drive.motor", "control", *BOTH, v=11, period=10)
    rig = opened(tmp_path, monkeypatch, writes={DRIVE: [low]})
    item = item_of(rig)
    assert item.consequence is not None
    assert item.consequence.on_choose == {"producer": "record_only", "consumer": "record_only"}
    assert item.consequence.confirmed_indicators == ()
    assert item.decision_required == (
        f"{LEAD}Both modules' nodes deviate from the interface. {CHOOSE}"
        "Either choice records only: the interface, fixed at decomposition, disagrees with both "
        "modules, and a new decomposition is the remedy."
    )
    choose(rig.run_dir, "consumer")
    again(rig, monkeypatch)
    rows = lines(rig)
    assert [(t["effect"], t["why_not"]) for t in of(rows, "decision_taken")] == [
        ("none", "record_only_source")
    ]
    assert "subtask_reopened" not in kinds(rows)


def test_a_run_that_records_only_says_so_on_the_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch, acts=False)
    item = item_of(rig)
    assert item.consequence is None
    assert item.decision_required == (
        f"{LEAD}The consumer's nodes deviate from the interface. {CHOOSE}"
        "In this run a choice is recorded, and nothing in the run acts on it."
    )


# --- the budget ----------------------------------------------------------------------------------


def _merged_at_three(rig: Rig) -> None:
    # fw's first two attempts are rejected by review (reviews 2 and 3), the third merges.
    rig.reviewer.verdicts[:] = ["pass", "fail", "fail"]


@pytest.mark.parametrize("merged_at", [1, 3, "fix"])
def test_a_reopen_spends_the_subtasks_own_budget_and_never_a_fresh_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merged_at: int | str
) -> None:
    rig = rig_for(tmp_path, fw_volts=11, dispatcher=FakeDispatcher(trajectories=tmp_path / "s"))
    rig.config_overrides.update(ACTS)
    mend(rig, {FW: MENDED_FW})
    if merged_at == 3:
        _merged_at_three(rig)
    if merged_at == "fix":
        rig.reviewer.results[2] = blocked_review()
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    start(loop)
    _layer(loop)
    loop.run()
    loop.close()
    if merged_at == "fix":
        # A person orders the one fix after fw's blocked review; the fix merges.
        view = read_queue(rig.run_dir)
        blocked = next(i for i in view.items if i.subtask_id == FW)
        record_decision(
            rig.run_dir,
            blocked.item_id,
            person=PersonDecision(verb="reject", note="give the pole", position=None),
            resolved_by="yasin",
            shown=ShownItem(
                item_sha256=view.digests[blocked.item_id],
                trajectories=statuses_now(rig.run_dir, blocked.item_id),
            ),
        )
        again(rig, monkeypatch)
    item = item_of(rig)
    assert item.consequence is not None
    words = item.decision_required
    if merged_at == 1:
        assert item.consequence.on_choose["producer"] == "reopen"
        assert 'reopens module "fw" for one more attempt (attempt 2)' in words
    elif merged_at == 3:
        assert item.consequence.on_choose["producer"] == "reopen"
        assert 'reopens module "fw" for one more attempt (its one fix)' in words
    else:
        assert item.consequence.on_choose["producer"] == "record_only"
        assert 'Choosing the producer records only: module "fw" has no attempt left.' in words
    choose(rig.run_dir, "producer")
    again(rig, monkeypatch)
    rows = lines(rig)
    fw = requests_of(rig, FW)
    if merged_at == "fix":
        assert "subtask_reopened" not in kinds(rows)
        assert [r.attempt for r in fw] == [1, 2]
        return
    k = 1 if merged_at == 1 else 3
    (reopened,) = of(rows, "subtask_reopened")
    assert reopened["attempt"] == k + 1
    assert [r.attempt for r in fw][-1] == k + 1
    assert fw[-1].kind == ("attempt" if k == 1 else "fix")
    assert fw[-1].repair_instruction is not None
    assert f"merged at attempt {k}," in fw[-1].repair_instruction
    # The ledger names the item that reopened the subtask; the attempt count goes on from k.
    ledger = [json.loads(x) for x in (rig.run_dir / "ledger.jsonl").read_bytes().splitlines()]
    last = [x for x in ledger if x["id"] == FW][-1]
    assert (last.get("reopened_by"), last["attempt_count"]) == (ITEM, k + 1)
    assert refusal(rows) is None


# --- replay holds the reopen to its decision -----------------------------------------------------


def _reopen_line(rows: Sequence[dict[str, Any]], **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    fw_merge = of(rows, "merged", subtask_id=FW)[0]
    base = {k: v for k, v in rows[-1].items() if k in ("ts", "run_id", "gate_mode")} | {
        "kind": "subtask_reopened",
        "subtask_id": FW,
        "item_id": ITEM,
        "shown_sha256": read_queue_digest(rows),
        "merge_commit": fw_merge["merge_commit"],
        "attempt": 2,
    }
    return base | changes


def read_queue_digest(rows: Sequence[dict[str, Any]]) -> str:
    taken = of(rows, "decision_taken")
    return str(taken[0]["shown_sha256"]) if taken else "0" * 64


def test_replay_refuses_a_reopen_no_decision_explains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bypass: a reopen line appended straight to the log, with no decision before it.
    rig = opened(tmp_path, monkeypatch)
    rows = lines(rig)
    assert "contract_item_raised" in kinds(rows)
    assert "decision_taken" not in kinds(rows)
    forged = _reopen_line(rows) | {"seq": len(rows)}
    why = refusal([*rows, forged])
    assert why is not None and "no taken decision explains" in why, why
    path = rig.run_dir / "events.jsonl"
    path.write_bytes(path.read_bytes() + json.dumps(forged).encode() + b"\n")
    dispatched = len(rig.dispatcher.requests)
    opening = escaped(rig.open)
    assert opening is not None and "CorruptEventLogError" in opening, opening
    assert "no taken decision explains" in opening, opening
    assert len(rig.dispatcher.requests) == dispatched
    # With the decision taken and the reopen not yet written: another subtask, commit or digest.
    cut = chosen(tmp_path / "decided", monkeypatch, kill=lambda e, _: e.kind == "subtask_reopened")
    held = lines(cut)
    assert kinds(held)[-1] == "decision_taken", kinds(held)[-3:]
    assert refusal([*held, _reopen_line(held)]) is None
    for wrong in (
        {"subtask_id": DRIVE},
        {"merge_commit": "f" * 40},
        {"shown_sha256": "f" * 64},
        {"item_id": f"{ITEM}-r2"},
        {"attempt": 3},
    ):
        why = refusal([*held, _reopen_line(held, **wrong)])
        assert why is not None and "reopen" in why, (wrong, why)
    # A second reopen for the one decision.
    twice = [*held, _reopen_line(held), _reopen_line(held)]
    why = refusal(twice)
    assert why is not None and "no taken decision explains" in why, why
    # Nothing about another subtask comes between the decision and its reopen.
    resolve = of(lines(chosen(tmp_path / "whole", monkeypatch)), "stage_entered", subtask_id=FW)
    assert resolve, "fw was never reopened"
    why = refusal([*held, resolve[-1]])
    assert why is not None and "reopen" in why, why


@pytest.mark.parametrize(
    "cut",
    [
        "between the decision and the reopen",
        "between the reopen and the resolve",
        "between the reopened merge's diff and its retests",
    ],
)
def test_a_kill_between_the_decision_and_the_reopen_resumes_to_exactly_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cut: str
) -> None:
    def reopened(written: list[Event]) -> bool:
        return any(e.kind == "subtask_reopened" for e in written)

    kills: dict[str, Callable[[Event, list[Event]], bool]] = {
        "between the decision and the reopen": lambda e, _: e.kind == "subtask_reopened",
        "between the reopen and the resolve": lambda e, w: (
            e.kind == "stage_entered" and reopened(w)
        ),
        "between the reopened merge's diff and its retests": lambda e, w: (
            e.kind == "contract_tested" and reopened(w)
        ),
    }
    reference = chosen(tmp_path / "reference", monkeypatch)
    rig = chosen(tmp_path / "cut", monkeypatch, kill=kills[cut])
    assert of(lines(rig), "decision_taken"), "the decision was not taken"
    assert again(rig, monkeypatch) == "done"
    rows = lines(rig)
    assert len(of(rows, "subtask_reopened")) == 1
    ours = json.dumps(comparable(read_events(rig.run_dir / "events.jsonl")), default=str)
    theirs = json.dumps(comparable(read_events(reference.run_dir / "events.jsonl")), default=str)
    assert ours.replace(str(rig.run_dir), "RUN") == theirs.replace(str(reference.run_dir), "RUN")
    assert refusal(rows) is None


def test_a_kill_inside_the_reopened_attempt_resumes_it_with_the_same_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = chosen(tmp_path / "reference", monkeypatch)
    rig = chosen(
        tmp_path / "cut",
        monkeypatch,
        kill=lambda e, w: e.kind == "gate_ran" and any(x.kind == "subtask_reopened" for x in w),
    )
    assert again(rig, monkeypatch) == "done"
    rows = lines(rig)
    assert len(of(rows, "subtask_reopened")) == 1
    assert [r["subtask_id"] for r in of(rows, "module_completed")] == [DRIVE, FW]
    # The attempt resumes from its completed session: no session is spawned again.
    ours, theirs = requests_of(rig, FW), requests_of(reference, FW)
    assert [(r.attempt, r.repair_instruction) for r in ours] == [
        (r.attempt, r.repair_instruction) for r in theirs
    ]
    assert len(ours) == 2
    assert refusal(rows) is None


def test_a_kill_on_the_way_to_a_second_round_resumes_to_the_uninterrupted_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reopened attempt still deviates: its retest fails, is ruled, and a round-2 item follows.
    def after_reopen(kind: str) -> Callable[[Event, list[Event]], bool]:
        return lambda e, w: e.kind == kind and any(x.kind == "subtask_reopened" for x in w)

    reference = chosen(tmp_path / "reference", monkeypatch, mended={})
    rows = lines(reference)
    raised = of(rows, "contract_item_raised")
    assert [r["item_id"] for r in raised] == [ITEM, f"{ITEM}-r2"]
    for kind in ("contract_ruled", "contract_item_raised"):
        rig = chosen(tmp_path / kind, monkeypatch, mended={}, kill=after_reopen(kind))
        again(rig, monkeypatch)
        ours = json.dumps(comparable(read_events(rig.run_dir / "events.jsonl")), default=str)
        theirs = json.dumps(
            comparable(read_events(reference.run_dir / "events.jsonl")), default=str
        )
        assert ours.replace(str(rig.run_dir), "RUN") == theirs.replace(
            str(reference.run_dir), "RUN"
        )
        assert [i.item_id for i in read_queue(rig.run_dir).items] == [ITEM, f"{ITEM}-r2"]


# --- the worktree, the record, the rerun, completion ---------------------------------------------


def test_a_reopened_attempt_starts_in_a_fresh_worktree_from_the_run_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, begin = _target(tmp_path)
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(begin)
    old = run.open_subtask("m1")
    (old / "m1" / "a.txt").write_text("1\n")
    first = commit_attempt(old, "m1", 1, "sess-1", repo=run.repo)
    merger = GitMerger(run, removal_timeout_s=60)
    head = merger.merge("m1", 1, first, "merge m1")
    # The old worktree keeps a file git will not remove it over: the removal is refused, and left.
    (old / "left.txt").write_text("untracked\n")
    assert merger.remove_worktree("m1").outcome == "refused"
    fresh: list[Path] = []
    assert escaped(lambda: fresh.append(run.open_subtask("m1", reopen=1))) is None
    assert fresh == [tmp_path / "run" / "worktrees" / "m1.reopen-1"]
    assert old.exists() and (old / "left.txt").exists()
    branch = "physgate/r1/m1.reopen-1"
    assert escaped(lambda: run.subtask_branch("m1", reopen=1)) is None
    assert run.subtask_branch("m1", reopen=1) == branch  # type: ignore[call-arg]
    assert _git(repo, "rev-parse", branch) == head
    assert _git(repo, "rev-parse", run.subtask_branch("m1")) == first
    (fresh[0] / "m1" / "a.txt").write_text("2\n")
    second = commit_attempt(fresh[0], "m1", 2, "sess-2", repo=run.repo)
    merged: list[str] = []
    assert escaped(lambda: merged.append(merger.merge("m1", 2, second, "m", reopen=1))) is None
    assert _git(repo, "rev-parse", run.run_branch) == merged[0]
    removals: list[Any] = []
    assert escaped(lambda: removals.append(merger.remove_worktree("m1", reopen=1))) is None
    assert (removals[0].path, removals[0].outcome) == (str(fresh[0]), "removed")
    assert old.exists()
    # In the loop: the reopened session is asked for in its own worktree, merged from its branch.
    rig = chosen(tmp_path / "loop", monkeypatch)
    fw = requests_of(rig, FW)
    assert [getattr(r, "reopened", None) for r in fw] == [0, 1]
    removed = of(lines(rig), "worktree_removed", subtask_id=FW)
    assert [r["path"] for r in removed] == [f"worktrees/{FW}", f"worktrees/{FW}.reopen-1"]


def test_the_earlier_merge_stays_on_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = opened(tmp_path / "before", monkeypatch)
    before = lines(reference)
    rig = chosen(tmp_path / "after", monkeypatch)
    rows = lines(rig)
    fw_lines = [r["kind"] for r in rows if r.get("subtask_id") == FW]
    assert "subtask_reopened" in fw_lines
    at = fw_lines.index("subtask_reopened")
    assert fw_lines[:at].count("merged") == 1 and fw_lines[at:].count("merged") == 1
    # The first merge, its diff and its writes are the lines the run wrote before the decision.
    for kind in ("merged", "diff_checked", "write_done"):
        assert [r | {"ts": ""} for r in of(rows, kind, subtask_id=FW, attempt=1)] == [
            r | {"ts": ""} for r in of(before, kind, subtask_id=FW, attempt=1)
        ], kind
    writes = of(rows, "write_done", subtask_id=FW)
    assert [(w["attempt"], w["node_id"]) for w in writes] == [(1, "fw.main"), (2, "fw.main")]
    ledger = [json.loads(x) for x in (rig.run_dir / "ledger.jsonl").read_bytes().splitlines()]
    fw = [x for x in ledger if x["id"] == FW]
    first = of(rows, "merged", subtask_id=FW)[0]["merge_commit"]
    assert any(x["merge_commit"] == first for x in fw)
    assert fw[-1].get("reopened_by") == ITEM
    assert fw[-1]["merge_commit"] == of(rows, "merged", subtask_id=FW)[1]["merge_commit"]


def test_the_contract_is_rerun_after_the_reopened_merge_and_never_marked_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chosen(tmp_path, monkeypatch)
    rows = lines(rig)
    assert "subtask_reopened" in kinds(rows)
    tested = of(rows, "contract_tested")
    assert [(t["result"]["outcome"], t["first"]) for t in tested] == [
        ("fail", True),
        ("pass", True),
        ("pass", False),
        ("pass", False),
    ]
    second_diff = of(rows, "diff_checked", subtask_id=FW)[1]["seq"]
    assert [t["seq"] for t in tested[2:]] == [second_diff + 1, second_diff + 2]
    pairs = [json.loads(p.model_dump_json()) for p in (P_FW, P_BACK)]
    assert [t["result"]["pair"] for t in tested[2:]] == pairs
    at = tested[2]["seq"]
    why = refusal([*rows[:at], rows[at] | {"first": True}])
    assert why is not None and "first" in why, why


def test_completion_reads_each_pairs_latest_contract_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chosen(tmp_path, monkeypatch)
    rows = lines(rig)
    assert of(rows, "contract_tested")[0]["result"]["outcome"] == "fail"
    assert "subtask_reopened" in kinds(rows)
    assert [r["subtask_id"] for r in of(rows, "module_completed")] == [DRIVE, FW]
    # Left deviating, the reopened module's retest fails again: completion is withheld.
    still = chosen(tmp_path / "still", monkeypatch, mended={})
    rows = lines(still)
    assert "subtask_reopened" in kinds(rows)
    assert of(rows, "module_completed") == []


# --- the waits ---------------------------------------------------------------------------------


@pytest.mark.parametrize("acts", [True, False], ids=["acts", "records"])
def test_the_closing_pass_and_the_system_gate_wait_for_an_open_contract_item_only_when_the_run_acts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, acts: bool
) -> None:
    # Sizing's plan: fw deviates when it merges, before the closing pass.
    rig = opened(
        tmp_path / "sized", monkeypatch, acts=acts, sizing=True, declared=(BUDGET, DRIVE, FW)
    )
    rows = lines(rig)
    assert "contract_item_raised" in kinds(rows)
    closing = of(rows, "stage_entered", subtask_id=CLOSING)
    called = [r for r in rows if r["kind"].startswith("integration_gate")]
    state = replay(read_events(rig.run_dir / "events.jsonl"))
    if not acts:
        assert closing and called
        return
    assert closing == [] and called == []
    step = state.next_step()
    assert (step.kind, step.subtask_id) == ("wait", CLOSING)
    # Replay refuses the closing pass's first attempt while the item is undecided.
    other = opened(tmp_path / "records", monkeypatch, acts=False, sizing=True)
    resolve = of(lines(other), "stage_entered", subtask_id=CLOSING)[0]
    why = refusal([*rows, resolve | {"seq": len(rows)}])
    assert why is not None and "waits" in why, why
    # Without the closing pass, the integration call waits.
    plain = opened(tmp_path / "plain", monkeypatch)
    rows = lines(plain)
    assert not [r for r in rows if r["kind"].startswith("integration_gate")]
    step = replay(read_events(plain.run_dir / "events.jsonl")).next_step()
    assert (step.kind, step.subtask_id) == ("wait", None)
    recorded = opened(tmp_path / "plain-records", monkeypatch, acts=False)
    call = next(r for r in lines(recorded) if r["kind"].startswith("integration_gate"))
    why = refusal([*rows, call | {"seq": len(rows)}])
    assert why is not None and "contract item" in why, why


# --- the rulings for this split ------------------------------------------------------------------


def test_a_reopen_whose_order_does_not_fit_one_read_records_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = opened(tmp_path, monkeypatch)
    monkeypatch.setattr(deciding, "fits_one_read", lambda data: False)
    choose(rig.run_dir, "producer", note="keep the drive")
    again(rig, monkeypatch)
    rows = lines(rig)
    taken = of(rows, "decision_taken")
    assert [(t["effect"], t["acts"], t["why_not"], t["order_too_long"]) for t in taken] == [
        ("none", False, "order_too_long", True)
    ]
    assert "subtask_reopened" not in kinds(rows)
    assert len(requests_of(rig, FW)) == 1
    assert refusal(rows) is None
    at = rows.index(taken[0])
    for forged in (
        taken[0] | {"order_too_long": False, "why_not": "record_only_source"},
        taken[0]
        | {"effect": "reopen", "acts": True, "why_not": None, "order_too_long": False}
        | {"reopens": FW},
    ):
        why = refusal([*rows[:at], forged])
        assert why is not None, forged


def test_a_reopen_is_refused_once_the_integration_call_is_on_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The item open where the integration call is on the record (as after a completion, which
    # follows the call): no choice on it can reopen a module, and a reopen forged there is refused.
    rig = opened(tmp_path, monkeypatch)
    events = read_events(rig.run_dir / "events.jsonl")
    state = replay(events)
    tested = state.contract_items.get(ITEM)
    assert tested is not None
    whole = read_events(chosen(tmp_path / "whole", monkeypatch).run_dir / "events.jsonl")
    calls = [e for e in whole if e.kind == "integration_gate_ran"]
    reopening = [e for e in whole if e.kind == "decision_taken"]
    assert len(calls) == 1 and len(reopening) == 1
    state.integration = calls[0]  # type: ignore[assignment]
    said: list[Any] = []
    assert escaped(lambda: said.append(deciding.contract_consequence(state, tested))) is None  # type: ignore[call-arg]
    assert said[0].on_choose == {"producer": "record_only", "consumer": "record_only"}
    forged = reopening[0].model_copy(update={"seq": len(events)})
    why = escaped(lambda: state.check(forged))
    assert why is not None and "does other than the record allows" in why, why


def test_a_completion_declaration_on_the_run_head_halts_before_integration_s_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = rig_for(tmp_path, dispatcher=FakeDispatcher(trajectories=tmp_path / "s"))

    class Everywhere(dict):  # type: ignore[type-arg]
        def __contains__(self, key: object) -> bool:
            return True

        def __missing__(self, key: str) -> Declaration:
            return Declaration(modules=(DRIVE,), sha256="c" * 64)

    rig.changes.held = Everywhere()
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    start(loop)
    assert escaped(loop.run) is None
    loop.close()
    rows = lines(rig)
    incidents = of(rows, "incident")
    assert [i["cause"] for i in incidents] == ["declaration_mismatch"]
    assert "before integration's window" in incidents[0]["detail"]
    assert of(rows, "stage_entered", subtask_id=INTEG) == []
    assert requests_of(rig, INTEG) == []


# --- no session's words reach a reopen order -----------------------------------------------------

STREAM = b'{"type": "assistant", "text": "STREAM-CANARY fw worked this out"}\n'
CANARIES = ("STREAM-CANARY", "SOURCE-CANARY", "WRITER-CANARY", "UNITCANARY")


class Streaming(FakeDispatcher):
    """Seals a canary into every session's own stream."""

    def run(self, request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401 - the port's types
        report = super().run(request, on_spawn)
        if self.trajectories is not None and report.trajectory:
            path = Path(report.trajectory)
            path.write_bytes(path.read_bytes() + STREAM)
            return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})
        return report


def _clean(where: str, text: str) -> None:
    found = [c for c in CANARIES if c in text]
    assert not found, (where, found)


def test_no_session_s_words_reach_a_reopen_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worded = node("fw.main", "firmware", *BOTH, v=11, period=10)
    worded["quantities"]["v"] |= {
        "source": "SOURCE-CANARY datasheet",
        "written_by": "WRITER-CANARY",
    }
    talking = node("drive.motor", "control", *BOTH, v=12, period=10)
    talking["quantities"]["v"] |= {"source": "SOURCE-CANARY", "written_by": "WRITER-CANARY"}
    # The interface's tilt quantity in fw's node, in a unit word the gate's parser refuses.
    worded["quantities"]["period"] |= {"unit": "UNITCANARY"}
    rig = chosen(
        tmp_path,
        monkeypatch,
        writes={FW: [worded], DRIVE: [talking]},
        dispatcher=Streaming(trajectories=tmp_path / "run" / "sessions"),
    )
    rows = lines(rig)
    assert "subtask_reopened" in kinds(rows)
    fw = requests_of(rig, FW)
    assert len(fw) == 2 and fw[1].repair_instruction is not None
    assert 'node "fw.main" holds 11 "volt"' in fw[1].repair_instruction
    for request in rig.dispatcher.requests:
        _clean(f"prompt of {request.subtask_id}/{request.attempt}", role_prompt(request))
    for artefact in rig.reviewer.seen:
        _clean(f"artefact of {artefact.subtask_id}", artefact.model_dump_json())
        if artefact.ordered_by_person is not None:
            _clean("person_order.md", person_order_text(artefact.ordered_by_person).decode())
    for item in read_queue(rig.run_dir).items:
        _clean(f"item {item.item_id}", item.model_dump_json())
    for line in rows:
        if line["kind"] == "contract_tested":
            for check in line["result"]["interfaces"]:
                for clause in check["clauses"]:
                    for n in clause["nodes"]:
                        n["reason"] = None
        if line["kind"] == "contract_ruled":
            for found in line["found"]:
                found["position"]["unit"] = ""
        _clean(f"the {line['kind']} line", json.dumps(line))
    _clean("decisions()", json.dumps(decisions(lines(rig))))
    assert [s["step"] for s in decisions(lines(rig)) if s["step"] == "reopened"] == ["reopened"]


def test_the_reopen_is_a_step_of_the_decision_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = chosen(tmp_path, monkeypatch)
    steps = [s for s in decisions(lines(rig)) if s["step"] == "reopened"]
    assert [{k: v for k, v in s.items() if k != "seq"} for s in steps] == [
        {"step": "reopened", "subtask_id": FW, "attempt": 2, "item_id": ITEM}
    ]
