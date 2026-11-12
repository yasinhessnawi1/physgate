"""Mechanical (ARCH-050): structure, mechanisms, loads; registered for planning only.

A plan may give it a module and the design reviewer judges that plan, but no session of this
role is dispatched until the role is built: its sizing owes a person's sign-off, which nothing
builds yet. A run whose plan names it halts at its first dispatch, with the cause named.
"""

from __future__ import annotations

from physgate.roles.role import Role

MECHANICAL = Role(
    name="mechanical", domain="mechanical", architecture="ARCH-050", planning_only=True
)
