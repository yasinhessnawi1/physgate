"""The role register (ARCH-050/ARCH-051): one module, one role, named here.

Mirrors ``physgate.flags``'s own register discipline: a role exists here or it
does not exist, and ``ROLES`` is the one place that answers "which roles can this
loop dispatch today." A run is held to it at its start
(:func:`require_registered`): decomposition before its one model call, and the run,
its resume and the loop before anything is dispatched. Curated content and a
reviewer's rubric existing for a role do not make it ready: the mechanical role, for
one, owes a person's sign-off on its sizing, which nothing builds yet. A role is
added here when everything its dispatch needs is in place, and never before its
always-loaded reading and its reviewer's promoted rubric exist.

The register holds both kinds of role: domain roles (ARCH-050) and the cross-cutting
roles (ARCH-051), sizing and integration, which have no domain. Each cross-cutting
duty has one owner at most; the register refuses a second (:func:`register_of`).
"""

from __future__ import annotations

from collections.abc import Iterable

from physgate.orchestrator.exceptions import RoleNotRegisteredError, RoleRegisterError
from physgate.roles.control import CONTROL
from physgate.roles.firmware import FIRMWARE
from physgate.roles.integration import INTEGRATION
from physgate.roles.role import CrossCuttingDuty, CrossCuttingRole, RegisteredRole, Role
from physgate.roles.sizing import SIZING


def register_of(roles: Iterable[RegisteredRole]) -> dict[str, RegisteredRole]:
    """``roles`` keyed by name, refusing a register no run could be held to.

    Raises:
        RoleRegisterError: two roles share a name, or two cross-cutting roles own one
            duty: two writers of the cross quantities, or two roles able to declare a
            module complete, would each be one too many.
    """
    register: dict[str, RegisteredRole] = {}
    owners: dict[CrossCuttingDuty, str] = {}
    for role in roles:
        if role.name in register:
            msg = "the role register already holds a role of this name"
            raise RoleRegisterError(msg, role=role.name)
        if isinstance(role, CrossCuttingRole):
            if role.owns in owners:
                msg = "a cross-cutting duty has one owner, and this one already has it"
                raise RoleRegisterError(
                    msg, role=role.name, owns=role.owns, owner=owners[role.owns]
                )
            owners[role.owns] = role.name
        register[role.name] = role
    return register


#: The roles the harness ships registered: those whose dispatch has everything it needs.
SHIPPED: tuple[RegisteredRole, ...] = (CONTROL, FIRMWARE)
#: Every role registered so far, keyed by name.
ROLES: dict[str, RegisteredRole] = register_of(SHIPPED)


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


__all__ = [
    "CONTROL",
    "FIRMWARE",
    "INTEGRATION",
    "ROLES",
    "SHIPPED",
    "SIZING",
    "CrossCuttingDuty",
    "CrossCuttingRole",
    "RegisteredRole",
    "Role",
    "register_of",
    "require_registered",
]
