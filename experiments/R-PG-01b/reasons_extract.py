"""R-PG-01b, CRITERIA.md §6: the finding lines of every review of the valid runs, and their loci.

Usage, in the run checkout, after every valid run has ended::

    reasons_extract.py --run I1=<run dir> --run F1=<run dir> [--run I2=... --run F2=...]
        --out <new work dir>

**Finding lines** are R-LAW-01 §2.2's: from each subtask's last review line, every entry of
``result.items`` whose result is ``unmet`` (sections 1 to 3) or ``confirmed`` (section 4), plus
``result.failing_item`` if it names an item not already among them; each with its evidence, every
rubric item id of its role's rubric replaced by ``[rule]``. Ids run ``L0001…`` in the order round,
arm (I, F), side (injected, twin), artefact id, the entry's position in ``result.items``.

**The locus** of a line is the set of (node id, quantity name) pairs of its design pair that it
names: the quantity name as a whole word, and the node id or the part of it after its first dot as
a whole word, case-folded (R-LAW-01 §2.2's rule, implemented from that description). A design
pair's pairs are every (node, quantity) of its base, its clean patch and its injected patch.

It writes, into ``--out`` (a new directory), never shown to any session:

- ``lines.jsonl``: every line, with its id, round, arm, side, artefact, role, section, item,
  position, its review's outcome, text, locus, whether it is an error-item line (its item is in
  the artefact's §6 item 10 cell) and whether it cites by row id one of the 62 rows R-PG-01's
  sheet left without a value (the descriptive tag);
- ``reviews.jsonl``: every (round, arm, side, artefact) review's outcome and cause, and, for an
  injected artefact, whether its review names the planted error by R-PG-01 §6 item 10's rule
  (``tally_rows.py``'s own ``tally``, with the twin condition);
- ``design.json``: each artefact's base, patches, changed pairs (R-LAW-01 §2.3), role and edge.

It prints counts only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import contrast as K  # noqa: E402

SECTIONS = ("acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking")
REJECTING = ("unmet", "confirmed")
#: A rubric item's own line in the rubric file (R-LAW-01's pattern).
ITEM_LINE = re.compile(r"^- \*\*(?P<id>[A-Z]{1,2}-?[0-9]+)\.")
ROW_ID = re.compile(r"(?<![A-Za-z0-9.])R[0-9]+[a-z]?\.[0-9]{2}(?![0-9])")


def rubric_ids(checkout: Path, role: str) -> set[str]:
    """The item ids the role's rubric defines, at the run commit."""
    text = (checkout / "knowledge" / "reviewers" / role / "rubric.md").read_text()
    return {m.group("id") for line in text.splitlines() if (m := ITEM_LINE.match(line))}


def strip_ids(text: str, ids: set[str]) -> str:
    """Every rubric item id becomes ``[rule]`` (R-LAW-01's stripping rule)."""
    for i in sorted(ids, key=len, reverse=True):
        text = re.sub(rf"(?<![\w.-]){re.escape(i)}(?![\w]|\.\d)", "[rule]", text)
    return text


def names_pair(text: str, node: str, quantity: str) -> bool:
    """§6's locus rule: the quantity as a whole word, and the node or its part after the dot."""
    low = text.casefold()
    if not re.search(rf"\b{re.escape(quantity.casefold())}\b", low):
        return False
    short = node.split(".", 1)[1] if "." in node else node
    return bool(
        re.search(rf"\b{re.escape(node.casefold())}\b", low)
        or re.search(rf"\b{re.escape(short.casefold())}\b", low)
    )


def rejecting_entries(result: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """§6: every ``unmet`` or ``confirmed`` item, and the failing item's if not among them."""
    items = result.get("items") or []
    out = [(i, it) for i, it in enumerate(items) if it.get("result") in REJECTING]
    fi = result.get("failing_item")
    if fi and fi not in {it["item"] for _, it in out}:
        out += [(i, it) for i, it in enumerate(items) if it.get("item") == fi]
    return sorted(out, key=lambda x: x[0])


class Designs:
    """The corpus's design pairs: base, patches, every pair, and the changed pairs."""

    def __init__(self, corpus: Path) -> None:
        self.base = json.loads((corpus / "base.json").read_text())["nodes"]
        self.artefacts = {
            p.stem: json.loads(p.read_text()) for p in sorted((corpus / "artefacts").glob("*.json"))
        }

    def patch(self, artefact: str, side: str) -> list[dict[str, Any]]:
        a = self.artefacts[artefact]
        return list((a["injected"] if side == "injected" else a["clean"])["nodes"])

    def pairs(self, artefact: str) -> set[tuple[str, str]]:
        out = set()
        for n in [*self.base, *self.patch(artefact, "twin"), *self.patch(artefact, "injected")]:
            for q in n.get("quantities") or {}:
                out.add((n["id"], q))
        return out

    def changed(self, artefact: str) -> set[tuple[str, str]]:
        """A (node, quantity) whose value or unit differs between the patches, or that one has
        and the other lacks; for a propagation item, every pair of the edge's two end nodes."""

        def values(side: str) -> dict[tuple[str, str], tuple[Any, Any]]:
            return {
                (n["id"], q): (v.get("value"), v.get("unit"))
                for n in self.patch(artefact, side)
                for q, v in (n.get("quantities") or {}).items()
            }

        clean, inj = values("twin"), values("injected")
        out = {k for k in clean.keys() | inj.keys() if clean.get(k) != inj.get(k)}
        edge = self.artefacts[artefact].get("edge")
        if edge:
            ends = {edge["source"], edge["target"]}
            out |= {(n, q) for (n, q) in self.pairs(artefact) if n in ends}
        return out


def missing_rows(sheet: bytes) -> set[str]:
    """The rows R-PG-01's sheet left without a value (62 of 163)."""
    return {k for k, r in json.loads(sheet)["rows"].items() if r["value"] is None}


def extract(
    runs: dict[str, Path],
    corpus: Path = C.REPO / C.ARM_I_CORPUS,
    ids: dict[str, set[str]] | None = None,
    any_count: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Every finding line and every review of the named runs, and the counts.

    ``corpus`` is arm I's (its base, artefacts and R-PG-01's sheet); ``ids`` each role's rubric
    item ids, read from the run commit's rubrics when not given.
    """
    tally = K.tally_module()
    designs = Designs(corpus)
    untagged = missing_rows((corpus / "sources.json").read_bytes())
    if ids is None:
        ids = {role: rubric_ids(C.REPO, role) for role in C.RUBRIC_SHA256}
    keyed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    reviews: list[dict[str, Any]] = []
    for key in sorted(runs, key=lambda k: (int(k[1:]), C.ARMS.index(k[0]))):
        arm, r = key[0], int(key[1:])
        run = runs[key]
        figures = tally.tally(run, None, any_count)
        per = {p["artefact"]: p for p in figures["per_artefact"]}
        rows = C.read_jsonl(run / "results.jsonl")
        last = {
            side: {
                x["subtask_id"]: x
                for x in C.read_jsonl(log)
                if x.get("kind") in ("review_ran", "review_unavailable")
            }
            for side, log in (
                ("injected", run / "events.jsonl"),
                ("twin", run / "controls" / "events.jsonl"),
            )
        }
        for row in rows:
            artefact = row["artefact"]
            p = per[artefact]
            role = p["role"]
            for side, sid in (("injected", row["review_id"]), ("twin", row["control_id"])):
                line = last[side].get(sid)
                outcome = p["review"] if side == "injected" else p["twin_review"]
                cause = p["review_cause"] if side == "injected" else p["twin_review_cause"]
                reviews.append(
                    {
                        "round": r,
                        "arm": arm,
                        "side": side,
                        "artefact": artefact,
                        "role": role,
                        "outcome": outcome,
                        "cause": cause,
                        "named": p["named"] if side == "injected" else None,
                        "error_items": p["error_items"],
                    }
                )
                if line is None or line["kind"] != "review_ran":
                    continue
                for pos, it in rejecting_entries(line["result"]):
                    text = strip_ids(it.get("evidence") or "", ids[role])
                    locus = sorted(
                        [n, q] for (n, q) in designs.pairs(artefact) if names_pair(text, n, q)
                    )
                    cited_rows = set(ROW_ID.findall(text))
                    keyed.append(
                        (
                            (r, C.ARMS.index(arm), C.SIDES.index(side), artefact, pos),
                            {
                                "round": r,
                                "arm": arm,
                                "side": side,
                                "artefact": artefact,
                                "role": role,
                                "section": it.get("section"),
                                "item": it.get("item"),
                                "position": pos,
                                "review_outcome": outcome,
                                "text": text,
                                "locus": locus,
                                "error_item_line": it.get("item") in p["error_items"],
                                "tag_missing_row": bool(cited_rows & untagged),
                            },
                        )
                    )
    keyed.sort(key=lambda x: x[0])
    lines = [{"line_id": f"L{n:04d}", **rec} for n, (_, rec) in enumerate(keyed, 1)]
    counts = {
        "lines": len(lines),
        "reviews": len(reviews),
        "lines_by_review_outcome": dict(Counter(x["review_outcome"] for x in lines)),
        "lines_by_side": dict(Counter(x["side"] for x in lines)),
        "empty_locus": sum(1 for x in lines if not x["locus"]),
        "rows_without_a_value_in_r_pg_01s_sheet": len(untagged),
    }
    return lines, reviews, counts


def design_record(corpus: Path = C.REPO / C.ARM_I_CORPUS) -> dict[str, Any]:
    """Each artefact's version material for the packets, and its changed pairs."""
    d = Designs(corpus)
    return {
        "base": d.base,
        "artefacts": {
            a: {
                "role": d.artefacts[a]["assigned_role"],
                "injected": d.patch(a, "injected"),
                "twin": d.patch(a, "twin"),
                "changed": sorted([n, q] for n, q in d.changed(a)),
            }
            for a in sorted(d.artefacts)
        },
    }


def parse_runs(specs: list[str]) -> dict[str, Path]:
    """``I1=<run dir>`` (a review root after a comma is allowed and ignored)."""
    out = {}
    for spec in specs:
        key, _, rest = spec.partition("=")
        if key[:1] not in C.ARMS or key[1:] not in ("1", "2"):
            raise SystemExit(f"a run is named I1, F1, I2 or F2, not {key}")
        out[key] = Path(rest.split(",")[0]).resolve()
    return out


def main(argv: list[str] | None = None) -> int:
    """Write the lines, reviews and designs; print counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--any-count", action="store_true", help="invented fixtures only")
    args = parser.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True)
    lines, reviews, counts = extract(parse_runs(args.run), any_count=args.any_count)
    (out / "lines.jsonl").write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in lines))
    (out / "reviews.jsonl").write_text(
        "".join(json.dumps(x, sort_keys=True) + "\n" for x in reviews)
    )
    (out / "design.json").write_text(json.dumps(design_record(), indent=1, sort_keys=True))
    (out / "extract_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
