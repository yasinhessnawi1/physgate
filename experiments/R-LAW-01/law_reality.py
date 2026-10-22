"""R-LAW-01, CRITERIA.md §2.3: the reality adjudication, its two controls, and its scoring.

Usage (from the repository root):

    python -I experiments/R-LAW-01/law_reality.py packets <work dir> <out dir>
    python -I experiments/R-LAW-01/law_reality.py controls <work> <packets> <sessions> <out>
    python -I experiments/R-LAW-01/law_reality.py score <work> <packets> <sessions> <controls>
        <control sessions> <prior adjudication json>

- ``packets``: one packet per design version (a set, a pair, a side) over the measured lines, the
  lines of every run on it pooled, shuffled from line-id order with ``random.Random(37)`` and cut
  into consecutive packets of at most 12, labelled F1…Fn: the injected versions first
  (``injected.txt`` lists them, in run order), then the twin versions (``twin.txt``). Each packet
  is the prior adjudication's, with the full parts sheet.
- ``controls``: after the injected versions' verdicts exist: per injected version holding an
  eligible line (``true_flaw``, origin ``introduced``, every locus pair a changed pair), one drawn
  with ``random.Random(43)`` from line-id order, in a packet of its own built for the clean twin.
- ``score``: every line's verdict (first try if valid, else the retry), both bars, reliability,
  each flaw's reality, and the agreement with the prior adjudication on its lines, into
  ``reality.jsonl`` and ``reality_summary.json``. Prints counts of sessions and verdicts present
  only; the bars and every distribution are read by the tally, never printed here.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402
import law_packets as P  # noqa: E402
import law_verify as V  # noqa: E402

CAP = 12
SEED_PACKETS = 37
SEED_CONTROL = 43
BAR = 0.70
TRUE = "true_flaw"
ARM_RUN = {"paired": "a-fresh", "generalist": "b-fresh"}


def reality_packet(
    pid: str, role: str, texts: list[str], sd: X.SetData, pair: str, side: str
) -> str:
    """The prior adjudication's packet, word for word, with the full parts sheet at its end."""
    patch = sd.patch(pair, side)
    found = "\n".join(f"### F{i}\n\n{t}\n" for i, t in enumerate(texts, 1))
    body = [
        f"# Packet {pid}",
        "",
        "A proposed revision of a design graph for a small two-wheeled self-balancing robot (a "
        "stand-in design built only from the parts sheet below). Each node holds quantities as "
        "{value, unit, source}; a source `derived: [R1.02] * [R5.03]` is arithmetic over the "
        "parts-sheet rows it names. Numbers are written to three significant figures. The revision "
        'is a change to the graph alone: it wrote the nodes listed under "What the revision wrote" '
        "(each replaces the base node of the same id, or adds a node); every other node is as in "
        "the base.",
        "",
        f"A reviewer of the {role} domain rejected this revision with the findings below (the "
        "reviewer's own words; rule numbers are replaced by [rule]).",
        "",
        "## Findings",
        "",
        found,
        "## What the revision wrote",
        "",
        "```json",
        json.dumps(patch, indent=1, sort_keys=True),
        "```",
        "",
        "## The base design (before the revision), all nodes",
        "",
        "```json",
        json.dumps(sd.base, indent=None, separators=(",", ":"), sort_keys=True),
        "```",
    ]
    return "\n".join(body) + "\n" + V.SHEET_MARK + sd.sheet.decode()


def measured(work: Path) -> list[dict[str, Any]]:
    lines = X.read_jsonl(work / "lines.jsonl")
    sl = json.loads((work / "slice.json").read_text())
    in_slice = {(s, p) for s in X.SET_ORDER for p in sl["pairs"][s]}
    return [x for x in lines if (x["set"], x["pair"]) not in in_slice]


def build_packets(
    lines: list[dict[str, Any]], sets: dict[str, X.SetData], out: Path
) -> dict[str, Any]:
    by_id = {x["line_id"]: x for x in lines}
    rng = random.Random(SEED_PACKETS)
    out.mkdir(parents=True, exist_ok=False)
    versions = P.versions_of(lines)
    ordered = [v for v in versions if v[2] == "injected"] + [v for v in versions if v[2] == "twin"]
    key: dict[str, Any] = {}
    lists: dict[str, list[str]] = {"injected": [], "twin": []}
    n = 0
    for st, pair, side in ordered:
        ids = list(versions[(st, pair, side)])
        rng.shuffle(ids)
        sd = sets[st]
        role = sd.artefacts[pair]["assigned_role"]
        for chunk in P.cut(ids, CAP):
            n += 1
            pid = f"Q{n:04d}"
            text = reality_packet(pid, role, [by_id[i]["text"] for i in chunk], sd, pair, side)
            (out / f"{pid}.md").write_text(text)
            key[pid] = {
                "set": st,
                "pair": pair,
                "side": side,
                "control": False,
                "findings": {f"F{i}": lid for i, lid in enumerate(chunk, 1)},
            }
            lists[side].append(pid)
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    for side, ids in lists.items():
        (out / f"{side}.txt").write_text("".join(i + "\n" for i in ids))
    return key


def verdicts(
    packets: Path, sessions: Path, digest: str = X.PARTS_SHEET_SHA256
) -> dict[str, dict[str, Any]]:
    """Per line: verdict, origin and the try used ("none" with verdict "missing")."""
    key = json.loads((packets / "key.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for pid in sorted(key):
        if not (sessions / f"{pid}.try1.json").exists():
            continue
        forms, used = V.session_forms(packets, sessions, pid, "reality", digest)
        for fid, lid in key[pid]["findings"].items():
            f = forms[fid]
            out[lid] = {
                "packet": pid,
                "verdict": f["verdict"] if f else "missing",
                "origin": f["origin"] if f else None,
                "try": used[fid],
                "standin": V.standin_marked(sessions, pid),
            }
    return out


def _loc(x: dict[str, Any]) -> set[tuple[str, str]]:
    return {(n, q) for n, q in x["locus"]}


def eligible_control(x: dict[str, Any], v: dict[str, Any] | None, sd: X.SetData) -> bool:
    """An injected line judged true_flaw, origin introduced, whose every locus pair is changed
    (an empty locus is not eligible: it holds no changed pair)."""
    if x["side"] != "injected" or v is None:
        return False
    if v["verdict"] != TRUE or v["origin"] != "introduced":
        return False
    loc = _loc(x)
    return bool(loc) and loc <= sd.changed_pairs(x["pair"])


def build_controls(
    lines: list[dict[str, Any]],
    sets: dict[str, X.SetData],
    got: dict[str, dict[str, Any]],
    first_number: int,
    out: Path,
) -> dict[str, Any]:
    rng = random.Random(SEED_CONTROL)
    out.mkdir(parents=True, exist_ok=False)
    key: dict[str, Any] = {}
    n = first_number - 1
    by_id = {x["line_id"]: x for x in lines}
    for (st, pair, side), ids in P.versions_of(lines).items():
        if side != "injected":
            continue
        elig = [i for i in ids if eligible_control(by_id[i], got.get(i), sets[st])]
        if not elig:
            continue
        lid = rng.choice(elig)
        n += 1
        pid = f"Q{n:04d}"
        role = sets[st].artefacts[pair]["assigned_role"]
        text = reality_packet(pid, role, [by_id[lid]["text"]], sets[st], pair, "twin")
        (out / f"{pid}.md").write_text(text)
        key[pid] = {
            "set": st,
            "pair": pair,
            "side": "twin",
            "control": True,
            "findings": {"F1": lid},
        }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    return key


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa of two raters' labels."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in ca.keys() | cb.keys()) / n / n
    return None if pe == 1 else (po - pe) / (1 - pe)


def prior_agreement(
    prior: dict[str, Any], lines: list[dict[str, Any]], got: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Each prior finding matched to its line by (pair, side, run, item), in order; the two
    verdicts compared where the line was adjudicated here."""
    pool: dict[tuple[str, str, str, str], list[str]] = {}
    for x in lines:
        if x["set"] == "fresh":
            pool.setdefault((x["pair"], x["side"], x["run"], x["item"]), []).append(x["line_id"])
    used: Counter[tuple[str, str, str, str]] = Counter()
    pairs, unmatched, not_here = [], 0, 0
    for p in prior["packets"].values():
        for f in p["findings"]:
            k = (p["artefact"], p["side"], ARM_RUN[f["arm"]], f["item"])
            cand = pool.get(k, [])
            if used[k] >= len(cand):
                unmatched += 1
                continue
            lid = cand[used[k]]
            used[k] += 1
            v = got.get(lid)
            if v is None or v["verdict"] == "missing":
                not_here += 1
                continue
            pairs.append((f["verdict"], v["verdict"]))
    return {
        "prior_findings": sum(len(p["findings"]) for p in prior["packets"].values()),
        "unmatched": unmatched,
        "not_adjudicated_here": not_here,
        "compared": len(pairs),
        "table": dict(Counter(f"{a}|{b}" for a, b in pairs)),
        "agree": sum(a == b for a, b in pairs),
        "kappa": kappa(pairs),
    }


def score(
    work: Path,
    packets: Path,
    sessions: Path,
    controls: Path,
    control_sessions: Path,
    prior_path: Path,
    sets: dict[str, X.SetData],
    prior_digest: str | None,
    digest: str = X.PARTS_SHEET_SHA256,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if prior_digest is not None and X.sha256_file(prior_path) != prior_digest:
        raise X.Refused("the prior adjudication's output is not at its recorded digest")
    lines = measured(work)
    by_id = {x["line_id"]: x for x in lines}
    got = verdicts(packets, sessions, digest)
    ctl = verdicts(controls, control_sessions, digest) if (controls / "key.json").exists() else {}
    # the calibration control
    inj_versions: dict[tuple[str, str], list[str]] = {}
    for x in lines:
        if x["side"] == "injected":
            inj_versions.setdefault((x["set"], x["pair"]), []).append(x["line_id"])
    holding = calibrated = 0
    for (st, pair), ids in inj_versions.items():
        ch = sets[st].changed_pairs(pair)
        on_change = [i for i in ids if _loc(by_id[i]) & ch]
        if not on_change:
            continue
        holding += 1
        calibrated += any(
            got.get(i, {}).get("verdict") == TRUE
            and got.get(i, {}).get("origin") in ("introduced", "both")
            for i in on_change
        )
    rejected = sum(1 for v in ctl.values() if v["verdict"] == "not_a_flaw")
    cal_ok = holding > 0 and calibrated / holding >= BAR
    rej_ok = len(ctl) > 0 and rejected / len(ctl) >= BAR
    flaws = X.read_jsonl(work / "flaws.jsonl")
    measured_ids = set(by_id)
    flaw_reality = {}
    for f in flaws:
        mine = [i for i in f["lines"] if i in measured_ids]
        if not mine:
            continue
        vs = [got.get(i, {}).get("verdict", "missing") for i in mine]
        if TRUE in vs:
            flaw_reality[f["flaw_id"]] = "real"
        elif all(v == "not_a_flaw" for v in vs):
            flaw_reality[f["flaw_id"]] = "not_real"
        else:
            flaw_reality[f["flaw_id"]] = "undecided"
    prior = json.loads(prior_path.read_text())
    rows = [
        {"line_id": lid, **got.get(lid, {"verdict": "missing", "origin": None, "try": "none"})}
        for lid in sorted(by_id)
    ]
    summary = {
        "lines": len(rows),
        "verdicts_by_side": {
            s: dict(Counter(r["verdict"] for r in rows if by_id[r["line_id"]]["side"] == s))
            for s in X.SIDE_ORDER
        },
        "calibration": {"holding": holding, "calibrated": calibrated, "bar_met": cal_ok},
        "rejection": {"controls": len(ctl), "not_a_flaw": rejected, "bar_met": rej_ok},
        "reliable": cal_ok and rej_ok,
        "flaw_reality": flaw_reality,
        "prior_agreement": prior_agreement(prior, lines, got),
        "retries_used": sum(1 for r in rows if r.get("try") == "try2"),
        "standin": any(r.get("standin") for r in rows),
        "control_lines": {lid: v for lid, v in ctl.items()},
    }
    return rows, summary


def main(argv: list[str]) -> int:
    try:
        sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
        if argv[:1] == ["packets"] and len(argv) == 3:
            key = build_packets(measured(Path(argv[1])), sets, Path(argv[2]))
            print(
                json.dumps(
                    {"packets": len(key), "lines": sum(len(k["findings"]) for k in key.values())}
                )
            )
            return 0
        if argv[:1] == ["controls"] and len(argv) == 5:
            work, packets, sessions, out = (Path(a) for a in argv[1:])
            got = verdicts(packets, sessions)
            first = len(json.loads((packets / "key.json").read_text())) + 1
            key = build_controls(measured(work), sets, got, first, out)
            print(json.dumps({"control_packets": len(key)}))
            return 0
        if argv[:1] == ["score"] and len(argv) == 7:
            work = Path(argv[1])
            digests = json.loads(X.INPUTS.read_text())
            rows, summary = score(
                work,
                Path(argv[2]),
                Path(argv[3]),
                Path(argv[4]),
                Path(argv[5]),
                Path(argv[6]),
                sets,
                digests["prior_adjudication"],
            )
            X.write_jsonl(work / "reality.jsonl", rows)
            (work / "reality_summary.json").write_text(
                json.dumps(summary, indent=1, sort_keys=True)
            )
            print(
                json.dumps(
                    {
                        "lines": summary["lines"],
                        "with_verdict": sum(1 for r in rows if r["verdict"] != "missing"),
                        "controls": summary["rejection"]["controls"],
                        "retries_used": summary["retries_used"],
                    }
                )
            )
            return 0
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
