"""The coverage rules refuse everything the gate refused before them, and fail no clean design.

``gate_before/record.json`` holds what units, magnitude, power, conservation and thermal said
before the coverage rules, over every graph the repository has: every graph the unit and
injected-error suites build, the equilibrium record's graphs, and the designs kept in the
fixtures and test corpora. ``gate_before/make_record.py`` says how it was made, and from
which commit.

Two directions are held:

- **No refusal is lost.** Every failing record comes back, on the same node and check, with
  the same value; its words are the same, except a magnitude refusal, whose range text may name
  a new source. The one exception is ruled and named: a stall current outside one maker's
  hobby-motor span is not an error by itself, so that span no longer blocks (the current
  headroom relation judges a stall current instead). Each refusal lost that way is counted.
  A second, ruled loosening leaves no refusal to count here: the electrical ``sample_rate``
  range widened from one part's register span (3.906 Hz to 8 kHz) to six makers' output data
  rates (0.78 Hz to 32 kHz), so an electrical rate in (8 kHz, 32 kHz] or [0.78, 3.906) Hz that
  failed before passes now. The widening is sourced, and the range is still an inertial
  sensor's: an ADC's or an audio codec's rate on an electrical node is refused by it, a named
  limit.
- **No clean design fails.** A graph that drew no failure before draws none now, except a
  graph a test built to hold an error of a kind the gate did not judge before. Each is named
  by the digest of its content (its nodes, sorted by id), never by its place in the record:
  the record's ``tests:NNNN`` ids are sorted indices, and every graph the suite gains moves
  them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from check_3_cases import random_mounts

from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.registry import REGISTRY
from physgate.state.store import Store

RECORD = Path(__file__).parent / "gate_before" / "record.json"
#: The record's digest, so the comparison is against the bytes that were made and reviewed.
RECORD_SHA256 = "ee0b6fde0b4b5cd16b0a9ba2a5b342fec00dfc7b128bb75632a6906265eefaa2"
CHECKS = ("units", "magnitude", "power", "conservation", "thermal")


def digest(payloads: list[dict[str, Any]]) -> str:
    """The sha256 of a graph's nodes, sorted by id and written canonically."""
    canonical = json.dumps(
        sorted(payloads, key=lambda p: str(p["id"])), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _cases() -> list[tuple[str, list[dict[str, Any]], list[dict[str, Any]]]]:
    data = RECORD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == RECORD_SHA256
    record = json.loads(data)["cases"]
    drawn = {f"check_3:{cid}": nodes for cid, nodes in random_mounts()}
    return [(c["id"], c.get("nodes") or drawn[c["id"]], c["before"]) for c in record]


def _now(root: Path, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    store = Store(root)
    try:
        for payload in payloads:
            assert store.write_node(dict(payload), str(payload["owner_role"])).accepted
    finally:
        store.close()
    view = GraphView.read(root, base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds())
    return [
        {"check": check.name, **o.model_dump(mode="json")}
        for check in REGISTRY
        if check.name in CHECKS
        for o in check.run(ctx).observations
    ]


def _key(record: dict[str, Any]) -> tuple[Any, ...]:
    message = record["message"]
    if record["check"] == "magnitude":
        message = message.split(", outside ")[0]
    return (record["check"], record["node"], json.dumps(record["value"], sort_keys=True), message)


def _ruled(record: dict[str, Any]) -> bool:
    return bool(
        record["check"] == "magnitude" and str(record["message"]).startswith("stall_current of ")
    )


@pytest.fixture(scope="module")
def judged(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, str, Any, Any]]:
    """(the case's id, its content digest, its records before, its records now)."""
    root = tmp_path_factory.mktemp("cases")
    return [
        (cid, digest(payloads), before, _now(root / str(k), payloads))
        for k, (cid, payloads, before) in enumerate(_cases())
    ]


def test_every_refusal_the_gate_made_before_the_rules_it_still_makes(
    judged: list[tuple[str, str, Any, Any]],
) -> None:
    failing = [o for _, _, before, _ in judged for o in before if o["outcome"] == "fail"]
    assert len(failing) == FAILURES_BEFORE
    lost: list[tuple[str, str, str]] = []
    ruled: list[tuple[str, str, str]] = []
    for cid, _, before, now in judged:
        kept = {_key(o) for o in now if o["outcome"] == "fail"}
        for o in before:
            if o["outcome"] == "fail" and _key(o) not in kept:
                (ruled if _ruled(o) else lost).append((cid, o["check"], o["node"]))
    assert lost == []
    assert len(ruled) == RULED_LOST


def test_no_graph_that_drew_no_failure_draws_one_now_unless_it_holds_a_named_error(
    judged: list[tuple[str, str, Any, Any]],
) -> None:
    clean = [
        (content, now)
        for _, content, before, now in judged
        if not any(o["outcome"] == "fail" for o in before)
    ]
    assert len(clean) == CLEAN_BEFORE
    new = sorted(
        (content, o["check"], o["node"])
        for content, now in clean
        for o in now
        if o["outcome"] == "fail"
    )
    assert new == sorted(NAMED_ERRORS)
    # Every named error is a graph the record holds: a digest that matches nothing would let
    # a stale name stand for a failure that no longer happens.
    held = {content for _, content, _, _ in judged}
    assert all(content in held for content, _, _ in NAMED_ERRORS)


def _reaches(payloads: list[dict[str, Any]]) -> set[str]:
    """Which of the new rules a graph gives something to judge."""
    limits = {p["id"] for p in payloads if "current_limit" in p["quantities"]}
    found = set()
    for p in payloads:
        q = p["quantities"]
        if "stall_current" in q and limits & set(p["constrains"]):
            found.add("headroom")
        if "energy_capacity" in q and "max_discharge_power" in q:
            found.add("discharge")
        if p["domain"] == "electrical" and "sample_rate" in q:
            found.add("sample_rate")
    return found


def test_the_clean_graphs_reach_every_new_rule() -> None:
    # A guard over graphs that hold nothing a new rule reads proves nothing about it.
    reached: dict[str, int] = {}
    for _, payloads, before in _cases():
        if not any(o["outcome"] == "fail" for o in before):
            for rule in _reaches(payloads):
                reached[rule] = reached.get(rule, 0) + 1
    assert reached == {"headroom": 40, "discharge": 6, "sample_rate": 20}


#: The failing records in the record, counted when it was made.
FAILURES_BEFORE = 310
#: Refusals the stall-current span made that are gone with it: the magnitude check's own
#: tests of that span (240 A, 240000 mA, and its two edges). Each is now the motor's
#: stall current recorded as having no range; where a driver is declared, the headroom
#: relation judges it.
RULED_LOST = 5
#: The graphs that drew no failure before the rules.
CLEAN_BEFORE = 1299
#: Graphs a test built to hold an error the gate did not judge before, each by the digest
#: of its content, with the check that now refuses it and the node refused.
NAMED_ERRORS: list[tuple[str, str, str]] = [
    # The unit check's test of the headroom relation it could not judge: electrical.driver
    # with a 1 A current_limit and electrical.motor with a 6 A stall_current, recorded then
    # as unchecked. The power check now refuses it.
    (
        "92ec6d55a91138cf800e434e2574d1054e3c138a5a1bec71064a57fb04a593ad",
        "power",
        "electrical.driver",
    ),
]
