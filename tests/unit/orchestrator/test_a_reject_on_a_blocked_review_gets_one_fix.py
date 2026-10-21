"""A rejection of an attempt whose review blocked gets one fix, by a fresh session, and no more.

ARCH-133 over the loop with stand-in ports. The fix is the next attempt, outside the repair
budget and always the subtask's last: a fresh session of the same role and model in the
subtask's worktree, told the review's verdict and the person's note in a fixed template and
nothing of the earlier session. It is gated and reviewed like any attempt, its reviewer told that
it is the fix a person ordered and what it was told. Accepted, it merges; not accepted, the
subtask ends rejected with no escalation question; its review reaching no verdict sends it to a
person once more, whose reject ends it. Its instruction is held to the canaries first; a killed
fix resumes as the same fix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from loop_fakes import (
    FakeChanges,
    FakeDispatcher,
    FakeGate,
    FakeMaterial,
    FakeReviewer,
    KilledError,
)
from test_a_blocked_review_is_a_review_that_goes_to_a_person import BLOCKING, blocked_review
from test_a_queue_decision_acts_at_a_boundary import (
    NO_VERDICT,
    LeftoverDispatcher,
    _of,
    _resume,
    _rig,
    _start,
    decide,
)

from physgate.orchestrator.events import (
    DecisionTaken,
    EscalationDecided,
    Halted,
    Incident,
    Merged,
    StageEntered,
    SubtaskRejected,
)
from physgate.orchestrator.exceptions import RunStateError
from physgate.orchestrator.ports import Leftover
from physgate.orchestrator.protocols import Artefact, ReviewResult
from physgate.orchestrator.queue import read_queue
from physgate.orchestrator.repair import LAST_ATTEMPT, STILL_GOVERNS, fix_instruction

NOTE = "the pole is the one the plant model's linearisation gives"


def _blocked_then(rig_dir: Path, *, on: int = 1, **kw: Any) -> Any:
    """A run whose review of attempt ``on`` blocked, the earlier ones rejected, decided reject."""
    results: dict[int, ReviewResult] = {on: blocked_review()}
    reviewer = kw.pop("reviewer", None) or FakeReviewer(
        verdicts=["fail"] * (on - 1), results=results
    )
    rig = _rig(rig_dir, reviewer=reviewer, **kw)
    loop = _start(rig, "s1")
    assert loop.run().kind == "done"
    loop.close()
    (item,) = read_queue(rig.run_dir).open_items()
    assert item.source == "review_blocked"
    assert item.consequence is not None and item.consequence.on_reject == "fix"
    decide(rig.run_dir, "reject", NOTE)
    return rig


# -- the fix is dispatched ---------------------------------------------------------------------


def test_a_reject_on_a_blocked_review_dispatches_one_fix_session_in_the_subtasks_worktree(
    tmp_path: Path,
) -> None:
    rig = _blocked_then(tmp_path / "run")
    _, kind = _resume(rig)
    assert kind == "done"
    first, fix = rig.dispatcher.requests
    assert (fix.kind, fix.attempt) == ("fix", 2)
    assert (fix.subtask_id, fix.module_dir, fix.spec_path, fix.model) == (
        first.subtask_id,
        first.module_dir,
        first.spec_path,
        first.model,
    )
    assert fix.repair_instruction == fix_instruction(
        1, blocked_review().finding, (BLOCKING.finding,), NOTE
    )
    text = fix.repair_instruction
    assert blocked_review().finding in text and BLOCKING.finding in text and NOTE in text
    assert STILL_GOVERNS in text and text.endswith(LAST_ATTEMPT)
    taken = _of(rig.run_dir, DecisionTaken)
    assert [(t.verb, t.effect, t.acts) for t in taken] == [("reject", "fix", True)]


def test_a_fix_session_is_told_nothing_of_the_implementers_trajectory(tmp_path: Path) -> None:
    rig = _blocked_then(tmp_path / "run")
    _resume(rig)
    first, fix = rig.dispatcher.requests
    stream = str(rig.run_dir / "sessions" / "sess-1" / "stdout.jsonl")
    assert fix.repair_instruction is not None
    for told in (fix.repair_instruction, fix.model_dump_json()):
        assert "sess-1" not in told and stream not in told and "sessions/" not in told
    # Nothing but the attempt, its instruction and its kind differs from an ordinary request.
    ordinary = first.model_dump()
    differs = {k for k, v in fix.model_dump().items() if ordinary[k] != v}
    assert differs == {"attempt", "repair_instruction", "kind"}


def test_an_accepted_fix_merges_through_gate_and_review(tmp_path: Path) -> None:
    rig = _blocked_then(tmp_path / "run")
    again, kind = _resume(rig)
    assert kind == "done"
    (merged,) = _of(rig.run_dir, Merged)
    assert (merged.subtask_id, merged.attempt) == ("s1", 2)
    assert rig.gate is not None and len(rig.gate.seen) == 2
    line = again.ledger.find("s1")
    assert line is not None and line.review_result == "pass" and line.attempt_count == 2
    assert again.state.subtasks["s1"].status == "done"


def test_the_reviewer_of_a_fix_is_told_it_is_a_fix(tmp_path: Path) -> None:
    rig = _blocked_then(tmp_path / "run")
    _resume(rig)
    first, fix = rig.reviewer.seen
    assert first.ordered_by_person is None
    order = fix.ordered_by_person
    assert order is not None
    assert (order.kind, order.item_id, order.of_attempt) == ("fix_after_block", "run-1-s1", 1)
    assert order.instruction == rig.dispatcher.requests[-1].repair_instruction


def test_an_artefact_no_person_ordered_is_recorded_exactly_as_before() -> None:
    artefact = Artefact(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        attempt_commit="a" * 40,
        worktree="w",
        graph_root="g",
        trajectory="t",
        scopes=("subtask",),
        base_revision=0,
    )
    assert "ordered_by_person" not in artefact.model_dump_json()


# -- how a fix ends ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "how",
    ["reading", "change check", "gate fail", "review fail", "review blocked"],
)
def test_a_fix_not_accepted_ends_the_subtask_rejected(tmp_path: Path, how: str) -> None:
    run_dir = tmp_path / "run"
    kw: dict[str, Any] = {}
    second: dict[int, ReviewResult] = {1: blocked_review()}
    verdicts: list[str] = []
    if how == "reading":
        kw["dispatcher"] = FakeDispatcher(trajectories=run_dir / "sessions", unread={2})
    elif how == "change check":
        kw["changes"] = FakeChanges(refuse={2: ("proposal", "a node another role owns")})
    elif how == "gate fail":
        kw["gate"] = FakeGate(verdicts=["pass", "fail"])
    elif how == "review fail":
        verdicts = ["blocked", "fail"]
    else:
        second[2] = blocked_review()
    kw["reviewer"] = FakeReviewer(verdicts=verdicts, results=second)
    rig = _blocked_then(run_dir, **kw)
    again, kind = _resume(rig)
    assert kind == "done"
    ended = _of(run_dir, SubtaskRejected)
    assert [(e.by, e.attempt, e.item_id) for e in ended] == [("fix_not_accepted", 2, None)]
    # No escalation question about the fix, no item, and no attempt 3 though the budget has one.
    assert [e.attempt for e in _of(run_dir, EscalationDecided)] == [1]
    assert len(read_queue(run_dir).items) == 1
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 2]
    assert again.state.subtasks["s1"].status == "rejected"
    assert rig.merger.merges == []


def test_a_fix_whose_review_is_unavailable_goes_to_the_queue_and_its_reject_ends_the_subtask(
    tmp_path: Path,
) -> None:
    reviewer = FakeReviewer(
        results={1: blocked_review()}, unavailable={2: NO_VERDICT, 3: NO_VERDICT}
    )
    rig = _blocked_then(tmp_path / "run", reviewer=reviewer)
    _, kind = _resume(rig)
    assert kind == "done"
    items = read_queue(rig.run_dir).items
    assert [i.item_id for i in items] == ["run-1-s1", "run-1-s1-r2"]
    second = items[1]
    assert second.source == "review_unavailable"
    assert second.consequence is not None and second.consequence.on_reject == "end_subtask"
    decide(rig.run_dir, "reject", "no second try", item_id="run-1-s1-r2")
    again, _ = _resume(rig)
    ended = _of(rig.run_dir, SubtaskRejected)
    assert [(e.by, e.item_id) for e in ended] == [("person", "run-1-s1-r2")]
    assert [r.attempt for r in rig.dispatcher.requests] == [1, 2]  # at most one fix
    assert again.state.subtasks["s1"].status == "rejected"


def test_a_fix_whose_review_is_unavailable_can_be_approved_and_merges(tmp_path: Path) -> None:
    reviewer = FakeReviewer(
        results={1: blocked_review()}, unavailable={2: NO_VERDICT, 3: NO_VERDICT}
    )
    rig = _blocked_then(tmp_path / "run", reviewer=reviewer)
    _resume(rig)
    decide(rig.run_dir, "approve", item_id="run-1-s1-r2")
    _resume(rig)
    assert [(m[0], m[1]) for m in rig.merger.merges] == [("s1", 2)]


def test_a_fix_after_a_block_on_attempt_three_is_attempt_four(tmp_path: Path) -> None:
    rig = _blocked_then(tmp_path / "run", on=3)
    again, kind = _resume(rig)
    assert kind == "done"
    assert [(r.attempt, r.kind) for r in rig.dispatcher.requests] == [
        (1, "attempt"),
        (2, "attempt"),
        (3, "attempt"),
        (4, "fix"),
    ]
    (merged,) = _of(rig.run_dir, Merged)
    assert merged.attempt == 4
    assert again.state.subtasks["s1"].status == "done"


def test_replay_refuses_an_attempt_four_that_is_not_a_fix(tmp_path: Path) -> None:
    rig = _rig(tmp_path / "run", reviewer=FakeReviewer(verdicts=["fail"] * 3))
    loop = _start(rig, "s1")
    loop.run()
    fourth = StageEntered(**loop.record.envelope(), subtask_id="s1", attempt=4, stage="resolve")
    with pytest.raises(ValueError, match="cannot start now|only the fix"):
        loop.state.check(fourth)
    loop.close()


# -- the canaries, and a kill ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("where", "kind", "cause"),
    [
        ("note", "held_out", "held_out_read"),
        ("verdict", "review_material", "review_material_read"),
    ],
)
def test_a_fix_instruction_showing_a_canary_halts(
    tmp_path: Path, where: str, kind: str, cause: str
) -> None:
    marker = "the pole is the one the plant" if where == "note" else "cannot be decided"
    material = (
        FakeMaterial(held_out=(marker,))
        if kind == "held_out"
        else FakeMaterial(review_material=(marker,))
    )
    rig = _blocked_then(tmp_path / "run", material=material)
    _, step = _resume(rig)
    assert step == "halted"
    (incident,) = _of(rig.run_dir, Incident)
    assert incident.cause == cause and incident.subtask_id == "s1"
    assert marker not in incident.detail
    assert len(rig.dispatcher.requests) == 1  # the fix was never spawned
    assert material.shown and NOTE in material.shown[-1]
    with pytest.raises(RunStateError, match="a person resolves that"):
        _resume(rig)


def test_a_killed_fix_session_resumes_as_the_same_fix(tmp_path: Path) -> None:
    rig = _blocked_then(tmp_path / "run")
    rig.dispatcher.kill_on = 2
    with pytest.raises(KilledError):
        _resume(rig)
    rig.dispatcher.kill_on = None
    _, kind = _resume(rig)
    assert kind == "done"
    _, killed, again = rig.dispatcher.requests
    assert (killed.kind, again.kind) == ("fix", "fix")
    assert killed == again
    assert [(m[0], m[1]) for m in rig.merger.merges] == [("s1", 2)]


def test_a_fix_with_a_quarantined_leftover_takes_nothing_more(tmp_path: Path) -> None:
    # Second fault: the fix's own session is left over, and its stream set aside unscanned.
    rig = _blocked_then(tmp_path / "run")
    rig.dispatcher.kill_on = 2
    with pytest.raises(KilledError):
        _resume(rig)
    left = [
        Leftover(
            session_id="sess-2",
            pid=1,
            killed=0,
            stopped=False,
            quarantine="operator: the disk was replaced",
            scan="unscanned (stream gone)",
        )
    ]
    rig.dispatcher = LeftoverDispatcher(trajectories=rig.run_dir / "sessions", left=lambda: left)
    with pytest.raises(RunStateError, match="a person resolves that"):
        _resume(rig)
    assert [h.detail for h in _of(rig.run_dir, Halted)][-1].startswith("stream_quarantined")
    assert rig.merger.merges == [] and len(rig.dispatcher.requests) == 0


# -- the same enforcement as any role session --------------------------------------------------


def test_a_fix_session_is_installed_with_exactly_a_role_sessions_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    import subprocess
    from types import SimpleNamespace

    from orch_helpers import SCRIPTED_BOUNDS, make_config

    from physgate.orchestrator import dispatch
    from physgate.orchestrator.credentials import Credential
    from physgate.orchestrator.dispatch import ClaudeDispatcher
    from physgate.orchestrator.ports import SessionRequest

    seen: list[list[str]] = []

    def fake_run(argv: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        seen.append(argv)
        out = {"settings": "s", "config": "c", "spawn_args": [], "spawn_env": {}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(out), "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    dispatcher = ClaudeDispatcher(
        config=make_config(),
        run=SimpleNamespace(subtask_branch=lambda subtask: f"b/{subtask}"),  # type: ignore[arg-type]
        store_root=tmp_path / "store",
        install_bin=tmp_path / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=tmp_path / "reviews",
    )
    monkeypatch.setattr(dispatch, "session_protected_roots", lambda *_a: ((), ()))
    base = SessionRequest(
        subtask_id="s1",
        attempt=2,
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction="Attempt 1 of 3 was rejected.",
        bounds=SCRIPTED_BOUNDS,
    )
    fix = base.model_copy(update={"kind": "fix", "repair_instruction": "The review blocked."})
    installed = []
    for n, request in enumerate((base, fix)):
        sdir = tmp_path / f"sdir-{n}"
        dispatcher._install(request, tmp_path / "worktree", sdir, None)
        installed.append([arg.replace(str(sdir), "<session>") for arg in seen[-1]])
    assert installed[0] == installed[1] and installed[0]
    # Only the prompt's closing block reads the kind.
    attempt_prompt, fix_prompt = dispatch.role_prompt(base), dispatch.role_prompt(fix)
    assert fix_prompt.startswith(attempt_prompt.split("\n\nAttempt 1")[0])
    assert "the one fix a person ordered" in fix_prompt
    assert "the one fix a person ordered" not in attempt_prompt


def test_a_fix_request_without_its_instruction_is_refused() -> None:
    from orch_helpers import SCRIPTED_BOUNDS
    from pydantic import ValidationError

    from physgate.orchestrator.ports import SessionRequest

    with pytest.raises(ValidationError, match="starts from its instruction"):
        SessionRequest(
            subtask_id="s1",
            attempt=2,
            assigned_role="control",
            spec_path="spec.md",
            module_dir="m",
            model="claude-opus-5-5",
            repair_instruction=None,
            bounds=SCRIPTED_BOUNDS,
            kind="fix",
        )
