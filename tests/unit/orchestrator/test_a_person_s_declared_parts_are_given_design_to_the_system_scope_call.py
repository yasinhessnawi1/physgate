"""A person's declared parts are the given design the system-scope call judges every attempt above.

ARCH-122 with ARCH-082. The system-scope call names what changed together above a baseline, and
the gate refuses a history that leaves any revision above it unnamed. A run that asks writes each
part a person has or makes before any session runs, at revisions above decomposition's head and
below every attempt's, and no attempt wrote them. They are given to the design as decomposition's
interface nodes are: the baseline the call is told is the last of them, so every attempt's writes
are named exactly as before, and every check still reads the declared nodes in the whole graph.
The history the operator's UI shows a node by is not this one, and is unchanged.
"""

from __future__ import annotations

from typing import Any

from physgate.orchestrator import change_sets as change_sets_module
from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.events import Decomposed, Event, PartsWriteDone, RunStarted, WriteDone
from physgate.orchestrator.protocols import ChangeSet

TS = "2026-11-15T12:00:00.000000Z"


def env(seq: int) -> dict[str, Any]:
    return {"seq": seq, "ts": TS, "run_id": "run-1", "gate_mode": "on"}


def decomposed(seq: int, head: int) -> Decomposed:
    return Decomposed(
        **env(seq),
        session_id="decomp",
        model="claude-sonnet-5",
        num_turns=1,
        subtasks=2,
        interface_nodes=("iface.power_bus",),
        spec_commit="a" * 40,
        head_revision=head,
    )


def parts_done(seq: int, revision: int) -> PartsWriteDone:
    return PartsWriteDone(**env(seq), node_id=f"electrical.part_{revision}", revision=revision)


def done(seq: int, subtask: str, attempt: int, revision: int) -> WriteDone:
    return WriteDone(
        **env(seq), subtask_id=subtask, attempt=attempt, node_id=f"n.r{revision}", revision=revision
    )


def _given() -> Any:  # noqa: ANN401 - the function, or a failed assertion that it is not built
    found = getattr(change_sets_module, "integration_history", None)
    assert found is not None, "the system-scope call is told no history that gives declared parts"
    return found


ASKED: list[Event] = [
    RunStarted(**env(0), config_sha256="a" * 64),
    decomposed(1, head=1),
    parts_done(2, 2),
    parts_done(3, 3),
    done(4, "s1", 1, 4),
    done(5, "s1", 1, 5),
    done(6, "s2", 1, 6),
]


def test_the_declared_parts_are_below_the_baseline_and_every_attempt_is_named_as_before() -> None:
    baseline, sets = _given()(ASKED)
    assert baseline == 3
    assert sets == (
        ChangeSet(subtask_id="s1", attempt=1, revisions=(4, 5)),
        ChangeSet(subtask_id="s2", attempt=1, revisions=(6,)),
    )


def test_a_run_that_asked_and_wrote_nothing_is_told_decomposition_s_head() -> None:
    events = [event for event in ASKED if not isinstance(event, PartsWriteDone)]
    assert _given()(events) == change_history(events)


def test_a_run_that_did_not_ask_is_told_exactly_what_it_was_told_before() -> None:
    events: list[Event] = [
        RunStarted(**env(0), config_sha256="a" * 64),
        decomposed(1, head=2),
        done(2, "s1", 1, 3),
        done(3, "s2", 2, 4),
    ]
    assert (
        _given()(events)
        == change_history(events)
        == (
            2,
            (
                ChangeSet(subtask_id="s1", attempt=1, revisions=(3,)),
                ChangeSet(subtask_id="s2", attempt=2, revisions=(4,)),
            ),
        )
    )


def test_a_parts_write_after_an_attempt_s_write_is_not_given() -> None:
    # Replay refuses such a log (no dispatch before the release); here the history alone is
    # asked, and a part written above an attempt is not folded into what came before it.
    events: list[Event] = [*ASKED[:2], done(2, "s1", 1, 2), parts_done(3, 3)]
    baseline, _ = _given()(events)
    assert baseline == 1


def test_the_ui_s_history_still_names_decomposition_s_head() -> None:
    # The history a node's revisions are labelled by is the one every reader had before.
    assert change_history(ASKED)[0] == 1
