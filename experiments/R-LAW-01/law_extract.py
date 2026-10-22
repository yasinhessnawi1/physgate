"""R-LAW-01, CRITERIA.md §2.1, §2.2 and §2.4: the finding lines, read from the allowlisted runs.

Usage (from the repository root):

    python -I experiments/R-LAW-01/law_extract.py digests --run <label>=<dir> ... --prior <file>
    python -I experiments/R-LAW-01/law_extract.py lines --run <label>=<dir> ... --out <dir>

- ``digests``: the "Inputs filled" fact. Writes ``inputs/digests.json``: the sha256 of the four
  files of every run of §2.1, of both manifests (checked against §2.1 first) and of the prior
  adjudication's output. Run once, before any script reads a finding line.
- ``lines``: refuses any run or set whose digest differs from ``inputs/digests.json`` or §2.1,
  takes the last review line per subtask, and writes ``lines.jsonl`` (line id, set, run, reviewer
  kind, side, pair, role, error class, section, item, position, stripped text, locus) and
  ``extract_counts.json``. Prints counts only, never a line's text.

The two corpora are read from their paths in this checkout, the only two §2.1 names. Every other
module of this experiment reads the sets and the lines through this one.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
INPUTS = HERE / "inputs" / "digests.json"

SET_ORDER = ("practice", "fresh")
SIDE_ORDER = ("injected", "twin")
SECTIONS = ("acceptance_criteria", "domain_standards", "antipatterns", "reward_hacking")
REJECTING = ("unmet", "confirmed")
RUN_FILES = ("results.jsonl", "events.jsonl", "controls/events.jsonl", "instrument.json")
PARTS_SHEET = "parts_sheet.md"
PARTS_SHEET_SHA256 = "29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f"
ROLES = ("control", "electrical", "firmware", "mechanical")


class Refused(Exception):
    """An input is not one §2.1 allows, or not at the digest §2.4 recorded."""


@dataclass(frozen=True)
class SetPin:
    """One corpus of §2.1: where it is in this checkout, its manifest digest, its seed."""

    name: str
    path: str
    manifest: str
    seed: int


@dataclass(frozen=True)
class RunPin:
    """One review run of §2.1, in the table's order."""

    label: str
    set: str
    commit: str
    run_id: str | None
    kind: str


SETS = {
    "practice": SetPin(
        "practice",
        "experiments/R-PG-02/practice/corpus-v1",
        "ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0",
        11,
    ),
    "fresh": SetPin(
        "fresh",
        "corpora/injected-errors/fresh-v1",
        "e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c",
        13,
    ),
}
RUNS = (
    RunPin("practice-0", "practice", "82cbf3b", "practice-it0", "paired"),
    RunPin("practice-1", "practice", "7f39327", "practice-r1", "paired"),
    RunPin("practice-2", "practice", "48929eb", "practice-r2", "paired"),
    RunPin("a-fresh", "fresh", "0936f1f", "rp2-2-a-fresh", "paired"),
    RunPin("b-fresh", "fresh", "0936f1f", "rp2-2-b-fresh", "generalist"),
    RunPin("repeat-K", "fresh", "eae78c0", None, "paired"),
    RunPin("round-1", "fresh", "8c51f48", None, "paired"),
)


@dataclass(frozen=True)
class Pins:
    """What the scripts hold their inputs to; the CLI uses only :data:`FROZEN`."""

    sets: dict[str, SetPin]
    runs: tuple[RunPin, ...]
    parts_sheet: str
    repo: Path


FROZEN = Pins(SETS, RUNS, PARTS_SHEET_SHA256, REPO)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    Path(path).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


# ---------------------------------------------------------------- a set


@dataclass
class SetData:
    """One corpus, held to its manifest: base nodes, artefacts and the full parts sheet."""

    name: str
    seed: int
    base: list[dict[str, Any]]
    artefacts: dict[str, dict[str, Any]]
    sheet: bytes
    _base_map: dict[tuple[str, str], tuple[Any, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._base_map = {
            (n["id"], q): (v.get("value"), v.get("unit"))
            for n in self.base
            for q, v in (n.get("quantities") or {}).items()
        }

    def patch(self, pair: str, side: str) -> list[dict[str, Any]]:
        a = self.artefacts[pair]
        return list((a["injected"] if side == "injected" else a["clean"])["nodes"])

    def version(self, pair: str, side: str) -> dict[str, dict[str, Any]]:
        """The design version: the base with the side's patch applied (a node replaced or added)."""
        nodes = {n["id"]: n for n in self.base}
        for n in self.patch(pair, side):
            nodes[n["id"]] = n
        return nodes

    def pair_quantities(self, pair: str) -> set[tuple[str, str]]:
        """Every (node, quantity) in the base, the clean patch and the injected patch."""
        out: set[tuple[str, str]] = set()
        for n in [*self.base, *self.patch(pair, "twin"), *self.patch(pair, "injected")]:
            for q in n.get("quantities") or {}:
                out.add((n["id"], q))
        return out

    def changed_pairs(self, pair: str) -> set[tuple[str, str]]:
        """§2.3: a (node, quantity) whose value or unit differs between the two patches, or that
        one patch has and the other lacks; for a propagation item, every quantity of the edge's
        two end nodes."""
        clean = {
            (n["id"], q): (v.get("value"), v.get("unit"))
            for n in self.patch(pair, "twin")
            for q, v in (n.get("quantities") or {}).items()
        }
        inj = {
            (n["id"], q): (v.get("value"), v.get("unit"))
            for n in self.patch(pair, "injected")
            for q, v in (n.get("quantities") or {}).items()
        }
        out = {k for k in clean.keys() | inj.keys() if clean.get(k) != inj.get(k)}
        edge = self.artefacts[pair].get("edge")
        if edge:
            ends = {edge["source"], edge["target"]}
            out |= {(n, q) for (n, q) in self.pair_quantities(pair) if n in ends}
        return out

    def unchanged(self, pair: str, locus: frozenset[tuple[str, str]]) -> bool:
        """§2.2 step D: the base holds every locus pair and neither patch writes its node with a
        different value or unit (a written node that lacks the quantity changes it)."""
        for n, q in locus:
            if (n, q) not in self._base_map:
                return False
            for side in SIDE_ORDER:
                for node in self.patch(pair, side):
                    if node["id"] == n:
                        v = (node.get("quantities") or {}).get(q)
                        if v is None or (v.get("value"), v.get("unit")) != self._base_map[(n, q)]:
                            return False
        return True


def load_set(pins: Pins, name: str, root: Path | None = None) -> SetData:
    """A set of §2.1, refused unless its manifest and every file read match their digests."""
    pin = pins.sets[name]
    root = Path(root) if root is not None else pins.repo / pin.path
    manifest_path = root / "MANIFEST.json"
    if sha256_file(manifest_path) != pin.manifest:
        raise Refused(f"set {name}: the manifest is not the one §2.1 names")
    files = json.loads(manifest_path.read_text())["files"]

    def held(rel: str) -> bytes:
        data = (root / rel).read_bytes()
        if files.get(rel) != sha256_bytes(data):
            raise Refused(f"set {name}: {rel} differs from its manifest")
        return data

    base = json.loads(held("base.json"))["nodes"]
    arts = {}
    for rel in sorted(r for r in files if r.startswith("artefacts/") and r.endswith(".json")):
        a = json.loads(held(rel))
        arts[a["id"]] = a
    sheet = held(PARTS_SHEET)
    if sha256_bytes(sheet) != pins.parts_sheet:
        raise Refused(f"set {name}: the parts sheet is not the one §2.5 names")
    return SetData(name, pin.seed, base, arts, sheet)


# ---------------------------------------------------------------- a run


@dataclass
class RunData:
    """One run of §2.1: its rows, the last review line per subtask on each side, its kind."""

    pin: RunPin
    rows: list[dict[str, Any]]
    last: dict[str, dict[str, dict[str, Any]]]
    gate: dict[str, dict[str, dict[str, Any]]]
    instrument: dict[str, Any]


def _last_lines(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    review: dict[str, dict[str, Any]] = {}
    gate: dict[str, dict[str, Any]] = {}
    for e in read_jsonl(path):
        if e.get("kind") in ("review_ran", "review_unavailable"):
            review[e["subtask_id"]] = e
        elif e.get("kind") == "gate_ran":
            gate[e["subtask_id"]] = e["result"]
    return review, gate


def run_digests(run_dir: Path) -> dict[str, str]:
    return {f: sha256_file(Path(run_dir) / f) for f in RUN_FILES}


def load_run(pins: Pins, pin: RunPin, run_dir: Path, digests: dict[str, Any]) -> RunData:
    """A run of §2.1, refused unless its four files match ``digests`` and its instrument the pin."""
    run_dir = Path(run_dir)
    want = digests.get("runs", {}).get(pin.label)
    if want is None:
        raise Refused(f"run {pin.label}: no digest recorded")
    have = run_digests(run_dir)
    if have != want:
        raise Refused(f"run {pin.label}: a file differs from its recorded digest")
    ins = json.loads((run_dir / "instrument.json").read_text())
    if ins.get("corpus_manifest_sha256") != pins.sets[pin.set].manifest:
        raise Refused(f"run {pin.label}: its corpus is not {pin.set}")
    if ins.get("reviewer_kind", "paired") != pin.kind:
        raise Refused(f"run {pin.label}: reviewer kind is not {pin.kind}")
    if pin.run_id is not None and ins.get("run_id") != pin.run_id:
        raise Refused(f"run {pin.label}: run id is not {pin.run_id}")
    if ins.get("seed") != pins.sets[pin.set].seed:
        raise Refused(f"run {pin.label}: seed is not {pins.sets[pin.set].seed}")
    inj, inj_gate = _last_lines(run_dir / "events.jsonl")
    tw, tw_gate = _last_lines(run_dir / "controls" / "events.jsonl")
    return RunData(
        pin,
        read_jsonl(run_dir / "results.jsonl"),
        {"injected": inj, "twin": tw},
        {"injected": inj_gate, "twin": tw_gate},
        ins,
    )


# ---------------------------------------------------------------- the text and the locus


ITEM_LINE = re.compile(r"^- \*\*(?P<id>[A-Z]{1,2}-?[0-9]+)\.")


def rubric_ids_from(text: str) -> set[str]:
    """The item ids a rubric file defines (the prior adjudication's item-line pattern)."""
    return {m.group("id") for line in text.splitlines() if (m := ITEM_LINE.match(line))}


_RUBRICS: dict[tuple[Path, str, str], set[str]] = {}


def rubric_ids(repo: Path, commit: str, role: str) -> set[str]:
    """The role's rubric item ids at the run's commit."""
    key = (repo, commit, role)
    if key not in _RUBRICS:
        done = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:knowledge/reviewers/{role}/rubric.md"],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            raise Refused(f"no {role} rubric at {commit}")
        _RUBRICS[key] = rubric_ids_from(done.stdout)
    return _RUBRICS[key]


def strip_ids(text: str, ids: set[str]) -> str:
    """Every rubric item id becomes ``[rule]`` (the prior adjudication's stripping rule)."""
    for i in sorted(ids, key=len, reverse=True):
        text = re.sub(rf"(?<![\w.-]){re.escape(i)}(?![\w]|\.\d)", "[rule]", text)
    return text


def names_pair(text: str, node: str, quantity: str) -> bool:
    """R-PG-02's frozen rule: the quantity as a word, and the node or its name after the dot."""
    low = text.casefold()
    if not re.search(rf"\b{re.escape(quantity.casefold())}\b", low):
        return False
    short = node.split(".", 1)[1] if "." in node else node
    return node.casefold() in low or bool(re.search(rf"\b{re.escape(short.casefold())}\b", low))


def locus_of(text: str, quantities: set[tuple[str, str]]) -> list[list[str]]:
    return sorted([n, q] for (n, q) in quantities if names_pair(text, n, q))


# ---------------------------------------------------------------- the lines


def rejecting_entries(result: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """§2.2: every ``unmet`` or ``confirmed`` item, plus the failing item's entry if not among
    them; each with its position in ``result.items``."""
    items = result.get("items") or []
    out = [(i, it) for i, it in enumerate(items) if it["result"] in REJECTING]
    fi = result.get("failing_item")
    if fi and fi not in {it["item"] for _, it in out}:
        out += [(i, it) for i, it in enumerate(items) if it["item"] == fi]
    return sorted(out, key=lambda x: x[0])


def extract(
    pins: Pins, sets: dict[str, SetData], runs: dict[str, RunData]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every finding line of §2.2, numbered L0001… in §2.2's order, and the counts."""
    rows: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    counts: dict[str, Any] = {"per_source": {}, "excluded": {}, "reviews_with_lines": 0}
    verdicts: Counter[str] = Counter()
    run_rank = {p.label: i for i, p in enumerate(pins.runs)}
    for pin in pins.runs:
        run, sd = runs[pin.label], sets[pin.set]
        per_side: Counter[str] = Counter()
        excl: Counter[str] = Counter()
        for row in run.rows:
            pair = row["artefact"]
            art = sd.artefacts[pair]
            role = art["assigned_role"]
            quantities = sd.pair_quantities(pair)
            ids = rubric_ids(pins.repo, pin.commit, role)
            for side, sid in (("injected", row["review_id"]), ("twin", row["control_id"])):
                line = run.last[side].get(sid)
                if line is None or line["kind"] != "review_ran":
                    continue
                res = line["result"]
                excl["criteria"] += len(res.get("criteria") or [])
                excl["spec_defects"] += len(res.get("spec_defects") or [])
                excl["indicators"] += len(res.get("indicators") or [])
                excl["finding"] += int(bool(res.get("finding")))
                excl["subject"] += int(bool(res.get("subject")))
                entries = rejecting_entries(res)
                if entries:
                    counts["reviews_with_lines"] += 1
                    verdicts[res.get("verdict", "?")] += 1
                for pos, it in entries:
                    text = strip_ids(it.get("evidence") or "", ids)
                    rec = {
                        "set": pin.set,
                        "run": pin.label,
                        "kind": pin.kind,
                        "side": side,
                        "pair": pair,
                        "role": role,
                        "error_class": art["error_class"],
                        "section": it["section"],
                        "item": it["item"],
                        "position": pos,
                        "subtask_id": sid,
                        "text": text,
                        "locus": locus_of(text, quantities),
                        "locus_raw_differs": locus_of(it.get("evidence") or "", quantities)
                        != locus_of(text, quantities),
                    }
                    key = (
                        SET_ORDER.index(pin.set),
                        run_rank[pin.label],
                        SIDE_ORDER.index(side),
                        pair,
                        pos,
                    )
                    rows.append((key, rec))
                    per_side[side] += 1
        counts["per_source"][pin.label] = {**dict(per_side), "total": sum(per_side.values())}
        counts["excluded"][pin.label] = dict(excl)
    rows.sort(key=lambda x: x[0])
    lines = []
    for n, (_, rec) in enumerate(rows, 1):
        lines.append({"line_id": f"L{n:04d}", **rec})
    counts["lines"] = len(lines)
    counts["review_verdicts"] = dict(verdicts)
    counts["by_section"] = dict(Counter(x["section"] for x in lines))
    counts["by_set_side"] = {
        s: dict(Counter(x["side"] for x in lines if x["set"] == s)) for s in SET_ORDER
    }
    counts["locus_raw_vs_stripped_differs"] = sum(x.pop("locus_raw_differs") for x in lines)
    counts["empty_locus"] = sum(1 for x in lines if not x["locus"])
    return lines, counts


# ---------------------------------------------------------------- the CLI


def _run_args(argv: list[str]) -> dict[str, Path]:
    out = {}
    for i, a in enumerate(argv):
        if a == "--run":
            label, _, path = argv[i + 1].partition("=")
            out[label] = Path(path).expanduser().resolve()
    return out


def _opt(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def load_all(
    pins: Pins, run_dirs: dict[str, Path], digests: dict[str, Any]
) -> tuple[dict[str, SetData], dict[str, RunData]]:
    """Both sets and all seven runs, each refused unless held to its pin; nothing else."""
    if set(run_dirs) != {p.label for p in pins.runs}:
        raise Refused("the runs given are not exactly the seven of §2.1")
    for name, pin in pins.sets.items():
        if digests.get("manifests", {}).get(name) != pin.manifest:
            raise Refused(f"the recorded manifest digest of {name} is not §2.1's")
    sets = {name: load_set(pins, name) for name in pins.sets}
    runs = {p.label: load_run(pins, p, run_dirs[p.label], digests) for p in pins.runs}
    return sets, runs


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("digests", "lines"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    run_dirs = _run_args(argv)
    try:
        if argv[0] == "digests":
            prior = _opt(argv, "--prior")
            if prior is None or set(run_dirs) != {p.label for p in RUNS}:
                raise Refused("digests needs all seven runs and --prior")
            if INPUTS.exists():
                raise Refused("inputs/digests.json exists; the inputs are filled once")
            for name, pin in SETS.items():
                if sha256_file(REPO / pin.path / "MANIFEST.json") != pin.manifest:
                    raise Refused(f"set {name}: the manifest is not the one §2.1 names")
            out = {
                "runs": {p.label: run_digests(run_dirs[p.label]) for p in RUNS},
                "run_ids": {
                    p.label: json.loads((run_dirs[p.label] / "instrument.json").read_text())[
                        "run_id"
                    ]
                    for p in RUNS
                },
                "manifests": {n: p.manifest for n, p in SETS.items()},
                "parts_sheet": PARTS_SHEET_SHA256,
                "prior_adjudication": sha256_file(Path(prior).expanduser()),
            }
            INPUTS.parent.mkdir(exist_ok=True)
            INPUTS.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
            print(json.dumps({"written": str(INPUTS.relative_to(REPO)), "runs": len(out["runs"])}))
            return 0
        out_dir = Path(_opt(argv, "--out") or "")
        digests = json.loads(INPUTS.read_text())
        sets, runs = load_all(FROZEN, run_dirs, digests)
        lines, counts = extract(FROZEN, sets, runs)
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "lines.jsonl", lines)
    (out_dir / "extract_counts.json").write_text(json.dumps(counts, indent=1, sort_keys=True))
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
