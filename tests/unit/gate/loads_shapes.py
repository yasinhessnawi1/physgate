"""The hand-made torque units and carriers the second old-versus-new record holds.

Each shape is a whole graph, stated in general terms (a unit held by its mount, a carrier
named by what it carries), with its clean form and the kinds of error a writer makes: a
reaction moment left at an old torque, a supported mass in the wrong unit or left stale, a
value matching no split. ``errors()`` names the graphs that hold an error, by content digest,
with the node the readings refuse.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

M = "mechanical"


def q(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": "hand-made", "written_by": M}


def node(
    node_id: str,
    quantities: dict[str, tuple[float, str]],
    *,
    kind: str = "component",
    constrains: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": M,
        "owner_role": M,
        "quantities": {k: q(v, u) for k, (v, u) in quantities.items()},
        "requirements": [],
        "constrains": list(constrains or []),
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-19T00:00:00Z",
        "no_change_justified": {},
    }


def unit(
    torque: float, reaction: float, ratio: float | None = None, unit: str = "N*m"
) -> list[dict[str, Any]]:
    quantities: dict[str, tuple[float, str]] = {
        "torque_peak": (torque, unit),
        "reaction_moment": (reaction, unit),
    }
    if ratio is not None:
        quantities["gear_ratio"] = (ratio, "dimensionless")
    return [node(f"{M}.gearboxes", quantities)]


def drive(
    robot_g: float, drivetrain_g: float, wheel_g: float, own_g: float = 19.8
) -> list[dict[str, Any]]:
    return [
        node(
            f"{M}.robot",
            {"mass": (robot_g, "g")},
            kind="module",
            constrains=[f"{M}.drivetrain", f"{M}.wheel_left", f"{M}.wheel_right"],
        ),
        node(
            f"{M}.drivetrain",
            {"supported_mass": (drivetrain_g, "g")},
            kind="module",
            constrains=[f"{M}.robot"],
        ),
        node(
            f"{M}.wheel_left",
            {"mass": (own_g, "g"), "supported_mass": (wheel_g, "g")},
            constrains=[f"{M}.drivetrain"],
        ),
        node(
            f"{M}.wheel_right",
            {"mass": (own_g, "g"), "supported_mass": (wheel_g, "g")},
            constrains=[f"{M}.drivetrain"],
        ),
    ]


def bracket(pack_g: float, supported_g: float, own_g: float | None) -> list[dict[str, Any]]:
    carrier: dict[str, tuple[float, str]] = {"supported_mass": (supported_g, "g")}
    if own_g is not None:
        carrier["mass"] = (own_g, "g")
    return [
        node("electrical.pack", {"mass": (pack_g, "g")}, constrains=[f"{M}.bracket"])
        | {"domain": "electrical", "owner_role": "electrical"},
        node(f"{M}.bracket", carrier),
    ]


#: (name, graph, the nodes the readings refuse, or None for a clean shape)
SHAPES: list[tuple[str, list[dict[str, Any]], tuple[str, ...] | None]] = [
    ("unit: reaction equals torque", unit(1.1, 1.1), None),
    ("unit: in the sheet's unit", unit(110, 110, unit="kgf*cm"), None),
    ("unit: reaction of the opposite sign", unit(1.1, -1.1), None),
    ("unit: with a ratio, readings disagree", unit(1.1, 1.1, ratio=148.3), None),
    ("unit: reaction left at an old torque", unit(0.38, 1.1), (f"{M}.gearboxes",)),
    (
        "unit: reaction in the sheet's unit left stale",
        unit(38.7, 110, unit="kgf*cm"),
        (f"{M}.gearboxes",),
    ),
    (
        "unit: a ratio cannot excuse a reaction matching neither reading",
        unit(1.1, 0.5, ratio=30),
        (f"{M}.gearboxes",),
    ),
    ("drive: whole and equal halves", drive(330, 330, 165), None),
    ("drive: supported mass in kilograms for grams", drive(330, 330000, 165), (f"{M}.drivetrain",)),
    (
        "drive: supported mass stale after the robot grew",
        drive(400, 330, 200),
        (f"{M}.drivetrain",),
    ),
    (
        # Sibling carriers are refused once, on the sum of their shares, on the first of them.
        "drive: the wheels' shares stale after the robot grew",
        drive(400, 400, 165),
        (f"{M}.wheel_left",),
    ),
    ("bracket: the whole", bracket(200, 200, None), None),
    ("bracket: the whole with its own mass, readings disagree", bracket(200, 250, 50), None),
    ("bracket: a tenfold supported mass", bracket(200, 2000, 50), (f"{M}.bracket",)),
]


def digest(payloads: list[dict[str, Any]]) -> str:
    """The sha256 of a graph's nodes, sorted by id and written canonically."""
    canonical = json.dumps(
        sorted(payloads, key=lambda p: str(p["id"])), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def errors() -> dict[str, list[str]]:
    """The content digest of every graph that holds an error, with the nodes refused."""
    return {digest(graph): sorted(on) for _, graph, on in SHAPES if on is not None}
