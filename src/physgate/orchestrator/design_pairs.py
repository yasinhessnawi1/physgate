"""Which module builds what another designs, read from the plan's specifications before any runs.

A plan in which one module implements what another designs has the designer write its design on a
node of its own and both specifications name it (the decomposition prompt asks for exactly that).
The pair is read from that: a node the designer's specification names under the designer's own
name, which is no interface node and no component of the plan, and which another module's
specification names too. That other module is the builder: it is not dispatched until the designer
has merged (ARCH-051's run order leaves it to the record to say so). The prompt tells the plan to
name the node so; a plan that names it otherwise is still read: the designer's own name is its
module's name in any case, with hyphens as underscores, and, where no other module could be meant,
that name with a hyphen-separated suffix left off (``balance`` for ``balance-control``) or its
role.

A node is named by its first two parts, so a specification that writes a quantity's path under it
(``control.law.gain``) names the node (``control.law``). A name inside a file path is no node, and
neither is a file's own name (``control.md``, ``firmware.c``): one whose last part is in
:data:`FILE_EXTENSIONS`. A last part that could name a quantity (``control.step``, a step
response; ``control.m``, a mass) is read as a node, whatever file type is spelt the same. Nor is
a node a specification names only as what a node of its own constrains (``"constrains":
["firmware.main_loop"]`` over one line or several, a YAML ``constrains:`` list, ``constrains X and
Y``, ``constrains the node X``, "constrained by X", a ``constrains`` edge to it): a constrained
node must follow every change of the node constraining it (ARCH-082), so the module writing that
edge designs for the node it names and implements nothing of it.

The pairs are fixed from the plan and recorded before the first dispatch. Only a designer that the
run dispatches before its builder makes a pair, as the prompt asks the plan to order them: the run
order is the harness's (ARCH-051), so a builder is never moved ahead of the module that opens the
domain work, and no two modules can wait on each other. A plan that puts a domain module's builder
before its designer is found here too (:func:`misordered_pairs`), so the decomposition refuses it
once, for the planner to reorder; this reading is of text, so a plan refused for its order a
second time is accepted, the suspected misorder recorded beside the pairs and no hold made. Two
modules that each name a node of the other's own are no misorder: no order could satisfy a
refusal of them. The later builds what the earlier designs, as the plan orders them, and the
earlier one's naming of the later one's node holds nothing; it is written on the pairs line beside
its pair (:func:`plan_mutual_namings`), so a reader sees it.
Nothing here reads the register, a store or a model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.plan import PartsPlan, Plan
from physgate.state.schema import NODE_ID_MAX_LENGTH, NODE_ID_PATTERN, NodeIdKey

#: A node id's form inside prose: parts joined by dots, not inside a path or a longer word, read
#: in any case and with a hyphen in its first part, as a module's name has (both are folded to the
#: id's own form). A sentence's closing full stop is not taken as a part: a part is at least one
#: character.
_NAMED = re.compile(
    r"(?<![A-Za-z0-9_./\\-])[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_]+)+(?![A-Za-z0-9_/\\-])"
)
#: The last parts that make a name a file's, never a node's: file types a specification of these
#: roles names (``firmware.c``, ``firmware.h``, a linker script, a map, an image). A word a design
#: node may end in (``step``, ``ts``, ``mat``, ``m``, ...) is left out, whatever file type is spelt
#: the same: such a file named inside a path is no node already. A node whose last part is one of
#: these loses its hold, which errs toward running the module, not toward ending the run.
FILE_EXTENSIONS: frozenset[str] = frozenset(
    {"py", "md", "cpp", "hpp", "ino", "json", "toml", "yaml", "yml", "txt", "csv", "ini"}
    | {"c", "h", "cc", "s", "hex", "elf", "ld", "map"}
)
#: A name as a ``constrains`` clause writes it: with or without backticks or quotes.
_QUOTED_NAME = r"[`\"']?[A-Za-z][A-Za-z0-9_.-]*[`\"']?"
#: What a node's ``constrains`` edges name, as a specification writes them: the field as JSON
#: (``"constrains": [...]``) or YAML (``constrains:`` and a list), or in prose (``constrains
#: firmware.main_loop``, ``constrains X and Y``, ``constrains the node X``, a ``constrains`` edge
#: to it, ``X is constrained by``-style ``constrained by Y``, ``constrains`` is ``[...]``). The
#: head ends where the edge's names begin; :func:`_edge_spans` reads them from there.
_CONSTRAINED = re.compile(
    r"\b(?:constrains|constrained\s+by)\b[`\"']?\s*(?::|\bis\b|\bedges?\s+to\b|\bto\b)?\s*"
    r"[`\"']?\s*(?:\bthe\s+)?(?:\bnodes?\s+)?",
    re.IGNORECASE,
)
#: A JSON or YAML flow list, to its closing bracket, over as many lines as it takes.
_FLOW_LIST = re.compile(r"\[[^\]]*\]")
#: A YAML block list: every ``- name`` line that follows.
_BLOCK_LIST = re.compile(rf"(?:-\s*{_QUOTED_NAME}\s*)+")
#: One name, or several in a sentence: ``X``, ``X, Y`` and ``X and Y``.
_NAME_LIST = re.compile(rf"{_QUOTED_NAME}(?:\s*(?:,\s*and\b|,|\band\b)\s*{_QUOTED_NAME})*")


def _edge_spans(spec: str) -> list[tuple[int, int]]:
    """The stretches of ``spec`` that name what a node's ``constrains`` edges name."""
    spans: list[tuple[int, int]] = []
    for head in _CONSTRAINED.finditer(spec):
        for shape in (_FLOW_LIST, _BLOCK_LIST, _NAME_LIST):
            found = shape.match(spec, head.end())
            if found is not None:
                spans.append(found.span())
                break
    return spans


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

    A name is read in the id's own form: lowercase, with a hyphen in its first part as an
    underscore. A file's own name (its last part a file extension) is no node; nor is a name
    that is, or lies under, one of ``excluded``, which is left out whole. A name where the
    specification writes what a node's ``constrains`` edges name is not read there: the module
    constrains that node, it does not implement it. Named anywhere else as well, it is read.
    """
    edges = _edge_spans(spec)
    found: dict[str, None] = {}
    for match in _NAMED.finditer(spec):
        if any(start <= match.start() < end for start, end in edges):
            continue
        first, *rest = match.group(0).lower().split(".")
        parts = [first.replace("-", "_"), *rest]
        if parts[-1] in FILE_EXTENSIONS:
            continue
        name, head = ".".join(parts), ".".join(parts[:2])
        if len(head) > NODE_ID_MAX_LENGTH or not NODE_ID_PATTERN.fullmatch(head):
            continue
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

    The module's name, with hyphens as underscores. Then, where no module is named so and no
    other module could be meant by it: the name with one or more hyphen-separated parts left off
    its end (``balance`` for ``balance-control``), and the module's role. A part two modules
    could be meant by, as a shortened name or a role, names neither.
    """
    owners = {module.name.replace("-", "_"): module.name for module in plan.modules}
    meant: dict[str, set[str]] = {}
    for module in plan.modules:
        parts = module.name.split("-")
        for key in {"_".join(parts[:end]) for end in range(1, len(parts))} | {module.role}:
            meant.setdefault(key, set()).add(module.name)
    for key, names in meant.items():
        if len(names) == 1 and key not in owners:
            owners[key] = next(iter(names))
    return owners


def _named_and_own(
    plan: Plan, modules: Sequence[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """What each of ``modules``' specifications names, and which of those nodes are its own."""
    excluded = _excluded(plan)
    owners = _owners(plan)
    spec_of = {module.name: module.spec for module in plan.modules}
    named = {name: named_nodes(spec_of[name], excluded) for name in modules}
    own = {
        name: [n for n in named[name] if owners.get(n.split(".")[0]) == name] for name in modules
    }
    return named, own


def plan_design_pairs(
    plan: Plan, subtask_of: Mapping[str, str], order: Sequence[str]
) -> tuple[DesignPair, ...]:
    """Every design pair of ``plan``, by builder in run order, then designer in run order.

    ``subtask_of`` maps each module to its subtask; ``order`` is the plan's modules in the order
    the run dispatches them. A designer pairs only with a builder dispatched after it.
    """
    named, own = _named_and_own(plan, order)
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


def plan_mutual_namings(
    plan: Plan, subtask_of: Mapping[str, str], order: Sequence[str]
) -> tuple[DesignPair, ...]:
    """Each pair's naming the other way round: its designer names a node of its builder's own.

    Read as :func:`plan_design_pairs` reads a pair, with the two the other way round, and only
    for a pair it gives, in its order: ``designer`` is the pair's builder, whose own nodes are
    ``nodes``, and ``builder`` the pair's designer, which names them. It holds nothing, as that
    module is dispatched first; it is recorded so a reader sees it.
    """
    named, own = _named_and_own(plan, order)
    module_of = {subtask_of[name]: name for name in order}
    found: list[DesignPair] = []
    for pair in plan_design_pairs(plan, subtask_of, order):
        designer, builder = module_of[pair.designer], module_of[pair.builder]
        nodes = tuple(sorted(n for n in own[builder] if n in named[designer]))
        if nodes:
            found.append(DesignPair(designer=pair.builder, builder=pair.designer, nodes=nodes))
    return tuple(found)


def misordered_pairs(plan: Plan, order: Sequence[str]) -> list[tuple[str, str, tuple[str, ...]]]:
    """Each builder ``order`` puts before its designer: (builder, designer, nodes), by module.

    ``order`` is the modules among which the plan's order is the run's: the domain modules, in
    the plan's order. Read as :func:`plan_design_pairs` reads a pair, with the two the other way
    round, by builder and then designer in that order. Two that each name a node of the other's
    own are none: no order could satisfy a refusal of them, and the pair follows the plan's order.
    """
    named, own = _named_and_own(plan, order)
    found: list[tuple[str, str, tuple[str, ...]]] = []
    for at, builder in enumerate(order):
        for designer in order[at + 1 :]:
            nodes = tuple(sorted(n for n in own[designer] if n in named[builder]))
            mutual = any(n in named[designer] for n in own[builder])
            if nodes and not mutual:
                found.append((builder, designer, nodes))
    return found


def recorded_design_pairs_problem(
    pairs: Sequence[DesignPair],
    *,
    modules: Sequence[str],
    interfaces: Sequence[str],
    mutual: Sequence[DesignPair] = (),
    misordered: Sequence[DesignPair] = (),
) -> str | None:
    """Why a recorded set of design pairs cannot be a plan's, given the run's own lines.

    ``modules`` are the subtasks that plan the plan's modules, in run order; ``interfaces`` the
    interface nodes the decomposition's line names. Each pair is of two of them, the designer
    dispatched first, each pair once, in the order :func:`plan_design_pairs` gives, and no node
    is an interface node. Each of ``mutual`` is a recorded pair the other way round, each once,
    in the pairs' order (:func:`plan_mutual_namings`), its nodes held as a pair's are. Each of
    ``misordered`` is a suspected misorder the plan was accepted with (:func:`misordered_pairs`):
    ``builder`` is dispatched before ``designer``, each is recorded once, by builder and then
    designer in run order, on no interface node, and none is a recorded pair the other way round.
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
    return _mutual_problem(pairs, mutual, interfaces) or _misordered_problem(
        pairs, misordered, interfaces, place
    )


def _misordered_problem(
    pairs: Sequence[DesignPair],
    misordered: Sequence[DesignPair],
    interfaces: Sequence[str],
    place: Mapping[str, int],
) -> str | None:
    held = {(pair.builder, pair.designer) for pair in pairs}
    keys: list[tuple[int, int]] = []
    for one in misordered:
        if one.designer not in place or one.builder not in place:
            return "a suspected misorder names a subtask that plans no module of the plan"
        if place[one.builder] >= place[one.designer]:
            return "a suspected misorder's builder is not dispatched before its designer"
        if (one.designer, one.builder) in held:
            return "a suspected misorder is a recorded pair the other way round"
        if any(_is_excluded(node, interfaces) for node in one.nodes):
            return "a suspected misorder is on an interface node"
        if list(one.nodes) != sorted(set(one.nodes)):
            return "a suspected misorder has its nodes not each named once, in id order"
        keys.append((place[one.builder], place[one.designer]))
    if keys != sorted(set(keys)):
        return "the suspected misorders are not each recorded once, in run order"
    return None


def _mutual_problem(
    pairs: Sequence[DesignPair], mutual: Sequence[DesignPair], interfaces: Sequence[str]
) -> str | None:
    at = {(pair.builder, pair.designer): index for index, pair in enumerate(pairs)}
    places: list[int] = []
    for one in mutual:
        if (one.designer, one.builder) not in at:
            return "a naming the other way round is no recorded pair the other way round"
        if any(_is_excluded(node, interfaces) for node in one.nodes):
            return "a naming the other way round is on an interface node"
        if list(one.nodes) != sorted(set(one.nodes)):
            return "a naming the other way round has its nodes not each named once, in id order"
        places.append(at[(one.designer, one.builder)])
    if places != sorted(set(places)):
        return "the namings the other way round are not each written once, in the pairs' order"
    return None
