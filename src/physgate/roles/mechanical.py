"""Mechanical (ARCH-050): structure, mechanisms, loads; registered for planning only.

A plan may give it a module and the design reviewer judges that plan, but no session of this
role is dispatched until the role is built with its tools. Its sizing owes a person's sign-off
(ARCH-130), which the rule table in ``orchestrator/sign_off.py`` names and code raises once a
module of it merges. A run whose plan names it halts at its first dispatch, with the cause named.
"""

from __future__ import annotations

from physgate.roles.role import Role

MECHANICAL = Role(
    name="mechanical", domain="mechanical", architecture="ARCH-050", planning_only=True
)
