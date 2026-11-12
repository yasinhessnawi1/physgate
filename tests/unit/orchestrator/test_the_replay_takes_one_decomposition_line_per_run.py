"""The replay takes one decomposition line per run, whatever came before it.

A run is decomposed once: its plan, its interfaces, its contract pairs and its system requirements
all come from that one line, and replay is how a recorded run is checked for forgery. A journal
with a second line could stand for a plan the run never followed. A call refused by its schema and
made again is not a second decomposition: it is recorded by its own lines (the retry line, or the
round's second proposal) and still ends in exactly one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from design_review_rig import outcome_of
from replan_rig import Step, decompose

from physgate.orchestrator.events import Event, read_events
from physgate.orchestrator.exceptions import CorruptEventLogError
from physgate.orchestrator.replay import replay

REFUSED = "schema_refused"
ONCE = "a run is decomposed once"


def _again(log: list[Event], *, update: dict[str, object] | None = None) -> list[Event]:
    """``log`` with its decomposition line written a second time right after it, renumbered."""
    at = next(i for i, e in enumerate(log) if e.kind == "decomposed")
    second = log[at].model_copy(update=update or {})
    shifted = [e.model_copy(update={"seq": e.seq + 1}) for e in log[at + 1 :]]
    return [*log[: at + 1], second.model_copy(update={"seq": log[at].seq + 1}), *shifted]


def _refused_for(log: list[Event]) -> str | None:
    got = outcome_of(lambda: replay(log))
    if not isinstance(got, BaseException):
        return None  # replayed
    assert isinstance(got, CorruptEventLogError), got
    return str(got.context["reason"])


@pytest.mark.parametrize(
    ("mode", "steps"),
    [
        ("off", [Step()]),
        ("off", [Step(call=REFUSED), Step()]),
        ("on", [Step(review="pass")]),
        ("on", [Step(call=REFUSED), Step(review="pass")]),
    ],
    ids=["one-call", "one-call-made-again", "reviewed", "reviewed-call-made-again"],
)
def test_a_second_decomposition_line_is_refused(
    tmp_path: Path, mode: str, steps: list[Step]
) -> None:
    ran = decompose(tmp_path, mode, steps)
    assert ran.code == 0, ran.err
    log = read_events(ran.run_dir / "events.jsonl")
    replay(log)
    assert _refused_for(_again(log)) == ONCE


def test_a_second_line_naming_another_plan_is_refused(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "off", [Step()])
    log = read_events(ran.run_dir / "events.jsonl")
    assert _refused_for(_again(log, update={"plan_sha256": "f" * 64})) == ONCE
