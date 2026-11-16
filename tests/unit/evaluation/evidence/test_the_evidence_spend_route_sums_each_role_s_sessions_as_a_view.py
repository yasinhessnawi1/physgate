"""The Evidence screen's spend: a run's cost line, and each role's sessions summed as a view.

``GET /api/evidence/spend/{root}/{name}/{date}`` answers the run's cost line at the price sheet
of that date, exactly what the product's cost route serves (``physgate cost``'s line: the sheet,
the basis, the reconciliation), and beside it the line's priced calls grouped. Each session's
call is a row of its own, with its subtask, attempt and outcome as the log's session end records
them; the sessions are grouped by the role their subtask was planned for, and each role's sum is
labelled a view, summed on the server. Decomposition's, the reviewers' and routing's calls are
apart, never in a role. A call the line names unread (no binary figure read, a cache's time to
live not read, a stream that is not the one sealed) marks its group a lower bound.

It refuses as the run list does, naming the run by its place: an unknown run is 404, a
configuration its first line does not name and a log line this package cannot read are 422, a
sheet date with no sheet is 422; no answer names a path on disk.
"""

from __future__ import annotations

import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from ui_evidence_rig import EvidenceRuns, evidence_runs
from ui_rig import context_over, evaluation_rig, fake_ui, serving

from physgate.orchestrator.events import (
    SessionEnded,
    SubtaskPlanned,
    TokensUsed,
    read_events,
)

#: A sheet that prices each call's cache writes by the time to live its result records.
PRICES = "2026-10-16"
#: The run priced here, whose sessions' results report the binary's own figure.
PRICED = "ev-priced"
VIEW = "a view: each session's priced call, summed by the role its subtask was planned for"


def _result(session_id: str, usage: Any) -> dict[str, Any]:  # noqa: ANN401 - the rig's usage
    """A result as the binary writes one: its usage, its writes by time to live, its cost."""
    body: dict[str, Any] = usage.model_dump()
    body["cache_creation"] = {
        "ephemeral_5m_input_tokens": usage.cache_creation_input_tokens,
        "ephemeral_1h_input_tokens": 0,
    }
    return {"type": "result", "session_id": session_id, "usage": body, "total_cost_usd": 0.0125}


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    base = tmp_path_factory.mktemp("spend")
    rig = evaluation_rig()
    priced = base / "priced"
    repo = rig.target_repo(base / "target")
    rig.fake_run(priced, PRICED, repo, gate=rig.Gate(fail_on={1}), session_result=_result)
    made: EvidenceRuns = evidence_runs(base / "evidence")
    return {"priced": priced, "made": made, "ui": fake_ui(base / "checkout"), "base": base}


def _get(root: Path, ui: Path, *targets: str) -> list[tuple[int, Any]]:
    answers: list[tuple[int, Any]] = []
    with serving(context_over(root, ui_root=ui)) as live:
        for target in targets:
            status, _, body = live.request("GET", target)
            answers.append((status, json.loads(body)))
    return answers


def _spend(name: str, date: str = PRICES) -> str:
    return f"/api/evidence/spend/0/{name}/{date}"


def _answered(built: dict[str, Any], root: Path | None = None) -> tuple[dict[str, Any], Any]:
    """The spend of the priced run, and the product's own cost line for it."""
    (status, spend), (cost_status, line) = _get(
        root or built["priced"], built["ui"], _spend(PRICED), f"/api/runs/0/{PRICED}/cost/{PRICES}"
    )
    assert cost_status == 200, line
    assert status == 200, spend
    assert set(spend) == {"source", "line", "view", "roles", "apart"}, spend
    return spend, line


def _hand(run_dir: Path, line: dict[str, Any]) -> dict[str, list[tuple[str, str, int, Any]]]:
    """Each role's sessions, by hand from the log: (session, subtask, attempt, priced call)."""
    log = read_events(run_dir / "events.jsonl")
    role_of = {e.subtask_id: e.assigned_role for e in log if isinstance(e, SubtaskPlanned)}
    ended = {e.session_id: e for e in log if isinstance(e, SessionEnded)}
    table: dict[str, list[tuple[str, str, int, Any]]] = {}
    for call in line["calls"]:
        kind, who = call["attribution"].split(":", 1)
        if kind == "session" and who in ended:
            end = ended[who]
            table.setdefault(role_of[end.subtask_id], []).append(
                (who, end.subtask_id, end.attempt, call)
            )
    return table


def _tokens(calls: list[Any]) -> dict[str, int]:
    summed: dict[str, int] = {}
    for call in calls:
        for key, count in call["tokens"].items():
            summed[key] = summed.get(key, 0) + count
    return summed


def test_the_line_is_the_product_s_cost_line_for_the_run_at_that_sheet(
    built: dict[str, Any],
) -> None:
    spend, line = _answered(built)
    assert spend["line"] == line
    assert spend["line"]["prices_date"] == PRICES
    assert spend["line"]["basis"] == "list_price"
    assert spend["line"]["reconciliation"] is not None


def test_the_answer_names_its_run_by_place_id_manifest_and_kind(built: dict[str, Any]) -> None:
    spend, line = _answered(built)
    assert spend["source"] == {
        "root": 0,
        "name": PRICED,
        "run_id": PRICED,
        "manifest_id": line["manifest_id"],
        "kind": "development",
        "harness_commit": spend["source"]["harness_commit"],
        "harness_clean": spend["source"]["harness_clean"],
    }
    recorded = json.loads((built["priced"] / PRICED / "run.json").read_text())["harness"]
    assert (spend["source"]["harness_commit"], spend["source"]["harness_clean"]) == (
        recorded["commit"],
        recorded["clean"],
    )


def test_each_role_holds_exactly_its_subtasks_sessions_each_as_its_call_was_priced(
    built: dict[str, Any],
) -> None:
    spend, line = _answered(built)
    hand = _hand(built["priced"] / PRICED, line)
    assert hand, "the fixture's run has no session priced"
    assert [role["role"] for role in spend["roles"]] == list(hand)
    for role in spend["roles"]:
        rows = [
            {
                **call,
                "session_id": who,
                "subtask_id": subtask,
                "attempt": attempt,
                "outcome": "completed",
                "lower_bound": False,
            }
            for who, subtask, attempt, call in hand[role["role"]]
        ]
        assert role["sessions"] == rows


def test_each_role_s_sum_is_its_sessions_summed_and_labelled_a_view(
    built: dict[str, Any],
) -> None:
    spend, line = _answered(built)
    hand = _hand(built["priced"] / PRICED, line)
    assert spend["view"] == VIEW
    for role in spend["roles"]:
        calls = [call for *_, call in hand[role["role"]]]
        assert len(calls) > 1, "a sum over one session proves no sum"
        assert role["sum"]["tokens"] == _tokens(calls)
        assert Decimal(role["sum"]["usd"]) == sum(Decimal(c["usd"]) for c in calls)
        assert role["sum"]["lower_bound"] is False


def test_decomposition_review_and_routing_are_apart_and_never_in_a_role(
    built: dict[str, Any],
) -> None:
    spend, line = _answered(built)
    in_roles = {row["attribution"] for role in spend["roles"] for row in role["sessions"]}
    assert all(a.startswith("session:") for a in in_roles)
    assert set(spend["apart"]) == {"decomposition", "review", "routing", "left_over"}
    reviews = [c for c in line["calls"] if c["attribution"].startswith("reviewer:")]
    assert reviews, "the fixture's run has no review priced"
    review = spend["apart"]["review"]
    assert review["calls"] == [{**c, "lower_bound": True} for c in reviews]
    assert review["sum"]["tokens"] == _tokens(reviews)
    assert Decimal(review["sum"]["usd"]) == sum(Decimal(c["usd"]) for c in reviews)
    # No review root is named to the server, so no reviewer's result is read: a lower bound.
    assert review["sum"]["lower_bound"] is True
    # The stand-in plan made no decomposition call and routing spends nothing: no sum at all.
    for empty in ("decomposition", "routing", "left_over"):
        assert spend["apart"][empty] == {"calls": [], "sum": None}, empty
    priced = {c["attribution"] for c in line["calls"]}
    apart = {row["attribution"] for group in spend["apart"].values() for row in group["calls"]}
    shown = in_roles | apart
    assert shown == priced, "every priced call is shown once"


def test_a_stream_changed_after_its_seal_marks_its_session_and_its_role_a_lower_bound(
    built: dict[str, Any], tmp_path: Path
) -> None:
    root = tmp_path / "priced"
    shutil.copytree(built["priced"] / PRICED, root / PRICED, symlinks=True)
    log = read_events(root / PRICED / "events.jsonl")
    broken = next(e.session_id for e in log if isinstance(e, SessionEnded) and e.trajectory_seal)
    stream = root / PRICED / "sessions" / broken / "stdout.jsonl"
    stream.write_bytes(stream.read_bytes() + b'{"type": "system"}\n')
    spend, line = _answered(built, root)
    assert line["reconciliation"]["seal_broken"] == [f"session:{broken}"]
    rows = {row["session_id"]: row for role in spend["roles"] for row in role["sessions"]}
    assert rows[broken]["seal_broken"] is True
    assert rows[broken]["lower_bound"] is True
    assert rows[broken]["binary_usd"] is None
    assert [r for r, row in rows.items() if row["lower_bound"]] == [broken]
    (role,) = [
        role for role in spend["roles"] if broken in {r["session_id"] for r in role["sessions"]}
    ]
    assert role["sum"]["lower_bound"] is True
    assert spend["line"]["lower_bound"] is True


def test_a_session_the_log_records_no_end_for_is_apart_and_in_no_role(
    built: dict[str, Any], tmp_path: Path
) -> None:
    root = tmp_path / "priced"
    shutil.copytree(built["priced"] / PRICED, root / PRICED, symlinks=True)
    log_path = root / PRICED / "events.jsonl"
    log = read_events(log_path)
    spent = next(
        e for e in log if isinstance(e, TokensUsed) and e.attribution.startswith("session:")
    )
    # A session a killed orchestrator left behind: its tokens are on the log, its end is not.
    ghost = spent.model_copy(
        update={
            "seq": log[-1].seq + 1,
            "attribution": "session:left-behind",
            "message_id": "m-left",
        }
    )
    with log_path.open("a") as out:
        out.write(ghost.model_dump_json() + "\n")
    spend, line = _answered(built, root)
    assert "session:left-behind" in {c["attribution"] for c in line["calls"]}
    left = spend["apart"]["left_over"]
    assert [c["attribution"] for c in left["calls"]] == ["session:left-behind"]
    in_roles = {row["session_id"] for role in spend["roles"] for row in role["sessions"]}
    assert "left-behind" not in in_roles
    assert spend["apart"]["review"]["calls"], "the reviews stay where they were"
    reviewed = {c["attribution"] for c in spend["apart"]["review"]["calls"]}
    assert "session:left-behind" not in reviewed


def test_a_session_ended_on_a_subtask_never_planned_is_refused_with_its_reason_and_never_a_500(
    built: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "priced"
    shutil.copytree(built["priced"] / PRICED, root / PRICED, symlinks=True)
    log_path = root / PRICED / "events.jsonl"
    log = read_events(log_path)
    spent = next(
        e for e in log if isinstance(e, TokensUsed) and e.attribution.startswith("session:")
    )
    ghost = spent.model_copy(
        update={
            "seq": log[-1].seq + 1,
            "attribution": "session:unplanned-end",
            "message_id": "m-unplanned",
        }
    )
    with log_path.open("a") as out:
        out.write(ghost.model_dump_json() + "\n")
    # The log's own reader refuses such a session end, so the reader the screen calls is handed
    # one: the answer must hold for a record the screen could ever be given.
    ended = next(e for e in log if isinstance(e, SessionEnded))
    unplanned = ended.model_copy(
        update={
            "seq": ghost.seq + 1,
            "session_id": "unplanned-end",
            "subtask_id": "never-planned",
            "trajectory_seal": None,
        }
    )
    monkeypatch.setattr(
        "physgate.evaluation.evidence.read_events", lambda path: [*read_events(path), unplanned]
    )
    with serving(context_over(root, ui_root=built["ui"])) as live:
        status, _, body = live.request("GET", _spend(PRICED))
    assert status == 422, body
    refused = json.loads(body)
    assert set(refused) == {"error", "root", "name", "record"}, refused
    assert (refused["root"], refused["name"]) == ("0", PRICED)
    assert "never-planned" in refused["error"], refused


def test_an_unknown_run_is_not_found_by_its_place(built: dict[str, Any]) -> None:
    ((status, body),) = _get(built["priced"], built["ui"], _spend("ev-none"))
    assert status == 404
    assert body == {"error": "no run of that name under that root", "root": "0", "name": "ev-none"}


def test_a_configuration_its_first_line_does_not_name_is_refused_by_place(
    built: dict[str, Any],
) -> None:
    made: EvidenceRuns = built["made"]
    ((status, body),) = _get(made.runs, built["ui"], _spend("ev-tampered"))
    assert status == 422
    assert body == {
        "error": "the run's first line does not name the configuration recorded beside it",
        "root": "0",
        "name": "ev-tampered",
        "record": "run.json",
    }


def test_a_log_line_this_package_cannot_read_is_refused_with_its_reason(
    built: dict[str, Any],
) -> None:
    made: EvidenceRuns = built["made"]
    ((status, body),) = _get(made.runs, built["ui"], _spend("ev-unreadable"))
    assert status == 422
    assert set(body) == {"error", "root", "name", "record", "offset", "reason"}
    assert (body["root"], body["name"], body["record"]) == ("0", "ev-unreadable", "events.jsonl")


def test_a_date_with_no_sheet_is_refused_naming_the_date(built: dict[str, Any]) -> None:
    ((status, body),) = _get(built["priced"], built["ui"], _spend(PRICED, "1999-01-01"))
    assert status == 422
    assert set(body) == {"error", "root", "name", "record", "date"}, body
    assert (body["root"], body["name"], body["record"], body["date"]) == (
        "0",
        PRICED,
        "prices",
        "1999-01-01",
    )


def test_no_answer_names_a_path_on_disk(built: dict[str, Any]) -> None:
    made: EvidenceRuns = built["made"]
    base: Path = built["base"]
    answers = [
        *_get(built["priced"], built["ui"], _spend(PRICED), _spend(PRICED, "1999-01-01")),
        *_get(made.runs, built["ui"], _spend("ev-tampered"), _spend("ev-unreadable")),
    ]
    for _, body in answers:
        text = json.dumps(body)
        assert str(base) not in text
        assert os.path.realpath(base) not in text
