"""A domain's interface that contradicts what a person declared raises the part again.

ARCH-122. At the release, before its gate call, an interface a domain produced (not one sizing
holds), joined to a declared node and holding one of its names with another value, compared as
a contract's clause compares (the same dimension, then ``math.isclose`` after conversion), is
refused as the gate's block is: the part's item is raised again as a new round naming the
interface, the name and both values, and the hold continues.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from gate_fixtures import node
from parts_rig import body, decide, log_of, started
from plan_hold_rig import again, dispatched

from physgate.orchestrator.queue import QueueResolution

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]
MOTOR = "control.motor_left"
IFACE = "iface.motor_mount"


def _of(log: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [one for one in log if one["kind"] == kind]


def interface(
    value: float, unit: str, *, owner: str = "control", joined: bool = True
) -> dict[str, Any]:
    payload = node(IFACE, kind="interface", domain="control", quantities={"mass": (value, unit)})
    payload["owner_role"] = owner
    for quantity in payload["quantities"].values():
        quantity["written_by"] = owner
    payload["constrains"] = [MOTOR] if joined else []
    return payload


def _released_with(tmp_path: Path, iface: dict[str, Any]) -> tuple[str, Any]:
    the_rig = started(tmp_path / "run")
    the_rig.diff.before = [iface]
    assert again(the_rig) == "wait"
    run_dir = the_rig.run_dir
    stated = body({"mass": (0.4, "kg"), "stall_current": (2.4, "A")})
    assert isinstance(decide(run_dir, IDS[0], "have", stated), QueueResolution)
    assert isinstance(decide(run_dir, IDS[1], "find"), QueueResolution)
    assert isinstance(decide(run_dir, IDS[2], "find"), QueueResolution)
    return again(the_rig), the_rig


def test_a_joined_domain_interface_with_another_value_raises_the_part_again(
    tmp_path: Path,
) -> None:
    step, the_rig = _released_with(tmp_path, interface(0.5, "kg"))
    assert step == "wait"
    log = log_of(the_rig.run_dir)
    (raised,) = _of(log, "parts_raised_again")
    assert raised["cause"] == "interface"
    (part,) = raised["parts"]
    assert (part["item_id"], part["node"]) == (IDS[0] + "-r2", MOTOR)
    for said in (IFACE, "mass", "0.5 kg", "0.4 kg"):
        assert said in part["why"]
    assert _of(log, "parts_gate_ran") == []
    assert the_rig.gate.releases == []
    assert _of(log, "parts_released") == []
    assert dispatched(the_rig.run_dir) == []


@pytest.mark.parametrize(
    "iface",
    [
        interface(400, "g"),
        interface(0.5, "kg", joined=False),
        interface(0.5, "kg", owner="sizing"),
    ],
    ids=["the-same-value-in-grams", "not-joined", "sizing-s-own-interface"],
)
def test_an_interface_that_agrees_is_not_joined_or_is_sizing_s_raises_nothing(
    tmp_path: Path, iface: dict[str, Any]
) -> None:
    step, the_rig = _released_with(tmp_path, iface)
    assert step == "done"
    log = log_of(the_rig.run_dir)
    assert _of(log, "parts_raised_again") == []
    assert len(_of(log, "parts_released")) == 1
