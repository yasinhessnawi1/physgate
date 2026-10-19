"""Whether a corpus's correct revisions say what their sources say: the twins' second precondition.

A clean twin is a correct revision only if its numbers are its sources' numbers. A
reviewer that rejects a twin for a number that differs from its own parts-sheet row is
right, and the twin is not a correct design; so before a corpus is used, its base and
every clean patch are held to the parts sheet, mechanically:

- a number whose source is a row's URL is one of that URL's rows, converted only between
  units: some row at that address, of the same dimension, equals it;
- a number whose source is ``derived: <arithmetic>`` is that arithmetic over the rows it
  cites, to three significant figures, as the authors' brief asks;
- a ``design: <reason>`` number is a choice, and is not checked.

A derived number that subtracts rows (a robot's weight less its chassis, say) is listed
apart as ``subtracted`` even when it is the arithmetic: it carries any disagreement
between those rows into the design, so a reviewer who adds the parts up again may find
a real inconsistency the design inherited from the sheet. It is a property of the sheet,
reported, never a fault of the twin.

Equal means within half a unit in the third significant figure of the source's number,
at most 0.5 per cent of it, as the gate's own rounding allowance is. A URL whose rows
hold no number of the right dimension cannot be checked, and is listed apart as
unresolved, never as a mismatch. The injected patches are never read: an error may sit in
their numbers, and that is the corpus's point.

What it reports is a list of bare facts, each naming where it is, the node, the quantity,
the number written and the number its source gives, so that a twin found wrong goes back
to its author with nothing else (the authors' rule). It never reads a review, a gate
result or an answer field.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from physgate.evaluation.inject.corpus import (
    Corpus,
    Payload,
    _evaluate,
    _numbers,
    derivation,
)
from physgate.gate.units import PINT_ERRORS, UnitRefusedError, parse

#: Half a unit in the third significant figure of the source's number, at most.
SHARE = Fraction(5, 1000)


@dataclass(frozen=True)
class SourceFinding:
    """One number that is not what its source says, or whose source cannot be read."""

    where: str
    node: str
    quantity: str
    kind: Literal["mismatch", "unresolved", "subtracted"]
    written: str
    source_gives: str
    source: str

    def fact(self) -> str:
        """The finding as one line an author can act on, and nothing else."""
        if self.kind == "subtracted":
            return (
                f"{self.where}: {self.quantity} of {self.node} is {self.written}, a difference "
                f"of parts-sheet rows ({self.source})"
            )
        if self.kind == "unresolved":
            return (
                f"{self.where}: {self.quantity} of {self.node} is {self.written}, and no row at "
                f"its source gives a number of that kind ({self.source})"
            )
        if self.source.startswith("derived:"):
            return (
                f"{self.where}: {self.quantity} of {self.node} is {self.written}, and its source "
                f"gives {self.source_gives} ({self.source})"
            )
        return (
            f"{self.where}: {self.quantity} of {self.node} is {self.written}, and no row at its "
            f"source gives that number; its rows of that kind give {self.source_gives} "
            f"({self.source})"
        )


def _close(written: Any, expected: Any) -> bool:  # noqa: ANN401 - pint quantities
    """``written`` equals ``expected`` within the source's own rounding."""
    value = Fraction(str(written.to(expected.units).magnitude))
    target = Fraction(str(expected.magnitude))
    return abs(value - target) <= SHARE * abs(target)


def _shown(quantity: Any) -> str:  # noqa: ANN401 - a pint quantity
    return f"{float(quantity.magnitude):.4g} {quantity.units:~}"


def _check_node(
    where: str,
    payload: Payload,
    numbers: dict[str, Any],
    by_url: dict[str, list[Any]],
) -> list[SourceFinding]:
    found = []
    for name, quantity in payload.get("quantities", {}).items():
        source = str(quantity["source"])
        head, _, rest = source.partition(":")
        if head == "design":
            continue
        try:
            written = parse(quantity["value"], quantity["unit"])
        except (UnitRefusedError, *PINT_ERRORS):
            continue  # the gate's unit check refuses it; not a source question
        node = str(payload["id"])
        subtracts = False
        if head == "derived":
            tree, rows = derivation(rest)
            subtracts = any(
                isinstance(n, ast.BinOp) and isinstance(n.op, ast.Sub) for n in ast.walk(tree)
            )
            operands = {f"_row{n}": numbers[r] for n, r in enumerate(rows) if r in numbers}
            if len(operands) != len(rows):
                continue  # the loader refuses a citation of a row that is not a number
            expected = _evaluate(tree, operands)
            candidates = [expected]
        else:
            candidates = by_url.get(source, [])
        same_kind = [c for c in candidates if c.dimensionality == written.dimensionality]
        if not same_kind:
            found.append(
                SourceFinding(where, node, name, "unresolved", _shown(written), "", source)
            )
            continue
        if not any(_close(written, c) for c in same_kind):
            gives = " or ".join(_shown(c.to(written.units)) for c in same_kind[:3])
            found.append(
                SourceFinding(where, node, name, "mismatch", _shown(written), gives, source)
            )
        elif subtracts:
            gives = _shown(same_kind[0].to(written.units))
            found.append(
                SourceFinding(where, node, name, "subtracted", _shown(written), gives, source)
            )
    return found


def check_sources(corpus: Corpus) -> list[SourceFinding]:
    """Every number of the base and of every clean patch that its source does not support.

    Raises:
        CorpusError: a row of the parts sheet has a unit the gate cannot read.
    """
    numbers = _numbers(corpus.sources)
    by_url: dict[str, list[Any]] = {}
    for row_id, row in corpus.sources.rows.items():
        if row_id in numbers:
            by_url.setdefault(row.url, []).append(numbers[row_id])
    found = []
    for payload in corpus.base.nodes:
        found += _check_node("base", payload, numbers, by_url)
    for artefact in corpus.artefacts:
        for payload in artefact.clean.nodes:
            found += _check_node(f"revision {artefact.id}", payload, numbers, by_url)
    return found
