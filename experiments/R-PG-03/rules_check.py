"""R-PG-03, CRITERIA.md §2.5 item 4: the mechanical rule checks, and the passed copies' digests.

Usage (from the checkout at ``R``)::

    python -I rules_check.py check --dir <dir> --sheet <sources.json> --ids <a01,a02,...>
        --out <new dir>
    python -I rules_check.py copies --dir <session dir> --record <passed.json>
    python -I rules_check.py message --facts <facts.json> [--facts ...] --out <message file>

``check`` reads ``<dir>/base.json`` and ``<dir>/clean/<id>.json`` for each id given, never any
other file, and holds the base and every revision to Appendix A's mechanical rules:

- **rule 3:** no node of a revision lacks a quantity that the same node has in the base;
- **rule 2:** no quantity's source cites a row whose quantity text names an absolute maximum:
  R4.04, R4.07, R6.06 and R7.09;
- **rule 5:** no quantity whose name reads as a limit or a rating (``*_limit``, ``max_*``,
  ``*_max``, ``rated_*`` or ``*_rating``) cites one of §2.5's 18 rows (five efficiency points and
  thirteen rows whose note or value marks the number as typical);
- **rule 4, listed and never returned:** every change to a ``requirement`` node, and every change
  to a quantity named ``*_limit``, ``max_*``, ``*_max``, ``min_*``, ``*_min``, ``rated_*`` or
  ``*_rating``, with its old and new value.

A source **cites** a row when it is ``derived:`` arithmetic naming the row, or when it is the row's
URL and the number written is that row's number, as the source check matches a URL's rows (same
dimension, within half a unit in the third significant figure). A row the sheet gives no number
for is cited by neither form.

It writes ``facts.json`` (the facts of rules 2, 3 and 5, each its check, place, node, quantity and
message), ``listed.json`` (rule 4) and, when there are facts, ``message.txt``: Appendix B's facts
template with one line per fact. ``message`` writes that template from the facts of every check of
a round. ``copies`` holds every passed copy in a session's directory to its recorded sha256
(``passed.json``: path to digest), read through no symlink. Each prints counts only and exits 0
only if nothing is found (``check``: no fact; ``copies``: every copy as recorded).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

#: Rule 2's rows: their quantity text names an absolute maximum.
ABS_MAX_ROWS = ("R4.04", "R4.07", "R6.06", "R7.09")
#: Rule 5's rows, fixed in §2.5: the efficiency points, then the rows marked typical.
TYPICAL_ROWS = (
    "R1.16",
    "R1.17",
    "R1.18",
    "R1.19",
    "R1.20",
    "R1.05",
    "R1.10",
    "R1a.02",
    "R1a.03",
    "R1a.10",
    "R1a.11",
    "R4.09",
    "R4.12",
    "R6.08",
    "R6.09",
    "R6.11",
    "R7.08",
    "R8.02",
)
#: A name that reads as a limit or a rating (rule 5).
LIMIT_NAME = re.compile(r"^(?:.+_limit|max_.+|.+_max|rated_.+|.+_rating)$")
#: The names whose every change is listed (rule 4).
LISTED_NAME = re.compile(r"^(?:.+_limit|max_.+|.+_max|min_.+|.+_min|rated_.+|.+_rating)$")
#: Half a unit in the third significant figure, as the source check matches (its SHARE).
SHARE = Fraction(5, 1000)
#: Appendix B's facts template, around its one line per fact.
TEMPLATE_HEAD = "The design was checked. These facts need a change before the next check:"
TEMPLATE_TAIL = (
    "Change only what these facts need, and keep every rule of `rules.md`. Then add one line to "
    "`done.md` saying the facts are answered, and stop."
)


class RefusedError(Exception):
    """An input is not one this script can read faithfully."""


def fact(check: str, place: str, node: str, quantity: str, message: str) -> dict[str, str]:
    """One bare fact: the check, where, the node, the quantity, the message."""
    return {"check": check, "place": place, "node": node, "quantity": quantity, "message": message}


def fact_line(f: dict[str, str]) -> str:
    """One fact as the template's line: the check, the node, the quantity, the message."""
    return (
        f"- {f['check']} ({f['place']}); node {f['node']}; quantity {f['quantity']}: {f['message']}"
    )


def message(facts: list[dict[str, str]]) -> str:
    """Appendix B's facts template, one line per fact."""
    lines = [TEMPLATE_HEAD, *(fact_line(f) for f in facts), TEMPLATE_TAIL]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- what a source cites


class Sheet:
    """The reviewers' sheet's numbers, by row and by URL, as the gate's unit registry reads them."""

    def __init__(self, sheet: bytes) -> None:
        """The sheet's bytes, read."""
        from physgate.evaluation.inject.corpus import _numbers, read_sheet

        self.sources = read_sheet(sheet)
        self.numbers = _numbers(self.sources)
        self.by_url: dict[str, list[str]] = {}
        for row_id, row in self.sources.rows.items():
            if row_id in self.numbers:
                self.by_url.setdefault(row.url, []).append(row_id)

    def cited(self, quantity: dict[str, Any]) -> set[str]:
        """The rows a quantity's source cites: by its arithmetic, or by its URL and number."""
        from physgate.evaluation.inject.corpus import derivation
        from physgate.gate.units import PINT_ERRORS, UnitRefusedError, parse

        source = str(quantity.get("source", ""))
        head, _, rest = source.partition(":")
        if head == "design":
            return set()
        if head == "derived":
            try:
                return set(derivation(rest)[1])
            except ValueError:
                return set()
        try:
            written = parse(quantity["value"], quantity["unit"])
        except (UnitRefusedError, *PINT_ERRORS, KeyError):
            return set()
        found = set()
        for row_id in self.by_url.get(source, []):
            number = self.numbers[row_id]
            if number.dimensionality != written.dimensionality:
                continue
            value = Fraction(str(written.to(number.units).magnitude))
            target = Fraction(str(number.magnitude))
            if abs(value - target) <= SHARE * abs(target):
                found.add(row_id)
        return found


# ---------------------------------------------------------------- the rules


def _nodes(payload: Any, where: str) -> list[dict[str, Any]]:  # noqa: ANN401 - JSON
    nodes = payload.get("nodes") if isinstance(payload, dict) else None
    if not isinstance(nodes, list) or not all(isinstance(n, dict) and "id" in n for n in nodes):
        raise RefusedError(f"{where} holds no list of nodes with ids")
    return nodes


def node_facts(sheet: Sheet, place: str, node: dict[str, Any]) -> list[dict[str, str]]:
    """Rules 2 and 5 on one node's quantities."""
    out = []
    for name, quantity in sorted((node.get("quantities") or {}).items()):
        if not isinstance(quantity, dict):
            continue
        rows = sheet.cited(quantity)
        for row in sorted(rows & set(ABS_MAX_ROWS)):
            out.append(
                fact(
                    "rule 2",
                    place,
                    str(node["id"]),
                    name,
                    f"its source cites {row}, a row whose quantity is an absolute maximum",
                )
            )
        if LIMIT_NAME.match(name):
            for row in sorted(rows & set(TYPICAL_ROWS)):
                out.append(
                    fact(
                        "rule 5",
                        place,
                        str(node["id"]),
                        name,
                        f"a limit or rating whose source cites {row}, which the sheet gives as an "
                        "operating point or a typical value",
                    )
                )
    return out


def _value(q: Any) -> Any:  # noqa: ANN401 - JSON
    return None if not isinstance(q, dict) else {"value": q.get("value"), "unit": q.get("unit")}


def check(directory: Path, ids: list[str], sheet: Sheet) -> dict[str, Any]:
    """Every rule fact and every rule 4 listing for the base and the named revisions.

    Raises:
        RefusedError: a file is missing, not JSON, or not of the format's form.
    """
    base_raw = common.read_inside(directory, directory / "base.json")
    if base_raw is None:
        raise RefusedError("base.json is not a regular file of the directory")
    base_nodes = _nodes(json.loads(base_raw), "base.json")
    base = {str(n["id"]): n for n in base_nodes}
    facts: list[dict[str, str]] = []
    for node in base_nodes:
        facts += node_facts(sheet, "base.json", node)
    requirement_changes: list[dict[str, Any]] = []
    limit_changes: list[dict[str, Any]] = []
    for rid in ids:
        if not re.fullmatch(r"[as][0-9]{2}", rid):
            raise RefusedError("a revision id is a letter and two digits")
        place = f"clean/{rid}.json"
        raw = common.read_inside(directory, directory / "clean" / f"{rid}.json")
        if raw is None:
            raise RefusedError(f"{place} is not a regular file of the directory")
        revision = json.loads(raw)
        clean = revision.get("clean") if isinstance(revision, dict) else None
        for node in _nodes(clean, place):
            nid = str(node["id"])
            facts += node_facts(sheet, place, node)
            before = base.get(nid)
            have = node.get("quantities") or {}
            had = (before or {}).get("quantities") or {}
            for name in sorted(set(had) - set(have)):
                facts.append(
                    fact(
                        "rule 3",
                        place,
                        nid,
                        name,
                        "the base's node has this quantity and the revision's node does not",
                    )
                )
            if node.get("kind") == "requirement" and json.dumps(node, sort_keys=True) != (
                json.dumps(before, sort_keys=True) if before is not None else None
            ):
                requirement_changes.append({"place": place, "node": nid, "new": before is None})
            for name in sorted(set(had) | set(have)):
                if LISTED_NAME.match(name) and _value(had.get(name)) != _value(have.get(name)):
                    limit_changes.append(
                        {
                            "place": place,
                            "node": nid,
                            "quantity": name,
                            "old": _value(had.get(name)),
                            "new": _value(have.get(name)),
                        }
                    )
    return {
        "facts": facts,
        "listed": {
            "requirement_changes": requirement_changes,
            "limit_changes": limit_changes,
        },
    }


def copies(directory: Path, record: dict[str, str]) -> dict[str, Any]:
    """Every passed copy in a session's directory against its recorded sha256."""
    changed, gone = [], []
    for rel, digest in sorted(record.items()):
        data = common.read_inside(directory, directory / rel)
        if data is None:
            gone.append(rel)
        elif common.sha256_bytes(data) != digest:
            changed.append(rel)
    return {
        "passed_copies": len(record),
        "changed": changed,
        "gone": gone,
        "holds": not changed and not gone,
    }


def main(argv: list[str] | None = None) -> int:
    """One subcommand; counts only; exit 0 only if nothing is found."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--dir", type=Path, required=True)
    c.add_argument("--sheet", type=Path, required=True)
    c.add_argument("--ids", required=True)
    c.add_argument("--out", type=Path, required=True)
    k = sub.add_parser("copies")
    k.add_argument("--dir", type=Path, required=True)
    k.add_argument("--record", type=Path, required=True)
    m = sub.add_parser("message")
    m.add_argument("--facts", type=Path, action="append", required=True)
    m.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            if args.out.exists():
                raise RefusedError("the output directory exists: nothing is written over")
            ids = [x for x in args.ids.split(",") if x]
            found = check(args.dir.resolve(), ids, Sheet(args.sheet.read_bytes()))
            args.out.mkdir(parents=True)
            (args.out / "facts.json").write_text(json.dumps(found["facts"], indent=1) + "\n")
            (args.out / "listed.json").write_text(json.dumps(found["listed"], indent=1) + "\n")
            if found["facts"]:
                (args.out / "message.txt").write_text(message(found["facts"]))
            counts = {
                "revisions": len(ids),
                "facts": {
                    r: sum(f["check"] == r for f in found["facts"])
                    for r in ("rule 2", "rule 3", "rule 5")
                },
                "listed": {k: len(v) for k, v in found["listed"].items()},
            }
            print(json.dumps(counts, sort_keys=True))
            return 1 if found["facts"] else 0
        if args.cmd == "copies":
            record = json.loads(args.record.read_text())
            found = copies(args.dir.resolve(), record)
            print(json.dumps(found, sort_keys=True))
            return 0 if found["holds"] else 1
        facts = [f for path in args.facts for f in json.loads(path.read_text())]
        if args.out.exists():
            raise RefusedError("the message exists: nothing is written over")
        args.out.write_text(message(facts))
        print(json.dumps({"facts": len(facts)}))
        return 0
    except RefusedError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
