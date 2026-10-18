"""Check 3 must not pass a structure whose balance it never read.

Two shapes of a broken balance pass today, both written by hand here:

- a structure whose supports declare their reactions and whose loads declare their
  masses, with no positions: no mount is formed, so the check evaluates nothing and
  the runner records a pass, although the vertical forces alone do not balance;
- a load that declares a ``load_force`` beside its ``mass``: the force is never read,
  so a balance that ignores it passes.

The positive control beside each keeps the fix from refusing a correct structure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gate_fixtures import graph, node

from physgate.gate import check_equilibrium
from physgate.gate.bounds_table import load_bounds
from physgate.gate.context import CheckContext
from physgate.gate.graph import GraphView
from physgate.gate.result import CheckRun

BODY = "mechanical.body"


def body(kg: float) -> dict[str, Any]:
    return node(BODY, domain="mechanical", kind="module", quantities={"mass": (kg, "kg")})


def wheel(side: str, force: float, x: float | None = None) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {"reaction_force": (force, "N"), "mass": (0.02, "kg")}
    if x is not None:
        q["support_position"] = (x, "m")
    return node(f"mechanical.wheel_{side}", domain="mechanical", quantities=q, constrains=[BODY])


def part(
    name: str, kg: float, x: float | None = None, extra_n: float | None = None
) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {"mass": (kg, "kg")}
    if x is not None:
        q["mount_position"] = (x, "m")
    if extra_n is not None:
        q["load_force"] = (extra_n, "N")
    return node(f"electrical.{name}", quantities=q, constrains=[BODY])


def run(tmp_path: Path, *payloads: dict[str, Any]) -> CheckRun:
    graph(tmp_path / "g", *payloads)
    view = GraphView.read(tmp_path / "g", base_revision=0)
    ctx = CheckContext(view=view, scope="system", bounds=load_bounds(), solver=None)
    return check_equilibrium.run(ctx)


# 0.30 kg carried: 2.94 N, shared by two wheels.
UNPLACED = (part("cell_pack", 0.15), part("frame", 0.10), part("board", 0.05))


def test_a_structure_without_positions_whose_reactions_do_not_carry_its_loads_is_refused(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 2.40), *UNPLACED)
    assert [o.outcome for o in ran.observations if o.node == BODY] == ["fail"]


def test_a_structure_without_positions_whose_reactions_carry_its_loads_is_not_refused(
    tmp_path: Path,
) -> None:
    ran = run(tmp_path, body(0.34), wheel("left", 1.47), wheel("right", 1.47), *UNPLACED)
    assert all(o.outcome != "fail" for o in ran.observations)


PLACED = (part("frame", 0.10, x=0.0), part("board", 0.05, x=0.0))


def test_a_load_force_declared_beside_a_mass_is_never_ignored(tmp_path: Path) -> None:
    # Balanced on the weights alone (0.30 kg, 2.94 N); the pack's extra 3 N is unread today.
    ran = run(
        tmp_path,
        body(0.34),
        wheel("left", 1.47, x=-0.05),
        wheel("right", 1.47, x=0.05),
        part("cell_pack", 0.15, x=0.0, extra_n=3.0),
        *PLACED,
    )
    assert any(o.node == BODY and o.outcome in ("fail", "unchecked") for o in ran.observations)


def test_a_placed_structure_that_balances_its_weights_still_passes(tmp_path: Path) -> None:
    ran = run(
        tmp_path,
        body(0.34),
        wheel("left", 1.47, x=-0.05),
        wheel("right", 1.47, x=0.05),
        part("cell_pack", 0.15, x=0.0),
        *PLACED,
    )
    assert ran.observations == () and ran.evaluated == 1
