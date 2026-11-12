"""Electrical (ARCH-050): power, the bus, protection; registered for planning only.

A plan may give it a module and the design reviewer judges that plan, but no session of this
role is dispatched until the role is built. A run whose plan names it halts at its first
dispatch, with the cause named.
"""

from __future__ import annotations

from physgate.roles.role import Role

ELECTRICAL = Role(
    name="electrical", domain="electrical", architecture="ARCH-050", planning_only=True
)
