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

A law's worked examples are run when it loads, through :func:`evaluate`, the evaluator the laws
check uses on a graph: a row whose pass example fails, whose fail example passes, or whose
example cannot be evaluated, is refused with the rest.

**Evaluation is exact.** Every side is a sum of monomials, so a side's value is the sum of each
monomial's coefficient times its inputs to their integer powers, in fractions, with nothing
rounded and no string evaluated. A summed member term contributes one term per member. An
equality of the ``rounding`` class may miss by the propagated rounding of its terms
(:func:`physgate.gate.tolerances.propagated_allowance`), each member its own term; a ``model``
law by its sourced share of the right side's magnitude; an inequality by nothing. A law that
would divide by a zero input cannot be evaluated, and says so.

**Patterns** (:func:`bindings`) say where a law forms an instance: wherever its anchor is, and
nowhere else. Each instance is either judged, or names why it cannot be: a missing input or
required name, a present excusing name, an edge into an interface node or into no node, a
subject that is an interface node, or a subject no member names.
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
from physgate.gate.graph import GraphView
from physgate.gate.relations import RELATION_INPUTS
from physgate.gate.tolerances import propagated_allowance
from physgate.gate.units import PINT_ERRORS, UREG, UnitRefusedError, measure
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
        _run_examples(self, parsed)
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

    def symbol_positions(self) -> list[tuple[str, int, int, int]]:
        """Where each symbol is written: ``(symbol, line, start, end)``, byte offsets in the line.

        Read off the checked expression's syntax tree, so a record can spell the instance in
        the row's own words.
        """
        body = ast.parse(self.expression, mode="eval").body
        if not isinstance(body, ast.Compare):
            return []
        return _positions(body.left) + _positions(body.comparators[0])

    def whole_sides(self) -> frozenset[tuple[int, int]]:
        """The positions ``(line, start)`` of symbols that are a whole side on their own."""
        body = ast.parse(self.expression, mode="eval").body
        if not isinstance(body, ast.Compare):
            return frozenset()
        return frozenset(
            (side.lineno, side.col_offset)
            for side in (body.left, body.comparators[0])
            if isinstance(side, ast.Name)
        )


def _positions(node: ast.expr) -> list[tuple[str, int, int, int]]:
    """The names in a checked side, with where each is written."""
    if isinstance(node, ast.Name):
        return [(node.id, node.lineno, node.col_offset, node.end_col_offset or node.col_offset)]
    if isinstance(node, ast.BinOp):
        return _positions(node.left) + _positions(node.right)
    if isinstance(node, ast.UnaryOp):
        return _positions(node.operand)
    return []


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


# --- evaluation ----------------------------------------------------------------------------

#: One symbol's value at one instance, in its kind's canonical unit: a number, or one number per
#: member for a summed symbol.
Value = Fraction | tuple[Fraction, ...]


class ZeroDivisorError(ValueError):
    """An instance the law cannot be evaluated on: it would divide by an input that is zero."""

    def __init__(self, symbols: tuple[str, ...]) -> None:
        """Name the symbols whose value is zero below the line."""
        super().__init__(f"it would divide by {', '.join(symbols)}, which is zero")
        self.symbols = symbols


@dataclass(frozen=True)
class Evaluation:
    """One instance of a law, evaluated exactly: both sides, the residual, and the verdict."""

    left: Fraction
    right: Fraction
    #: ``left - right``.
    residual: Fraction
    #: What the tolerance class lets an equality miss by; ``None`` for an inequality.
    allowance: Fraction | None
    holds: bool


def terms(
    monomials: tuple[Monomial, ...], values: Mapping[str, Value]
) -> list[tuple[Fraction, int, int]]:
    """Each term of a side as ``(value, positive, negative)``, for the value and its rounding.

    A monomial is its coefficient times its inputs to their powers; ``positive`` and
    ``negative`` count its declared factors above and below the line. A summed symbol stands
    alone in its monomial, so it gives one plain term per member.

    Raises:
        ZeroDivisorError: an input below the line is zero.
    """
    found: list[tuple[Fraction, int, int]] = []
    for monomial in monomials:
        summed = values[monomial.powers[0][0]] if len(monomial.powers) == 1 else None
        if isinstance(summed, tuple):
            found.extend((monomial.coefficient * member, 1, 0) for member in summed)
            continue
        zero = tuple(s for s, p in monomial.powers if p < 0 and values[s] == 0)
        if zero:
            raise ZeroDivisorError(zero)
        value = monomial.coefficient
        positive = negative = 0
        for symbol, power in monomial.powers:
            number = values[symbol]
            if isinstance(number, tuple):
                msg = f"the summed symbol {symbol} stands alone in its term"
                raise TypeError(msg)
            value *= number**power
            if power > 0:
                positive += power
            else:
                negative -= power
        found.append((value, positive, negative))
    return found


def side_value(monomials: tuple[Monomial, ...], values: Mapping[str, Value]) -> Fraction:
    """The exact value of one side over ``values``.

    Raises:
        ZeroDivisorError: an input below the line is zero.
    """
    return sum((value for value, _, _ in terms(monomials, values)), Fraction(0))


def evaluate(law: Law, parsed: Expression, values: Mapping[str, Value]) -> Evaluation:
    """Evaluate ``law``, whose checked expression is ``parsed``, over ``values``, exactly.

    ``values`` holds every symbol's value in its kind's canonical unit; the canonical units are
    coherent, so the sides' values are in one unit.

    Raises:
        ZeroDivisorError: an input below the line is zero.
    """
    left_terms = terms(parsed.left, values)
    right_terms = terms(parsed.right, values)
    left = sum((v for v, _, _ in left_terms), Fraction(0))
    right = sum((v for v, _, _ in right_terms), Fraction(0))
    residual = left - right
    allowance: Fraction | None
    if law.tolerance == "rounding":
        allowance = propagated_allowance([*left_terms, *right_terms])
        holds = abs(residual) <= allowance
    elif law.tolerance == "model" and law.model is not None:
        allowance = Fraction(law.model.share) * abs(right)
        holds = abs(residual) <= allowance
    else:
        allowance = None
        holds = residual <= 0 if parsed.comparator == "<=" else residual >= 0
    return Evaluation(left=left, right=right, residual=residual, allowance=allowance, holds=holds)


# --- patterns ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Binding:
    """One instance of a law in a graph: where each place is, or why it cannot be judged."""

    #: The node holding the anchor: the law's ``self`` or ``subject``.
    anchor: str
    #: The node an ``edge`` law's edge names, where it has one.
    target: str | None = None
    #: For a ``members`` law, each summed symbol's members, in id order.
    members: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: Names the instance needs and the graph does not give there.
    missing: tuple[str, ...] = ()
    #: Why the instance cannot be judged, besides a missing name; ``None`` if it can be.
    reason: str | None = None
    #: The names the reason is about.
    about: tuple[str, ...] = ()

    def judgeable(self) -> bool:
        """Whether every input is there and nothing excuses the law."""
        return not self.missing and self.reason is None

    def nodes(self) -> tuple[str, ...]:
        """Every node the instance reads, the anchor first."""
        found = [self.anchor]
        if self.target is not None:
            found.append(self.target)
        found.extend(m for _, members in self.members for m in members)
        return tuple(dict.fromkeys(found))


def _names_at(law: Law, place: str) -> list[str]:
    """The catalogue names the law reads at ``place``, then the ones it requires there."""
    read = [entry.name for entry in law.symbols.values() if entry.place == place]
    required = [c.name for c in law.requires if c.place == place]
    return list(dict.fromkeys([*read, *required]))


def _excuse(law: Law, quantities: Collection[str], place: str) -> Condition | None:
    """The first excusing name present at ``place``, if any."""
    return next((c for c in law.unless if c.place == place and c.name in quantities), None)


def _absent(names: list[str], quantities: Collection[str]) -> list[str]:
    return [n for n in names if n not in quantities]


def bindings(law: Law, view: GraphView) -> list[Binding]:
    """Every instance of ``law`` in ``view``: one per anchor (per edge for an ``edge`` law).

    Instances are in node-id order, an edge law's in its targets' id order.
    """
    anchor_name = law.symbols[law.anchor].name
    found: list[Binding] = []
    for node_id, node in view.nodes.items():
        if anchor_name not in node.quantities:
            continue
        if law.pattern == "node":
            found.append(_on_node(law, node_id, node.quantities))
        elif law.pattern == "edge":
            found.extend(_on_edges(law, view, node_id))
        else:
            found.append(_on_members(law, view, node_id))
    return found


def _on_node(law: Law, node_id: str, quantities: Collection[str]) -> Binding:
    excuse = _excuse(law, quantities, "self")
    if excuse is not None:
        return Binding(anchor=node_id, reason=excuse.reason, about=(excuse.name,))
    return Binding(anchor=node_id, missing=tuple(_absent(_names_at(law, "self"), quantities)))


def _on_edges(law: Law, view: GraphView, node_id: str) -> list[Binding]:
    own = view.nodes[node_id].quantities
    excuse = _excuse(law, own, "self")
    if excuse is not None:
        return [Binding(anchor=node_id, reason=excuse.reason, about=(excuse.name,))]
    missing_here = _absent(_names_at(law, "self"), own)
    wanted = _names_at(law, "target")
    read = [entry.name for entry in law.symbols.values() if entry.place == "target"]
    found: list[Binding] = []
    for target in sorted(set(view.nodes[node_id].constrains)):
        held = view.nodes.get(target)
        if held is None:
            found.append(
                Binding(
                    anchor=node_id,
                    target=target,
                    reason=f"its edge names {target}, which is not in the graph",
                    about=tuple(read),
                )
            )
        elif held.kind == "interface":
            found.append(
                Binding(
                    anchor=node_id,
                    target=target,
                    reason=f"its edge names {target}, an interface node fixed at decomposition",
                    about=tuple(read),
                )
            )
        elif any(name in held.quantities for name in read):
            there = _excuse(law, held.quantities, "target")
            if there is not None:
                found.append(
                    Binding(anchor=node_id, target=target, reason=there.reason, about=(there.name,))
                )
                continue
            missing = (*missing_here, *_absent(wanted, held.quantities))
            found.append(Binding(anchor=node_id, target=target, missing=tuple(missing)))
    if not found:
        # No node its edges name holds what the law reads there: the anchor is unjudged.
        found.append(Binding(anchor=node_id, missing=(*missing_here, *read)))
    return found


def _on_members(law: Law, view: GraphView, node_id: str) -> Binding:
    if view.nodes[node_id].kind == "interface":
        # An interface holds values fixed at decomposition, not a part's own: the law refuses
        # nothing there, whatever its members sum to, as an edge into an interface refuses
        # nothing.
        read = [entry.name for entry in law.symbols.values() if entry.place == "subject"]
        return Binding(
            anchor=node_id,
            reason=f"its subject {node_id} is an interface node fixed at decomposition",
            about=tuple(read),
        )
    own = view.nodes[node_id].quantities
    excuse = _excuse(law, own, "subject")
    if excuse is not None:
        return Binding(anchor=node_id, reason=excuse.reason, about=(excuse.name,))
    missing = _absent(_names_at(law, "subject"), own)
    constrained = view.constrained_by(node_id)
    summed = sorted(s for s, entry in law.symbols.items() if entry.place == "each")
    members = tuple(
        (s, tuple(m for m in constrained if law.symbols[s].name in view.nodes[m].quantities))
        for s in summed
    )
    empty = [law.symbols[s].name for s, held in members if not held]
    if empty:
        return Binding(
            anchor=node_id,
            members=members,
            reason=f"no member names it and holds {', '.join(empty)}",
            about=tuple(empty),
        )
    for _, held in members:
        for member in held:
            there = view.nodes[member].quantities
            excused = _excuse(law, there, "each")
            if excused is not None:
                return Binding(
                    anchor=node_id, members=members, reason=excused.reason, about=(excused.name,)
                )
            missing.extend(n for n in _absent(_names_at(law, "each"), there) if n not in missing)
    return Binding(anchor=node_id, members=members, missing=tuple(missing))


def _run_examples(law: Law, parsed: Expression) -> None:
    """Evaluate each worked example and refuse the law if one does not give its outcome."""
    for example in law.example:
        values: dict[str, Value] = {}
        for symbol, given in example.values.items():
            kind = KINDS[QUANTITIES[law.symbols[symbol].name].kind]
            try:
                if isinstance(given, list):
                    values[symbol] = tuple(measure(kind, v.value, v.unit).magnitude for v in given)
                else:
                    values[symbol] = measure(kind, given.value, given.unit).magnitude
            except (UnitRefusedError, *PINT_ERRORS):
                msg = f"the {example.outcome} example's {symbol} is in a unit its kind refuses"
                raise ValueError(msg) from None
        try:
            holds = evaluate(law, parsed, values).holds
        except ZeroDivisorError as exc:
            msg = f"the {example.outcome} example cannot be evaluated: {exc}"
            raise ValueError(msg) from None
        if holds != (example.outcome == "pass"):
            gives = "passes" if holds else "fails"
            msg = f"the {example.outcome} example {gives}: it does not give its stated outcome"
            raise ValueError(msg)


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
