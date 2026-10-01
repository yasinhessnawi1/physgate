"""The register of domain roles (ARCH-050/ARCH-051): one module, one role, named here.

Mirrors ``physgate.flags``'s own register discipline: a role exists here or it
does not exist, and ``ROLES`` is the one place that answers "which domain roles
can this loop dispatch today." A later reviewer pair for these two roles, and
the mechanical and electrical rows, are added the same way.
"""

from __future__ import annotations

from physgate.roles.control import CONTROL
from physgate.roles.firmware import FIRMWARE
from physgate.roles.role import Role

#: Every domain role registered so far, keyed by name.
ROLES: dict[str, Role] = {role.name: role for role in (CONTROL, FIRMWARE)}

__all__ = ["CONTROL", "FIRMWARE", "ROLES", "Role"]
