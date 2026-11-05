"""The laws cost at most a quarter more than the gate without them, on a dense graph.

The budget is a ratio measured in one process, never a time: a clock budget passes on one host
and fails on a slower one with no change to the code. On a graph of 40 supplies and 160
consumers that each draw from every supply (200 nodes, 6,400 edges), the whole gate at system
scope, built with a table of fifteen laws over every pattern and tolerance class, is timed
against the same gate built with the tracked table, which holds no law. Calls alternate between
the two, so a slow spell of the host weighs on both alike, and each pair gives one ratio. The
median ratio is held to the bound; the interquartile range and the smallest ratio are printed
beside it, with each side's median time.

Three of the fifteen laws bind on every supply or every edge of the graph, one leaves every
consumer unjudged, and the rest find no anchor: the cost of forming, evaluating and recording
instances is all in the measurement, as is the cost of looking for anchors that are not there.

The bound was set before any gate carrying a law had been timed. Moving it is a change to what
the gate may cost, recorded beside the measurement that prompted it.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest
from gate_fixtures import graph, node
from law_cases import full_table, table
from law_fixtures import laws_module

from physgate.gate.graph import GraphView
from physgate.gate.runner import PhysicsGate

#: The most the full law table may cost, as a multiple of the gate without it.
LAW_COST_RATIO = 1.25
#: Interleaved pairs measured, after one warm-up call of each.
PAIRS = 21


def dense(root: Path) -> GraphView:
    supplies = [
        node(
            f"electrical.s{i:02d}",
            kind="module",
            quantities={"power_supply": (10_000, "W"), "rated_output_power": (10_000, "W")},
        )
        for i in range(40)
    ]
    ids = [s["id"] for s in supplies]
    consumers = [
        node(f"electrical.c{i:03d}", quantities={"power_draw": (1.25, "W")}, constrains=ids)
        for i in range(160)
    ]
    graph(root, *supplies, *consumers)
    return GraphView.read(root, base_revision=0)


def timed(gate: PhysicsGate, view: GraphView) -> float:
    started = time.perf_counter()
    gate.run(view, ["system"], "on")
    return time.perf_counter() - started


@pytest.mark.integration
def test_the_full_law_table_costs_at_most_a_quarter_more_at_system_scope(tmp_path: Path) -> None:
    view = dense(tmp_path / "g")
    with_laws = PhysicsGate(laws=table(tmp_path / "t", full_table()))
    without = PhysicsGate(laws=laws_module().load_laws())
    laws = [r for r in with_laws.run(view, ["system"], "on").checks if r.name == "laws"]
    # The laws really bind: every edge, every supply, and every consumer left unjudged.
    judged = sum(getattr(r.details, "evaluated", 0) for r in laws if r.outcome == "pass")
    assert judged == 6_400 + 40 + 40
    assert sum(1 for r in laws if r.outcome == "unchecked") == 160
    timed(with_laws, view)
    timed(without, view)
    ratios, full, bare = [], [], []
    for pair in range(PAIRS):
        if pair % 2 == 0:
            a = timed(with_laws, view)
            b = timed(without, view)
        else:
            b = timed(without, view)
            a = timed(with_laws, view)
        full.append(a)
        bare.append(b)
        ratios.append(a / b)
    median = statistics.median(ratios)
    q1, _, q3 = statistics.quantiles(ratios, n=4)
    # The measured numbers, for the record.
    print(
        f"law cost ratio over {PAIRS} interleaved pairs: median {median:.4f}, "
        f"IQR {q1:.4f}-{q3:.4f}, min {min(ratios):.4f}; median times: with laws "
        f"{statistics.median(full):.4f} s, without {statistics.median(bare):.4f} s"
    )
    assert median <= LAW_COST_RATIO, f"the laws cost {median:.3f} times the gate without them"
