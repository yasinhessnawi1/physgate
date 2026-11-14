"""A dispute on a quantity a person declared is refused: no position can change it.

ARCH-040's precedence puts a person's declaration above sizing and every domain, and a declared
quantity is written only by the parts writer. So the one dispute parser, which the hook and the
change check both read with, refuses a dispute of a quantity whose head is declared, naming it,
and accepts one of a quantity of the same node that is not. A fault an earlier rule of the parser
refuses (the file's name, who may dispute) keeps its reason.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_a_dispute_is_checked_at_the_hook_and_recorded_after_the_change_check import (  # noqa: E402
    NODES,
    OTHER,
    PATH,
    PLANNED,
    attempt,
    body,
    quantity,
    sizing_registered,  # noqa: F401 - the register as a run that sizes has it
    through_hook,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import make_store, write_config  # noqa: E402

from physgate.hooks import graph  # noqa: E402
from physgate.hooks.config import SessionConfig  # noqa: E402
from physgate.orchestrator import dispute  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.dispute import DisputeError, parse  # noqa: E402
from physgate.state.schema import DECLARED_SOURCE  # noqa: E402
from physgate.state.store import Store  # noqa: E402

RECORD = {"item_id": "run-1-parts-1", "decision_sha256": "a" * 64, "operator": "yasin"}
DECLARED = {
    "value": 24,
    "unit": "V",
    "source": DECLARED_SOURCE,
    "written_by": "sizing",
    "declared": dict(RECORD),
}


def _bus(**quantities: Any) -> dict[str, Any]:  # noqa: ANN401
    (bus,) = [n for n in NODES if n["id"] == "sizing.bus"]
    return {**bus, "quantities": quantities}


#: The bus as the parts writer left it: its supply voltage declared, its peak current sizing's.
BUS = _bus(supply_voltage=DECLARED, peak_current=quantity(3, "A"))


def nodes() -> dict[str, dict[str, Any]]:
    found = {str(n["id"]): n for n in NODES}
    found["sizing.bus"] = BUS
    return found


def _store(root: Path) -> None:
    """The graph, the bus written by sizing and then declared through the parts writer's door."""
    others = [n for n in NODES if n["id"] != "sizing.bus"]
    make_store(root, _bus(peak_current=quantity(3, "A")), *others)
    store = Store(root)
    try:
        assert store.declare(BUS, ("run-1-parts-1",)).accepted
    finally:
        store.close()


def _refusal(path: str, data: bytes, role: str = "control") -> str:
    try:
        parse(path, data, role, nodes())
    except DisputeError as exc:
        return str(exc)
    return "accepted"


def test_a_dispute_of_a_declared_quantity_is_refused_naming_it() -> None:
    said = _refusal(PATH, body())
    assert said != "accepted"
    assert "supply_voltage" in said and "declared" in said


def test_a_dispute_of_the_same_nodes_quantity_that_is_not_declared_is_its_position() -> None:
    read = parse(OTHER, body(5, "A"), "control", nodes())
    assert (read.position.name, read.position.value) == ("peak_current", 5)


def test_a_role_that_may_not_dispute_keeps_its_reason_on_a_declared_quantity() -> None:
    said = _refusal(PATH, body(), role="sizing")
    assert said == dispute.disputer_problem("sizing")


def test_a_malformed_name_keeps_its_reason_on_a_declared_quantity() -> None:
    assert _refusal(PATH.replace(".json", ".txt"), body()) == dispute.NAMED


def test_a_malformed_body_on_a_declared_quantity_is_refused_as_declared() -> None:
    said = _refusal(PATH, body(value="24"))
    assert "declared" in said and said != dispute.VALUE


def _session(tmp_path: Path, role: str) -> SessionConfig:
    home = tmp_path / role
    home.mkdir(parents=True, exist_ok=True)
    config = write_config(home, role=role)[2]
    _store(Path(str(config.store_root)))
    return config


def test_the_hook_refuses_it_as_the_parser_does(tmp_path: Path) -> None:
    config = _session(tmp_path, "control")
    told = through_hook(config, "Write", body())
    assert told.startswith(graph.DISPUTE_REFUSED.format(detail=""))
    assert "supply_voltage" in told and "declared" in told
    assert through_hook(config, "Write", body(5, "A"), path=OTHER) == "allow"


def test_the_change_check_refuses_it_as_the_disputes(tmp_path: Path) -> None:
    run, commit = attempt(tmp_path, "s1", {PATH: body()})
    store = tmp_path / "store"
    _store(store)
    check = GitChangeChecker(run, store, dict(PLANNED)).check("s1", commit, "control")
    assert (check.refused_by, check.subject, check.disputes) == ("dispute", PATH, ())
    assert "declared" in str(check.reason)


@pytest.mark.parametrize("value", [24, 30])
def test_the_value_stated_does_not_matter(value: int) -> None:
    said = _refusal(PATH, body(value))
    assert "declared" in said
