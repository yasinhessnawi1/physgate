"""What a person decided of each part, for the roles that read it after the release (ARCH-122).

Two readers need the decisions once a run that asks is released: sizing treats a declared value as
fixed, and sourcing checks only the parts a person does not have or make. Both read them here:

- :func:`parts_choices` gives each component's choice and the values it declared, keyed by the
  component's own node id (the bill of materials' line for an electrical part). It reads only the
  replayed release line, which replay has already held to the plan, the decisions, the landed
  writes and the release gate, so a part raised again appears with its final choice alone. It
  never reads more than a plan may name. A run that does not ask names nothing; a run that asks
  and is not released is refused, since a reader then would take every owned part as one to find.
- :func:`choice_of` says what a node was decided as: a node the map does not name is to find.
- :func:`bom_lines` names the bill of materials' lines from the nodes alone, and
  :func:`bom_lines_to_check` the ones a check of the bill of materials will consider: those a
  person left to find. No such check is built yet; these give it what to look at.
- :func:`sourcing_lines` stands where sourcing will. A part a person has is skipped as owned, one
  a person makes as custom, and a part to find is left unchecked: the stub validates nothing, so
  no line it records is ever validated.

Nothing here reads a file, writes, or imports the evaluation or the reviewers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from physgate.orchestrator.events import ReleasedPart, StatedValue
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.plan import MAX_COMPONENTS

if TYPE_CHECKING:
    from physgate.orchestrator.replay import RunState
    from physgate.state.schema import Node

PartChoice = Literal["have", "make", "find"]
SourcingStatus = Literal["skipped", "unchecked"]
SkipReason = Literal["owned", "custom"]

#: Why sourcing skips a part: one a person has is owned, one a person makes is custom.
SKIP_REASONS: Mapping[PartChoice, SkipReason] = MappingProxyType(
    {"have": "owned", "make": "custom"}
)


class PartsChoiceError(OrchestratorError):
    """The parts' choices cannot be read from this run as it stands."""


@dataclass(frozen=True)
class Choice:
    """What a person decided of one component: the choice, and each value it declared by name."""

    choice: PartChoice
    declared: Mapping[str, StatedValue]


@dataclass(frozen=True)
class SourcingLine:
    """One bill-of-materials line as sourcing records it: skipped with its reason, or unchecked."""

    node: str
    status: SourcingStatus
    reason: SkipReason | None


def _choice(part: ReleasedPart) -> Choice:
    declared = {} if part.parts is None else dict(part.parts.declared)
    return Choice(choice=part.choice, declared=MappingProxyType(declared))


def parts_choices(state: RunState) -> Mapping[str, Choice]:
    """Each component's choice and declared values, from the run's release line alone.

    Keyed by the component's own node id. Empty for a run that does not ask.

    Raises:
        PartsChoiceError: the run asks and its parts are not released yet, or the release names
            more components than a plan may hold.
    """
    if not state.asks_parts:
        return MappingProxyType({})
    released = state.parts_released
    if released is None:
        msg = "the run asks which parts a person has, and its parts are not released yet"
        raise PartsChoiceError(msg)
    if len(released.components) > MAX_COMPONENTS:
        msg = f"the release names more components than the {MAX_COMPONENTS} a plan may hold"
        raise PartsChoiceError(msg, components=str(len(released.components)))
    return MappingProxyType({part.node: _choice(part) for part in released.components})


def choice_of(choices: Mapping[str, Choice], node: str) -> PartChoice:
    """What ``node`` was decided as: a node the map does not name is to find."""
    held = choices.get(node)
    return "find" if held is None else held.choice


def sourcing_lines(
    bom_lines: Iterable[str], choices: Mapping[str, Choice]
) -> tuple[SourcingLine, ...]:
    """Each bill-of-materials line as the stub sourcing records it, in the order given.

    A part a person has or makes is skipped, as owned or custom; any other is left unchecked.
    Nothing is validated.
    """
    lines: list[SourcingLine] = []
    for node in bom_lines:
        reason = SKIP_REASONS.get(choice_of(choices, node))
        status: SourcingStatus = "unchecked" if reason is None else "skipped"
        lines.append(SourcingLine(node=node, status=status, reason=reason))
    return tuple(lines)


def bom_lines(nodes: Iterable[Node]) -> tuple[str, ...]:
    """The bill of materials' lines: the id of every electrical component, in the order given.

    Read from the nodes alone, with no mark on a node: a sizing node, a mechanical component and an
    interface are no line.
    """
    return tuple(
        node.id for node in nodes if node.kind == "component" and node.domain == "electrical"
    )


def bom_lines_to_check(nodes: Iterable[Node], choices: Mapping[str, Choice]) -> tuple[str, ...]:
    """The lines a check of the bill of materials will consider: those a person left to find.

    A part a person has or makes is not checked. A line the choices do not name is to find, so a
    run that does not ask gives every line. No such check is built yet.
    """
    return tuple(line for line in bom_lines(nodes) if choice_of(choices, line) == "find")
