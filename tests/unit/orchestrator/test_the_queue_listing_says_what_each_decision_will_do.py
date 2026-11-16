"""``physgate queue list`` says, for each open item, what each decision will do.

The sentences are made from the item's own consequence record and from nothing else: an item
whose approve only records says so, with the reason the record gives, before a person decides;
an item that states no consequence is listed exactly as before. The record is never changed.
The same sentences are read by the operator UI's own rows from one fixture, so a change to
either copy that the other does not follow fails a row.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from parts_rig import RUN_ID, body, decide, item, item_id, listed
from test_a_reopen_supersedes_the_other_items_on_its_module import OTHER, reopened

from physgate.cli import main
from physgate.orchestrator.queue import (
    QUEUE_NAME,
    ApprovalQueue,
    QueueItem,
    queue_listing,
    read_queue,
)
from physgate.orchestrator.queue_words import decision_sentences

SAYS = "what_each_decision_does"
FIXTURE = Path(__file__).parents[2] / "fixtures" / "queue_sentences.json"
ROWS: list[dict[str, Any]] = json.loads(FIXTURE.read_text())


def _item(consequence: dict[str, Any] | None, source: str = "review_unavailable") -> QueueItem:
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
                "consequence": consequence,
            }
        )
    )


def _printed(run: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()
    assert main(["queue", "list", "--run-dir", str(run)]) == 0
    printed: dict[str, Any] = json.loads(capsys.readouterr().out)
    return printed


def _run_with(tmp_path: Path, *items: QueueItem) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    queue = ApprovalQueue(run / QUEUE_NAME)
    for one in items:
        queue.add(one)
    return run


@pytest.mark.parametrize("row", ROWS, ids=[r["name"] for r in ROWS])
def test_every_sentence_is_the_one_the_shared_fixture_holds(row: dict[str, Any]) -> None:
    said = decision_sentences(_item(row["consequence"], row["source"]))
    assert said == row["sentences"]


@pytest.mark.parametrize("row", ROWS[:3] + ROWS[10:12], ids=lambda r: r["name"])
def test_the_listing_prints_those_sentences_and_changes_nothing_else(
    row: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_with(tmp_path, _item(row["consequence"], row["source"]))
    printed = _printed(run, capsys)
    (entry,) = printed["open"]
    assert entry.get(SAYS) == row["sentences"]
    # The served listing is the same lines: the sentences are all the command adds.
    served = queue_listing(run)
    plain = {k: v for k, v in entry.items() if k != SAYS}
    assert {**printed, "open": [plain]} == served


def test_an_item_that_states_no_consequence_is_listed_exactly_as_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_with(tmp_path, _item(None))
    printed = _printed(run, capsys)
    assert printed == queue_listing(run)
    (entry,) = printed["open"]
    assert "consequence" not in entry
    assert SAYS not in entry


def test_the_record_is_not_changed_by_listing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_with(tmp_path, _item(ROWS[1]["consequence"], ROWS[1]["source"]))
    before = (run / QUEUE_NAME).read_bytes()
    _printed(run, capsys)
    assert (run / QUEUE_NAME).read_bytes() == before


def test_a_superseded_contract_item_says_nothing_of_what_a_choice_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = reopened(tmp_path, monkeypatch)
    stored = next(i for i in read_queue(rig.run_dir).items if i.item_id == OTHER)
    # The line still says the producer's choice reopens a module; the run will not do that.
    assert stored.consequence is not None and stored.consequence.on_choose is not None
    assert stored.consequence.on_choose["producer"] == "reopen"
    entries = {e["item_id"]: e for e in _printed(rig.run_dir, capsys)["open"]}
    assert OTHER in entries
    assert SAYS not in entries[OTHER]


def test_a_choice_the_item_refuses_is_not_described(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = listed(tmp_path / "run", item())
    again = item().model_copy(update={"item_id": item_id(1, 2)})
    assert not isinstance(decide(run, item_id(1), "have", body({"mass": (1, "kg")})), Exception), (
        "the first round is decided"
    )
    ApprovalQueue(run / QUEUE_NAME).add(again)
    (entry,) = [e for e in _printed(run, capsys)["open"] if e["item_id"] == item_id(1, 2)]
    said = entry[SAYS]
    assert RUN_ID in entry["run_id"]
    assert "choose_have" in said and "choose_make" in said
    assert "choose_find" not in said
