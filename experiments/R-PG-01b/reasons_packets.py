"""R-PG-01b, CRITERIA.md §6: the reality packets, both controls' packets, and the pinned prompt.

Usage, in the run checkout::

    reasons_packets.py prompts <out dir>
    reasons_packets.py packets <work dir> <out dir>
    reasons_packets.py controls <work dir> <packets dir> <sessions dir> <out dir>
    reasons_packets.py blind <work dir> <packets dir>

- ``prompts``: R-LAW-01's reality adjudication's system prompt and output schema (its Appendix E),
  verbatim, each held to its pinned sha256 (§6), written as ``reality_prompt.txt`` and
  ``reality_schema.json``.
- ``packets``: one packet per design version (an artefact and a side), pooling the lines of all
  the runs on it: the lines of every review that came to ``fail`` (a ``blocked`` review is class B
  and is not adjudicated; a ``pass`` is no rejection). In each version, lines are shuffled from
  line-id order with one ``random.Random(37)`` (the injected versions first, in artefact order,
  then the twin versions), cut into consecutive packets of at most 12, labelled F1 to Fn.
- ``controls``: after the injected versions' verdicts exist, the rejection control (R-LAW-01
  §2.3's rule): the eligible lines are injected-side lines judged ``true_flaw`` with origin
  ``introduced`` whose locus is non-empty and every pair of it a changed pair; for each injected
  version holding one, one is drawn with ``random.Random(43)`` from line-id order and placed in a
  packet of its own, built for that pair's clean twin, with that single finding.
- ``blind``: every packet held to its template: outside the findings' own words and the table,
  no arm, round, side, error class, expected check, verdict or gate record; exit 1 on any.

A packet is R-LAW-01's reality packet (the prior adjudication's text, word for word): the role's
one sentence, the findings, the nodes the revision wrote, the base design's nodes, and the
authors' table ``parts_sheet.md`` verbatim (``29f9568c…``), never the converted sheet. Each
packet's ``key.json`` entry, which no session is shown, maps it to its version and each label to
its line id. It prints counts only.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CAP = 12
REALITY_PROMPT_SHA256 = "41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913"
REALITY_SCHEMA_SHA256 = "57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324"
#: R-LAW-01 Appendix E's system prompt, one line (wrapped there for reading).
REALITY_PROMPT = " ".join(
    (
        "You are an experienced mechatronics design engineer adjudicating review findings on a "
        "proposed",
        "revision of a design graph. For each finding, decide from the packet (and general "
        "engineering and",
        "datasheet knowledge, which you must say you used when you use it) whether the design as "
        "revised",
        "really has the defect the finding states (true_flaw), does not (not_a_flaw), or whether "
        "the packet",
        "does not give enough to decide (undecidable). For a true_flaw, say whether the defect is "
        "absent from",
        "the base design with the base values and so introduced by the revision (introduced), "
        "already present",
        "in the base design (already_in_base), or both; otherwise origin is n/a. Judge the defect "
        "itself, not",
        "the quality of the wording. Answer every finding id, with a reason of one or two "
        "sentences.",
    )
)
#: R-LAW-01 Appendix E's output schema.
REALITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"enum": ["true_flaw", "not_a_flaw", "undecidable"]},
                    "origin": {"enum": ["introduced", "already_in_base", "both", "n/a"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "verdict", "origin", "reason"],
            },
        }
    },
    "required": ["findings"],
}
VERDICTS = ("true_flaw", "not_a_flaw", "undecidable")
ORIGINS = ("introduced", "already_in_base", "both", "n/a")
#: R-LAW-01's reality packet text around the findings, word for word.
INTRO = (
    "A proposed revision of a design graph for a small two-wheeled self-balancing robot (a "
    "stand-in design built only from the parts sheet below). Each node holds quantities as "
    "{value, unit, source}; a source `derived: [R1.02] * [R5.03]` is arithmetic over the "
    "parts-sheet rows it names. Numbers are written to three significant figures. The revision "
    'is a change to the graph alone: it wrote the nodes listed under "What the revision wrote" '
    "(each replaces the base node of the same id, or adds a node); every other node is as in "
    "the base."
)
ROLE_SENTENCE = (
    "A reviewer of the {role} domain rejected this revision with the findings below (the "
    "reviewer's own words; rule numbers are replaced by [rule])."
)
SHEET_MARK = "\n## The parts sheet\n\n"
#: Words no packet may hold outside the findings' own words and the table (§6).
FORBIDDEN = (
    "injected", "twin", "clean twin", "arm", "round", "error_class", "expected_check",
    "error class", "expected check", "verdict", "gate", "gate_ran", "review_ran", "true_flaw",
    "not_a_flaw", "undecidable", "unit error", "magnitude error", "equilibrium error",
    "propagation error", "rpb", "R-PG-01", "fullsheet",
)  # fmt: skip


class Refused(Exception):
    """An input is not the one §6 names."""


def prompt_and_schema() -> tuple[str, dict[str, Any]]:
    """The pinned prompt and schema, each held to its sha256."""
    if hashlib.sha256(REALITY_PROMPT.encode()).hexdigest() != REALITY_PROMPT_SHA256:
        raise Refused("the reality prompt is not R-LAW-01's")
    if hashlib.sha256(json.dumps(REALITY_SCHEMA).encode()).hexdigest() != REALITY_SCHEMA_SHA256:
        raise Refused("the reality schema is not R-LAW-01's")
    return REALITY_PROMPT, REALITY_SCHEMA


def table(corpus: Path = C.REPO / C.ARM_I_CORPUS, digest: str = C.TABLE_SHA256) -> bytes:
    """The authors' table, verbatim, held to its digest."""
    data = (corpus / C.TABLE_NAME).read_bytes()
    if C.sha256_bytes(data) != digest:
        raise Refused("the table is not the authors' parts_sheet.md")
    return data


def reality_packet(
    pid: str, role: str, texts: list[str], base: list[Any], patch: list[Any], sheet: bytes
) -> str:
    """R-LAW-01's reality packet, word for word, with the authors' table at its end."""
    found = "\n".join(f"### F{i}\n\n{t}\n" for i, t in enumerate(texts, 1))
    body = [
        f"# Packet {pid}",
        "",
        INTRO,
        "",
        ROLE_SENTENCE.format(role=role),
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
        json.dumps(base, indent=None, separators=(",", ":"), sort_keys=True),
        "```",
    ]
    return "\n".join(body) + "\n" + SHEET_MARK + sheet.decode()


def adjudicated(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The lines a session judges: those of the reviews that came to ``fail``."""
    return [x for x in lines if x["review_outcome"] == "fail"]


def versions(lines: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    """Each design version's line ids, in line-id order: the injected versions, then the twins'."""
    out: dict[tuple[str, str], list[str]] = {}
    for x in sorted(lines, key=lambda x: x["line_id"]):
        out.setdefault((x["artefact"], x["side"]), []).append(x["line_id"])
    order = sorted(out, key=lambda v: (C.SIDES.index(v[1]), v[0]))
    return {v: out[v] for v in order}


def build_packets(work: Path, out: Path, sheet: bytes) -> dict[str, Any]:
    """The reality packets of every version (``packets``)."""
    lines = adjudicated(C.read_jsonl(work / "lines.jsonl"))
    design = json.loads((work / "design.json").read_text())
    by_id = {x["line_id"]: x for x in lines}
    rng = random.Random(C.PACKET_SEED)
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    lists: dict[str, list[str]] = {"injected": [], "twin": []}
    n = 0
    for (artefact, side), ids in versions(lines).items():
        ids = list(ids)
        rng.shuffle(ids)
        a = design["artefacts"][artefact]
        for start in range(0, len(ids), CAP):
            chunk = ids[start : start + CAP]
            n += 1
            pid = f"Q{n:04d}"
            text = reality_packet(
                pid, a["role"], [by_id[i]["text"] for i in chunk], design["base"], a[side], sheet
            )
            (out / f"{pid}.md").write_text(text)
            key[pid] = {
                "artefact": artefact,
                "side": side,
                "control": False,
                "findings": {f"F{i}": lid for i, lid in enumerate(chunk, 1)},
            }
            lists[side].append(pid)
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    for side, ids in lists.items():
        (out / f"{side}.txt").write_text("".join(i + "\n" for i in ids))
    return key


def structured(path: Path) -> dict[str, Any] | None:
    """A session's structured output, from the binary's JSON result."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    messages = data if isinstance(data, list) else [data]
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    so = results[-1].get("structured_output") if results else None
    return so if isinstance(so, dict) else None


def valid_forms(path: Path, fids: list[str]) -> dict[str, dict[str, Any]]:
    """The valid forms of one try, by finding id: a verdict and an origin of the schema's."""
    so = structured(path)
    found: dict[str, dict[str, Any]] = {}
    if so is None or not isinstance(so.get("findings"), list):
        return found
    for f in so["findings"]:
        if not isinstance(f, dict) or f.get("id") not in fids or f["id"] in found:
            continue
        if (
            f.get("verdict") in VERDICTS
            and f.get("origin") in ORIGINS
            and isinstance(f.get("reason"), str)
        ):
            found[f["id"]] = f
    return found


def verdicts(packets: Path, sessions: Path) -> dict[str, dict[str, Any]]:
    """Per line: the first try's valid form, else the retry's, else ``missing``."""
    key = json.loads((packets / "key.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for pid in sorted(key):
        fids = list(key[pid]["findings"])
        t1 = valid_forms(sessions / f"{pid}.try1.json", fids)
        t2 = valid_forms(sessions / f"{pid}.try2.json", fids)
        for fid, lid in key[pid]["findings"].items():
            form, used = (
                (t1[fid], "try1")
                if fid in t1
                else ((t2[fid], "try2") if fid in t2 else (None, "none"))
            )
            out[lid] = {
                "packet": pid,
                "verdict": form["verdict"] if form else "missing",
                "origin": form["origin"] if form else None,
                "try": used,
            }
    return out


def eligible(x: dict[str, Any], v: dict[str, Any] | None, changed: set[tuple[str, str]]) -> bool:
    """R-LAW-01 §2.3: injected, ``true_flaw``, ``introduced``, a locus of changed pairs only."""
    if x["side"] != "injected" or v is None:
        return False
    if v["verdict"] != "true_flaw" or v["origin"] != "introduced":
        return False
    locus = {(n, q) for n, q in x["locus"]}
    return bool(locus) and locus <= changed


def build_controls(
    work: Path, packets: Path, sessions: Path, out: Path, sheet: bytes
) -> dict[str, Any]:
    """The rejection control's packets (``controls``), numbered after the reality packets."""
    lines = adjudicated(C.read_jsonl(work / "lines.jsonl"))
    design = json.loads((work / "design.json").read_text())
    got = verdicts(packets, sessions)
    by_id = {x["line_id"]: x for x in lines}
    rng = random.Random(C.CONTROL_SEED)
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    n = len(json.loads((packets / "key.json").read_text()))
    for (artefact, side), ids in versions(lines).items():
        if side != "injected":
            continue
        a = design["artefacts"][artefact]
        changed = {(c[0], c[1]) for c in a["changed"]}
        pool = [i for i in ids if eligible(by_id[i], got.get(i), changed)]
        if not pool:
            continue
        lid = rng.choice(pool)
        n += 1
        pid = f"Q{n:04d}"
        text = reality_packet(
            pid, a["role"], [by_id[lid]["text"]], design["base"], a["twin"], sheet
        )
        (out / f"{pid}.md").write_text(text)
        key[pid] = {"artefact": artefact, "side": "twin", "control": True, "findings": {"F1": lid}}
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    return key


def blind(work: Path, packets: Path, sheet: bytes) -> dict[str, Any]:
    """Every packet held to its template: rebuilt from its key, it is the file, byte for byte.

    So nothing but the template's fixed words, the role's one sentence, the findings' own words,
    the version's nodes and the table is in any packet: no arm, round, side, class, check,
    verdict or gate record. The fixed words are also held to :data:`FORBIDDEN`.
    """
    design = json.loads((work / "design.json").read_text())
    by_id = {x["line_id"]: x for x in C.read_jsonl(work / "lines.jsonl")}
    key = json.loads((packets / "key.json").read_text())
    differ = 0
    for pid, k in sorted(key.items()):
        a = design["artefacts"][k["artefact"]]
        texts = [by_id[lid]["text"] for lid in k["findings"].values()]
        want = reality_packet(pid, a["role"], texts, design["base"], a[k["side"]], sheet)
        differ += (packets / f"{pid}.md").read_text() != want
    fixed = INTRO + " " + ROLE_SENTENCE + " " + SHEET_MARK
    hits = {
        w: n
        for w in FORBIDDEN
        if (n := len(re.findall(rf"(?<![\w-]){re.escape(w)}(?![\w-])", fixed, re.I)))
    }
    files = len(list(packets.glob("Q*.md")))
    return {
        "packets": len(key),
        "files": files,
        "not_their_template": differ,
        "hits_in_the_fixed_words": hits,
        "blind": differ == 0 and not hits and files == len(key),
    }


def main(argv: list[str]) -> int:
    """One subcommand; counts only."""
    try:
        if argv[:1] == ["prompts"] and len(argv) == 2:
            prompt, schema = prompt_and_schema()
            out = Path(argv[1])
            out.mkdir(parents=True)
            (out / "reality_prompt.txt").write_text(prompt)
            (out / "reality_schema.json").write_text(json.dumps(schema))
            print(json.dumps({"prompt": REALITY_PROMPT_SHA256, "schema": REALITY_SCHEMA_SHA256}))
            return 0
        if argv[:1] == ["packets"] and len(argv) == 3:
            key = build_packets(Path(argv[1]), Path(argv[2]), table())
            lines = sum(len(k["findings"]) for k in key.values())
            print(json.dumps({"packets": len(key), "lines": lines}))
            return 0
        if argv[:1] == ["controls"] and len(argv) == 5:
            work, packets, sessions, out = (Path(a) for a in argv[1:])
            key = build_controls(work, packets, sessions, out, table())
            print(json.dumps({"control_packets": len(key)}))
            return 0
        if argv[:1] == ["blind"] and len(argv) == 3:
            found = blind(Path(argv[1]), Path(argv[2]), table())
            print(json.dumps(found, sort_keys=True))
            return 0 if found["blind"] else 1
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
