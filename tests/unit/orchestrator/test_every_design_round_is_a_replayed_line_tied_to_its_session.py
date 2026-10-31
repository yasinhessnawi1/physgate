"""Every design round is a line a fresh process replays, tied to its round by its sessions.

A run that reviews its plan records, for each round, a ``PlanProposed`` line after the call's
tokens: the round, the call's session, model and turns, the plan's digest or why there is none,
and the call's own start and end. Each review line names its round and the review's own start and
end, so the call and the review are timed apart. Each round's plan file digests to its proposal's
digest. Replay ties each round's call tokens to its proposal's session, which is new to the run,
and each review to its round's proposal. A held round's stream is served to the operator's UI
held to its round's seal. No product code reads the rounds to total them.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from design_review_rig import outcome_of, refusal
from replan_rig import Step, decompose, events, journal

from physgate.orchestrator.events import read_events

SRC = Path(__file__).resolve().parents[3] / "src" / "physgate"


def _of(log: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in log if one["kind"] == kind]


def _ended(run_dir: Path) -> dict[int, dict[str, Any]]:
    return {one["round"]: one for one in journal(run_dir) if one["kind"] == "round_ended"}


@pytest.fixture
def three(tmp_path: Path) -> Path:
    ran = decompose(
        tmp_path / "three", "repair:2", [Step(), Step(review="blocked"), Step(review="pass")]
    )
    assert ran.code == 0, ran.code
    return ran.run_dir


def test_every_round_is_a_proposal_and_a_review_line_with_its_own_times(three: Path) -> None:
    log, ended = events(three), _ended(three)
    proposals = _of(log, "plan_proposed")
    assert [p["round"] for p in proposals] == [1, 2, 3]
    reviews = _of(log, "design_review_ran")
    assert [r.get("round") for r in reviews] == [1, 2, 3]
    for proposal, review in zip(proposals, reviews, strict=True):
        k = proposal["round"]
        assert proposal["session_id"] == ended[k]["session_id"]
        assert proposal["plan_sha256"] == ended[k]["plan_sha256"] == review["plan_sha256"]
        assert proposal["model"] == "claude-sonnet-5" and proposal["num_turns"] == 1
        assert proposal["started"] == ended[k]["started"]
        assert proposal["ended"] == ended[k]["call_ended"]
        assert review["started"] == ended[k]["review_started"]
        assert review["ended"] == ended[k]["ended"]
        assert "cause" not in proposal


def test_the_call_and_the_review_are_timed_apart(three: Path) -> None:
    ended = _ended(three)
    assert sorted(ended) == [1, 2, 3]
    for k, one in ended.items():
        assert {"call_ended", "review_started"} <= set(one), f"round {k} times only its span"
        assert one["started"] <= one["call_ended"] <= one["review_started"] <= one["ended"], k


def test_each_proposal_follows_its_call_s_tokens_and_precedes_its_review(three: Path) -> None:
    log = events(three)
    at = {id(one): i for i, one in enumerate(log)}
    assert _of(log, "plan_proposed"), "no proposal on the record"
    for proposal in _of(log, "plan_proposed"):
        spent = [
            at[id(t)]
            for t in _of(log, "tokens_used")
            if t["attribution"] == f"decomposition:{proposal['session_id']}"
        ]
        [review] = [r for r in _of(log, "design_review_ran") if r["round"] == proposal["round"]]
        assert spent and max(spent) < at[id(proposal)] < at[id(review)]


def test_each_round_s_plan_file_digests_to_its_proposal_s_digest(three: Path) -> None:
    # Read from the durable record by a fresh process: the log, then each round's file.
    proposals = [e for e in read_events(three / "events.jsonl") if e.kind == "plan_proposed"]
    assert len(proposals) == 3, "no proposal on the record"
    for proposal in proposals:
        plan = three / "decomposition" / f"round-{proposal.round}" / "plan.json"
        assert hashlib.sha256(plan.read_bytes()).hexdigest() == proposal.plan_sha256


@pytest.mark.parametrize(
    ("step", "cause"),
    [
        (Step(call="no_structured_output"), "no_structured_output"),
        (Step(refusal="plan_refused"), "plan_refused"),
    ],
)
def test_a_round_with_no_plan_is_proposed_with_its_cause(
    tmp_path: Path, step: Step, cause: str
) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(), step])
    log = events(ran.run_dir)
    proposals = _of(log, "plan_proposed")
    assert [p["round"] for p in proposals] == [1, 2]
    assert proposals[-1].get("cause") == cause
    assert "plan_sha256" not in proposals[-1]
    assert log[-1]["kind"] == "halted" and log[-1]["reason"] == "decomposition_failed"


@pytest.mark.parametrize("policy", ["observe", "on"])
def test_a_single_round_run_proposes_round_one(tmp_path: Path, policy: str) -> None:
    ran = decompose(tmp_path, policy, [Step()])
    log = events(ran.run_dir)
    assert [p["round"] for p in _of(log, "plan_proposed")] == [1]
    assert [r.get("round") for r in _of(log, "design_review_ran")] == [1]


def test_a_run_that_does_not_review_its_plan_proposes_nothing(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "off", [Step()])
    assert ran.code == 0, ran.code
    assert not _of(events(ran.run_dir), "plan_proposed")


def _two_rounds(tmp_path: Path) -> list[dict[str, Any]]:
    ran = decompose(tmp_path / "two", "repair:3", [Step(), Step(review="pass")])
    assert ran.code == 0, ran.code
    return events(ran.run_dir)


def _sessions(log: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for one in _of(log, "tokens_used"):
        what, _, who = one["attribution"].partition(":")
        if what == "decomposition" and who not in seen:
            seen.append(who)
    return seen


def _reattributed(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first, second = _sessions(log)
    return [
        {**one, "attribution": f"decomposition:{first}"}
        if one.get("attribution") == f"decomposition:{second}"
        else one
        for one in log
    ]


def _deleted(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    second = _sessions(log)[1]
    return [one for one in log if one.get("attribution") != f"decomposition:{second}"]


def _extra_round(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A second earlier review, its own reviewer's tokens before it, with no call between.
    first = _of(log, "design_review_ran")[0]
    at = log.index(first)
    spent = {**log[at - 1], "attribution": "reviewer:forged-review", "message_id": "rx"}
    result = {**first["result"], "session_id": "forged-review"}
    return [*log[: at + 1], spent, {**first, "result": result}, *log[at + 1 :]]


def _proposal_dropped(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposals = _of(log, "plan_proposed")
    assert proposals, "no proposal on the record"
    return [one for one in log if one is not proposals[-1]]


def _review_renumbered(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reviews = _of(log, "design_review_ran")
    assert reviews and "round" in reviews[0], "no review line names its round"
    return [{**one, "round": 2} if one is reviews[0] else one for one in log]


def _proposal_session_reused(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposals = _of(log, "plan_proposed")
    assert len(proposals) == 2, "no proposal on the record"
    first, second = proposals[0]["session_id"], proposals[1]["session_id"]
    return [
        {**one, "session_id": first}
        if one is proposals[1]
        else {**one, "attribution": f"decomposition:{first}"}
        if one.get("attribution") == f"decomposition:{second}"
        else one
        for one in log
    ]


def _proposal_digest_changed(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    proposals = _of(log, "plan_proposed")
    assert proposals, "no proposal on the record"
    return [{**one, "plan_sha256": "e" * 64} if one is proposals[0] else one for one in log]


def _decomposed_by_another(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assert _of(log, "plan_proposed"), "no proposal on the record"
    first = _sessions(log)[0]
    return [{**one, "session_id": first} if one["kind"] == "decomposed" else one for one in log]


EDITS = {
    "round 2's call tokens re-attributed to round 1": _reattributed,
    "round 2's call tokens deleted": _deleted,
    "a forged extra earlier round": _extra_round,
    "the last proposal dropped": _proposal_dropped,
    "a review on another round's number": _review_renumbered,
    "a proposal under an earlier round's session": _proposal_session_reused,
    "a review of a plan its proposal did not name": _proposal_digest_changed,
    "the plan decomposed by another round's session": _decomposed_by_another,
}


@pytest.mark.parametrize("name", list(EDITS))
def test_replay_refuses_a_round_not_tied_to_its_own_sessions(tmp_path: Path, name: str) -> None:
    log = _two_rounds(tmp_path)
    assert refusal(tmp_path, log) == "", "the unedited log is refused"
    edited = outcome_of(lambda: EDITS[name](log))
    assert not isinstance(edited, Exception), f"{name}: {edited!r}"
    assert refusal(tmp_path, edited) != "", f"{name}: replay accepted it"


def test_the_held_round_s_stream_is_served_held_to_its_round_s_seal(tmp_path: Path) -> None:
    from ui_rig import context_over, fake_ui

    from physgate.ui import readers
    from physgate.ui.table import ROUTES

    root = tmp_path / "root"
    ran = decompose(root, "repair:1", [Step(), Step()])
    assert ran.code == 0, ran.code
    patterns = [route.pattern for route in ROUTES]
    assert any(p.endswith("/trajectories/decomposition/{round:round}") for p in patterns), patterns
    served = getattr(readers, "decomposition_round_stream", None)
    assert served is not None, "the UI serves no later round's stream"
    context = context_over(root, ui_root=fake_ui(tmp_path / "checkout"))
    params = {"root": "0", "name": ran.run_dir.name}
    [listed] = json.loads(readers.queue(context, params).body)["open"]
    assert listed["trajectory_statuses"] == ["holds"]
    stream = ran.run_dir / "decomposition" / "round-2" / "stdout.jsonl"
    found = outcome_of(lambda: served(context, {**params, "round": "2"}))
    assert getattr(found, "body", None) == stream.read_bytes(), found
    stream.write_text("{}\n")
    assert isinstance(outcome_of(lambda: served(context, {**params, "round": "2"})), Exception)
    assert isinstance(outcome_of(lambda: served(context, {**params, "round": "3"})), Exception)


#: The only modules that may name the rounds' records: their writer, their lines and their replay.
ALLOWED = {
    "orchestrator/events.py",
    "orchestrator/record.py",
    "orchestrator/replay.py",
    "orchestrator/design_rounds.py",
}
ROUND_NAMES = {"PlanProposed", "RoundEnded", "RoundsEnded", "read_journal"}


def test_no_product_code_but_the_writer_and_replay_reads_the_rounds() -> None:
    named: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        found = {
            node.id if isinstance(node, ast.Name) else node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Name | ast.Attribute)
            and (node.id if isinstance(node, ast.Name) else node.attr) in ROUND_NAMES
        }
        found |= {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name in ROUND_NAMES
        }
        if found:
            named[path.relative_to(SRC).as_posix()] = found
    assert named, "nothing names the rounds' records"
    assert "PlanProposed" in named.get("orchestrator/events.py", set())
    assert set(named) <= ALLOWED, {k: v for k, v in named.items() if k not in ALLOWED}
