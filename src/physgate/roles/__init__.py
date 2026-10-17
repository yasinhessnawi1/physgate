"""The register of domain roles (ARCH-050/ARCH-051): one module, one role, named here.

Mirrors ``physgate.flags``'s own register discipline: a role exists here or it
does not exist, and ``ROLES`` is the one place that answers "which domain roles
can this loop dispatch today." A run is held to it at its start
(:func:`require_registered`): decomposition before its one model call, and the run,
its resume and the loop before anything is dispatched. Curated content and a
reviewer's rubric existing for a role do not make it ready: the mechanical role, for
one, owes a person's sign-off on its sizing, which nothing builds yet. A role is
added here when everything its dispatch needs is in place.
"""

from __future__ import annotations

from collections.abc import Iterable

from physgate.orchestrator.exceptions import RoleNotRegisteredError
from physgate.roles.control import CONTROL
from physgate.roles.firmware import FIRMWARE
from physgate.roles.role import Role

#: The roles the harness ships registered: those whose dispatch has everything it needs.
SHIPPED: tuple[Role, ...] = (CONTROL, FIRMWARE)
#: Every domain role registered so far, keyed by name.
ROLES: dict[str, Role] = {role.name: role for role in SHIPPED}


def require_registered(roles: Iterable[str]) -> None:
    """Refuse a run that names a role the register does not hold.

    Raises:
        RoleNotRegisteredError: one or more of ``roles`` is not in :data:`ROLES`; every
            such role is named.
    """
    unknown = sorted(set(roles) - set(ROLES))
    if unknown:
        msg = "the run names a role the role register does not hold, so it cannot dispatch it"
        raise RoleNotRegisteredError(
            msg, roles=",".join(unknown), registered=",".join(sorted(ROLES))
        )


__all__ = ["CONTROL", "FIRMWARE", "ROLES", "SHIPPED", "Role", "require_registered"]
