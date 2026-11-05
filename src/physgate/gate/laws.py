"""The law table: closed-form laws as data, loaded once when the gate is built.

Each law is one row of ``knowledge/laws/laws.toml``, a curated file protected like the bounds
tables beside it: a textbook relation over quantities the design-state graph holds, read only
by their exact catalogue names and bound to the graph by one of three patterns (a node's own
quantities, a node and the node its ``constrains`` edge names, or a subject and the members
whose edges name it). The rows are content a person approved; this module is the one place
that reads them, and it refuses at build time any row that could not have been approved as
written. **A table that does not load stops the gate from being built.**

A row is refused, naming it, when:

- its fields are missing, empty or of the wrong shape; its literature source lacks a part,
  or is a data sheet rather than a text (a data sheet's numbers are the worked examples',
  never the law's);
- no promotion line records its approval, or, at ``block``, its move to ``block``;
- a symbol, a required name or an excusing name is not an exact catalogue name: a name the
  gate only reads through a suffix or qualifier joins no law, as it joins no relation;
- a symbol's kind carries the radian, or is an absolute temperature: each needs a rule of
  its own before a law may read it;
- its expression is not one comparison of two sums of monomials over its declared symbols
  and declared literals, within the bounds below; read by a syntax-tree walk against an
  allowlist, never evaluated;
- its two sides are not one dimension, or two bare terms are of different kinds (a torque and
  an energy share a dimension and are never the same quantity);
- its input names and comparator are those of a relation the checks already form;
- its comparator is outside its tolerance class, or a ``model`` allowance lacks its source or
  exceeds a quarter;
- it lacks a worked passing or failing example, or an example lacks a symbol;
- it is at ``block`` without a clearance meeting the bar: at least ``BLOCK_MIN_EVALUATED``
  evaluated instances on clean designs, from at least ``BLOCK_MIN_DESIGNS`` different designs,
  none of them an unexplained block. The bar was set by a person before any audit counted
  anything; changing it is a recorded change of what the gate may refuse.

Running the worked examples, and evaluating a law over a graph, are the laws check's.
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.gate.bounds_table import KNOWLEDGE_DIR
from physgate.gate.catalogue import EITHER_ANGLE, KINDS, QUANTITIES, inferred_by
from physgate.gate.exceptions import GateError
from physgate.gate.relations import RELATION_INPUTS
from physgate.gate.units import UREG
from physgate.orchestrator.protocols import TOLERANCE_COMPARATORS, LawStatus

#: The table, in the tracked knowledge tree beside the bounds tables, outside every domain
#: directory. Read at build time from the checkout the orchestrator runs from.
LAWS_PATH = KNOWLEDGE_DIR / "laws" / "laws.toml"
#: The promotion record every approval and every move to ``block`` is held to.
PROMOTIONS_PATH = KNOWLEDGE_DIR / "promotions.jsonl"

#: An expression's bounds, checked before the parser sees it, so a row cannot make the gate
#: slow: characters, then syntax-tree nodes, then the size of an exponent.
MAX_EXPRESSION_LENGTH = 256
MAX_EXPRESSION_NODES = 64
MAX_EXPONENT = 3
#: The widest relative allowance a ``model`` law may carry: an idealised relation that needs
#: more is not a law the gate judges.
MODEL_MAX_SHARE = Fraction(1, 4)
#: The block bar. A law may be moved to ``block`` only once the audit has evaluated it on at
#: least this many instances on clean designs, drawn from at least this many different
#: designs, with no block it could not explain. A design is one lineage of a base graph: the
#: practice set's clean twins are one, each evaluation run's graph is one, and the gate's own
#: hand-made fixtures are none. Set by a person before any audit data was counted.
BLOCK_MIN_EVALUATED = 10
BLOCK_MIN_DESIGNS = 2

#: The places each binding pattern has. A new pattern is code and a decision, never a row.
PLACES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {"node": ("self",), "edge": ("self", "target"), "members": ("subject", "each")}
)
#: The places an anchor may sit: where an instance of the law is formed.
ANCHOR_PLACES = frozenset({"self", "subject"})

FORMAT = 1

Place = Literal["self", "target", "subject", "each"]
Comparator = Literal["==", "<=", ">="]
_Text = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
_Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
_Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_Candidate = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
_Count = Annotated[int, Field(ge=0)]


class LawTableError(GateError):
    """A law table that does not load. The gate is not built on it."""


class ExpressionError(ValueError):
    """A law's expression that the parser refuses: a form outside its allowlist."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, allow_inf_nan=False)


class Symbol(_Frozen):
    """One symbol of a law: a catalogue name, and its place in the binding pattern."""

    name: _Text
    place: Place


class Condition(_Frozen):
    """A name whose presence a law needs (``requires``) or that excuses it (``unless``)."""

    name: _Text
    place: Place
    #: Why the law does not hold where the name is present; an ``unless`` must say.
    reason: _Text | None = None


class LiteralDeclared(_Frozen):
    """An integer the law itself carries (the 2 of a half), never a count of parts."""

    value: _Text
    reason: _Text


class Source(_Frozen):
    """Where the law is stated: a text, never a data sheet, with how it was read."""

    kind: Literal["textbook", "standard", "paper"]
    title: _Text
    edition: _Text
    section: _Text
    read: datetime.date
    reading: Literal["in full", "secondary"]


class Approved(_Frozen):
    """The person's approval: the staged candidate it promoted, and when."""

    candidate_id: _Candidate
    date: datetime.date


class Cleared(_Frozen):
    """The audit that cleared a law to block, and the person's approval of the move."""

    audit_sha256: _Sha256
    evaluated_clean: _Count
    designs: list[_Text]
    unexplained: _Count
    approved: datetime.date


class ModelAllowance(_Frozen):
    """A ``model`` law's relative allowance, as a ratio of integers, and its source."""

    share: _Text
    source: _Text


class ExampleValue(_Frozen):
    """One worked number, with its unit."""

    value: float | int
    unit: _Text


class Example(_Frozen):
    """A worked example from a cited data sheet or text, and the outcome it must give."""

    outcome: Literal["pass", "fail"]
    source: _Text
    values: dict[str, ExampleValue | list[ExampleValue]]


@dataclass(frozen=True)
class Monomial:
    """One term of a side: a rational coefficient times declared symbols to integer powers."""

    coefficient: Fraction
    #: (symbol, power) pairs, sorted by symbol, each power non-zero.
    powers: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class Expression:
    """A law's checked expression: two sums of monomials and the comparator between them."""

    left: tuple[Monomial, ...]
    comparator: Comparator
    right: tuple[Monomial, ...]
    #: Every integer the expression carries as a coefficient (exponents are not literals).
    literals: frozenset[int]

    def monomials(self) -> tuple[Monomial, ...]:
        """Both sides' monomials, left first."""
        return (*self.left, *self.right)


class Law(_Frozen):
    """One row of the law table, checked whole when it loads."""

    id: _Id
    statement: _Text
    expression: _Text
    pattern: Literal["node", "edge", "members"]
    anchor: _Text
    tolerance: Literal["rounding", "inequality", "model"]
    status: LawStatus
    overlaps: _Text
    idealisation: _Text
    literals: list[LiteralDeclared] = []
    requires: list[Condition] = []
    unless: list[Condition] = []
    symbols: dict[str, Symbol]
    source: Source
    approved: Approved
    example: list[Example]
    cleared: Cleared | None = None
    model: ModelAllowance | None = None

    @model_validator(mode="after")
    def _sound(self) -> Law:
        _check_binding(self)
        _check_names(self)
        parsed = parse_expression(self.expression, tuple(self.symbols))
        _check_literals(self, parsed)
        _check_summed_terms(self, parsed)
        _check_tolerance(self, parsed)
        _check_dimension(self, parsed)
        _check_new(self, parsed)
        _check_examples(self)
        _check_status(self)
        return self

    def parsed(self) -> Expression:
        """The checked expression."""
        return parse_expression(self.expression, tuple(self.symbols))

    def input_names(self) -> frozenset[str]:
        """Every catalogue name the law reads, requires or is excused by."""
        return frozenset(
            {s.name for s in self.symbols.values()}
            | {c.name for c in (*self.requires, *self.unless)}
        )


# --- the parser ---------------------------------------------------------------------------

_COMPARATORS: Mapping[type, Comparator] = MappingProxyType(
    {ast.Eq: "==", ast.LtE: "<=", ast.GtE: ">="}
)
_REFUSED_NODES: Mapping[type, str] = MappingProxyType(
    {
        ast.Call: "a call",
        ast.Attribute: "an attribute",
        ast.Subscript: "a subscript",
        ast.Lambda: "a lambda",
        ast.List: "a list",
        ast.Tuple: "a tuple",
        ast.Dict: "a dict",
        ast.Set: "a set",
        ast.BoolOp: "a boolean operation",
        ast.Compare: "a comparison inside a side",
        ast.IfExp: "a conditional",
        ast.NamedExpr: "an assignment",
        ast.Starred: "a starred name",
    }
)


def parse_expression(text: str, symbols: Collection[str]) -> Expression:
    """Check ``text`` against the allowlist and read it as two sums of monomials.

    The length is bounded before ``ast.parse`` sees the text, and the number of syntax-tree
    nodes while the tree is read; ``ast.parse`` builds a tree and runs nothing, and the tree is
    read by this module alone, node by node, never handed to anything that evaluates it.

    Raises:
        ExpressionError: the text is too long or too large, does not parse, or holds a form
            outside the allowlist, or a name ``symbols`` does not declare.
    """
    if len(text) > MAX_EXPRESSION_LENGTH:
        msg = f"the expression is longer than {MAX_EXPRESSION_LENGTH} characters"
        raise ExpressionError(msg)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        msg = "the expression does not parse"
        raise ExpressionError(msg) from None
    body = tree.body
    if not isinstance(body, ast.Compare) or len(body.ops) != 1 or len(body.comparators) != 1:
        msg = "an expression is one comparison of two sides"
        raise ExpressionError(msg)
    comparator = _COMPARATORS.get(type(body.ops[0]))
    if comparator is None:
        msg = f"the comparator {type(body.ops[0]).__name__} is not one of ==, <= and >="
        raise ExpressionError(msg)
    reader = _Reader(frozenset(symbols))
    left = reader.side(body.left)
    right = reader.side(body.comparators[0])
    return Expression(
        left=left, comparator=comparator, right=right, literals=frozenset(reader.literals)
    )


class _Reader:
    """Reads one expression's sides as sums of monomials, collecting its literals."""

    def __init__(self, symbols: frozenset[str]) -> None:
        self.symbols = symbols
        self.literals: set[int] = set()
        # The expression and the comparison count as two nodes.
        self.nodes = 2

    def visit(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_EXPRESSION_NODES:
            msg = f"the expression has more than {MAX_EXPRESSION_NODES} syntax-tree nodes"
            raise ExpressionError(msg)

    def side(self, node: ast.expr, sign: int = 1) -> tuple[Monomial, ...]:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
            self.visit()
            right_sign = sign if isinstance(node.op, ast.Add) else -sign
            return (*self.side(node.left, sign), *self.side(node.right, right_sign))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            self.visit()
            return self.side(node.operand, -sign)
        coefficient, powers = self.monomial(node)
        cleaned = tuple(sorted((s, p) for s, p in powers.items() if p != 0))
        return (Monomial(coefficient=sign * coefficient, powers=cleaned),)

    def monomial(self, node: ast.expr) -> tuple[Fraction, dict[str, int]]:
        self.visit()
        refused = _REFUSED_NODES.get(type(node))
        if refused is not None:
            msg = f"{refused} is not allowed in a law"
            raise ExpressionError(msg)
        if isinstance(node, ast.Name):
            if node.id not in self.symbols:
                msg = f"the name {node.id} is not declared among the law's symbols"
                raise ExpressionError(msg)
            return Fraction(1), {node.id: 1}
        if isinstance(node, ast.Constant):
            return Fraction(self.literal(node.value)), {}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            coefficient, powers = self.monomial(node.operand)
            return -coefficient, powers
        if isinstance(node, ast.BinOp):
            return self.product(node)
        msg = f"{type(node).__name__} is not allowed in a law"
        raise ExpressionError(msg)

    def literal(self, value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            msg = f"a literal of type {type(value).__name__} is not allowed in a law"
            raise ExpressionError(msg)
        if isinstance(value, str):
            msg = "a string is not allowed in a law"
            raise ExpressionError(msg)
        if isinstance(value, float):
            msg = "a float literal is not allowed in a law; a literal is an integer"
            raise ExpressionError(msg)
        self.literals.add(value)
        return value

    def product(self, node: ast.BinOp) -> tuple[Fraction, dict[str, int]]:
        if isinstance(node.op, ast.Add | ast.Sub):
            msg = "each side is a sum of monomials, and a sum inside a product is not a monomial"
            raise ExpressionError(msg)
        if isinstance(node.op, ast.Pow):
            return self.power(node)
        if not isinstance(node.op, ast.Mult | ast.Div):
            msg = f"the operator {type(node.op).__name__} is not allowed in a law"
            raise ExpressionError(msg)
        left_coefficient, left = self.monomial(node.left)
        right_coefficient, right = self.monomial(node.right)
        if isinstance(node.op, ast.Div):
            if right_coefficient == 0:
                msg = "the expression divides by zero"
                raise ExpressionError(msg)
            right_coefficient = 1 / right_coefficient
            right = {s: -p for s, p in right.items()}
        powers = dict(left)
        for symbol, power in right.items():
            powers[symbol] = powers.get(symbol, 0) + power
        return left_coefficient * right_coefficient, powers

    def power(self, node: ast.BinOp) -> tuple[Fraction, dict[str, int]]:
        exponent = _integer(node.right)
        if exponent is None or exponent == 0 or abs(exponent) > MAX_EXPONENT:
            msg = f"an exponent is a non-zero integer from -{MAX_EXPONENT} to {MAX_EXPONENT}"
            raise ExpressionError(msg)
        if not isinstance(node.left, ast.Name):
            msg = "a power's base is one declared symbol"
            raise ExpressionError(msg)
        _, base = self.monomial(node.left)
        return Fraction(1), {symbol: exponent for symbol in base}


def _integer(node: ast.expr) -> int | None:
    """The integer ``node`` spells, signed, or ``None``."""
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _integer(node.operand)
        return None if inner is None else -inner
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    return None


# --- the row's checks ------------------------------------------------------------------------


def _check_binding(law: Law) -> None:
    places = PLACES[law.pattern]
    if not law.symbols:
        msg = "a law declares its symbols"
        raise ValueError(msg)
    for symbol, entry in law.symbols.items():
        if entry.place not in places:
            msg = f"symbol {symbol}'s place {entry.place} is not one the {law.pattern} pattern has"
            raise ValueError(msg)
    for condition in (*law.requires, *law.unless):
        if condition.place not in places:
            msg = f"the place {condition.place} is not one the {law.pattern} pattern has"
            raise ValueError(msg)
    anchor = law.symbols.get(law.anchor)
    if anchor is None or anchor.place not in ANCHOR_PLACES:
        msg = f"the anchor {law.anchor} is not a declared symbol on self or subject"
        raise ValueError(msg)
    used = {entry.place for entry in law.symbols.values()}
    needed = {"edge": "target", "members": "each"}.get(law.pattern)
    if needed is not None and needed not in used:
        msg = f"the {law.pattern} pattern reads at least one symbol on {needed}"
        raise ValueError(msg)
    for condition in law.unless:
        if condition.reason is None:
            msg = f"unless {condition.name} gives the reason the law does not hold there"
            raise ValueError(msg)


def _plain_name(name: str, what: str) -> None:
    """Refuse a name that is not an exact catalogue name."""
    if name in QUANTITIES:
        return
    if inferred_by(name) is not None:
        msg = (
            f"{what} {name} is only a suffix or qualifier reading of a catalogue name, which "
            "joins no law"
        )
        raise ValueError(msg)
    msg = f"{what} {name} is not in the catalogue"
    raise ValueError(msg)


def _check_names(law: Law) -> None:
    for symbol, entry in law.symbols.items():
        _plain_name(entry.name, f"symbol {symbol}'s name")
        kind = KINDS[QUANTITIES[entry.name].kind]
        if kind.angle != 0 or entry.name in EITHER_ANGLE:
            msg = f"symbol {symbol}'s name {entry.name} carries the radian, which needs a rule"
            raise ValueError(msg)
        if kind.absolute:
            msg = f"symbol {symbol}'s name {entry.name} is an absolute temperature"
            raise ValueError(msg)
    for field, conditions in (("requires", law.requires), ("unless", law.unless)):
        for condition in conditions:
            _plain_name(condition.name, f"{field} name")


def _check_literals(law: Law, parsed: Expression) -> None:
    declared: set[int] = set()
    for literal in law.literals:
        try:
            value = int(literal.value)
        except ValueError:
            msg = f"the declared literal {literal.value} is not an integer"
            raise ValueError(msg) from None
        if str(value) != literal.value.strip():
            msg = f"the declared literal {literal.value} is not an integer"
            raise ValueError(msg)
        declared.add(value)
    undeclared = sorted(parsed.literals - declared)
    if undeclared:
        msg = (
            f"the literal {undeclared[0]} is not declared with its reason; a count of parts "
            "comes from the graph, never from the expression"
        )
        raise ValueError(msg)


def _check_summed_terms(law: Law, parsed: Expression) -> None:
    each = {s for s, entry in law.symbols.items() if entry.place == "each"}
    for symbol in each:
        holding = [m for m in parsed.monomials() if any(s == symbol for s, _ in m.powers)]
        if len(holding) != 1 or holding[0].powers != ((symbol, 1),):
            msg = f"a summed member term ({symbol}) stands alone, once, to the first power"
            raise ValueError(msg)


def _check_tolerance(law: Law, parsed: Expression) -> None:
    if parsed.comparator not in TOLERANCE_COMPARATORS[law.tolerance]:
        msg = f"the {law.tolerance} tolerance does not admit {parsed.comparator!r}"
        raise ValueError(msg)
    if (law.tolerance == "model") != (law.model is not None):
        msg = "a model tolerance, and only a model tolerance, carries its model allowance"
        raise ValueError(msg)
    if law.model is not None:
        try:
            share = Fraction(law.model.share)
        except (ValueError, ZeroDivisionError):
            msg = f"the model allowance {law.model.share} is not a ratio of integers"
            raise ValueError(msg) from None
        if not 0 < share <= MODEL_MAX_SHARE:
            msg = f"a model allowance is above 0 and at most {MODEL_MAX_SHARE}"
            raise ValueError(msg)


def _dimension_of(law: Law, monomial: Monomial) -> Any:
    quantity = UREG.Quantity(1, "dimensionless")
    for symbol, power in monomial.powers:
        canonical = KINDS[QUANTITIES[law.symbols[symbol].name].kind].canonical
        quantity = quantity * UREG.Quantity(1, canonical) ** power
    return quantity.dimensionality


def _check_dimension(law: Law, parsed: Expression) -> None:
    dimensions = [_dimension_of(law, m) for m in parsed.monomials()]
    if any(d != dimensions[0] for d in dimensions[1:]):
        msg = "the two sides are not one dimension under the kinds of the law's symbols"
        raise ValueError(msg)
    bare = {
        QUANTITIES[law.symbols[m.powers[0][0]].name].kind
        for m in parsed.monomials()
        if len(m.powers) == 1 and m.powers[0][1] == 1
    }
    if len(bare) > 1:
        msg = f"bare terms of different kinds are not one quantity: {', '.join(sorted(bare))}"
        raise ValueError(msg)


def _check_new(law: Law, parsed: Expression) -> None:
    names = frozenset(entry.name for entry in law.symbols.values())
    comparator = "<=" if parsed.comparator in ("<=", ">=") else "=="
    for relation, inputs in RELATION_INPUTS.items():
        if inputs.names == names and inputs.comparator == comparator:
            msg = f"the law restates the relation {relation}, which the checks already form"
            raise ValueError(msg)
    if law.overlaps != "none" and law.overlaps not in RELATION_INPUTS:
        msg = f"overlaps names {law.overlaps}, which is no relation the checks form"
        raise ValueError(msg)


def _check_examples(law: Law) -> None:
    outcomes = {example.outcome for example in law.example}
    if outcomes != {"pass", "fail"}:
        msg = "a law carries a worked example that passes and one that fails"
        raise ValueError(msg)
    for example in law.example:
        if set(example.values) != set(law.symbols):
            msg = f"a {example.outcome} example gives a value for every symbol and no other"
            raise ValueError(msg)
        for symbol, value in example.values.items():
            summed = law.symbols[symbol].place == "each"
            if summed != isinstance(value, list) or (summed and not value):
                msg = f"a {example.outcome} example gives {symbol} one value, or a list if summed"
                raise ValueError(msg)


def _check_status(law: Law) -> None:
    if law.status == "warn":
        if law.cleared is not None:
            msg = "a law on probation carries no clearance (cleared)"
            raise ValueError(msg)
        return
    cleared = law.cleared
    if cleared is None:
        msg = "a law at block carries the audit that cleared it (cleared)"
        raise ValueError(msg)
    if len(set(cleared.designs)) != len(cleared.designs):
        msg = "a design is named twice in the clearance"
        raise ValueError(msg)
    if cleared.evaluated_clean < BLOCK_MIN_EVALUATED:
        msg = (
            f"a law blocks only after at least {BLOCK_MIN_EVALUATED} evaluated instances on "
            f"clean designs; the audit counted {cleared.evaluated_clean}"
        )
        raise ValueError(msg)
    if len(cleared.designs) < BLOCK_MIN_DESIGNS:
        msg = f"a law blocks only after an audit over at least {BLOCK_MIN_DESIGNS} designs"
        raise ValueError(msg)
    if cleared.unexplained != 0:
        msg = "a law with an unexplained block on a clean design stays on probation"
        raise ValueError(msg)


# --- the table -------------------------------------------------------------------------------


class _Meta(_Frozen):
    format: Literal[1]


@dataclass(frozen=True)
class LawTable:
    """The loaded table: every law by id, and the digest and path of the file it came from."""

    laws: Mapping[str, Law]
    sha256: str
    path: str

    def statuses(self) -> Mapping[str, LawStatus]:
        """Each law's probation state, by id."""
        return MappingProxyType({law_id: law.status for law_id, law in self.laws.items()})

    def input_names(self) -> frozenset[str]:
        """Every catalogue name any law reads, requires or is excused by."""
        return frozenset(name for law in self.laws.values() for name in law.input_names())

    def content(self) -> list[dict[str, Any]]:
        """What the table says, law by law in id order: the catalogue digest's ``laws`` key."""
        return [self.laws[law_id].model_dump(mode="json") for law_id in sorted(self.laws)]


def _where(row: Mapping[str, Any], index: int) -> str:
    law_id = row.get("id")
    return f"law {law_id}" if isinstance(law_id, str) and law_id else f"law #{index}"


def _refusal(exc: ValidationError) -> tuple[str, str]:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first["loc"]) or "row"
    return where, str(first["msg"]).removeprefix("Value error, ")


def _promotion_lines(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file():
        return []
    lines: list[Mapping[str, Any]] = []
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError:
            msg = "a promotion line is not JSON"
            raise LawTableError(msg, path=str(path), line=str(number)) from None
        if isinstance(line, dict):
            lines.append(line)
    return lines


def _check_promotions(law: Law, lines: list[Mapping[str, Any]], path: Path) -> None:
    approved = any(
        line.get("kind") == "law"
        and line.get("law_id") == law.id
        and line.get("candidate_id") == law.approved.candidate_id
        for line in lines
    )
    if not approved:
        msg = f"law {law.id}: no promotion line records its approval"
        raise LawTableError(msg, law=law.id, promotions=str(path))
    if law.cleared is None:
        return
    moved = any(
        line.get("kind") == "law_status"
        and line.get("law_id") == law.id
        and line.get("status") == "block"
        and line.get("audit_sha256") == law.cleared.audit_sha256
        for line in lines
    )
    if not moved:
        msg = f"law {law.id}: no promotion line records its move to block status"
        raise LawTableError(msg, law=law.id, promotions=str(path))


def load_laws(path: Path | None = None, promotions: Path | None = None) -> LawTable:
    """Load the law table at ``path``, each approval held to the record at ``promotions``.

    Raises:
        LawTableError: the table is missing or not TOML, or a row does not load (the error
            names the row and the field), or a law is in it twice.
    """
    table_path = Path(path) if path is not None else LAWS_PATH
    lines_path = Path(promotions) if promotions is not None else PROMOTIONS_PATH
    if not table_path.is_file():
        msg = f"the law table {table_path} does not exist"
        raise LawTableError(msg, path=str(table_path))
    raw = table_path.read_bytes()
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        msg = "the law table is not TOML"
        raise LawTableError(msg, path=str(table_path), reason=str(exc)) from None
    try:
        _Meta.model_validate(parsed.get("meta"))
    except ValidationError:
        msg = f"the law table's [meta] does not say format = {FORMAT}"
        raise LawTableError(msg, path=str(table_path)) from None
    rows = parsed.get("law", [])
    unexpected = set(parsed) - {"meta", "law"}
    if not isinstance(rows, list) or unexpected:
        msg = "the law table holds [meta] and [[law]] rows and nothing else"
        raise LawTableError(msg, path=str(table_path))
    lines = _promotion_lines(lines_path)
    laws: dict[str, Law] = {}
    for index, row in enumerate(rows):
        where = _where(row if isinstance(row, dict) else {}, index)
        try:
            law = Law.model_validate(row)
        except ValidationError as exc:
            field, why = _refusal(exc)
            msg = f"{where}: {field}: {why}"
            raise LawTableError(msg, law=where, field=field) from None
        if law.id in laws:
            msg = f"law {law.id} is in the table twice"
            raise LawTableError(msg, law=law.id)
        _check_promotions(law, lines, lines_path)
        laws[law.id] = law
    return LawTable(
        laws=MappingProxyType(laws),
        sha256=hashlib.sha256(raw).hexdigest(),
        path=str(table_path),
    )
