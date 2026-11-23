"""A plan of a few modules, its reads and its designs, run through the real loop over the fakes.

A shape names the modules in plan order, who reads from whom, and who builds what whom designs.
Every producer owns one interface node, which all its readers read; every module writes one node
constraining each interface it touches, all of one value, so no contract fails. Sizing, if the
plan has it, is closed by a pass of the same directory after every other module.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from loop_fakes import FakeDispatcher, KilledError, Rig
from test_a_pairs_contract_is_tested_once_both_its_modules_merged_and_blocks_nothing import (
    INTEG,
    entry,
    hooked,
    node,
    rig_for,
    side,
)
from test_a_queue_decision_acts_at_a_boundary import _layer

from physgate.contracts.pairs import ContractPair
from physgate.orchestrator import record
from physgate.orchestrator.design_pairs import DesignPair
from physgate.orchestrator.events import Event
from physgate.orchestrator.loop import Loop
from physgate.orchestrator.plan import InterfaceConsumers, SystemRequirement
from physgate.orchestrator.record import DecompositionSummary
from physgate.orchestrator.run_config import ModelStrings
from physgate.oslayer.probe import Present
from physgate.state.store import journal_records_after

ACTS = {
    "queue_decisions": "act",
    "os_layer": Present(mechanism="seatbelt", claude_version="2.1.301"),
}
#: Each subtask's role and module directory. Named so that the pairs, which the plan gives in
#: the order of their modules' names, put firmware's interface before sizing's, as a real run's.
SIZING, CLOSING = "sz-6a7b8c", "sz-c-9d0e1f"
CONTROL, FIRMWARE, ELECTRICAL = "drive-0a1b2c", "fw-3d4e5f", "el-4a5b6c"
#: A second module of the control and of the firmware role, for plans with many readers.
CONTROL2, FIRMWARE2 = "drive2-1a2b3c", "fw2-9a8b7c"
ROLE_OF = {
    SIZING: ("sizing", "sz"),
    CONTROL: ("control", "drive"),
    FIRMWARE: ("firmware", "fw"),
    ELECTRICAL: ("electrical", "el"),
    CONTROL2: ("control", "drive2"),
    FIRMWARE2: ("firmware", "fw2"),
}
NAMES = ("control", "electrical", "firmware", "sizing", "integration")


#: The most lines one process of a rig's run writes before the rig calls it a loop with no end.
#: The longest run of the wait rows writes a few hundred; a stuck loop writes without limit.
LINE_LIMIT = 2000


def bounded(loop: Loop, limit: int = LINE_LIMIT) -> Loop:
    """``loop``, whose writes are counted: past ``limit`` lines in one process, an assertion fails.

    The loop's own guard halts a wait line owed again; this bound is the rig's, so that a loop
    that spins another way fails a row as an assertion and never hangs it.
    """
    written = [0]
    emit = loop._emit  # noqa: SLF001 - the rig counts what the loop writes

    def counted(event: Event) -> None:
        written[0] += 1
        assert written[0] <= limit, (
            f"the loop wrote {written[0]} lines in one process and is not going to stop; "
            f"the last was {event.kind!r}"
        )
        emit(event)

    loop._emit = counted  # type: ignore[method-assign]  # noqa: SLF001
    return loop


@pytest.fixture
def under_release(monkeypatch: pytest.MonkeyPatch) -> None:
    """The run starts under the mark ``release``: the cycle rule before it was narrowed."""
    monkeypatch.setattr(record, "WAIT_CYCLE", "release")


def module_of(subtask_id: str) -> str:
    return subtask_id.rsplit("-", 1)[0]


def law_of(designer: str) -> str:
    """The design node ``designer`` writes and its builder builds."""
    return f"{ROLE_OF[designer][0]}.balance_controller"


def interface_of(producer: str) -> str:
    return f"{ROLE_OF[producer][0]}.out"


@dataclass(frozen=True)
class Shape:
    """``order``; ``reads`` as (producer, consumer); ``design`` as (designer, builder)."""

    order: tuple[str, ...]
    reads: tuple[tuple[str, str], ...] = ()
    design: tuple[tuple[str, str], ...] = ()
    closing: bool = True

    def pairs(self) -> tuple[ContractPair, ...]:
        grouped = sorted(self.reads, key=lambda r: (module_of(r[0]), module_of(r[1])))
        return tuple(
            ContractPair(
                producer=side(p, ROLE_OF[p][0]),
                consumer=side(c, ROLE_OF[c][0]),
                interfaces=(interface_of(p),),
            )
            for p, c in grouped
        )

    def interfaces(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(interface_of(p) for p, _ in self.reads))

    def touching(self, subtask_id: str) -> list[str]:
        mine = [interface_of(p) for p, c in self.reads if subtask_id in (p, c)]
        return sorted(set(mine))

    def begin(self, loop: Loop) -> None:
        plan = [entry(s, *ROLE_OF[s]) for s in self.order]
        if self.closing and SIZING in self.order:
            plan.append(entry(CLOSING, "sizing", "sz"))
        plan.append(entry(INTEG, "integration", "integration"))
        interfaces = self.interfaces()
        consumers = tuple(
            InterfaceConsumers(
                interface=interface_of(p),
                consumers=tuple(sorted({module_of(c) for q, c in self.reads if q == p})),
            )
            for p in dict.fromkeys(p for p, _ in self.reads)
        )
        requirement = (
            '{"requirement": "1", "contributing": [{"module": "drive", "criterion": "1"}]}'
        )
        head = journal_records_after(loop.run_dir.parent / "store", 0)[-1].rev
        summary = DecompositionSummary(
            session_id="decomposition",
            model="claude-sonnet-5",
            num_turns=1,
            subtasks=len(plan),
            interface_nodes=interfaces,
            spec_commit="e" * 40,
            head_revision=head,
            interface_consumers=consumers,
            system_requirements=(SystemRequirement.model_validate_json(requirement),),
            contract_pairs=self.pairs(),
            design_pairs=tuple(
                DesignPair(designer=d, builder=b, nodes=(law_of(d),)) for d, b in self.design
            )
            or None,
        )
        loop.record.start(plan, decomposed=summary)

    def rig(self, tmp_path: Path, verdicts: Sequence[str] = ("fail", "fail", "fail")) -> Rig:
        """A rig over a store holding the shape's interfaces; ``verdicts`` the reviews, in order."""
        nodes = [
            node(interface_of(p), ROLE_OF[p][0], kind="interface", v=12)
            for p in dict.fromkeys(p for p, _ in self.reads)
        ]
        rig = rig_for(
            tmp_path,
            interfaces=nodes,
            dispatcher=FakeDispatcher(trajectories=tmp_path / "run" / "sessions"),
        )
        writes: dict[str, list[dict[str, Any]]] = {}
        for s in (*self.order, CLOSING):
            role, mod = ROLE_OF.get(s, ("sizing", "sz"))
            made = [node(f"{mod}.main", role, *self.touching(SIZING if s == CLOSING else s), v=12)]
            made += [node(law_of(d), role, v=12) for d, _ in self.design if d == s]
            writes[s] = made
        rig.diff.writes.update(writes)  # type: ignore[attr-defined]
        rig.reviewer.verdicts[:] = list(verdicts)
        rig.config_overrides.update(ACTS)
        rig.config_overrides["models"] = ModelStrings(
            decomposition="claude-sonnet-5",
            roles=dict.fromkeys(NAMES, "claude-sonnet-5"),
            reviewers=dict.fromkeys(NAMES, "claude-opus-5-5"),
        )
        return rig


def first_run(rig: Rig, monkeypatch: pytest.MonkeyPatch, shape: Shape) -> str:
    """The first process, until it stops: the step it stopped at."""
    loop = bounded(rig.open())
    hooked(monkeypatch, loop, declared=shape.order)
    shape.begin(loop)
    _layer(loop)
    try:
        return str(loop.run().kind)
    finally:
        loop.close()


def resumed(rig: Rig, monkeypatch: pytest.MonkeyPatch, shape: Shape) -> str:
    """A fresh process takes the run over; the step it stopped at."""
    loop = bounded(rig.open())
    hooked(monkeypatch, loop, declared=shape.order)
    _layer(loop)
    try:
        return str(loop.resume().kind)
    finally:
        loop.close()


def resumed_before(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, shape: Shape, line: Callable[[Event], bool]
) -> None:
    """A fresh process takes the run over, killed before it writes the first line ``line`` picks."""
    loop = bounded(rig.open())
    killed = False
    hooked(monkeypatch, loop, declared=shape.order, kill=lambda event, _: line(event))
    _layer(loop)
    try:
        loop.resume()
    except KilledError:
        killed = True
    finally:
        loop.close()
    assert killed, "the run ended without writing the line it was to be killed before"
