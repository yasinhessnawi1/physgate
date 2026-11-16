"""``physgate queue list`` says, for each open item, what each decision will do.

The sentences are made from the item's own consequence record and from nothing else: an item
whose approve only records says so, with the reason the record gives, before a person decides;
an item that states no consequence is listed exactly as before. The record is never changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from physgate.cli import main
from physgate.orchestrator.queue import (
    QUEUE_NAME,
    ApprovalQueue,
    ItemConsequence,
    QueueItem,
)

COMMIT = "c" * 40
SAYS = "what_each_decision_does"


def _item(
    consequence: ItemConsequence | None,
    *,
    source: str = "review_unavailable",
) -> QueueItem:
    return QueueItem.model_validate_json(
        json.dumps(
            {
                "item_id": "run-1-s1",
                "ts": "2026-11-16T09:00:00.000000Z",
                "run_id": "run-1",
                "subtask_id": "s1",
                "source": source,
                "decision_required": "Decide.",
                "artefact_diff": "",
                "triggering_finding": "no verdict",
                "quantities": [],
                "trajectories": ["sessions/s-1/stdout.jsonl"],
                "consequence": None if consequence is None else consequence.model_dump(mode="json"),
            }
        )
    )


def _consequence(**over: object) -> ItemConsequence:
    fields: dict[str, object] = {
        "attempt": 1,
        "attempt_commit": COMMIT,
        "on_approve": "merge_attempt",
        "on_reject": "retry",
        "why_record_only": None,
        "confirmed_indicators": (),
        "scan_hits": (),
    }
    fields.update(over)
    return ItemConsequence.model_validate_json(json.dumps(fields))


def _listed(
    tmp_path: Path, item: QueueItem, capsys: pytest.CaptureFixture[str]
) -> dict[str, object]:
    run = tmp_path / "run"
    run.mkdir()
    ApprovalQueue(run / QUEUE_NAME).add(item)
    capsys.readouterr()
    assert main(["queue", "list", "--run-dir", str(run)]) == 0
    open_items = json.loads(capsys.readouterr().out)["open"]
    assert len(open_items) == 1
    return dict(open_items[0])


def test_an_approve_that_only_records_says_so_and_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = _listed(
        tmp_path,
        _item(_consequence(on_approve="record_only", why_record_only="gate", on_reject="fix")),
        capsys,
    )
    assert listed.get(SAYS) == {
        "approve": (
            "Approving records your decision. It will not merge this attempt, because the "
            "physics gate refused the attempt, and a person overrides the reviewer alone."
        ),
        "reject": (
            "Rejecting orders one fix by a fresh session, the subtask's last attempt. If it is "
            "not accepted, the subtask ends rejected."
        ),
    }


def test_an_approve_that_records_for_an_item_of_its_kind_says_nothing_is_merged_or_changed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    said = _listed(
        tmp_path,
        _item(
            _consequence(
                attempt=None,
                attempt_commit=None,
                on_approve="record_only",
                on_reject="record_only",
                why_record_only="source",
            ),
        ),
        capsys,
    ).get(SAYS)
    assert said == {
        "approve": (
            "Approving records your decision. It will not merge or change anything, because "
            "for an item of this kind a decision is recorded and changes nothing in the run."
        ),
        "reject": (
            "Rejecting records your decision. It will not change anything in the run, because "
            "for an item of this kind a decision is recorded and changes nothing in the run."
        ),
    }


def test_a_confirmed_indicator_is_named_as_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consequence = _consequence(
        on_approve="record_only",
        why_record_only="indicator_in_history",
        confirmed_indicators=({"attempt": 2, "kind": "disabled_checks"},),
    )
    said = _listed(tmp_path, _item(consequence), capsys).get(SAYS)
    assert isinstance(said, dict)
    assert said.get("approve") == (
        "Approving records your decision. It will not merge this attempt, because the review "
        "of attempt 2 (disabled_checks) confirmed a reward-hacking indicator."
    )


def test_an_approve_that_merges_says_what_it_merges(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    said = _listed(tmp_path, _item(_consequence(attempt=3)), capsys).get(SAYS)
    assert isinstance(said, dict)
    assert said.get("approve") == (
        f"Approving puts attempt 3 (commit {COMMIT[:12]}) into the run, merged exactly as shown."
    )
    assert said.get("reject") == (
        "Rejecting spends this attempt, and the next attempt starts from your note."
    )


def test_each_choice_of_a_choice_item_says_what_it_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    consequence = _consequence(
        attempt=None,
        attempt_commit=None,
        on_approve="record_only",
        on_reject="record_only",
        why_record_only="source",
        on_choose={"sizing": "fix", "domain": "resize"},
    )
    said = _listed(tmp_path, _item(consequence, source="arbitration"), capsys).get(SAYS)
    assert isinstance(said, dict)
    assert said.get("choose_sizing", "").startswith(
        "Choosing sizing's value: one fix is made by a fresh session"
    )
    assert said.get("choose_domain", "").startswith(
        "Choosing the domain's value: the subtask waits while sizing's closing pass"
    )


def test_an_item_that_states_no_consequence_says_nothing_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = _listed(tmp_path, _item(None), capsys)
    assert "consequence" not in listed
    assert SAYS not in listed
    assert listed["item_id"] == "run-1-s1"
