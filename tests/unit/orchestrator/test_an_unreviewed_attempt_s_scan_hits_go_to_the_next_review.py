"""An attempt refused before review leaves its scan hits to the next attempt that is reviewed.

ARCH-133: an approve merges none while the scan before review found a reward-hacking indicator in
the streams of any attempt no review judged, since an earlier attempt's work is in the commit an
approve merges. An attempt refused before review (here by the change check, as a line too long for
a reviewer's read was refused in two live runs) is never reviewed itself, so its hits are put
before the reviewer of the next attempt that is reviewed, marked with the attempt they came from,
each to be confirmed or dismissed as that review's own are. Then:

- a hit that review dismissed no longer makes an approve record only, and the approve merges;
- a hit it confirmed still does (``indicator_in_history``);
- a hit it left unanswered is still unjudged, and still makes an approve record only;
- with no later attempt reviewed, every hit is still unjudged, as before;
- the item names the attempt each hit is from, and which review judged an earlier attempt's;
- nothing else an approve never merges past moves: an automated refusal of the last attempt, a
  stream that no longer holds its seal, a decision written while a session ran without the OS
  layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeChanges, FakeDispatcher, FakeGate, FakeReviewer, Rig, plan

from physgate.orchestrator.events import (
    DecisionTaken,
    Event,
    Incident,
    OsLayerChecked,
    ReviewRan,
    read_events,
)
from physgate.orchestrator.exceptions import ReviewUnavailableError
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.protocols import IndicatorReport, ReviewResult, SpecDefect
from physgate.orchestrator.queue import (
    QUEUE_NAME,
    PersonDecision,
    QueueItem,
    ShownItem,
    read_queue,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.trajectory import seal
from physgate.oslayer.probe import Present

PRESENT = Present(mechanism="seatbelt", claude_version="2.1.301")
ACT = {"queue_decisions": "act", "os_layer": PRESENT}
NO_VERDICT = ReviewUnavailableError("no verdict", cause="invalid_verdict")
#: The change check's refusal of attempt 1, before any gate or review.
LONG_LINE = ("long_line", "a line of the diff is longer than one read shows whole")
NOTE = "the mass is taken from the parts sheet"


@dataclass
class SkippingDispatcher(FakeDispatcher):
    """Every session's stream shows one test switched off, by a tool call of its own id."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        if report.trajectory is None or self.trajectories is None:
            return report
        written = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": hit(report.session_id),
                        "name": "Write",
                        "input": {"file_path": "t.py", "content": "@pytest.mark.skip\n"},
                    }
                ],
            },
        }
        path = Path(report.trajectory)
        path.write_bytes(json.dumps(written).encode() + b"\n" + path.read_bytes())
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


def hit(session_id: str) -> str:
    """The id of the tool call that switched a test off in ``session_id``'s stream."""
    return f"toolu_{session_id.replace('-', '_')}"


def judged(evidence: str, disposition: str = "dismissed") -> IndicatorReport:
    return IndicatorReport(
        kind="disabled_checks",
        evidence=evidence,
        disposition=disposition,  # type: ignore[arg-type]
        reason="the skip marks a test of hardware the run does not have"
        if disposition == "dismissed"
        else "the skip hides the failing gain test",
    )


def result(verdict: str, n: int, *indicators: IndicatorReport) -> ReviewResult:
    blocking = (SpecDefect(finding="no motor inductance is given", blocking=True),)
    return ReviewResult(
        verdict=verdict,  # type: ignore[arg-type]
        finding="the gain is sound" if verdict != "fail" else "the gain changed silently",
        reviewer_model="claude-opus-5-5",
        session_id=f"rev-{n}",
        usage=(),
        indicators=indicators,
        spec_defects=blocking if verdict == "blocked" else (),
    )


def _rig(run_dir: Path, **kw: Any) -> Rig:
    run_dir.mkdir(parents=True, exist_ok=True)
    kw.setdefault("dispatcher", SkippingDispatcher(trajectories=run_dir / "sessions"))
    kw.setdefault("changes", FakeChanges(refuse={1: LONG_LINE}))
    kw.setdefault("config_overrides", dict(ACT))
    return Rig(run_dir, **kw)


def _layer(loop: Loop, present: bool = True) -> None:
    state = PRESENT if present else {"state": "absent", "reason": "unsupported_platform"}
    loop.record.emit(
        OsLayerChecked.model_validate(
            {**loop.record.envelope(), "state": state, "as_recorded": None}
        )
    )


def _run(rig: Rig, *ids: str, present: bool = True) -> Loop:
    loop = rig.open()
    loop.start(plan(*ids))
    _layer(loop, present)
    loop.run()
    loop.close()
    return loop


def _resume(rig: Rig, **kw: Any) -> str:
    loop = rig.open()
    _layer(loop)
    kind = loop.resume(**kw).kind
    loop.close()
    return kind


def _events(run_dir: Path) -> list[Event]:
    return list(read_events(run_dir / "events.jsonl"))


def _of(run_dir: Path, kind: type[Any]) -> list[Any]:
    return [e for e in _events(run_dir) if isinstance(e, kind)]


def decide(run_dir: Path, verb: str, note: str | None = NOTE, item_id: str = "run-1-s1") -> None:
    view = read_queue(run_dir)
    shown = ShownItem(
        item_sha256=view.digests[item_id], trajectories=statuses_now(run_dir, item_id)
    )
    record_decision(
        run_dir,
        item_id,
        person=PersonDecision(verb=verb, note=note),  # type: ignore[arg-type]
        resolved_by="yasin",
        shown=shown,
    )


def _item(run_dir: Path, item_id: str = "run-1-s1") -> QueueItem:
    return next(i for i in read_queue(run_dir).items if i.item_id == item_id)


def _marked(item: QueueItem) -> list[tuple[str, int | None]]:
    """Each scan hit the item carries, with the attempt it says the hit is from."""
    assert item.consequence is not None
    return [(h.evidence, h.model_dump().get("attempt")) for h in item.consequence.scan_hits]


def _judged_earlier(item: QueueItem) -> list[dict[str, Any]]:
    """Which earlier attempts' hits a review judged, as the item's line says it."""
    assert item.consequence is not None
    return list(item.consequence.model_dump(mode="json").get("judged_earlier", []))


def _review_judged(run_dir: Path) -> list[tuple[int, tuple[int, ...]]]:
    """Each review line: its attempt, and the earlier attempts whose hits it judged."""
    return [
        (r.attempt, tuple(r.model_dump().get("judged_earlier", ())))
        for r in _of(run_dir, ReviewRan)
    ]


# -- (a) the next review dismisses them: an approve merges ---------------------------------------


def _dismissed_then_blocked(run_dir: Path) -> Rig:
    """Attempt 1 refused before review; attempt 2's review dismisses both hits and blocks."""
    both = (judged(hit("sess-1")), judged(hit("sess-2")))
    return _rig(run_dir, reviewer=FakeReviewer(results={1: result("blocked", 1, *both)}))


def test_hits_a_later_review_dismissed_no_longer_hold_an_approve_and_it_merges(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _dismissed_then_blocked(run_dir)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, (1,))]
    item = _item(run_dir)
    assert item.source == "review_blocked" and item.consequence is not None
    assert item.consequence.on_approve == "merge_attempt"
    assert item.consequence.why_record_only is None
    assert _marked(item) == []
    assert _judged_earlier(item) == [{"attempt": 1, "judged_by": 2}]
    decide(run_dir, "approve")
    assert _resume(rig) == "done"
    taken = _of(run_dir, DecisionTaken)
    assert [(t.verb, t.effect, t.acts, t.why_not) for t in taken] == [
        ("approve", "merge", True, None)
    ]
    assert [(m[0], m[1]) for m in rig.merger.merges] == [("s1", 2)]


def test_the_next_review_is_given_the_earlier_attempt_s_streams(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _dismissed_then_blocked(run_dir)
    _run(rig, "s1")
    seen = rig.reviewer.seen[0]
    assert seen.attempt == 2
    unjudged = seen.model_dump().get("unjudged")
    assert unjudged is not None, "the review was given no earlier attempt"
    assert [u["attempt"] for u in unjudged] == [1]
    assert [s["session_id"] for s in unjudged[0]["sessions"]] == ["sess-1"]


def test_an_attempt_a_review_judged_gives_its_hits_to_no_later_review(tmp_path: Path) -> None:
    # Attempt 2's review judges attempt 1's hits and fails; attempt 3's review is given none.
    run_dir = tmp_path / "run"
    both = (judged(hit("sess-1")), judged(hit("sess-2")))
    reviewer = FakeReviewer(
        results={1: result("fail", 1, *both), 2: result("blocked", 2, judged(hit("sess-3")))}
    )
    rig = _rig(run_dir, reviewer=reviewer)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, (1,)), (3, ())]
    assert "unjudged" not in rig.reviewer.seen[1].model_dump()
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.on_approve == "merge_attempt"
    assert _judged_earlier(item) == [{"attempt": 1, "judged_by": 2}]


# -- (b) the next review confirms one: approve records only, as it did -----------------------------


def test_an_earlier_hit_a_later_review_confirmed_still_holds_an_approve(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    reviewer = FakeReviewer(
        results={1: result("fail", 1, judged(hit("sess-1"), "confirmed"), judged(hit("sess-2")))},
        unavailable={2: NO_VERDICT},
    )
    rig = _rig(run_dir, reviewer=reviewer)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, (1,))]
    item = _item(run_dir)
    assert item.consequence is not None
    assert item.consequence.why_record_only == "indicator_in_history"
    # Attempt 3's review reached no verdict, so its own hit is the one no review judged.
    assert _marked(item) == [(hit("sess-3"), 3)]
    decide(run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["indicator_in_history"]
    assert rig.merger.merges == []


# -- (c) the next review leaves one unanswered: it stays unjudged ---------------------------------


def test_an_earlier_hit_the_review_left_unanswered_stays_unjudged(tmp_path: Path) -> None:
    # A reviewer that answers only its own attempt's hit judged nothing of attempt 1.
    run_dir = tmp_path / "run"
    reviewer = FakeReviewer(results={1: result("blocked", 1, judged(hit("sess-2")))})
    rig = _rig(run_dir, reviewer=reviewer)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, ())]
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert _marked(item) == [(hit("sess-1"), 1)]
    assert _judged_earlier(item) == []
    decide(run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []


# -- (d) no later attempt is reviewed: as before ---------------------------------------------


def test_with_no_later_review_every_hit_is_unjudged_and_says_its_attempt(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    _run(rig, "s1")
    assert _of(run_dir, ReviewRan) == []
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.why_record_only == "scan_hit"
    assert _marked(item) == [(hit("sess-1"), 1), (hit("sess-2"), 2)]
    assert _judged_earlier(item) == []
    decide(run_dir, "approve", note=None)
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []


# -- (e) a run recorded before: its item is taken as it was listed ---------------------------------


def _as_written_before(run_dir: Path) -> None:
    """Rewrite the items file as a writer before this change wrote it: no hit names its attempt."""
    items = run_dir / QUEUE_NAME
    lines = []
    for raw in items.read_bytes().splitlines():
        data = json.loads(raw)
        consequence = data["item"]["consequence"] if "item" in data else data.get("consequence")
        for h in (consequence or {}).get("scan_hits", []):
            h.pop("attempt", None)
        lines.append(QueueItem.model_validate_json(json.dumps(data)).model_dump_json().encode())
    items.write_bytes(b"\n".join(lines) + b"\n")


def test_an_item_listed_before_hits_named_their_attempt_is_taken_as_listed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    _run(rig, "s1")
    _as_written_before(run_dir)
    assert "attempt" not in json.dumps(
        [h.model_dump() for h in _item(run_dir).consequence.scan_hits]  # type: ignore[union-attr]
    )
    decide(run_dir, "approve", note=None)
    assert _resume(rig) == "done"
    assert _of(run_dir, Incident) == []
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["scan_hit"]
    assert rig.merger.merges == []


def test_an_item_whose_hits_are_partly_marked_is_not_one_the_run_wrote(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _rig(run_dir, reviewer=FakeReviewer(unavailable={1: NO_VERDICT}))
    _run(rig, "s1")
    items = run_dir / QUEUE_NAME
    data = json.loads(items.read_bytes())
    assert len(data["consequence"]["scan_hits"]) == 2
    data["consequence"]["scan_hits"][0].pop("attempt", None)
    items.write_bytes(
        QueueItem.model_validate_json(json.dumps(data)).model_dump_json().encode() + b"\n"
    )
    decide(run_dir, "approve", note=None)
    assert _resume(rig) == "halted"
    assert [i.cause for i in _of(run_dir, Incident)] == ["queue_item_mismatch"]
    assert _of(run_dir, DecisionTaken) == [] and rig.merger.merges == []


# -- (f) what an approve never merges past, with the earlier hits judged and dismissed -------------


@pytest.mark.parametrize(
    ("setup", "why"),
    [
        ({"gate": FakeGate(verdicts=["pass", "fail"])}, "last_rejection_automated"),
        ({"changes": FakeChanges(refuse={1: LONG_LINE, 3: ("proposal", "refused")})},
         "last_rejection_automated"),
        ({"dispatcher": "unread"}, "last_rejection_automated"),
    ],
    ids=["gate", "change check", "reading"],
)  # fmt: skip
def test_an_approve_still_never_merges_past_an_automated_refusal(
    tmp_path: Path, setup: dict[str, Any], why: str
) -> None:
    run_dir = tmp_path / "run"
    if setup.get("dispatcher") == "unread":
        setup = {"dispatcher": SkippingDispatcher(trajectories=run_dir / "sessions", unread={3})}
    both = (judged(hit("sess-1")), judged(hit("sess-2")))
    rig = _rig(run_dir, reviewer=FakeReviewer(results={1: result("fail", 1, *both)}), **setup)
    _run(rig, "s1")
    assert _review_judged(run_dir) == [(2, (1,))]
    item = _item(run_dir)
    assert item.consequence is not None and item.consequence.on_approve == "record_only"
    decide(run_dir, "approve")
    _resume(rig)
    assert [(t.effect, t.acts, t.why_not) for t in _of(run_dir, DecisionTaken)] == [
        ("none", False, why)
    ]
    assert rig.merger.merges == []


def test_an_approve_still_never_merges_when_the_judged_attempt_s_stream_changed(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _dismissed_then_blocked(run_dir)
    _run(rig, "s1")
    decide(run_dir, "approve")
    first = run_dir / "sessions" / "sess-1" / "stdout.jsonl"
    first.write_bytes(first.read_bytes() + b"{}\n")
    assert _resume(rig) == "halted"
    assert [i.cause for i in _of(run_dir, Incident)] == ["trajectory_tampered"]
    assert rig.merger.merges == [] and _of(run_dir, DecisionTaken) == []


@pytest.fixture
def entry_check_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run's refusal to act without the OS layer, switched off, to reach the held window."""
    monkeypatch.setattr(Loop, "_require_os_layer", lambda self: None)


@pytest.mark.usefixtures("entry_check_off")
def test_an_approve_written_while_a_session_ran_without_the_layer_is_still_held(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    rig = _dismissed_then_blocked(run_dir)
    # s1's two sessions, then s2's: the person approves s1's item while s2's session runs.
    rig.dispatcher.during[3] = lambda: decide(run_dir, "approve")
    rig.changes = FakeChanges(refuse={1: LONG_LINE})
    _run(rig, "s1", "s2", present=False)
    taken = _of(run_dir, DecisionTaken)
    assert [(t.subtask_id, t.acts, t.why_not) for t in taken] == [
        ("s1", False, "held_os_layer_off")
    ]
    assert [m[0] for m in rig.merger.merges] == ["s2"]
