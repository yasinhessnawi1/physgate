"""The shape of a graph node, validated at every boundary.

The architecture's node shape is the authority here, and it is stricter than the
guard the store comparison measured: that guard checked only that a unit string
was present, while the architecture's node carries a value, a unit, a source and
the role that wrote it. All four are mandatory, extras are refused, and the value
must be a number. Verified against the frozen workload before this was written:
across its five seeds there are exactly two quantity shapes, the full four on
every legal quantity and those minus the unit on every deliberately faulty one,
so the stricter model accepts every legal write and refuses every faulty one
exactly as the looser guard did.

Validation is strict rather than coercing, which was a deliberate choice and is
measured in the tests: in the coercing mode the string ``"2.4"``, the boolean
``True``, ``NaN`` and infinity are all accepted as the value of a quantity. Every
one of those would reach the physics gate as a number it could do arithmetic on,
and two of them are not numbers at all. An integer is still accepted, because
JSON has no way to say that ``2`` is a float.

A quantity a person declared (a part they own, a constraint on one they make) carries a
record of the decision that made it, :class:`Declared`, and the one source reserved for it.
The schema holds the two together and refuses a source that only reads like the reserved
one. Who may write such a quantity is not the schema's to say: it holds the shape, and the
store and the layers before it hold the writer.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import SkipJsonSchema

from physgate.state.exceptions import MalformedNodeIdError, MissingUnitError

#: A node id is a dotted identifier. The graph stores one file per node and
#: names that file after the id, so anything carrying a separator, a parent
#: reference or an absolute path would write outside the graph directory. Ids
#: come from agents, so this is untrusted input and the pattern is a whitelist
#: rather than a list of things to reject.
NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
NODE_ID_MAX_LENGTH = 128

NodeKind = Literal["component", "module", "requirement", "interface"]

#: The architecture enumerates the domain in exactly the notation it uses for
#: the kind, and the physics gate routes on it, so it is closed the same way.
DomainKind = Literal["mechanical", "electrical", "control", "firmware", "cross"]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]


def _says_something(reason: str) -> str:
    if not reason.strip():
        msg = "a justification gives its reason; blank text is not one"
        raise ValueError(msg)
    return reason


#: Why a node was left as it is although a node constraining it changed: its
#: owner's explicit claim, which the propagation check records and never verifies.
Justification = Annotated[str, AfterValidator(_says_something)]
#: A node id used as a key: the same whitelist, and the same bound, as a node's own id.
NodeIdKey = Annotated[
    str, StringConstraints(pattern=NODE_ID_PATTERN.pattern, max_length=NODE_ID_MAX_LENGTH)
]


#: How a quantity is read off a simulation record: a closed set, each defined on the
#: record's own samples. A frequency record carries a loop's magnitude (a ratio) and phase
#: (in rad); a time record names the trace the value is read from.
FREQUENCY_EXTRACTORS = (
    "phase_margin",
    "gain_crossover_frequency",
    "gain_margin_upper",
    "gain_margin_lower",
    "stability_margin",
    "sensitivity_peak",
    "complementary_sensitivity_peak",
    "delay_margin",
)
TIME_EXTRACTORS = ("max", "min", "max_abs", "final")
Extractor = Literal[
    "phase_margin",
    "gain_crossover_frequency",
    "gain_margin_upper",
    "gain_margin_lower",
    "stability_margin",
    "sensitivity_peak",
    "complementary_sensitivity_peak",
    "delay_margin",
    "max",
    "min",
    "max_abs",
    "final",
]
#: A record's id and a trace's name, as the record format spells them.
SeriesName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class SeriesRef(BaseModel):
    """The simulation record a quantity was read from, and how it was read.

    Names only, never numbers: a record is evidence beside the run, not design state, and
    the graph holds only where to find it. Whether the quantity agrees with the record is
    checked before the attempt reaches the gate.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    record: SeriesName
    extract: Extractor
    #: The trace a time extractor reads; a frequency extractor reads the loop's own traces.
    trace: SeriesName | None = None

    @model_validator(mode="after")
    def _the_trace_fits_the_extractor(self) -> SeriesRef:
        if self.extract in TIME_EXTRACTORS and self.trace is None:
            msg = f"the extractor {self.extract!r} reads a named trace, and none is named"
            raise ValueError(msg)
        if self.extract in FREQUENCY_EXTRACTORS and self.trace is not None:
            msg = f"the extractor {self.extract!r} reads the loop's own traces; name none"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_an_absent_trace(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.trace is None:
            data.pop("trace", None)
        return data


#: The source of a quantity a person declared, and of no other quantity.
DECLARED_SOURCE = "declared by the person"

#: What a source may not fold to unless it is the reserved one itself: the reserved text and
#: the short forms a writer would reach for.
_IMITATIONS = frozenset({"declared", "userdeclared", "persondeclared", "declaredbytheperson"})
#: Characters that separate words without being letters: dashes, connectors such as the
#: underscore, and formatting marks that print as nothing.
_SEPARATORS = frozenset({"Pd", "Pc", "Cf"})


def _folded(source: str) -> str:
    """``source`` as a reader takes it in: compatibility forms, case and separators aside."""
    text = unicodedata.normalize("NFKC", source).casefold()
    return "".join(
        char for char in text if not (char.isspace() or unicodedata.category(char) in _SEPARATORS)
    )


def imitates_declared(source: str) -> bool:
    """True if ``source`` reads like the reserved source without being it."""
    return source != DECLARED_SOURCE and _folded(source) in _IMITATIONS


def _is_a_name(operator: str) -> str:
    if not operator.strip() or not operator.isprintable():
        msg = "the operator is a printable name, not blank"
        raise ValueError(msg)
    return operator


class Declared(BaseModel):
    """The decision behind a quantity a person declared: a record, not a claim.

    It names the approval-queue item the person decided, the digest of the decision's line
    as recorded, and who decided, so that the quantity can be rebuilt from that line and a
    quantity no line explains can be told apart.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: A queue item's id is plain identifiers joined by hyphens, never a path.
    item_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,300}$")]
    decision_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    operator: Annotated[
        str, StringConstraints(min_length=1, max_length=64), AfterValidator(_is_a_name)
    ]


class Quantity(BaseModel):
    """One physical quantity: a number, its unit, where it came from, who wrote it.

    A bare number is not a quantity. Neither is a number with an empty unit. A quantity read
    off a simulation record names that record in ``series``; one that names none is dumped
    exactly as before the field existed, so no node, journal line or digest changes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)

    value: float | int
    unit: NonEmptyStr
    source: NonEmptyStr
    written_by: NonEmptyStr
    series: SeriesRef | None = None
    #: The decision that made a quantity a person declared; absent on every other quantity
    #: and then left out of every dump, as ``series`` is. It is kept out of the JSON schema,
    #: and this class's docstring is left as it was, because the decomposition's answer is
    #: held to that schema: what every run sends stays byte for byte the same, and a plan
    #: is offered no way to declare for a person.
    declared: SkipJsonSchema[Declared | None] = None

    @model_validator(mode="after")
    def _declared_and_its_source_go_together(self) -> Quantity:
        # The imitation first: with a record beside it, it is still an imitation.
        if imitates_declared(self.source):
            msg = (
                f"the source {self.source!r} imitates {DECLARED_SOURCE!r}, which is reserved "
                "for a quantity a person declared through a recorded decision"
            )
            raise ValueError(msg)
        if self.declared is None:
            if self.source == DECLARED_SOURCE:
                msg = f"a quantity of the source {DECLARED_SOURCE!r} names no decision"
                raise ValueError(msg)
            return self
        if self.source != DECLARED_SOURCE:
            msg = (
                "a quantity names the decision that declared it only under the source "
                f"{DECLARED_SOURCE!r}"
            )
            raise ValueError(msg)
        if self.series is not None:
            msg = "a declared quantity was stated by a person: it names no simulation record"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def _omit_what_is_absent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.series is None:
            data.pop("series", None)
        if self.declared is None:
            data.pop("declared", None)
        return data


class Node(BaseModel):
    """One node of the design-state graph."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    #: The pattern is the schema's only, for the plan's answer: the binary holds the model's
    #: interface nodes to it. A node's id is validated by :func:`validate_node_id`, which the
    #: store and the run's opening call, so a refusal keeps the reason each gives.
    id: Annotated[
        str,
        Field(
            max_length=NODE_ID_MAX_LENGTH, json_schema_extra={"pattern": NODE_ID_PATTERN.pattern}
        ),
    ]
    kind: NodeKind
    domain: DomainKind
    owner_role: NonEmptyStr
    quantities: dict[str, Quantity] = Field(default_factory=dict)
    requirements: list[str] = Field(default_factory=list)
    constrains: list[str] = Field(default_factory=list)
    model: str | None = None
    geometry_hash: NonEmptyStr
    updated: NonEmptyStr
    #: For a node other nodes constrain: which of their changes this node was
    #: deliberately left unchanged for, and why, keyed by the constraining node's
    #: id. A changed quantity must reach every node it constrains or be excused
    #: here, by that node's own owner (ARCH-082); an excuse written on the node
    #: that changed would be the changer excusing itself.
    no_change_justified: dict[NodeIdKey, Justification] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _a_declared_quantity_is_its_owner_s(self) -> Node:
        # A node is one writer's. A declared quantity under another name would give a node
        # two, and the name is what every reader of the node takes its writer from.
        for name, quantity in self.quantities.items():
            if quantity.declared is not None and quantity.written_by != self.owner_role:
                msg = (
                    f"the declared quantity {name!r} is written by the node's owner "
                    f"({self.owner_role!r}), not by {quantity.written_by!r}"
                )
                raise ValueError(msg)
        return self


def validate_node_id(node_id: object) -> str:
    """Return ``node_id`` if it is a legal identifier, else raise.

    Raises:
        MalformedNodeIdError: the id is not a string, is too long, or does not
            match the dotted-identifier pattern.
    """
    if not isinstance(node_id, str):
        msg = "node id is not a string"
        raise MalformedNodeIdError(msg, node_id=repr(node_id))
    if len(node_id) > NODE_ID_MAX_LENGTH:
        msg = "node id is too long"
        raise MalformedNodeIdError(msg, node_id=node_id[:64], length=str(len(node_id)))
    # The whole name: the pattern's ``$`` also matches before a final newline, and a
    # newline in a name would reach a file name and every log that prints it.
    if NODE_ID_PATTERN.fullmatch(node_id) is None:
        msg = "node id is not a dotted identifier"
        raise MalformedNodeIdError(msg, node_id=node_id)
    return node_id


def quantities_are_valid(payload: dict[str, Any]) -> bool:
    """True if every quantity in ``payload`` is a well-formed quantity.

    Separate from :class:`Node` because the store reports a quantity fault as a
    rejection with the frozen reason string, not as a raise.
    """
    quantities = payload.get("quantities") or {}
    if not isinstance(quantities, dict):
        return False
    for entry in quantities.values():
        try:
            Quantity.model_validate(entry)
        except Exception:  # noqa: BLE001 - any validation failure is the answer
            return False
    return True


def validate_node(payload: dict[str, Any]) -> Node:
    """Validate a whole node payload.

    Raises:
        MalformedNodeIdError: the id is not a legal identifier.
        MissingUnitError: a quantity is not a well-formed quantity.
    """
    validate_node_id(payload.get("id"))
    if not quantities_are_valid(payload):
        msg = "a quantity is missing its unit, its number, or carries an unknown field"
        raise MissingUnitError(msg, node_id=str(payload.get("id")))
    return Node.model_validate(payload)
