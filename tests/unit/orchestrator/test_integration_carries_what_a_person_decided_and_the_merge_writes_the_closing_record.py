"""Integration carries what a person decided; the merge of its attempt writes the closing record.

A person's choice with a note on a failed contract's item is an open point of the design. The
issued state integration reads names it, its reviewer reads the same bytes, and integration's own
diff under its module must hold the item's id: an attempt that leaves it out is refused, by id,
beside the sign-off refusal, and the next attempt may pass. The merge of the passing attempt writes
the closing record of the decisions, built from the log alone, so replay rebuilds the same bytes;
a run with no noted decision writes none, and its state keeps its bytes.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, FakeMerger, FakeReviewer, sha
from test_a_blocked_review_is_a_review_that_goes_to_a_person import blocked_review
from test_a_choice_on_a_failed_contract_reopens_the_other_module import (  # noqa: F401
    DECLARED,
    _sizing_registered,
    again,
    choose,
    chosen,
    opened,
)
from test_a_failed_contract_is_ruled_by_clause_and_goes_to_a_person_as_one_item import (
    ITEM,
    SIGN_OFF,
    decide,
)
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    INTEG,
    hooked,
)
from test_a_queue_decision_acts_at_a_boundary import _layer

from physgate.orchestrator.carried import CLOSING_RECORD_PATH, closing_record
from physgate.orchestrator.events import (
    AttemptRejected,
    DecisionTaken,
    IntegrationStateIssued,
    Merged,
    ProposalsChecked,
    read_events,
)
from physgate.orchestrator.integration_state import issued_state
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.queue import (
    PersonDecision,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
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
    #: The lines the patch adds, where they are not the lines the module's files hold.
    adds: tuple[str, ...] | None = None
    #: The files of integration's module the id check could not read for their size.
    unread: tuple[str, ...] = ()

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

    def reached(self, attempt_commit: str) -> bool:
        return any(
            sha(f"{INTEG}-{n}-{call}") == attempt_commit
            for n in range(self.from_attempt, 6)
            for call in range(40)
        )

    def module_text(self, attempt_commit: str, module_dir: str) -> str:
        held = self.reached(attempt_commit) and module_dir == "modules/integration"
        return "\n".join(self.says) if held else ""

    def module_unread(self, attempt_commit: str, module_dir: str) -> tuple[str, ...]:
        return self.unread if self.reached(attempt_commit) else ()

    def artefact_diff(self, attempt_commit: str) -> str:
        for n in range(self.from_attempt, 6):
            if any(sha(f"{INTEG}-{n}-{call}") == attempt_commit for call in range(40)):
                lines = "\n".join(
                    f"+{line}" for line in (self.says if self.adds is None else self.adds)
                )
                path = "modules/integration/README.md"
                head = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n"
                return f"{head}{lines}\n"
        return super().artefact_diff(attempt_commit)


def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, note: str | None, **kw: Any) -> Any:  # noqa: ANN401
    merger = Merging(
        says=kw.pop("says", (f"Open point: {ITEM}.",)), from_attempt=kw.pop("from_attempt", 2)
    )
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


def test_a_refusal_says_which_files_over_the_size_bound_the_check_did_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merger = Merging(says=(), from_attempt=1, unread=("modules/integration/planted-limits.md",))
    rig = chosen(tmp_path, monkeypatch, "producer", note=NOTE, signs=True, merger=merger)
    events = read_events(rig.run_dir / "events.jsonl")
    (first, *_) = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert first.refused_by == "declaration" and first.reason is not None
    assert ITEM in first.reason
    assert "did not read 1 file under modules/integration/ over the bound of 1048576 bytes" in (
        first.reason
    )
    # The name is a session's: guarded like the id, never copied as it stands.
    assert '"modules/integration/[word withheld]-limits.md"' in first.reason
    assert evaluation_words(first.reason) == []


def test_a_refusal_says_nothing_of_a_bound_where_every_file_was_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _ = run(tmp_path, monkeypatch, NOTE, says=())
    events = read_events(rig.run_dir / "events.jsonl")
    (first, *_) = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert first.reason is not None and "did not read" not in first.reason


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


# --- a decision taken while a blocked integration attempt waits -------------------------------


@dataclass
class BlocksIntegrationOnce(FakeReviewer):
    """The reviewer blocks integration's first attempt, and passes everything else."""

    done: bool = False

    def review(self, artefact: Any) -> Any:  # noqa: ANN401
        if artefact.subtask_id == INTEG and not self.done:
            self.done = True
            self.seen.append(artefact)
            return blocked_review()
        return super().review(artefact)


def approve(rig: Any, item_id: str, note: str) -> None:  # noqa: ANN401
    view = read_queue(rig.run_dir)
    shown = ShownItem(
        item_sha256=view.digests[item_id], trajectories=statuses_now(rig.run_dir, item_id)
    )
    record_decision(
        rig.run_dir,
        item_id,
        person=PersonDecision(verb="approve", note=note),
        resolved_by="reviewer-a",
        shown=shown,
    )


def test_a_decision_taken_while_integrations_blocked_attempt_waits_is_in_the_record_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, merger = run(tmp_path, monkeypatch, NOTE, from_attempt=1, reviewer=BlocksIntegrationOnce())
    approve(rig, "run-1-integ", "Accepted; the loop gain is checked on hardware before use.")
    assert again(rig, monkeypatch) == "done"
    events = read_events(rig.run_dir / "events.jsonl")
    (merged,) = [e for e in events if isinstance(e, Merged) and e.subtask_id == INTEG]
    (record,) = [r for who, r in merger.written if who == INTEG]
    assert record is not None
    body = json.loads(record[CLOSING_RECORD_PATH])["decisions"]
    assert [(d["item"], d["kind"], d["in_issued_state"]) for d in body] == [
        (ITEM, "failed contract", True),
        ("run-1-integ", "blocked review", False),
    ]
    # Replay rebuilds the same bytes from the lines before the merge.
    assert closing_record(replay(events[: merged.seq])) == record[CLOSING_RECORD_PATH]


def test_a_pass_that_adds_nothing_where_the_module_already_holds_each_id_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    merger = Merging(says=(f"Open point: {ITEM}.",), from_attempt=1, adds=())
    rig = chosen(tmp_path, monkeypatch, "producer", note=NOTE, signs=True, merger=merger)
    events = read_events(rig.run_dir / "events.jsonl")
    checks = [e for e in events if isinstance(e, ProposalsChecked) and e.subtask_id == INTEG]
    assert [(c.attempt, c.refused_by) for c in checks] == [(1, None)]


HELD_NOTE = "Accepted; the loop gain is checked on hardware before use."


def held_rig(
    root: Path, monkeypatch: pytest.MonkeyPatch, digest: str | None
) -> tuple[Any, Merging]:
    """The run as far as integration's first attempt, on a host with no OS layer.

    Where ``digest`` is given, a person's approve of the item integration's blocked attempt is
    about to raise is written while that attempt's session runs: held, as a session's own shell
    could have written it. The person signs drive's sign-off between the processes.
    """
    from physgate.orchestrator.queue import DECISIONS_NAME, QueueResolution

    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)
    merger = Merging(says=(f"Open point: {ITEM}.",), from_attempt=1)
    rig = opened(
        root,
        monkeypatch,
        merger=merger,
        reviewer=BlocksIntegrationOnce(),
        dispatcher=FakeDispatcher(trajectories=root / "run" / "sessions"),
    )
    choose(rig.run_dir, "producer", NOTE)
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    _layer(loop)
    assert loop.resume().kind == "wait"
    loop.close()
    decide(rig.run_dir, "approve", item_id=SIGN_OFF)
    original = rig.dispatcher.run
    planted: list[int] = []

    def run(request: Any, on_spawn: Any = None) -> Any:  # noqa: ANN401
        if digest is not None and request.subtask_id == INTEG and not planted:
            planted.append(1)
            line = QueueResolution(
                item_id="run-1-integ",
                decision=f"approve: {HELD_NOTE}",
                verb="approve",
                note=HELD_NOTE,
                shown_sha256=digest,
                resolved_by="reviewer-a",
                ts="2026-09-26T12:00:00.000000Z",
            )
            path = rig.run_dir / DECISIONS_NAME
            path.write_bytes(path.read_bytes() + line.model_dump_json().encode() + b"\n")
        return original(request, on_spawn)

    rig.dispatcher.run = run  # type: ignore[method-assign]
    loop = rig.open()
    hooked(monkeypatch, loop, declared=DECLARED)
    _layer(loop, present=False)
    kind = loop.resume().kind
    loop.close()
    assert kind in ("done", "wait", "halted")
    return rig, merger


def test_a_held_decision_confirmed_after_integrations_state_was_issued_says_it_was_not_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "x"
    # The first run only learns the digest of the item the second will write its line for.
    dry, _ = held_rig(root, monkeypatch, None)
    digest = read_queue(dry.run_dir).digests["run-1-integ"]
    shutil.rmtree(root)
    rig, merger = held_rig(root, monkeypatch, digest)
    held = [e for e in read_events(rig.run_dir / "events.jsonl") if isinstance(e, DecisionTaken)]
    assert [(t.item_id, t.acts, t.why_not) for t in held][-1] == (
        "run-1-integ",
        False,
        "held_os_layer_off",
    )
    # The state integration holds names the first decision only: a held one is not carried.
    assert [r for who, r in merger.written if who == INTEG] == []
    resumed = rig.open()
    hooked(monkeypatch, resumed, declared=DECLARED)
    _layer(resumed, present=False)
    assert resumed.resume(confirm=("run-1-integ",), confirmed_by="operator").kind == "done"
    resumed.close()
    events = read_events(rig.run_dir / "events.jsonl")
    (merged,) = [e for e in events if isinstance(e, Merged) and e.subtask_id == INTEG]
    (record,) = [r for who, r in merger.written if who == INTEG]
    assert record is not None
    body = json.loads(record[CLOSING_RECORD_PATH])["decisions"]
    assert [(d["item"], d["acts"], d["in_issued_state"]) for d in body] == [
        (ITEM, True, True),
        ("run-1-integ", True, False),
    ]
    issued = [e for e in events if isinstance(e, IntegrationStateIssued)]
    confirmation = [e for e in events if isinstance(e, DecisionTaken) and e.confirmed_by][0]
    assert issued[-1].seq < confirmation.seq < merged.seq
    assert closing_record(replay(events[: merged.seq])) == record[CLOSING_RECORD_PATH]
