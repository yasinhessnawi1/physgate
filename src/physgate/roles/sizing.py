"""Sizing (ARCH-051): the one writer of the quantities that tie domains together.

Motor torque and current, battery capacity and discharge, mass and inertia: each is
a quantity more than one domain depends on, written on a node of domain ``cross``
that sizing owns and no other role may write. Sizing writes no domain node either.
Interface nodes are not sizing's: they are fixed when the work is decomposed.
"""

from __future__ import annotations

from physgate.roles.role import CrossCuttingRole

SIZING = CrossCuttingRole(name="sizing", architecture="ARCH-051", owns="cross_nodes")
