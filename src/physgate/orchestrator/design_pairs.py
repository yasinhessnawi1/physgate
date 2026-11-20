"""Which module builds what another designs, read from the plan's specifications before any runs.

A plan in which one module implements what another designs has the designer write its design on a
node of its own and both specifications name it (the decomposition prompt asks for exactly that).
The pair is read from that: a node the designer's specification names under the designer's own
name (its module's name, or its role where no other module has that role), which is no interface
node and no component of the plan, and which another module's specification names too. That other
module is the builder: it is not dispatched until the designer has merged (ARCH-051's run order
leaves it to the record to say so).

A node is named by its first two parts, so a specification that writes a quantity's path under it
(``control.law.gain``) names the node (``control.law``). A name inside a file path is no node.

The pairs are fixed from the plan and recorded before the first dispatch. Only a designer that the
run dispatches before its builder makes a pair, as the prompt asks the plan to order them: the run
order is the harness's (ARCH-051), so a builder is never moved ahead of the module that opens the
domain work, and no two modules can wait on each other. Nothing here reads the register, a store
or a model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.plan import PartsPlan, Plan
from physgate.state.schema import NodeIdKey

#: A node id's form inside prose: lowercase parts joined by dots, not inside a path or a longer
#: word. A sentence's closing full stop is not taken as a part: a part is at least one character.
_NAMED = re.compile(r"(?<![A-Za-z0-9_./\\-])[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+(?![A-Za-z0-9_/\\-])")


class DesignPair(BaseModel):
    """A module that builds what another designs: the two subtasks, and the design's nodes.

    ``designer`` and ``builder`` are the subtasks that plan the two modules; ``nodes`` the
    designer's nodes the builder's specification names, by their first two parts, in id order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    designer: NonEmptyStr
    builder: NonEmptyStr
    nodes: Annotated[tuple[NodeIdKey, ...], Field(min_length=1)]


def named_nodes(spec: str, excluded: Sequence[str] = ()) -> list[str]:
    """Every node a specification names, by its first two parts, in the order first named.

    A name that is, or lies under, one of ``excluded`` is left out whole.
    """
    found: dict[str, None] = {}
    for match in _NAMED.finditer(spec):
        name = match.group(0)
        head = ".".join(name.split(".")[:2])
        if not _is_excluded(name, excluded) and not _is_excluded(head, excluded):
            found.setdefault(head, None)
    return list(found)


def _excluded(plan: Plan) -> tuple[str, ...]:
    """The ids no design is held on: the interface nodes and the components, as the plan gives."""
    ids = [node.id for node in plan.interface_nodes]
    if isinstance(plan, PartsPlan):
        ids += [entry.node for entry in plan.components]
    return tuple(ids)


def _is_excluded(node: str, excluded: Sequence[str]) -> bool:
    return any(node == other or node.startswith(f"{other}.") for other in excluded)


def _owners(plan: Plan) -> dict[str, str]:
    """Each first part a node may begin with to be a module's own, to the module it names.

    The module's name; and its role, where no other module has it and no module is named so.
    """
    owners = {module.name.replace("-", "_"): module.name for module in plan.modules}
    roles = [module.role for module in plan.modules]
    for module in plan.modules:
        if roles.count(module.role) == 1:
            owners.setdefault(module.role, module.name)
    return owners


def plan_design_pairs(
    plan: Plan, subtask_of: Mapping[str, str], order: Sequence[str]
) -> tuple[DesignPair, ...]:
    """Every design pair of ``plan``, by builder in run order, then designer in run order.

    ``subtask_of`` maps each module to its subtask; ``order`` is the plan's modules in the order
    the run dispatches them. A designer pairs only with a builder dispatched after it.
    """
    excluded = _excluded(plan)
    owners = _owners(plan)
    spec_of = {module.name: module.spec for module in plan.modules}
    named = {name: named_nodes(spec_of[name], excluded) for name in order}
    own = {name: [n for n in named[name] if owners.get(n.split(".")[0]) == name] for name in order}
    pairs: list[DesignPair] = []
    for at, builder in enumerate(order):
        for designer in order[:at]:
            nodes = sorted(n for n in own[designer] if n in named[builder])
            if nodes:
                pairs.append(
                    DesignPair(
                        designer=subtask_of[designer],
                        builder=subtask_of[builder],
                        nodes=tuple(nodes),
                    )
                )
    return tuple(pairs)


def recorded_design_pairs_problem(
    pairs: Sequence[DesignPair],
    *,
    modules: Sequence[str],
    interfaces: Sequence[str],
) -> str | None:
    """Why a recorded set of design pairs cannot be a plan's, given the run's own lines.

    ``modules`` are the subtasks that plan the plan's modules, in run order; ``interfaces`` the
    interface nodes the decomposition's line names. Each pair is of two of them, the designer
    dispatched first, each pair once, in the order :func:`plan_design_pairs` gives, and no node
    is an interface node.
    """
    place = {subtask: index for index, subtask in enumerate(modules)}
    keys: list[tuple[int, int]] = []
    for pair in pairs:
        if pair.designer not in place or pair.builder not in place:
            return "a pair names a subtask that plans no module of the plan"
        if place[pair.designer] >= place[pair.builder]:
            return "a pair's designer is not dispatched before its builder"
        if any(_is_excluded(node, interfaces) for node in pair.nodes):
            return "a pair holds a builder on an interface node"
        if list(pair.nodes) != sorted(set(pair.nodes)):
            return "a pair's nodes are not each named once, in id order"
        keys.append((place[pair.builder], place[pair.designer]))
    if keys != sorted(set(keys)):
        return "the pairs are not each recorded once, by builder and then designer in run order"
    return None
