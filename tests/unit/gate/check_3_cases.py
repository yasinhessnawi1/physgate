"""Seeded random mounts for holding the equilibrium check to what it refused before.

Shared by the test that compares the check with its record from before the fix and by the
script that made that record, so both judge exactly the same graphs. Each mount has 1 to 4
supports (pins, or one fixed), 0 to 5 loads by mass, by force or both, placed or not, and
reactions solved by statics, perturbed or missing, with supports' own masses and a stray
reaction beside them now and then. About three in ten declare no position at all, so the
structures judged by forces alone are reached, failing and passing.
"""

from __future__ import annotations

import random
from typing import Any

SEED = 20261018
COUNT = 800
G = 9.80665


def node(
    nid: str,
    domain: str,
    q: dict[str, tuple[float, str]],
    constrains: list[str],
    kind: str = "component",
) -> dict[str, Any]:
    """A whole node payload."""
    return {
        "id": nid,
        "kind": kind,
        "domain": domain,
        "owner_role": domain,
        "quantities": {
            k: {"value": v, "unit": u, "source": "datasheet", "written_by": domain}
            for k, (v, u) in q.items()
        },
        "requirements": [],
        "constrains": constrains,
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-18T12:00:00Z",
    }


def _sig(x: float) -> float:
    return float(f"{x:.3g}")


def _loads(
    rng: random.Random, i: int, m: str, placing: bool
) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    out, loads = [], []
    for j in range(rng.randint(0, 5)):
        q: dict[str, tuple[float, str]] = {}
        x = round(rng.uniform(-0.2, 0.2), 3)
        mass, force = _sig(rng.uniform(0.01, 2)), _sig(rng.uniform(0.1, 20))
        kind = rng.choices(["mass", "force", "both"], [0.6, 0.2, 0.2])[0]
        if kind in ("mass", "both"):
            q["mass"] = (mass, "kg")
        if kind in ("force", "both"):
            q["load_force"] = (force, "N")
        placed = placing and rng.random() < 0.85
        if placed:
            q["mount_position"] = (x, "m")
        loads.append((mass * G if kind != "force" else force, x if placed else 0.0))
        out.append(node(f"electrical.load_{i}_{j}", "electrical", q, [m]))
    return out, loads


def random_mount(rng: random.Random, i: int) -> list[dict[str, Any]]:
    """One mount and its members, drawn from ``rng``."""
    m = f"mechanical.plate_{i}"
    own = {"mass": (_sig(rng.uniform(0.05, 2)), "kg")} if rng.random() < 0.3 else {}
    out = [node(m, "mechanical", own, [], kind=rng.choice(["module", "component"]))]
    placing = rng.random() >= 0.3
    members, loads = _loads(rng, i, m, placing)
    out += members
    n_sup = rng.randint(1, 4)
    xs = sorted(round(rng.uniform(-0.25, 0.25), 3) for _ in range(n_sup))
    fixed = placing and n_sup == 1 and rng.random() < 0.6
    total = sum(w for w, _ in loads)
    moment = 0.0
    if n_sup == 1:
        reactions = [total]
        moment = sum(w * (x - xs[0]) for w, x in loads)
    elif n_sup == 2 and xs[0] != xs[1]:
        at_b = sum(w * (x - xs[0]) for w, x in loads) / (xs[1] - xs[0])
        reactions = [total - at_b, at_b]
    else:
        reactions = [total / n_sup] * n_sup
    mode = rng.choices(["solved", "perturbed", "missing"], [0.45, 0.45, 0.1])[0]
    for k in range(n_sup):
        r = reactions[k]
        if mode == "perturbed" and rng.random() < 0.7:
            r = r * rng.uniform(0.3, 1.7) + rng.uniform(-1, 1)
        q: dict[str, tuple[float, str]] = {}
        if placing and rng.random() < 0.9:
            q["support_position"] = (xs[k], "m")
        if not (mode == "missing" and k == 0):
            q["reaction_force"] = (_sig(r) if r else 0.0, "N")
        if fixed:
            q["reaction_moment"] = (_sig(moment) if moment else 0.0, "N*m")
        if rng.random() < 0.3:
            q["mass"] = (_sig(rng.uniform(0.01, 0.1)), "kg")
        out.append(node(f"mechanical.support_{i}_{k}", "mechanical", q, [m]))
    if rng.random() < 0.1:
        stray = {"reaction_force": (_sig(rng.uniform(0, 5)), "N")}
        out.append(node(f"mechanical.stray_{i}", "mechanical", stray, []))
    return out


def random_mounts() -> list[tuple[str, list[dict[str, Any]]]]:
    """Every seeded random mount, by case id."""
    rng = random.Random(SEED)
    return [(f"random:{i:03d}", random_mount(rng, i)) for i in range(COUNT)]
