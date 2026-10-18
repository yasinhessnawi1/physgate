"""The torque-unit and carrier readings fail no clean shape, and lose no refusal the check made.

``loads_before/record.json`` holds what the equilibrium check said, at master's commit before
the readings, over the hand-made torque units and carriers of ``loads_before/shapes.py``:
clean shapes and the kinds of error a writer makes. ``loads_before/make.py`` says how it was
made. Two directions are held, as the other records hold them:

- **No refusal is lost.** Every failing record before comes back on the same node with the
  same value and words. Before the readings the check refused none of these shapes (it read
  none of them), and the test says so by count rather than assuming it.
- **No clean shape fails.** A shape that drew no failure before draws none now, except the
  shapes built to hold an error, each named by the digest of its content with the node the
  readings refuse; and every one of those is refused now, so the readings reach the kinds of
  error they were written for.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from loads_before.shapes import SHAPES, digest, errors

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.state.store import Store

RECORD = Path(__file__).parent / "loads_before" / "record.json"
#: The record's digest, so the comparison is against the bytes that were made and reviewed.
RECORD_SHA256 = "8fdf8d5aa86b05bf8bfa72e0ee4a8315c1cc73a4b8d720155befd98db4538ae1"
#: The failing records in the record, counted when it was made: the check read none of these.
FAILURES_BEFORE = 0


def _now(root: Path, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    store = Store(root)
    try:
        for payload in payloads:
            assert store.write_node(dict(payload), str(payload["owner_role"])).accepted
    finally:
        store.close()
    view = GraphView.read(root, base_revision=0)
    ran = check_equilibrium.run(CheckContext(view=view, scope="system", bounds=load_bounds()))
    return [o.model_dump(mode="json") for o in ran.observations]


@pytest.fixture(scope="module")
def judged(tmp_path_factory: pytest.TempPathFactory) -> list[tuple[str, str, Any, Any]]:
    """(the shape's name, its content digest, its records before, its records now)."""
    data = RECORD.read_bytes()
    assert hashlib.sha256(data).hexdigest() == RECORD_SHA256
    cases = json.loads(data)["cases"]
    root = tmp_path_factory.mktemp("shapes")
    return [
        (c["name"], digest(c["nodes"]), c["before"], _now(root / str(k), c["nodes"]))
        for k, c in enumerate(cases)
    ]


def test_the_record_holds_every_shape_as_it_is_written_today(
    judged: list[tuple[str, str, Any, Any]],
) -> None:
    assert [name for name, _, _, _ in judged] == [name for name, _, _ in SHAPES]
    assert [content for _, content, _, _ in judged] == [digest(graph) for _, graph, _ in SHAPES]


def test_every_refusal_the_check_made_before_the_readings_it_still_makes(
    judged: list[tuple[str, str, Any, Any]],
) -> None:
    failing = [o for _, _, before, _ in judged for o in before if o["outcome"] == "fail"]
    assert len(failing) == FAILURES_BEFORE
    for _, _, before, now in judged:
        kept = {
            (o["node"], o["message"], json.dumps(o["value"])) for o in now if o["outcome"] == "fail"
        }
        for o in before:
            if o["outcome"] == "fail":
                assert (o["node"], o["message"], json.dumps(o["value"])) in kept


def test_no_clean_shape_fails_and_every_shape_built_to_hold_an_error_does(
    judged: list[tuple[str, str, Any, Any]],
) -> None:
    named = errors()
    assert len(named) >= 6
    for name, content, before, now in judged:
        assert not any(o["outcome"] == "fail" for o in before), name
        refused = sorted({o["node"] for o in now if o["outcome"] == "fail"})
        if content in named:
            assert refused == named[content], name
        else:
            assert refused == [], name


def test_the_shapes_reach_both_readings_and_their_unchecked_cases() -> None:
    units = [g for _, g, _ in SHAPES if any("torque_peak" in n["quantities"] for n in g)]
    carriers = [g for _, g, _ in SHAPES if any("supported_mass" in n["quantities"] for n in g)]
    assert len(units) >= 5 and len(carriers) >= 5
