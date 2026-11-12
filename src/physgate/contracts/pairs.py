"""The module pairs whose interface contract is tested, read from the plan before any module runs.

A pair is ordered: the module that produces an interface, and one module that reads it. It holds
every interface between those two modules in that direction, so two modules coupled both ways
are two pairs. An interface's producer is the one module of the role that owns its node, and its
consumers are the modules the plan names for it. Both sides are read by role, since a node
carries the role that owns it and no module: a plan with the integration role therefore gives
each role that produces or reads an interface one module (:func:`pairing_problems`).

The set is fixed from the plan and recorded before the first dispatch. The run-event log holds a
recorded set to the plan's own lines (:func:`recorded_pairs_problem`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.plan import IntegratedPlan, ModuleName
from physgate.state.schema import NODE_ID_MAX_LENGTH

_InterfaceId = Annotated[str, StringConstraints(min_length=1, max_length=NODE_ID_MAX_LENGTH)]

#: What the harness appends to a plan module's name to mint the id of the subtask that plans it.
_MINTED = "-[0-9a-f]{6}"


class ContractError(Exception):
    """A contract that cannot be formed, or checked, as the plan defines it."""

    def __init__(self, message: str, **context: str) -> None:
        """Store ``context`` alongside the message."""
        super().__init__(message)
        self.context: dict[str, str] = dict(context)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Side(_Frozen):
    """One module of a pair: its name in the plan, the subtask that planned it, and its role.

    For the module of the role that owns the cross nodes, the subtask is its opening pass.
    """

    module: ModuleName
    subtask_id: NonEmptyStr
    role: NonEmptyStr


class ContractPair(_Frozen):
    """A module that produces interfaces, one module that reads them, and those interfaces."""

    producer: Side
    consumer: Side
    interfaces: Annotated[tuple[_InterfaceId, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _two_roles_and_each_interface_once(self) -> ContractPair:
        if self.producer.role == self.consumer.role:
            msg = "a pair's two modules are of two roles"
            raise ValueError(msg)
        if list(self.interfaces) != sorted(set(self.interfaces)):
            msg = "a pair names each of its interfaces once, in order"
            raise ValueError(msg)
        return self


def pairing_problems(plan: IntegratedPlan) -> list[str]:
    """Each interface whose producing role, or a consumer's role, has more than one module.

    A consumer the plan does not have, and a role with no module, are other rules' to name.
    """
    modules_of: dict[str, list[str]] = {}
    for module in plan.modules:
        modules_of.setdefault(module.role, []).append(module.name)
    role_of = {module.name: module.role for module in plan.modules}
    readers = {entry.interface: entry.consumers for entry in plan.interface_consumers}
    found: list[str] = []
    for node in plan.interface_nodes:
        sides = {node.owner_role: "produced by"}
        for reader in readers.get(node.id, ()):
            if reader in role_of:
                sides.setdefault(role_of[reader], "read by a module of")
        for role, how in sides.items():
            names = modules_of.get(role, [])
            if len(names) > 1:
                found.append(
                    f"interface node {node.id!r} is {how} the {role!r} role, which has "
                    f"{len(names)} modules in the plan ({', '.join(names)}): a contract's two "
                    "sides are read by role, so a role that produces or reads an interface has "
                    "one module"
                )
    return found


def plan_pairs(plan: IntegratedPlan, subtask_of: Mapping[str, str]) -> tuple[ContractPair, ...]:
    """Every pair of ``plan``, in order; ``subtask_of`` maps each module to its subtask.

    Raises:
        ContractError: a role that produces or reads an interface has other than one module, a
            consumer is no module of the plan or of another role than the producer, or a module
            has no subtask.
    """
    problems = pairing_problems(plan)
    role_of = {module.name: module.role for module in plan.modules}
    producer_of: dict[str, str] = {}
    for node in plan.interface_nodes:
        owners = [name for name, role in role_of.items() if role == node.owner_role]
        if len(owners) != 1:
            problems.append(f"interface node {node.id!r} has no one module that produces it")
        else:
            producer_of[node.id] = owners[0]
    if problems:
        msg = "the plan's contract pairs cannot be formed: " + "; ".join(problems)
        raise ContractError(msg)
    consumers = {entry.interface: entry.consumers for entry in plan.interface_consumers}
    try:
        sides = {
            name: Side(module=name, subtask_id=subtask_of[name], role=role)
            for name, role in role_of.items()
        }
        return group(producer_of, consumers, sides)
    except (KeyError, ValidationError) as exc:
        msg = f"the plan's contract pairs cannot be formed: {exc}"
        raise ContractError(msg) from None


def group(
    producer_of: Mapping[str, str],
    consumers: Mapping[str, Sequence[str]],
    sides: Mapping[str, Side],
) -> tuple[ContractPair, ...]:
    """The pairs these producers and consumers make: one per (producer, consumer), in order.

    Raises:
        KeyError: an interface with no producer, or a module with no side.
        ValidationError: a producer's own role among its consumers.
    """
    between: dict[tuple[str, str], list[str]] = {}
    for interface, readers in consumers.items():
        for reader in readers:
            between.setdefault((producer_of[interface], reader), []).append(interface)
    return tuple(
        ContractPair(producer=sides[p], consumer=sides[c], interfaces=tuple(sorted(found)))
        for (p, c), found in sorted(between.items())
    )


def recorded_pairs_problem(
    pairs: Sequence[ContractPair],
    *,
    interfaces: Sequence[str],
    consumers: Mapping[str, Sequence[str]],
    planned: Mapping[str, str],
    completion: str | None,
) -> str | None:
    """Why a recorded set of pairs is not the one the plan's recorded lines give; or ``None``.

    The log records each interface's consumers (the decomposition's line) and each subtask's
    role (its planning line), not which role owns an interface node, nor which module a subtask
    plans. Those two are read from the pairs, and held to the planning lines: a side's subtask is
    planned (``planned`` maps each to its role), is not the completion owner's, is of the side's
    role, and is the one minted for its module, which no closing pass is. The pairs are then
    rebuilt from the consumers and must equal the record.
    """
    sides: dict[str, Side] = {}
    producer_of: dict[str, str] = {}
    for pair in pairs:
        for side in (pair.producer, pair.consumer):
            if sides.setdefault(side.module, side) != side:
                return f"module {side.module!r} is named with two subtasks or roles"
        for interface in pair.interfaces:
            if producer_of.setdefault(interface, pair.producer.module) != pair.producer.module:
                return f"interface {interface!r} is given two producers"
    for side in sides.values():
        role = planned.get(side.subtask_id)
        if role is None or side.subtask_id == completion:
            return f"module {side.module!r} names {side.subtask_id!r}, no planned module's subtask"
        if role != side.role:
            return (
                f"module {side.module!r} is named with the role {side.role!r}, and its subtask "
                f"is planned for {role!r}"
            )
        if re.fullmatch(re.escape(side.module) + _MINTED, side.subtask_id) is None:
            return f"subtask {side.subtask_id!r} is not the one planned for module {side.module!r}"
    if set(producer_of) != set(interfaces):
        return "the pairs do not cover the plan's interface nodes exactly"
    try:
        rebuilt = group(producer_of, consumers, sides)
    except KeyError as exc:
        return f"the plan names consumer {exc} of an interface, which is in no pair"
    except ValidationError:
        return "a consumer the plan names is of its interface's producing role"
    if rebuilt != tuple(pairs):
        return "the pairs are not the ones the plan gives"
    return None
