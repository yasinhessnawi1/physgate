"""R-LAW-01, CRITERIA.md §3 and §5.6: the gate re-run on every design version, and the G match.

Usage (from the repository root, with the project environment):

    uv run python -I experiments/R-LAW-01/law_regate.py gate <work dir> <a-fresh run dir>
    uv run python -I experiments/R-LAW-01/law_regate.py match <work dir>

- ``gate``: refuses unless this checkout's gate is the pinned tree, its bounds tables and unit
  spelling the pinned blobs, and its catalogue the pinned digest. Gates every design version of
  both sets (the base with that side's patch, under the instrument's subtask ids and scopes,
  which end in the integration call), writes ``regate.jsonl``, and compares the fresh set's
  records with the ``a-fresh`` run's gate lines byte for byte (each parsed and dumped as the
  instrument's own model). Exit 1 if anything differs: a deviation (§12).
- ``match``: §5.6's match of each line against the failing records of its version, using the
  deciding form (``law_verify.deciding_form``) from ``codes.jsonl``; writes ``matches.jsonl``.

Prints counts only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402

GATE_TREE = "1e169aac5679d743d4b0585090a45bcd06ea1a63"
BLOBS = {
    "knowledge/electrical/bounds.toml": "3bbdc33b7e4ab1df2b2a32d48003fbffa876ebc0",
    "knowledge/cross/bounds.toml": "b68fd58f31a9469124d4accc26a8a9c6f1dde7cf",
    "src/physgate/unit_spelling.py": "eaa4ce697092d27545a19c87c6d92fc6f1e966fc",
}
CATALOGUE_SHA256 = "9bf73a7dfd74f49fc0b094a45df9564fdff5de129e170d06ce8d54851a841c88"
CHECKS = {
    "units": 1,
    "magnitude": 2,
    "equilibrium": 3,
    "power": 4,
    "conservation": 5,
    "thermal": 6,
    "propagation": 7,
}


def _catalogue() -> tuple[frozenset[str], tuple[str, ...]]:
    from physgate.gate.catalogue import QUANTITIES, SUFFIXES

    return frozenset(QUANTITIES), tuple(s.suffix for s in SUFFIXES)


def appendix_c() -> dict[str, tuple[int, Callable[[str], bool], tuple[str, ...]]]:
    """Appendix C: each gate relation's check, a membership test for its quantity set, and the
    names whose whole-word presence in a record selects it (empty for checks 1, 2 and 7)."""
    names, suffixes = _catalogue()

    def fixed(*qs: str) -> tuple[Callable[[str], bool], tuple[str, ...]]:
        s = frozenset(qs)
        return (lambda q: q in s), tuple(qs)

    mount = fixed(
        "support_position",
        "mount_position",
        "reaction_force",
        "reaction_moment",
        "load_force",
        "mass",
    )
    power = fixed(
        "power_draw", "power_supply", "energy_capacity", "max_discharge_power", "rated_output_power"
    )
    return {
        "units_kind": (1, lambda q: q in names or q.endswith(suffixes), ()),
        "magnitude_range": (2, lambda q: q == "sample_rate", ()),
        "mount_balance": (3, *mount),
        "forces_only": (3, *mount),
        "torque_unit": (
            3,
            *fixed("torque_peak", "reaction_moment", "gear_ratio", "external_gear_ratio"),
        ),
        "carrier": (3, *fixed("supported_mass", "mass")),
        "power_budget": (4, *power),
        "supply_covered": (4, *power),
        "source_rating": (4, *power),
        "current_limit": (4, *fixed("stall_current", "current_limit")),
        "discharge_rate": (4, *fixed("max_discharge_power", "energy_capacity")),
        "mass_sum": (5, *fixed("mass")),
        "energy_balance": (5, *fixed("input_power", "output_power", "heat_dissipation")),
        "junction_limit": (
            6,
            *fixed(
                "ambient_temperature", "thermal_resistance", "heat_dissipation", "max_temperature"
            ),
        ),
        "heat_budget": (6, *fixed("heat_dissipation", "heat_rejection_capacity")),
        "propagation": (7, lambda q: q in names, ()),
    }


RELATION_NAMES = (
    "units_kind",
    "magnitude_range",
    "mount_balance",
    "forces_only",
    "torque_unit",
    "carrier",
    "power_budget",
    "supply_covered",
    "source_rating",
    "current_limit",
    "discharge_rate",
    "mass_sum",
    "energy_balance",
    "junction_limit",
    "heat_budget",
    "propagation",
)


def word_in(word: str, text: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


# ---------------------------------------------------------------- the pins


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def check_pins(repo: Path, tree: str = GATE_TREE, catalogue: str = CATALOGUE_SHA256) -> None:
    """Refuse unless the working copy's gate, bounds, spelling and catalogue are §3's."""
    if _git(repo, "rev-parse", "HEAD:src/physgate/gate") != tree:
        raise X.Refused("the gate is not the pinned tree")
    paths = ["src/physgate/gate", *BLOBS]
    if _git(repo, "status", "--porcelain", "--", *paths):
        raise X.Refused("the gate or its tables differ from the commit")
    for path, blob in BLOBS.items():
        if _git(repo, "rev-parse", f"HEAD:{path}") != blob:
            raise X.Refused(f"{path} is not the pinned blob")
    from physgate.gate.catalogue import catalogue_digest

    if catalogue_digest() != catalogue:
        raise X.Refused("the catalogue is not the pinned digest")


# ---------------------------------------------------------------- the gate


def canonical(result: dict[str, Any]) -> str:
    """A gate result as the instrument's model dumps it, keys sorted."""
    from physgate.orchestrator.protocols import GateResult

    parsed = GateResult.model_validate_json(json.dumps(result))
    return json.dumps(parsed.model_dump(mode="json"), sort_keys=True)


def gate_set(set_root: Path, seed: int) -> list[dict[str, Any]]:
    """Every design version of one set, gated as the instrument gated it."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate, control_id, review_id
    from physgate.gate.runner import PhysicsGate

    corpus = load_corpus(set_root.resolve())
    gate = PhysicsGate()
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for a in corpus.artefacts:
            for side, sid, patch in (
                ("injected", review_id(seed, a.id), a.injected),
                ("twin", control_id(seed, a.id), a.clean),
            ):
                res = _gate(gate, materialise(corpus.base, patch, Path(tmp) / sid), sid)
                out.append(
                    {
                        "pair": a.id,
                        "side": side,
                        "subtask_id": sid,
                        "result": res.model_dump(mode="json"),
                    }
                )
    return out


def compare(records: list[dict[str, Any]], run: X.RunData) -> dict[str, Any]:
    """The fresh set's records against the run's last gate line per subtask, byte for byte."""
    first = {**run.gate["injected"], **run.gate["twin"]}
    differ = missing = 0
    for r in records:
        line = first.get(r["subtask_id"])
        if line is None:
            missing += 1
            continue
        differ += canonical(line) != json.dumps(r["result"], sort_keys=True)
    return {
        "compared": len(records),
        "missing": missing,
        "differ": differ,
        "holds": differ == 0 and missing == 0 and bool(records),
    }


# ---------------------------------------------------------------- the match


def record_nodes(record: dict[str, Any], node_ids: set[str]) -> set[str]:
    """Its node, its module, and every string in its details equal to a node id of the version."""
    out = {x for x in (record.get("node"), record.get("module")) if x}

    def walk(v: Any) -> None:  # noqa: ANN401
        if isinstance(v, str) and v in node_ids:
            out.add(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list | tuple):
            for x in v:
                walk(x)

    walk(record.get("details"))
    return out


def record_relations(record: dict[str, Any], table: dict[str, Any]) -> list[str]:
    k = record["check"]
    rows = [r for r, (c, _, _) in table.items() if c == k]
    if k in (1, 2, 7):
        return rows
    dumped = json.dumps(record, sort_keys=True)
    return [r for r in rows if any(word_in(q, dumped) for q in table[r][2])]


def in_q(k: int, q: str, table: dict[str, Any]) -> bool:
    return any(member(q) for (c, member, _) in table.values() if c == k)


def matches(
    line: dict[str, Any],
    form: dict[str, Any] | None,
    records: list[dict[str, Any]],
    node_ids: set[str],
    table: dict[str, Any],
) -> list[dict[str, Any]]:
    """§5.6: the failing records of the line's version that match it under its deciding form."""
    if form is None:
        return []
    inputs = form.get("inputs") or []
    if not inputs:
        return []
    found = []
    for rec in records:
        if rec.get("outcome") != "fail":
            continue
        k = rec["check"]
        nodes = record_nodes(rec, node_ids)
        hit = False
        for n, q in line["locus"]:
            if n in nodes and in_q(k, q, table):
                if k in (1, 7) and not word_in(q, rec.get("message") or ""):
                    continue
                hit = True
                break
        if not hit:
            continue
        rels = record_relations(rec, table)
        if form.get("gate_relation") in rels:
            ok = True
        else:
            qs = [i.get("quantity") for i in inputs]
            ok = all(isinstance(q, str) for q in qs) and any(
                all(table[r][1](q) for q in qs) for r in rels
            )
        if ok:
            found.append(
                {"check": k, "name": rec["name"], "scope": rec["scope"], "relations": rels}
            )
    return found


def match_all(
    lines: list[dict[str, Any]],
    forms: dict[str, dict[str, Any] | None],
    regate: list[dict[str, Any]],
    sets: dict[str, X.SetData],
) -> list[dict[str, Any]]:
    table = appendix_c()
    by_version = {(r["set"], r["pair"], r["side"]): r["result"]["checks"] for r in regate}
    out = []
    for line in lines:
        v = (line["set"], line["pair"], line["side"])
        node_ids = set(sets[line["set"]].version(line["pair"], line["side"]))
        found = matches(line, forms.get(line["line_id"]), by_version[v], node_ids, table)
        out.append({"line_id": line["line_id"], "matched": bool(found), "records": found})
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] not in ("gate", "match"):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    work = Path(argv[1])
    try:
        if argv[0] == "gate":
            if len(argv) != 3:
                raise X.Refused("gate needs the a-fresh run dir")
            check_pins(X.REPO)
            digests = json.loads(X.INPUTS.read_text())
            pin = next(p for p in X.RUNS if p.label == "a-fresh")
            run = X.load_run(X.FROZEN, pin, Path(argv[2]), digests)
            rows: list[dict[str, Any]] = []
            out: dict[str, Any] = {}
            for name in X.SET_ORDER:
                sp = X.SETS[name]
                X.load_set(X.FROZEN, name)
                recs = gate_set(X.REPO / sp.path, sp.seed)
                rows += [{"set": name, **r} for r in recs]
                out[name] = {"versions": len(recs)}
            out["fresh_against_a_fresh"] = compare([r for r in rows if r["set"] == "fresh"], run)
            X.write_jsonl(work / "regate.jsonl", rows)
            (work / "regate_check.json").write_text(json.dumps(out, indent=1, sort_keys=True))
            print(json.dumps(out, sort_keys=True))
            return 0 if out["fresh_against_a_fresh"]["holds"] else 1
        import law_verify as V

        lines = [x for x in X.read_jsonl(work / "lines.jsonl")]
        codes = X.read_jsonl(work / "codes.jsonl")
        forms = V.deciding_forms(codes)
        sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
        m = match_all(lines, forms, X.read_jsonl(work / "regate.jsonl"), sets)
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    X.write_jsonl(work / "matches.jsonl", m)
    print(json.dumps({"lines": len(m), "with_deciding_form": sum(1 for v in forms.values() if v)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
