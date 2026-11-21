"""Each promoted law, seen through the real loop: it warns, names itself, and blocks nothing.

The nine laws in the table are all at ``warn``. This drives one stand-in run through the
``physgate`` command with the real binary on the scripted endpoint (no model, no key) and the
real gate, once per gate mode, and reads what the loop wrote:

- **A tripping design**: one design that breaks each of the nine laws, every one with the values
  of that law's own failing example in the table, on nodes that carry none of the law's excusing
  names and no other law's inputs. Under ``on`` and under ``observe`` each law's record is a
  warning that names the law, the instance, both sides, the residual and the allowance, the
  digest of the table and the law's status, with the count of instances evaluated. The verdict
  is not a failure, nothing is blocked, the reviewer stand-in runs, the module merges and nothing
  is escalated. The record is stamped with the run's mode.
- **Gate mode off**: no check runs, so no law record is written.
- **A clean design**: the same nine shapes with values the laws hold for. Each law passes once,
  over the one instance it finds, and no law warns.
- **The catch table** counts the warnings as no catch: a warning is not a blocked artefact.

**No row here is about a law at ``block``.** Every law is at ``warn``: a law moves to ``block``
only when the owner approves it, after the false-positive audit, and none has. A law at ``block``
has no row because none exists. The real-model run of the slice is a later step: it is the first
real run after this merges.

The gate's lines (``physgate gate-events``) carry the check, the node, the outcome, whether it
blocks and the run's mode; the law's own name is in the record the loop wrote to the event log,
which is what the per-law rows read. The stand-in role is ``electrical``, which owes no
sign-off, so the run ends.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import node
from gate_run import build_install, drive_run

from physgate.gate.laws import load_laws
from physgate.orchestrator.catches import catches
from physgate.orchestrator.events import (
    GateRan,
    GateSkipped,
    IntegrationGateRan,
    Merged,
    ReviewRan,
)
from physgate.orchestrator.gate_events import GateEvent
from physgate.orchestrator.protocols import CheckRecord, LawDetails, PassDetails

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("PHYSGATE_CLAUDE_BIN") or shutil.which("claude")),
        reason="no Claude Code binary on this machine",
    ),
]

BRIEF = (
    "STAND-IN BRIEF, written for the law library's integration rows; not the reference "
    "design's brief.\n\nSize the power and drive of a small robot.\n"
)

#: A node that is a motor-like part, for the laws read at one node.
Q = dict[str, tuple[float | int, str]]


@dataclass(frozen=True)
class Case:
    """One law's tripping shape, and what its record must say.

    ``anchor`` is the node the law's record sits on. ``left`` and ``right`` are the two sides
    in the units the check records them in (SI), from the law's failing example.
    """

    law_id: str
    anchor: str
    left: float
    right: float
    nodes: tuple[dict[str, Any], ...]
    clean: tuple[dict[str, Any], ...]


def _units(prefix: str, moment: float) -> tuple[dict[str, Any], ...]:
    """Two torque units under one carrier, each reacting ``moment`` N*m (check 3 reads it).

    Each unit's torque is its own reaction, so the equilibrium check holds; the carrier's
    reaction is what the law sums.
    """
    return tuple(
        node(
            f"electrical.{prefix}_unit_{i}",
            quantities={"reaction_moment": (0.0167, "N*m"), "torque_peak": (0.0167, "N*m")},
            constrains=[f"electrical.{prefix}_carrier"],
        )
        for i in (1, 2)
    )


def _case(law_id: str, anchor: str, left: float, right: float, bad: Q, good: Q) -> Case:
    return Case(
        law_id,
        f"electrical.{anchor}",
        left,
        right,
        (node(f"electrical.{anchor}", quantities=bad),),
        (node(f"electrical.{anchor}", quantities=good),),
    )


def _edge_case(
    law_id: str, anchor: str, left: float, right: float, bad: tuple[Q, Q], good: tuple[Q, Q]
) -> Case:
    def pair(quantities: tuple[Q, Q]) -> tuple[dict[str, Any], ...]:
        return (
            node(
                f"electrical.{anchor}",
                quantities=quantities[0],
                constrains=[f"electrical.{anchor}_target"],
            ),
            node(f"electrical.{anchor}_target", quantities=quantities[1]),
        )

    return Case(law_id, f"electrical.{anchor}", left, right, pair(bad), pair(good))


CASES: tuple[Case, ...] = (
    _case(
        "electrical_power",
        "power_node",
        9e-4,
        4.95e-4,
        {"power_draw": (0.9, "mW"), "supply_voltage": (3.3, "V"), "current_draw": (0.15, "mA")},
        {"power_draw": (0.495, "mW"), "supply_voltage": (3.3, "V"), "current_draw": (0.15, "mA")},
    ),
    _case(
        "no_load_below_stall",
        "no_load_node",
        150,
        1.5,
        {"no_load_current": (150, "A"), "rated_stall_current": (1.5, "A")},
        {"no_load_current": (0.2, "A"), "rated_stall_current": (1.5, "A")},
    ),
    _case(
        "overall_gear_ratio_product",
        "gear_node",
        144,
        148.176,
        {
            "overall_gear_ratio": (144, "1"),
            "gear_ratio": (51.45, "1"),
            "external_gear_ratio": (2.88, "1"),
        },
        {
            "overall_gear_ratio": (148.176, "1"),
            "gear_ratio": (51.45, "1"),
            "external_gear_ratio": (2.88, "1"),
        },
    ),
    _edge_case(
        "rate_throughput_output_data_rate",
        "odr_loop",
        208,
        104,
        ({"update_rate": (208, "Hz")}, {"output_data_rate": (104, "Hz")}),
        ({"update_rate": (100, "Hz")}, {"output_data_rate": (104, "Hz")}),
    ),
    _edge_case(
        "rate_throughput_sample_rate",
        "sr_loop",
        250,
        128,
        ({"update_rate": (250, "Hz")}, {"sample_rate": (128, "Hz")}),
        ({"update_rate": (100, "Hz")}, {"sample_rate": (128, "Hz")}),
    ),
    Case(
        "reaction_moment_sum",
        "electrical.rm_carrier",
        0.0167,
        0.0334,
        (
            node("electrical.rm_carrier", quantities={"reaction_moment": (0.0167, "N*m")}),
            *_units("rm", 0.0167),
        ),
        (
            node("electrical.rm_carrier", quantities={"reaction_moment": (0.0334, "N*m")}),
            *_units("rm", 0.0167),
        ),
    ),
    _case(
        "stall_current_within_peak_stall",
        "stall_node",
        1.8,
        1.35,
        {"stall_current": (1.8, "A"), "peak_stall_current": (1.35, "A")},
        {"stall_current": (1.35, "A"), "peak_stall_current": (1.8, "A")},
    ),
    _case(
        "within_rating_current",
        "rating_i_node",
        1.4,
        1,
        {"current_draw": (1.4, "A"), "current_limit": (1, "A")},
        {"current_draw": (0.8, "A"), "current_limit": (1, "A")},
    ),
    _case(
        "within_rating_voltage",
        "rating_v_node",
        14.4,
        12,
        {"supply_voltage": (14.4, "V"), "absolute_maximum_voltage": (12, "V")},
        {"supply_voltage": (7.2, "V"), "absolute_maximum_voltage": (12, "V")},
    ),
)

TRIPPING = tuple(n for case in CASES for n in case.nodes)
CLEAN = tuple(n for case in CASES for n in case.clean)
IDS = [case.law_id for case in CASES]

#: One run per (design, mode), made by the first row that asks for it.
_RUNS: dict[tuple[str, str], tuple[Any, list[Any], Any, list[dict[str, Any]]]] = {}


@pytest.fixture(scope="module")
def install(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_install(tmp_path_factory)


def run_of(
    design: str,
    mode: str,
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[Any, list[Any], Any, list[dict[str, Any]]]:
    if (design, mode) not in _RUNS:
        _RUNS[design, mode] = drive_run(
            tmp_path,
            install,
            monkeypatch,
            capsys,
            [("drive", "modules/power")],
            TRIPPING if design == "tripping" else CLEAN,
            f"laws_{design}_{mode}",
            gate_mode=mode,
            brief=BRIEF,
        )
    return _RUNS[design, mode]


def law_records(events: list[Any]) -> list[CheckRecord]:
    """Every laws-check record of the attempts' gate calls."""
    return [
        r for e in events if isinstance(e, GateRan) for r in e.result.checks if r.name == "laws"
    ]


@pytest.mark.parametrize("mode", ["on", "observe"])
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_tripping_design_makes_each_law_warn_and_blocks_nothing(
    case: Case,
    mode: str,
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, lines = run_of(
        "tripping", mode, tmp_path, install, monkeypatch, capsys
    )
    (gated,) = [e for e in events if isinstance(e, GateRan)]
    warned = [
        r
        for r in gated.result.checks
        if r.name == "laws" and r.outcome == "warn" and isinstance(r.details, LawDetails)
        if r.details.law_id == case.law_id
    ]
    (record,) = warned
    details = record.details
    assert isinstance(details, LawDetails)
    # The record names the law, the instance, both sides, the residual, the digest and the status.
    assert (record.node, record.scope, record.blocking, record.gate_mode) == (
        case.anchor,
        "module",
        False,
        mode,
    )
    assert details.law_status == "warn"
    assert case.anchor in details.expression
    assert details.left.value == pytest.approx(case.left, rel=1e-9)
    assert details.right.value == pytest.approx(case.right, rel=1e-9)
    assert details.residual.value != 0
    assert details.laws_sha256 == load_laws().sha256
    assert details.evaluated == 1
    assert details.statement and details.source and details.inputs
    # Nothing is blocked: the verdict is not a failure, the reviewer runs, the module merges.
    assert (gated.result.verdict, gated.result.failing_check, gated.result.mode) == (
        "pass",
        None,
        mode,
    )
    assert [r for r in gated.result.checks if r.outcome == "fail"] == []
    assert len([e for e in events if isinstance(e, ReviewRan)]) == 1 and reviewer.calls == 1
    assert len([e for e in events if isinstance(e, Merged)]) == 1
    assert set(printed["subtasks"].values()) == {"done"}
    assert printed["open_queue_items"] == []
    # The gate's lines carry the warning on its node, stamped with the run's mode.
    carried = [
        x
        for x in lines
        if x["name"] == "laws" and x["outcome"] == "warn" and x["node"] == case.anchor
    ]
    assert [(x["scope"], x["check"], x["blocking"], x["gate_mode"]) for x in carried] == [
        ("module", 8, False, mode),
        ("system", 8, False, mode),
    ]
    # The integration call judges the same instance again at system scope, and warns too.
    (integrated,) = [e for e in events if isinstance(e, IntegrationGateRan)]
    assert (integrated.result.verdict, integrated.result.mode) == ("pass", mode)
    assert [
        r.details.law_id
        for r in integrated.result.checks
        if r.name == "laws" and r.outcome == "warn" and isinstance(r.details, LawDetails)
        if r.node == case.anchor
    ] == [case.law_id]


@pytest.mark.parametrize("mode", ["on", "observe"])
def test_the_catch_table_counts_the_warnings_as_no_catch(
    mode: str,
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, events, _, lines = run_of("tripping", mode, tmp_path, install, monkeypatch, capsys)
    warned = [r for r in law_records(events) if r.outcome == "warn"]
    assert sorted(r.details.law_id for r in warned if isinstance(r.details, LawDetails)) == sorted(
        IDS
    )
    rows = catches([GateEvent.model_validate(x) for x in lines])
    (laws,) = [r for r in rows if r.name == "laws"]
    assert laws.check == 8 and laws.gate_mode == mode
    assert (laws.blocking_failures, laws.artefacts_caught, laws.caught_after_reviewer_passed) == (
        0,
        0,
        0,
    )
    assert laws.checks_run >= 1


def test_with_the_gate_off_no_law_record_is_written(
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, lines = run_of(
        "tripping", "off", tmp_path, install, monkeypatch, capsys
    )
    assert law_records(events) == []
    assert [e for e in events if isinstance(e, GateRan)] == []
    (skipped,) = [e for e in events if isinstance(e, GateSkipped)]
    assert skipped.reason == "gate_mode=off"
    assert lines == []
    assert len([e for e in events if isinstance(e, Merged)]) == 1 and reviewer.calls == 1
    assert printed["step"] == "done"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_a_clean_design_passes_each_law_once_and_none_warns(
    case: Case,
    tmp_path: Path,
    install: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    printed, events, reviewer, _ = run_of("clean", "on", tmp_path, install, monkeypatch, capsys)
    (gated,) = [e for e in events if isinstance(e, GateRan)]
    laws = [r for r in gated.result.checks if r.name == "laws"]
    assert [r for r in laws if r.outcome in ("warn", "fail")] == []
    passes = [
        r
        for r in laws
        if r.outcome == "pass"
        and isinstance(r.details, PassDetails)
        and r.details.law_id == case.law_id
    ]
    (one,) = passes
    assert isinstance(one.details, PassDetails) and one.details.evaluated == 1
    assert gated.result.verdict == "pass"
    assert reviewer.calls == 1 and set(printed["subtasks"].values()) == {"done"}
