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
Whoever enforces a duty finds its owner through :func:`owner_of`, by the duty and never
by a role's name, and that lookup counts the owners again rather than trust the
register's earlier check.
It also refuses every other way of handing a domain role what a cross-cutting role
holds: a domain role of the ``cross`` domain or name, and any row under a cross-cutting
role's name that is not that role as defined here.
"""

from __future__ import annotations

from collections.abc import Iterable

from physgate.knowledge import loader
from physgate.orchestrator.exceptions import (
    DutyUnownedError,
    RoleNotRegisteredError,
    RoleRegisterError,
)
from physgate.roles.control import CONTROL
from physgate.roles.firmware import FIRMWARE
from physgate.roles.integration import INTEGRATION
from physgate.roles.role import CrossCuttingDuty, CrossCuttingRole, RegisteredRole, Role
from physgate.roles.sizing import SIZING

#: The cross-cutting roles as defined here, by name: their names belong to these rows.
_DEFINED: dict[str, CrossCuttingRole] = {role.name: role for role in (SIZING, INTEGRATION)}
#: Names no role may take. ``design`` is the plan's reviewer's key among a run's reviewer
#: pins, so a role of that name would share its pin with the reviewer of the plan.
_RESERVED_NAMES = frozenset({"design"})


def register_of(roles: Iterable[RegisteredRole]) -> dict[str, RegisteredRole]:
    """``roles`` keyed by name, refusing a register no run could be held to.

    Raises:
        RoleRegisterError: a role takes a reserved name; a domain role is of the
            ``cross`` domain or named ``cross``; a row under a cross-cutting role's name
            is not that role as defined here; two roles share a name, of either kind;
            or two cross-cutting roles own one duty: two writers of the cross
            quantities, or two roles able to declare a module complete, would each be
            one too many.
    """
    register: dict[str, RegisteredRole] = {}
    owners: dict[CrossCuttingDuty, str] = {}
    for role in roles:
        if role.name in _RESERVED_NAMES:
            msg = "this name pins the plan's reviewer, so no role may take it"
            raise RoleRegisterError(msg, role=role.name)
        if isinstance(role, Role) and loader.CROSS in (role.domain, role.name):
            msg = "a domain role is never of the cross domain or named after it"
            raise RoleRegisterError(msg, role=role.name, domain=role.domain)
        defined = _DEFINED.get(role.name)
        if defined is not None and role != defined:
            msg = "this name is a cross-cutting role's, and this row is not that role"
            raise RoleRegisterError(msg, role=role.name)
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
SHIPPED: tuple[RegisteredRole, ...] = (CONTROL, FIRMWARE, INTEGRATION)
#: Every role registered so far, keyed by name.
ROLES: dict[str, RegisteredRole] = register_of(SHIPPED)


def owner_of(duty: CrossCuttingDuty) -> str:
    """The name of the one registered role that owns ``duty``, read from :data:`ROLES` now.

    Whoever enforces a duty asks here, so the register stays the one place that says
    which role holds it, and no rule names that role itself. The owners are counted
    again on every call: :func:`register_of` refuses a second owner when the register
    is built, but :data:`ROLES` is a mapping that anything in the process can change
    afterwards, as a stand-in role is added to it, and a rule that trusted the earlier
    check would hand the duty to whichever owner it met first.

    Raises:
        DutyUnownedError: no registered role owns ``duty``.
        RoleRegisterError: more than one registered role owns it.
    """
    owners = sorted(
        role.name
        for role in ROLES.values()
        if isinstance(role, CrossCuttingRole) and role.owns == duty
    )
    if not owners:
        msg = "no registered role owns this duty"
        raise DutyUnownedError(msg, owns=duty, registered=",".join(sorted(ROLES)))
    if len(owners) > 1:
        msg = "more than one registered role owns this duty, which has one owner"
        raise RoleRegisterError(msg, owns=duty, owners=",".join(owners))
    return owners[0]


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
    "owner_of",
    "register_of",
    "require_registered",
]
