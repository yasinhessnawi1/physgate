"""The integration call names what changed together, and in what order, from the log alone.

The propagation check judges "the same commit" as one merged attempt, since a
role writes only its own nodes (ARCH-082, ARCH-005). The baseline is the journal
head decomposition recorded; every later revision belongs to the attempt whose
``write_done`` line names it.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from physgate.orchestrator.change_sets import change_history
from physgate.orchestrator.events import Decomposed, Event, RunStarted, WriteDone
from physgate.orchestrator.protocols import ChangeSet, IntegrationArtefact

TS = "2026-09-27T12:00:00.000000Z"


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


def done(seq: int, subtask: str, attempt: int, revision: int) -> WriteDone:
    return WriteDone(
        **env(seq), subtask_id=subtask, attempt=attempt, node_id=f"n.r{revision}", revision=revision
    )


def test_the_baseline_is_what_decomposition_recorded_and_each_attempt_is_one_change_set() -> None:
    events: list[Event] = [
        RunStarted(**env(0), config_sha256="a" * 64),
        decomposed(1, head=2),
        done(2, "s1", 1, 3),
        done(3, "s1", 1, 4),
        done(4, "s2", 2, 5),
    ]
    baseline, sets = change_history(events)
    assert baseline == 2
    assert sets == (
        ChangeSet(subtask_id="s1", attempt=1, revisions=(3, 4)),
        ChangeSet(subtask_id="s2", attempt=2, revisions=(5,)),
    )


def test_a_run_begun_without_a_decomposition_has_baseline_zero() -> None:
    baseline, sets = change_history(
        [RunStarted(**env(0), config_sha256="a" * 64), done(1, "s1", 1, 1)]
    )
    assert baseline == 0 and sets == (ChangeSet(subtask_id="s1", attempt=1, revisions=(1,)),)


def test_an_attempt_resumed_between_its_writes_is_still_one_change_set() -> None:
    # A resumed apply keeps the writes that landed and writes only the rest, so one
    # attempt's revisions may be separated by lines of the resume; they stay together.
    events: list[Event] = [
        decomposed(0, head=1),
        done(1, "s1", 1, 2),
        RunStarted(**env(2), config_sha256="a" * 64),
        done(3, "s1", 1, 3),
    ]
    assert change_history(events)[1] == (ChangeSet(subtask_id="s1", attempt=1, revisions=(2, 3)),)


def test_a_run_that_wrote_nothing_has_no_change_sets() -> None:
    assert change_history([decomposed(0, head=4)]) == (4, ())


def artefact(baseline: int, *sets: tuple[str, int, tuple[int, ...]]) -> IntegrationArtefact:
    return IntegrationArtefact(
        run_id="run-1",
        graph_root="/store",
        run_head="b" * 40,
        baseline_revision=baseline,
        change_sets=tuple(ChangeSet(subtask_id=s, attempt=a, revisions=r) for s, a, r in sets),
    )


def test_the_integration_artefact_accepts_a_history_in_order() -> None:
    assert artefact(2, ("s1", 1, (3, 4)), ("s2", 1, (5,))).change_sets[1].revisions == (5,)


@pytest.mark.parametrize(
    ("baseline", "sets"),
    [
        (3, (("s1", 1, (3,)),)),
        (0, (("s1", 1, (2,)), ("s2", 1, (1,)))),
        (0, (("s1", 1, (2, 2)),)),
        (0, (("s1", 1, (1,)), ("s2", 1, (1,)))),
        (0, (("s1", 1, ()),)),
    ],
    ids=[
        "a revision at the baseline",
        "attempts out of order",
        "a revision twice in one set",
        "one revision in two sets",
        "an empty change set",
    ],
)
def test_the_integration_artefact_refuses_a_history_that_cannot_have_happened(
    baseline: int, sets: tuple[tuple[str, int, tuple[int, ...]], ...]
) -> None:
    with pytest.raises(ValidationError):
        artefact(baseline, *sets)


def test_the_integration_artefact_requires_a_history() -> None:
    with pytest.raises(ValidationError, match="baseline_revision"):
        IntegrationArtefact(run_id="run-1", graph_root="/store", run_head="b" * 40)  # type: ignore[call-arg]
