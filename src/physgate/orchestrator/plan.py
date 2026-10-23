"""The plan's form: what the run's one model call answers, as code holds it.

The models live apart from the call that asks for them so that the run-event log can
type what it records of a plan with the very models the plan was held to: a list read
back from the log is parsed through them, with every bound they carry, and never through
a looser shape of its own. Nothing here calls a model or reads the register.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from physgate.orchestrator.common import NonEmptyStr
from physgate.state.schema import NODE_ID_MAX_LENGTH, Node


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


#: The longest specification the decomposition may issue a module, in characters.
SPEC_MAX_CHARS = 32_768

#: A module's name in the plan.
_ModuleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]


class PlannedModule(_Frozen):
    """One module of the design, as the decomposition proposes it."""

    name: _ModuleName
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

    module: _ModuleName
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


class InterfaceConsumers(_Frozen):
    """The modules that read one interface node's quantities, by their names in the plan.

    The interface by its node's id. The module that produces the node is not among them.
    """

    interface: Annotated[str, StringConstraints(min_length=1, max_length=NODE_ID_MAX_LENGTH)]
    consumers: Annotated[tuple[_ModuleName, ...], Field(min_length=1)]


class IntegratedPlan(Plan):
    """The plan of a run with the integration role (ARCH-051).

    Integration has no module in the plan: the harness writes its specification from the
    recorded plan. What it checks is fixed here, before any module runs: the consumers of
    every interface node, from which the module pairs whose contract is tested are read,
    and the system requirements allocated to it.
    """

    interface_consumers: tuple[InterfaceConsumers, ...]
    system_requirements: tuple[SystemRequirement, ...]


def plan_sha256(plan: Plan) -> str:
    """The plan's digest: sha256 of its canonical JSON, every field of its own form in it.

    Taken from the plan object, whose dump is of its own form: a holder typed with the
    base form, as the call's outcome is, dumps an integrated plan without its two lists.
    """
    canonical = json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
