"""The plan's form: what the run's one model call answers, as code holds it.

The models live apart from the call that asks for them so that the run-event log can
type what it records of a plan with the very models the plan was held to: a list read
back from the log is parsed through them, with every bound they carry, and never through
a looser shape of its own, and is held to the same rules across the two lists
(:func:`list_problems`). Nothing here calls a model or reads the register.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Collection, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.orchestrator.common import NonEmptyStr
from physgate.state.schema import NODE_ID_MAX_LENGTH, Node, NodeIdKey
from physgate.state.vocabulary import shadowing_quantity_names


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


#: Where the harness puts the integration subtask in a run with the integration role. The
#: harness writes that subtask's specification from the recorded plan, so no planned module
#: may sit in this directory, above it or below it; and the run-event log takes the completion
#: owner's subtask in no other directory.
INTEGRATION_MODULE_DIR = "modules/integration"

#: The longest specification the decomposition may issue a module, in characters.
SPEC_MAX_CHARS = 32_768

#: A module's name in the plan.
ModuleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]


class PlannedModule(_Frozen):
    """One module of the design, as the decomposition proposes it."""

    name: ModuleName
    role: NonEmptyStr
    module_dir: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}$")]
    #: Long enough for a specification that states its plant, sensors, timing and numbered
    #: criteria in full (a reviewable one runs past 20,000 characters), and still bounded.
    spec: Annotated[str, StringConstraints(min_length=1, max_length=SPEC_MAX_CHARS)]


class Plan(_Frozen):
    """The decomposition's answer: modules with their specifications, and interfaces."""

    modules: Annotated[tuple[PlannedModule, ...], Field(min_length=1, max_length=50)]
    interface_nodes: Annotated[tuple[Node, ...], Field(min_length=1)]


# The docstrings of the three models below are sent with the schema, as their
# descriptions: they are what the decomposition is told each entry means.


class Contribution(_Frozen):
    """A module criterion that contributes to a system requirement.

    The module by its name in the plan, and the number of one acceptance criterion
    that module's specification numbers under a heading that names acceptance criteria.
    """

    module: ModuleName
    criterion: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,6}$")]


#: The longest system requirement, in characters: a criterion's number, or a requirement
#: in the brief's own words where the brief numbers none.
REQUIREMENT_MAX_CHARS = 500


class SystemRequirement(_Frozen):
    """A requirement of the brief that only the assembled system can show.

    Given as the brief's acceptance-criterion number where the brief numbers its
    criteria under a heading that names acceptance criteria, and in the brief's own words
    otherwise; with every module criterion that contributes to it.
    """

    requirement: Annotated[str, StringConstraints(min_length=1, max_length=REQUIREMENT_MAX_CHARS)]
    contributing: Annotated[tuple[Contribution, ...], Field(min_length=1)]


#: The most system requirements a plan may allocate to integration, as many as it may plan
#: modules. Each is written whole into integration's specification, which is held to
#: :data:`SPEC_MAX_CHARS` as a module's is.
MAX_SYSTEM_REQUIREMENTS = 50

#: The system requirements, bounded in number; the run-event log reads them back with the bound.
SystemRequirements = Annotated[
    tuple[SystemRequirement, ...], Field(max_length=MAX_SYSTEM_REQUIREMENTS)
]


class InterfaceConsumers(_Frozen):
    """The modules that read one interface node's quantities, by their names in the plan.

    The interface by its node's id. The module that produces the node is not among them.
    """

    interface: Annotated[str, StringConstraints(min_length=1, max_length=NODE_ID_MAX_LENGTH)]
    consumers: Annotated[tuple[ModuleName, ...], Field(min_length=1)]


class IntegratedPlan(Plan):
    """The plan of a run with the integration role (ARCH-051).

    Integration has no module in the plan: the harness writes its specification from the
    recorded plan. What it checks is fixed here, before any module runs: the consumers of
    every interface node, from which the module pairs whose contract is tested are read,
    and the system requirements allocated to it.
    """

    interface_consumers: tuple[InterfaceConsumers, ...]
    system_requirements: SystemRequirements


#: The most components a plan may list: a person decides each one before anything is
#: dispatched, and each decision is its own item.
MAX_COMPONENTS = 20
#: The most quantity names a component may list in either of its two lists.
MAX_COMPONENT_NAMES = 12
#: The longest label a component is shown to a person under, in characters.
LABEL_MAX_CHARS = 80

#: A quantity's name, as the gate's catalogue spells its own: what a part on hand states.
QuantityName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
#: The domains a component may be of. The cross domain holds quantities, never parts.
ComponentDomain = Literal["mechanical", "electrical", "control", "firmware"]
ComponentNames = Annotated[tuple[QuantityName, ...], Field(max_length=MAX_COMPONENT_NAMES)]


class Component(_Frozen):
    """One physical part of the design that a person could already own or could make.

    The node by an id of its own, which no interface node has; the domain the part is of;
    the role of the module it belongs to; a label a person would know the part by; and the
    quantities a part on hand must state, each by its catalogue name: in ``own`` those only
    its own domain reads, in ``shared`` those more than one domain depends on. Names only:
    the values are the person's to state, never the plan's.
    """

    node: NodeIdKey
    domain: ComponentDomain
    role: NonEmptyStr
    label: Annotated[str, StringConstraints(min_length=1, max_length=LABEL_MAX_CHARS)]
    own: ComponentNames
    shared: ComponentNames


class PartsPlan(Plan):
    """The plan of a run that asks which parts a person has or can make (ARCH-122).

    It lists the design's components, none where the design has no such part. The list is
    fixed here, before anything is dispatched: a person decides each entry, and what they
    state of a part they have is written onto its node before any role reads it.
    """

    components: Annotated[tuple[Component, ...], Field(max_length=MAX_COMPONENTS)]


class IntegratedPartsPlan(IntegratedPlan, PartsPlan):
    """The plan of a run with the integration role that also asks about parts: both forms."""


def duplicate_id_problems(components: Sequence[Component]) -> list[str]:
    """What is wrong where two components of a list are given one id."""
    ids = [entry.node for entry in components]
    return ["two components share a node id"] if len(set(ids)) != len(ids) else []


def component_id_problems(entry: Component, interfaces: Collection[str]) -> list[str]:
    """What is wrong with a component's id, given the plan's interface nodes' ids."""
    if entry.node in interfaces:
        return [f"component {entry.node!r} has the id of an interface node"]
    return []


def component_name_problems(entry: Component) -> list[str]:
    """What is wrong with the quantity names a component lists, in its two lists."""
    said = f"component {entry.node!r}"
    found: list[str] = []
    for name, count in Counter((*entry.own, *entry.shared)).items():
        if name in entry.own and name in entry.shared:
            found.append(f"{said} names {name!r} as its own and as shared")
        elif count > 1:
            found.append(f"{said} names {name!r} more than once")
    # The rule an interface node's names are held to: a name that shadows a relation's
    # quantity would put a person's value where no relation reads it.
    for name, relation in shadowing_quantity_names(tuple((*entry.own, *entry.shared))):
        found.append(
            f"{said} names {name!r}, which shadows {relation!r}, a quantity a relation "
            "reads; it is named by the catalogue's name"
        )
    return found


def component_list_problems(
    interfaces: Sequence[str], components: Sequence[Component]
) -> list[str]:
    """What is wrong with a component list, given only the interface nodes' ids.

    The plan's rules that need nothing but the list and ``interfaces``: no two components
    share an id, none has an interface node's, and each one's names are given once, in one
    list, by the catalogue's spelling. The plan check holds a plan to them, beside the rules
    that need its modules and the run's roles; the run-event log holds a recorded line to
    them, with the line's own interface nodes, on its way back in.
    """
    found = duplicate_id_problems(components)
    known = set(interfaces)
    for entry in components:
        found += component_id_problems(entry, known)
        found += component_name_problems(entry)
    return found


class CriterionWords(_Frozen):
    """An acceptance criterion the brief numbers, in the brief's own words.

    Recorded for each system requirement the plan gives by the brief's criterion number, so what
    integration and its reviewer read says what the number stands for. No part of the plan or its
    schema: the harness takes the words from the brief the decomposition was given, and the record
    holds that brief by its digest alone, so the words cannot be held to it on replay.
    """

    criterion: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,6}$")]
    words: Annotated[str, StringConstraints(min_length=1, max_length=SPEC_MAX_CHARS)]


def words_problems(
    requirements: Sequence[SystemRequirement], words: Sequence[CriterionWords]
) -> list[str]:
    """What is wrong with the brief's words against the requirement list they are recorded for.

    Each entry names a requirement of the list, once, in the list's order; a list of none is
    never recorded (the field is left out instead).
    """
    if not words:
        return ["the brief's words are recorded only when there are some"]
    listed = [r.requirement for r in requirements]
    named = [w.criterion for w in words]
    if any(n not in listed for n in named):
        return ["the brief's words name a criterion that is no system requirement of the plan"]
    places = [listed.index(n) for n in named]
    if places != sorted(set(places)):
        return ["the brief's words name each requirement once, in the plan's order"]
    return []


def list_problems(
    interfaces: Sequence[str],
    consumers: Sequence[InterfaceConsumers],
    requirements: Sequence[SystemRequirement],
) -> list[str]:
    """What is wrong across integration's two lists, given only the interface nodes' ids.

    The plan's rules that need nothing but the lists and ``interfaces``: every consumers
    entry is for one of them, each of them has exactly one entry, an entry names each
    consumer once, and each requirement is listed once. The plan check holds a plan to
    them, beside the rules that need its modules and its brief; the run-event log holds a
    recorded line to them, with the line's own interface nodes, on its way back in.
    """
    found: list[str] = []
    known = set(interfaces)
    for entry in consumers:
        if entry.interface not in known:
            found.append(
                f"interface_consumers names {entry.interface!r}, which is no interface node "
                "of the plan"
            )
            continue
        for consumer, count in Counter(entry.consumers).items():
            if count > 1:
                found.append(
                    f"interface node {entry.interface!r} names {consumer!r} as a consumer "
                    "more than once"
                )
    entries = Counter(entry.interface for entry in consumers)
    for node_id in dict.fromkeys(interfaces):
        if entries[node_id] == 0:
            found.append(f"interface node {node_id!r} has no consumers entry")
        elif entries[node_id] > 1:
            found.append(f"interface node {node_id!r} has more than one consumers entry")
    for requirement, count in Counter(r.requirement for r in requirements).items():
        if count > 1:
            found.append(f"system requirement {requirement!r} is listed more than once")
    return found


def plan_bytes(plan: Plan) -> bytes:
    """The plan's canonical JSON, every field of its own form in it: what its digest is taken over.

    Taken from the plan object, whose dump is of its own form: a holder typed with the
    base form, as the call's outcome is, dumps an integrated plan without its two lists.
    """
    return json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def plan_sha256(plan: Plan) -> str:
    """The plan's digest: sha256 of :func:`plan_bytes`."""
    return hashlib.sha256(plan_bytes(plan)).hexdigest()
