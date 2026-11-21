"""Integration carries what a person decided; the merge of its attempt writes the closing record.

A person's choice with a note on a failed contract's item is an open point of the design. The
issued state integration reads names it, its reviewer reads the same bytes, and integration's own
diff under its module must hold the item's id: an attempt that leaves it out is refused, by id,
beside the sign-off refusal, and the next attempt may pass. The merge of the passing attempt writes
the closing record of the decisions, built from the log alone, so replay rebuilds the same bytes;
a run with no noted decision writes none, and its state keeps its bytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeMerger, sha
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (  # noqa: F401
    _sizing_registered,
    chosen,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import ITEM
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    INTEG,
)

from physgate.orchestrator.carried import CLOSING_RECORD_PATH, closing_record
from physgate.orchestrator.events import (
    AttemptRejected,
    IntegrationStateIssued,
    Merged,
    ProposalsChecked,
    read_events,
)
from physgate.orchestrator.integration_state import issued_state
from physgate.orchestrator.replay import replay
from physgate.reviewers.rubric import evaluation_words

#: The shape of a real approval's note: the decision, what it rests on, what stays open.
NOTE = (
    "The interface stands for the typical plant. At the high end of the estimate the limit cannot "
    "be met; this is accepted for now. Open residual: measure the quantity before hardware."
)


@dataclass
class Merging(FakeMerger):
    """The fake merger, told what each merge was asked to write, and what an attempt adds."""

    written: list[tuple[str, Mapping[str, str] | None]] = field(default_factory=list)
    #: From this attempt of integration on, its diff under its module holds these lines.
    says: tuple[str, ...] = ()
    from_attempt: int = 2

    def merge(
        self,
        subtask_id: str,
        attempt: int,
        attempt_commit: str,
        message: str,
        reopen: int = 0,
        contracts: Mapping[str, str] | None = None,
        records: Mapping[str, str] | None = None,
    ) -> str:
        self.written.append((subtask_id, records))
        return super().merge(subtask_id, attempt, attempt_commit, message, reopen)

    def artefact_diff(self, attempt_commit: str) -> str:
        for n in range(self.from_attempt, 6):
            if any(sha(f"{INTEG}-{n}-{call}") == attempt_commit for call in range(40)):
                lines = "\n".join(f"+{line}" for line in self.says)
                path = "modules/integration/README.md"
                head = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n"
                return f"{head}{lines}\n"
        return super().artefact_diff(attempt_commit)


def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, note: str | None, **kw: Any) -> Any:  # noqa: ANN401
    merger = Merging(says=kw.pop("says", (f"Open point: {ITEM}.",)))
    rig = chosen(tmp_path, monkeypatch, "producer", note=note, signs=True, merger=merger, **kw)
    return rig, merger


def test_an_attempt_that_leaves_a_decisions_id_out_is_refused_by_id_and_the_next_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = run(tmp_path, monkeypatch, NOTE)
    events = read_events(rig.run_dir / "events.jsonl")
    checks = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert [(c.attempt, c.refused_by) for c in checks] == [(1, "declaration"), (2, None)]
    assert checks[0].reason is not None and ITEM in checks[0].reason
    assert "limits statement" in checks[0].reason
    assert evaluation_words(checks[0].reason) == []
    (rejected,) = [e for e in events if isinstance(e, AttemptRejected) and e.subtask_id == INTEG]
    assert (rejected.attempt, rejected.finding.source) == (1, "declaration")


def test_the_check_passes_the_first_attempt_that_holds_every_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = run(tmp_path, monkeypatch, NOTE, says=())
    merger = Merging(says=(f"Open point: {ITEM}.",), from_attempt=1)
    again = chosen(
        tmp_path / "again", monkeypatch, "producer", note=NOTE, signs=True, merger=merger
    )
    events = read_events(again.run_dir / "events.jsonl")
    checks = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert [(c.attempt, c.refused_by) for c in checks] == [(1, None)]
    assert rig is not again


def test_the_issued_state_names_the_decision_and_the_reviewer_reads_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = run(tmp_path, monkeypatch, NOTE)
    events = read_events(rig.run_dir / "events.jsonl")
    issued = [e for e in events if isinstance(e, IntegrationStateIssued)]
    assert len(issued) == 2
    for line in issued:
        text = issued_state(replay(events[: line.seq])).decode()
        assert f'### Open point: item "{ITEM}"' in text
        assert '"choose"' in text and 'item kind: "failed contract"' in text
        assert "\n## Decisions taken on queue items\n" in text
        assert NOTE.split(".")[0] in text.replace('\\"', '"')
    # The reviewer of integration's attempt is handed these bytes: the record it checks against.
    seen = [a for a in rig.reviewer.seen if a.subtask_id == INTEG]
    assert seen and all(a.integration_state is not None for a in seen)
    last = issued[-1]
    assert seen[-1].integration_state is not None
    assert seen[-1].integration_state.sha256 == last.sha256


def test_the_merge_of_integrations_attempt_writes_the_closing_record_replay_rebuilds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, merger = run(tmp_path, monkeypatch, NOTE)
    events = read_events(rig.run_dir / "events.jsonl")
    (merged,) = [e for e in events if isinstance(e, Merged) and e.subtask_id == INTEG]
    (record,) = [r for who, r in merger.written if who == INTEG]
    assert record is not None and list(record) == [CLOSING_RECORD_PATH]
    # Rebuilt from the log's lines before the merge, as replay holds them: the same bytes.
    rebuilt = closing_record(replay(events[: merged.seq]))
    assert rebuilt is not None and record[CLOSING_RECORD_PATH] == rebuilt
    assert f'"item": "{ITEM}"' in rebuilt and NOTE in rebuilt
    assert '"verb": "choose"' in rebuilt and '"kind": "failed contract"' in rebuilt
    # No other module's merge writes it.
    assert [r for who, r in merger.written if who != INTEG] == [None] * (len(merger.written) - 1)
    replay(events)


@pytest.mark.parametrize("note", [None], ids=["no note"])
def test_a_run_with_no_noted_decision_writes_no_file_and_asks_no_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, note: str | None
) -> None:
    rig, merger = run(tmp_path, monkeypatch, note, says=())
    events = read_events(rig.run_dir / "events.jsonl")
    assert all(r is None for _, r in merger.written)
    checks = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert all(c.refused_by is None for c in checks)
    for line in (e for e in events if isinstance(e, IntegrationStateIssued)):
        assert b"Decisions taken" not in issued_state(replay(events[: line.seq]))
