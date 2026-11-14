"""An approve merges once an earlier refused attempt's hits are judged, attempt by attempt.

Take a subtask whose attempt 1 was refused before review as a line too long for a reviewer's read,
with eleven scan hits in its stream: six lint suppressions and five shell commands the hook
layer refused for naming a protected path. Attempt 2's review rejects it, attempt 3's blocks
with its own three hits judged and dismissed, and the escalated item still carried attempt 1's
eleven as "no review judged", so the owner's approve recorded only. Nothing could merge it.

The same sequence here: attempt 2's reviewer is given attempt 1's streams, and its eleven hits
are the ones it must answer. With every one dismissed, the escalated item's approve merges
attempt 3. With one confirmed, the approve records only, as an indicator in the history always
made it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from accounted import forged_account_before_each_open  # noqa: F401 - the rig's forger
from loop_fakes import FakeDispatcher, FakeReviewer, Rig
from test_a_refused_call_is_named_for_what_it_was import (
    IMPORT,
    LINT,
    SHELL,
    _result,
    _use,
    eleven_hit_attempt,
)
from test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review import (
    _item,
    _of,
    _resume,
    _rig,
    _run,
    decide,
    judged,
    result,
)

from physgate.orchestrator.events import DecisionTaken, ReviewRan
from physgate.orchestrator.ports import SessionReport, SessionRequest, SpawnHook
from physgate.orchestrator.trajectory import seal
from physgate.reviewers.scan import scan

#: Attempt 1's eleven hits, by the id of the call each is.
ATTEMPT_1 = ("w1", "w2", "w3", "w4", "w5", "b1", "r1", "r2", "r3", "r4", "r5")
#: Attempt 2's own hit, and attempt 3's own three: each a suppressed import, as in a real stream.
ATTEMPT_2 = ("a2-w1",)
ATTEMPT_3 = ("a3-w1", "a3-w2", "a3-w3")


def _suppressed(*calls: str) -> str:
    lines: list[str] = []
    for call in calls:
        lines.append(_use(call, "Write", file_path=f"modules/control/{call}.py", content=IMPORT))
        lines.append(_result(call, "File created", error=False))
    return "\n".join(lines) + "\n"


@dataclass
class ControlDispatcher(FakeDispatcher):
    """Each attempt's stream holds the calls the scan flags in a refused attempt."""

    def run(self, request: SessionRequest, on_spawn: SpawnHook | None = None) -> SessionReport:
        report = super().run(request, on_spawn)
        if report.trajectory is None or self.trajectories is None:
            return report
        stream = {1: eleven_hit_attempt(), 2: _suppressed(*ATTEMPT_2), 3: _suppressed(*ATTEMPT_3)}
        path = Path(report.trajectory)
        path.write_bytes(stream[request.attempt].encode() + path.read_bytes())
        return report.model_copy(update={"trajectory_seal": seal(path.read_bytes())})


def _control(run_dir: Path, confirmed: str | None = None) -> Rig:
    """Attempt 1 refused as a long line; attempt 2's review rejects; attempt 3's blocks."""
    earlier = tuple(
        judged(call, "confirmed" if call == confirmed else "dismissed", attempt=1)
        for call in ATTEMPT_1
    )
    second = result("fail", 1, *earlier, *(judged(c) for c in ATTEMPT_2))
    third = result("blocked", 2, *(judged(c) for c in ATTEMPT_3))
    return _rig(
        run_dir,
        dispatcher=ControlDispatcher(trajectories=run_dir / "sessions"),
        reviewer=FakeReviewer(results={1: second, 2: third}),
    )


def test_attempt_2_s_reviewer_is_given_attempt_1_s_eleven_hits(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _control(run_dir)
    _run(rig, "s1")
    seen = rig.reviewer.seen[0]
    assert seen.attempt == 2
    given = seen.model_dump().get("unjudged")
    assert given is not None, "attempt 2's reviewer was given no earlier attempt"
    assert [u["attempt"] for u in given] == [1]
    hits = [h for s in given[0]["sessions"] for h in scan(Path(s["trajectory"]).read_text())]
    assert sorted(h.evidence for h in hits) == sorted(ATTEMPT_1)
    assert Counter(h.what for h in hits) == {LINT: 6, SHELL: 5}
    # Attempt 2's review judged attempt 1's hits: attempt 3's reviewer is given none.
    assert "unjudged" not in rig.reviewer.seen[1].model_dump()
    assert [
        (r.attempt, tuple(r.model_dump().get("judged_earlier", ())))
        for r in _of(run_dir, ReviewRan)
    ] == [(2, (1,)), (3, ())]


def test_with_every_hit_dismissed_the_escalated_item_s_approve_merges(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _control(run_dir)
    _run(rig, "s1")
    item = _item(run_dir)
    assert item.source == "review_blocked" and item.consequence is not None
    assert item.consequence.on_approve == "merge_attempt"
    assert item.consequence.why_record_only is None
    assert item.consequence.scan_hits == ()
    assert item.consequence.model_dump(mode="json").get("judged_earlier") == [
        {"attempt": 1, "judged_by": 2}
    ]
    decide(run_dir, "approve")
    assert _resume(rig) == "done"
    taken = _of(run_dir, DecisionTaken)
    assert [(t.verb, t.effect, t.acts, t.why_not) for t in taken] == [
        ("approve", "merge", True, None)
    ]
    assert [(m[0], m[1]) for m in rig.merger.merges] == [("s1", 3)]


def test_with_one_hit_confirmed_the_approve_records_only(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    rig = _control(run_dir, confirmed="r1")
    _run(rig, "s1")
    item = _item(run_dir)
    assert item.consequence is not None
    assert item.consequence.why_record_only == "indicator_in_history"
    decide(run_dir, "approve")
    _resume(rig)
    assert [t.why_not for t in _of(run_dir, DecisionTaken)] == ["indicator_in_history"]
    assert rig.merger.merges == []
