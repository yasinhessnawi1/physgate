"""R-LAW-01 §2.3, §3 and §5.6 on invented records: the gate pins, the G match, reality scoring.

Run explicitly, from the repository root: uv run pytest -q experiments/R-LAW-01
"""

from __future__ import annotations

from typing import Any

import law_extract as X
import law_reality as R
import law_regate as G
import pytest

NODE_IDS = {"e.reg", "e.board_a", "e.board_b", "m.frame"}


def record(check: int, name: str, message: str = "m", **kw: Any) -> dict[str, Any]:  # noqa: ANN401
    r = {
        "check": check,
        "name": name,
        "scope": "system",
        "outcome": "fail",
        "node": None,
        "module": None,
        "message": message,
        "details": {},
    }
    r.update(kw)
    return r


def line(*locus: tuple[str, str]) -> dict[str, Any]:
    return {"line_id": "L0001", "locus": [list(p) for p in locus]}


def form(gate_relation: str, *quantities: str) -> dict[str, Any]:
    return {
        "gate_relation": gate_relation,
        "inputs": [
            {"symbol": f"x{i}", "node": "e.reg", "quantity": q, "value": 1, "unit": "W"}
            for i, q in enumerate(quantities)
        ],
    }


@pytest.fixture(scope="module")
def table() -> dict[str, Any]:
    return G.appendix_c()


def test_the_checkout_holds_the_pinned_gate() -> None:
    G.check_pins(X.REPO)
    with pytest.raises(X.Refused, match="tree"):
        G.check_pins(X.REPO, tree="0" * 40)
    with pytest.raises(X.Refused, match="catalogue"):
        G.check_pins(X.REPO, catalogue="0" * 64)


def test_appendix_c_names_every_relation(table: dict[str, Any]) -> None:
    assert set(table) == set(G.RELATION_NAMES)
    assert table["units_kind"][1]("motor_voltage")  # a suffix-kind name
    assert not table["propagation"][1]("motor_voltage")


def test_a_power_record_matches_by_node_quantity_and_relation(table: dict[str, Any]) -> None:
    rec = record(
        4,
        "power",
        node="e.reg",
        details={"form": "power", "consumers": ["e.board_a"], "power_draw": 1},
    )
    hits = G.matches(
        line(("e.board_a", "power_draw")),
        form("power_budget", "power_draw"),
        [rec],
        NODE_IDS,
        table,
    )
    assert hits and "power_budget" in hits[0]["relations"]
    # the inputs of a form naming another relation still match when every one lies in a relation
    assert G.matches(
        line(("e.reg", "power_draw")),
        form("none", "power_draw", "power_supply"),
        [rec],
        NODE_IDS,
        table,
    )
    # an input outside every relation of the record, and no relation named: no match
    assert not G.matches(
        line(("e.reg", "power_draw")), form("none", "power_draw", "mass"), [rec], NODE_IDS, table
    )


def test_no_match_without_a_failing_record_inputs_or_a_locus_node(table: dict[str, Any]) -> None:
    rec = record(4, "power", node="e.reg", details={"power_draw": 1})
    passing = dict(rec, outcome="pass")
    f = form("power_budget", "power_draw")
    assert not G.matches(line(("e.reg", "power_draw")), f, [passing], NODE_IDS, table)
    assert not G.matches(
        line(("e.reg", "power_draw")), form("power_budget"), [rec], NODE_IDS, table
    )
    assert not G.matches(line(("m.frame", "power_draw")), f, [rec], NODE_IDS, table)
    assert not G.matches(line(("e.reg", "mass")), f, [rec], NODE_IDS, table)
    assert not G.matches(line(("e.reg", "power_draw")), None, [rec], NODE_IDS, table)


def test_checks_1_and_7_need_the_quantity_in_the_message(table: dict[str, Any]) -> None:
    rec = record(
        7,
        "propagation",
        message="e.reg changed; e.board_a not revisited",
        node="e.reg",
        details={"form": "propagation", "unwritten": ["e.board_a"]},
    )
    f = form("propagation", "power_draw")
    assert not G.matches(line(("e.board_a", "power_draw")), f, [rec], NODE_IDS, table)
    rec2 = dict(rec, message="e.reg power_draw changed; e.board_a not revisited")
    assert G.matches(line(("e.board_a", "power_draw")), f, [rec2], NODE_IDS, table)


def test_a_record_s_nodes_come_from_its_details(table: dict[str, Any]) -> None:
    rec = record(
        5,
        "conservation",
        node=None,
        module="m.frame",
        details={"members": [{"id": "e.board_b"}], "text": "not a node"},
    )
    assert G.record_nodes(rec, NODE_IDS) == {"m.frame", "e.board_b"}
    assert G.record_relations(dict(rec, details={"mass": 1}), table) == ["mass_sum"]
    assert G.record_relations(rec, table) == []


# ---------------------------------------------------------------- reality


def test_prior_agreement_kappa() -> None:
    assert R.kappa([("a", "a"), ("b", "b")]) == 1.0
    assert R.kappa([("a", "b"), ("b", "a")]) == -1.0
    assert R.kappa([]) is None


def test_a_control_needs_an_introduced_true_flaw_on_changed_pairs_only() -> None:
    class SD:
        def changed_pairs(self, pair: str) -> set[tuple[str, str]]:
            return {("n", "q")}

    sd: Any = SD()
    x = {"side": "injected", "pair": "p", "locus": [["n", "q"]]}
    v = {"verdict": "true_flaw", "origin": "introduced"}
    assert R.eligible_control(x, v, sd)
    assert not R.eligible_control(dict(x, locus=[["n", "q"], ["n", "r"]]), v, sd)
    assert not R.eligible_control(dict(x, locus=[]), v, sd)
    assert not R.eligible_control(dict(x, side="twin"), v, sd)
    assert not R.eligible_control(x, dict(v, origin="both"), sd)
    assert not R.eligible_control(x, None, sd)
