"""R-LAW-01, CRITERIA.md §4, §6 and §7: the prompts, the schemas, and the coder, adjudicator and
audit packets with their keys. No model runs here.

Usage (from the repository root):

    python -I experiments/R-LAW-01/law_packets.py prompts <out dir> [<bank item> ...]
    python -I experiments/R-LAW-01/law_packets.py coders <work dir> <measured|slice> <out dir>
    python -I experiments/R-LAW-01/law_packets.py adjudicator <work dir> <step> <out dir>
    python -I experiments/R-LAW-01/law_packets.py audit <coder-1 packets dir> <out dir>
    python -I experiments/R-LAW-01/law_packets.py blind <packets dir>

- ``prompts``: the coder's and adjudicator's system prompts (version 0, or with the named bank
  items of Appendix D taken), the reality prompt (Appendix E, held to its sha256), and the three
  output schemas, each with its sha256 in ``prompts.json``. Every text is cut from the frozen
  ``CRITERIA.md`` (held to its sha256), never retyped.
- ``coders``: coder 1's and coder 2's packets (``c1/``, ``c2/``) over the measured or the slice
  lines: per design version, lines shuffled from line-id order with ``random.Random(29)`` and
  ``random.Random(31)``, cut into consecutive packets of at most 10.
- ``adjudicator``: the disputed lines of a step (codes after §5.5 differ, both forms present),
  ``random.Random(41)``, at most 10 per packet, forms labelled A and B in an order drawn by the
  same generator.
- ``audit``: 20 % of coder 1's packets, rounded up, drawn with ``random.Random(47)`` from
  packet-id order, copied byte for byte.
- ``blind``: counts of forbidden fields in every packet (arm, run, reviewer kind, role, item id,
  side, class, check, gate, verdict); exit 1 if any is found outside the findings' own words.

A packet ``<id>.md`` is what a session reads; ``key.json`` (never shown to a session) maps each
packet to its version and each finding label to its line id.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402
import law_regate as G  # noqa: E402
import law_verify as V  # noqa: E402

CRITERIA = X.HERE / "CRITERIA.md"
CRITERIA_SHA256 = "eefb0efe832b450c862ed6f4505fa9721c1a97d0423b94039685cde6044f5d87"
REALITY_PROMPT_SHA256 = "41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913"
REALITY_SCHEMA_SHA256 = "57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324"
CODER_CAP = 10
ADJ_CAP = 10
SEED_C1, SEED_C2, SEED_ADJ, SEED_AUDIT = 29, 31, 41, 47
AUDIT_SHARE = 0.20
EXAMPLES_PLACEHOLDER = (
    "[The fourteen examples of the pre-registration's section 5.4, verbatim, in that order.]"
)
CODER_SPAN_PLACEHOLDER = (
    '[The coder\'s prompt from "THE DESIGN DATA" to "WORKED EXAMPLES", verbatim.]'
)

#: Appendix D's rewordings: each replaces exactly the named sentence of Appendix A. The named
#: sentence is the one the bank's quoted words begin, or the step or rule it names.
REWORDINGS = {
    "W1": (
        "If it asserts several, take the one its first sentence asserts, set multiple_defects to "
        'true, and list up to two further defects in "further", each with a one-sentence '
        "restatement and a code (these are recorded only).",
    ),
    "W2": (
        "If the defect is not a disagreement among numeric values of the design, or between such "
        "a value and a bound, go to step 5.",
    ),
    "W3": ("G before L.",),
    "W4": (
        "A bound can decide what an equality cannot: a missing factor that physics bounds (an "
        'efficiency <= 1) still decides a claim that breaks the bound: L, tolerance "inequality".',
    ),
    "W5": ('"This value differs from the datasheet it cites" is D (source).',),
    "W6": (
        '"relative": an idealised relation written with ==, with a percentage of at most 25, '
        "justified in one sentence; the miss is measured against the larger side.",
    ),
    "W7": (
        "Records: absent and required by a written rule is D (record); absent with no such rule, "
        "or present but unconvincing, is N (traceability).",
    ),
    "W8": (
        'Kind "limit": one operating value against one rating, or one requirement written in the '
        'graph, of the same kind of quantity, written "a <= b" or "a >= b" with one input on each '
        "side and no number in it, on the same node or on two nodes joined by one direct "
        '"constrains" edge.',
    ),
}
BANK_ORDER = (
    "W1",
    "W2",
    "W3",
    "W4",
    "W5",
    "W6",
    "W7",
    "W8",
    "X1",
    "X2",
    "X3",
    "X4",
    "X5",
    "X6",
    "X7",
    "X8",
)


def criteria_text() -> str:
    data = CRITERIA.read_bytes()
    if hashlib.sha256(data).hexdigest() != CRITERIA_SHA256:
        raise X.Refused("CRITERIA.md is not the frozen file")
    return data.decode()


def _section(text: str, start: str, end: str | None) -> str:
    s = text.index(start)
    e = text.index(end, s + len(start)) if end else len(text)
    return text[s:e]


def _blocks(text: str) -> list[str]:
    return re.findall(r"```\n(.*?)\n```", text, re.S)


def bank(text: str) -> dict[str, dict[str, Any]]:
    """Appendix D's items: id, the code pair it addresses, and its text."""
    d = _section(text, "## Appendix D.", "## Appendix E.")
    out: dict[str, dict[str, Any]] = {}
    for m in re.finditer(
        r"^- \*\*(?P<id>[WX]\d)(?P<label>[^*\[]*?)\s*\[(?P<a>[^–\]]+)–(?P<b>[^\]]+)\]\*\*"
        r"(?P<rest>.*?)(?=^- \*\*|^\*\*|\Z)",
        d,
        re.M | re.S,
    ):
        body = " ".join(m.group("rest").split())
        out[m.group("id")] = {
            "pair": tuple(sorted((m.group("a").strip(), m.group("b").strip()))),
            "label": m.group("label").strip(" ,"),
            "body": body,
        }
    return out


def _new_sentence(body: str) -> str:
    """A rewording's new sentence: the quoted text after the named place."""
    m = re.search(r':\s*"(.*)"\s*$', body)
    if not m:
        raise X.Refused("a rewording has no quoted text")
    return m.group(1)


def _replace_sentence(prompt: str, old: str, new: str) -> str:
    pattern = r"\s+".join(re.escape(w) for w in old.split())
    found = re.findall(pattern, prompt)
    if len(found) != 1:
        raise X.Refused(f"the named sentence is not found exactly once: {old[:40]}")
    return re.sub(pattern, lambda _m: new, prompt, count=1)


def coder_prompt(taken: tuple[str, ...] = ()) -> str:
    """Appendix A with §5.4's examples in place, and the taken bank items applied."""
    text = criteria_text()
    a = _section(text, "## Appendix A.", "## Appendix B.")
    prompt = _blocks(a)[0]
    ex = _section(text, "### 5.4 Worked examples", "### 5.5")
    lines = ex.splitlines()
    first = next(i for i, x in enumerate(lines) if x.startswith("1. "))
    examples = "\n".join(lines[first:]).strip()
    if prompt.count(EXAMPLES_PLACEHOLDER) != 1:
        raise X.Refused("Appendix A's examples placeholder is not found once")
    prompt = prompt.replace(EXAMPLES_PLACEHOLDER, examples)
    items = bank(text)
    unknown = set(taken) - set(items)
    if unknown:
        raise X.Refused(f"not bank items: {sorted(unknown)}")
    for wid in (i for i in BANK_ORDER if i in taken and i.startswith("W")):
        prompt = _replace_sentence(prompt, REWORDINGS[wid][0], _new_sentence(items[wid]["body"]))
    extra = [i for i in BANK_ORDER if i in taken and i.startswith("X")]
    if extra:
        added = []
        for n, xid in enumerate(extra, 15):
            it = items[xid]
            added.append(f"{n}. **{it['label']}** {it['body']}")
        anchor = examples.splitlines()[-1]
        prompt = prompt.replace(anchor, anchor + "\n" + "\n".join(added), 1)
    return prompt


def adjudicator_prompt(coder: str) -> str:
    """Appendix B, with the coder's prompt from THE DESIGN DATA through its worked examples."""
    text = criteria_text()
    b = _blocks(_section(text, "## Appendix B.", "## Appendix C."))[0]
    s = coder.index("THE DESIGN DATA")
    e = coder.index("\nOUTPUT\n")
    if b.count(CODER_SPAN_PLACEHOLDER) != 1:
        raise X.Refused("Appendix B's placeholder is not found once")
    return b.replace(CODER_SPAN_PLACEHOLDER, coder[s:e].rstrip("\n"))


def reality_prompt() -> tuple[str, dict[str, Any]]:
    """Appendix E's prompt (one line) and schema, each held to its sha256."""
    e = _blocks(_section(criteria_text(), "## Appendix E.", None))
    prompt = " ".join(e[0].split("\n"))
    if hashlib.sha256(prompt.encode()).hexdigest() != REALITY_PROMPT_SHA256:
        raise X.Refused("the reality prompt is not the prior one")
    schema = json.loads(e[1])
    if hashlib.sha256(json.dumps(schema).encode()).hexdigest() != REALITY_SCHEMA_SHA256:
        raise X.Refused("the reality schema is not the prior one")
    return prompt, schema


def coder_schema(adjudicator: bool = False) -> dict[str, Any]:
    """Appendix A's output schema (Appendix B's adds ``chosen``)."""
    props: dict[str, Any] = {
        "id": {"type": "string"},
        "defect": {"type": "string"},
        "code": {"enum": list(V.CODES)},
        "multiple_defects": {"type": "boolean"},
        "reason": {"type": "string"},
        "gate_relation": {"enum": [*G.RELATION_NAMES, "none"]},
        "relation": {"type": "string"},
        "law": {"type": "string"},
        "kind": {"enum": ["law", "limit"]},
        "inputs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "node": {"type": "string"},
                    "quantity": {"type": "string"},
                    "requirement": {"type": "integer"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                },
                "required": ["symbol", "node", "value", "unit"],
            },
        },
        "missing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "node": {"type": ["string", "null"]},
                    "quantity": {"type": "string"},
                },
                "required": ["node", "quantity"],
            },
        },
        "tolerance": {"enum": ["rounding", "inequality", "relative"]},
        "tolerance_percent": {"type": "number"},
        "evaluation": {"type": "string"},
        "family": {"enum": [1, 2, 3, 4, 5, 6, 7, "none"]},
        "fallback_code": {"enum": list(V.FALLBACKS)},
        "d_kind": {"enum": list(V.D_KINDS)},
        "n_kind": {"enum": list(V.N_KINDS)},
        "further": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {"defect": {"type": "string"}, "code": {"enum": list(V.CODES)}},
                "required": ["defect", "code"],
            },
        },
    }
    required = ["id", "defect", "code", "multiple_defects", "reason"]
    if adjudicator:
        props["chosen"] = {"enum": ["A", "B", "other"]}
        required.append("chosen")
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {"type": "object", "properties": props, "required": required},
            }
        },
        "required": ["findings"],
    }


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_prompts(out: Path, taken: tuple[str, ...]) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    cp = coder_prompt(taken)
    ap = adjudicator_prompt(cp)
    rp, rs = reality_prompt()
    files = {
        "coder_prompt.txt": cp,
        "adjudicator_prompt.txt": ap,
        "reality_prompt.txt": rp,
        "coder_schema.json": json.dumps(coder_schema()),
        "adjudicator_schema.json": json.dumps(coder_schema(adjudicator=True)),
        "reality_schema.json": json.dumps(rs),
    }
    for name, body in files.items():
        (out / name).write_text(body)
    meta = {"taken": list(taken), "sha256": {n: sha(b) for n, b in files.items()}}
    (out / "prompts.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    return meta


# ---------------------------------------------------------------- packets


def intro() -> str:
    """The packet's opening paragraph, cut from Appendix A's packet template."""
    tpl = _blocks(_section(criteria_text(), "## Appendix A.", "## Appendix B."))[1]
    para = tpl.split("\n\n")[1]
    return para


def design_json(nodes: dict[str, dict[str, Any]]) -> str:
    """Every node of the version, every field but ``updated``, quantities without ``written_by``."""
    out = []
    for nid in sorted(nodes):
        n = {k: v for k, v in nodes[nid].items() if k != "updated"}
        n["quantities"] = {
            q: {k: v for k, v in body.items() if k != "written_by"}
            for q, body in (n.get("quantities") or {}).items()
        }
        out.append(n)
    return json.dumps(out, indent=1, sort_keys=True)


CODER_FINDINGS = "## Findings (the reviewers' own words; rule numbers are replaced by [rule])\n\n"
ADJ_FINDINGS = (
    "## Findings and the two forms (the reviewers' own words; rule numbers are replaced by "
    "[rule])\n\n"
)
DESIGN_MARK = "\n## The design, all nodes\n\n"


def form_keys() -> frozenset[str]:
    """The fields of a coder's form (Appendix A's schema): all an adjudicator is shown of one."""
    return frozenset(coder_schema()["properties"]["findings"]["items"]["properties"])


def coder_packet(pid: str, texts: list[str], nodes: dict[str, Any], sheet: bytes) -> str:
    findings = "\n".join(f"### F{i}\n{t}\n" for i, t in enumerate(texts, 1))
    return (
        f"# Packet {pid}\n\n{intro()}\n\n"
        f"{CODER_FINDINGS}"
        f"{findings}{DESIGN_MARK}{design_json(nodes)}\n"
        f"{V.SHEET_MARK}{sheet.decode()}"
    )


def adjudicator_packet(
    pid: str,
    items: list[tuple[str, dict[str, Any], dict[str, Any]]],
    nodes: dict[str, Any],
    sheet: bytes,
) -> str:
    """The disputed findings with the two forms, each cut to the schema's fields (anything else a
    session wrote beside them is not part of the form)."""
    keys = form_keys()
    parts = []
    for i, (text, a, b) in enumerate(items, 1):
        fa = json.dumps(
            {**{k: v for k, v in a.items() if k in keys}, "id": f"F{i}"}, sort_keys=True
        )
        fb = json.dumps(
            {**{k: v for k, v in b.items() if k in keys}, "id": f"F{i}"}, sort_keys=True
        )
        parts.append(f"### F{i}\n{text}\n\nForm A:\n{fa}\n\nForm B:\n{fb}\n")
    return (
        f"# Packet {pid}\n\n{intro()}\n\n"
        f"{ADJ_FINDINGS}" + "\n".join(parts) + f"{DESIGN_MARK}{design_json(nodes)}\n"
        f"{V.SHEET_MARK}{sheet.decode()}"
    )


def versions_of(lines: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[str]]:
    """Each design version's line ids, versions in (set, pair, side) order, ids in line-id order."""
    out: dict[tuple[str, str, str], list[str]] = {}
    for x in sorted(lines, key=lambda x: x["line_id"]):
        out.setdefault((x["set"], x["pair"], x["side"]), []).append(x["line_id"])
    order = sorted(out, key=lambda v: (X.SET_ORDER.index(v[0]), v[1], X.SIDE_ORDER.index(v[2])))
    return {v: out[v] for v in order}


def cut(ids: list[str], cap: int) -> list[list[str]]:
    return [ids[i : i + cap] for i in range(0, len(ids), cap)]


def build_coder_packets(
    lines: list[dict[str, Any]], sets: dict[str, X.SetData], seed: int, out: Path
) -> dict[str, Any]:
    by_id = {x["line_id"]: x for x in lines}
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=False)
    key: dict[str, Any] = {}
    n = 0
    for (st, pair, side), ids in versions_of(lines).items():
        ids = list(ids)
        rng.shuffle(ids)
        nodes = sets[st].version(pair, side)
        for chunk in cut(ids, CODER_CAP):
            n += 1
            pid = f"P{n:04d}"
            text = coder_packet(pid, [by_id[i]["text"] for i in chunk], nodes, sets[st].sheet)
            (out / f"{pid}.md").write_text(text)
            key[pid] = {
                "set": st,
                "pair": pair,
                "side": side,
                "findings": {f"F{i}": lid for i, lid in enumerate(chunk, 1)},
            }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    return key


def disputed(codes: list[dict[str, Any]], step: str) -> list[str]:
    """Lines whose two coders' codes after §5.5 differ, both forms present."""
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in codes:
        if r["step"] == step and r["who"] in ("c1", "c2"):
            by.setdefault(r["line_id"], {})[r["who"]] = r
    return sorted(
        lid
        for lid, w in by.items()
        if "c1" in w
        and "c2" in w
        and w["c1"]["form"] is not None
        and w["c2"]["form"] is not None
        and w["c1"]["code"] != w["c2"]["code"]
    )


def build_adjudicator_packets(
    lines: list[dict[str, Any]],
    codes: list[dict[str, Any]],
    step: str,
    sets: dict[str, X.SetData],
    out: Path,
) -> dict[str, Any]:
    want = set(disputed(codes, step))
    by_id = {x["line_id"]: x for x in lines}
    forms = {
        (r["line_id"], r["who"]): r["form"]
        for r in codes
        if r["step"] == step and r["who"] in ("c1", "c2")
    }
    rng = random.Random(SEED_ADJ)
    out.mkdir(parents=True, exist_ok=False)
    key: dict[str, Any] = {}
    n = 0
    chosen = [x for x in lines if x["line_id"] in want]
    for (st, pair, side), ids in versions_of(chosen).items():
        ids = list(ids)
        rng.shuffle(ids)
        nodes = sets[st].version(pair, side)
        for chunk in cut(ids, ADJ_CAP):
            n += 1
            pid = f"P{n:04d}"
            items, labels = [], {}
            for i, lid in enumerate(chunk, 1):
                c1_is_a = rng.random() < 0.5
                a, b = (forms[(lid, "c1")], forms[(lid, "c2")])
                if not c1_is_a:
                    a, b = b, a
                items.append((by_id[lid]["text"], a, b))
                labels[f"F{i}"] = {"A": "c1" if c1_is_a else "c2", "B": "c2" if c1_is_a else "c1"}
            (out / f"{pid}.md").write_text(adjudicator_packet(pid, items, nodes, sets[st].sheet))
            key[pid] = {
                "set": st,
                "pair": pair,
                "side": side,
                "findings": {f"F{i}": lid for i, lid in enumerate(chunk, 1)},
                "labels": labels,
            }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    return key


def build_audit(c1: Path, out: Path) -> list[str]:
    key = json.loads((c1 / "key.json").read_text())
    ids = sorted(key)
    k = math.ceil(AUDIT_SHARE * len(ids))
    picked = sorted(random.Random(SEED_AUDIT).sample(ids, k))
    out.mkdir(parents=True, exist_ok=False)
    for pid in picked:
        shutil.copyfile(c1 / f"{pid}.md", out / f"{pid}.md")
    (out / "key.json").write_text(json.dumps({p: key[p] for p in picked}, indent=1, sort_keys=True))
    return picked


# ---------------------------------------------------------------- blinding


FORBIDDEN = (
    *(p.label for p in X.RUNS),
    "practice-it0",
    "practice-r1",
    "practice-r2",
    "rp2-2-a-fresh",
    "rp2-2-b-fresh",
    "gr2-noise2",
    "gr2-r1",
    "paired",
    "generalist",
    "injected",
    "twin",
    "assigned_role",
    "error_class",
    "expected_check",
    "subtask",
    "review_id",
    "control_id",
    "gate_ran",
    "review_ran",
    "failing_check",
    "verdict",
    "true_flaw",
    "not_a_flaw",
    "undecidable",
    "reality",
    "arm",
)
ITEM_ID = re.compile(r"(?<![\w.-])(?:[A-Z]{2}-\d{1,2}|[ADSR]\d{1,2})(?![\w]|\.\d)")
#: Keys no node shown to a session holds: what the artefact says about itself. A coder's design
#: also never shows a node's ``updated`` or a quantity's ``written_by`` (§4).
ARTEFACT_KEYS = frozenset({"assigned_role", "error_class", "expected_check"})
CODER_HIDDEN_KEYS = ARTEFACT_KEYS | {"updated", "written_by"}
REALITY_TAIL = re.compile(
    r"\n## What the revision wrote\n\n```json\n(?P<patch>.*)\n```\n\n"
    r"## The base design \(before the revision\), all nodes\n\n```json\n(?P<base>.*)\n```\n",
    re.S,
)


def _count(part: str, words: Iterable[str]) -> dict[str, int]:
    out = {}
    for w in words:
        c = len(re.findall(rf"(?<![\w-]){re.escape(w)}(?![\w-])", part, re.I))
        if c:
            out[w] = c
    return out


def _keys(obj: Any) -> set[str]:  # noqa: ANN401 - any JSON value
    if isinstance(obj, dict):
        return set(obj) | {k for v in obj.values() for k in _keys(v)}
    if isinstance(obj, list):
        return {k for v in obj for k in _keys(v)}
    return set()


def shown_design(version: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """What §4 lets a coder see of a version, written out apart from :func:`design_json`."""
    out = []
    for nid in sorted(version):
        n = {k: v for k, v in version[nid].items() if k != "updated"}
        n["quantities"] = {
            q: {k: v for k, v in body.items() if k != "written_by"}
            for q, body in (version[nid].get("quantities") or {}).items()
        }
        out.append(n)
    return out


class _Blind:
    """One packet dir's blind check; see :func:`blind_counts`."""

    def __init__(self, packets: Path, sets: dict[str, X.SetData] | None) -> None:
        kp = packets / "key.json"
        self.keys: dict[str, Any] = json.loads(kp.read_text()) if kp.exists() else {}
        self.sets = sets
        self.roles = set(X.ROLES)
        self.classes: set[str] = set()
        for sd in (sets or {}).values():
            for a in sd.artefacts.values():
                self.roles.add(str(a["assigned_role"]))
                self.classes |= {str(a["error_class"]), str(a["expected_check"])}
        self.hits = {
            "structure": 0,
            "sheet": 0,
            "findings_words": 0,
            "findings_item_ids": 0,
            "findings_values": 0,
            "forms_words": 0,
        }
        self.where: dict[str, int] = {}

    def add(self, hit: str, label: str, n: int = 1) -> None:
        self.hits[hit] += n
        self.where[label] = self.where.get(label, 0) + n

    def values(self, part: str) -> dict[str, int]:
        out = {f"role:{w}": c for w, c in _count(part, sorted(self.roles)).items()}
        out.update({f"class:{w}": c for w, c in _count(part, sorted(self.classes)).items()})
        return out

    def residue(self, label: str, text: str) -> None:
        """Text the template does not hold: a leak, with every value and word in it named."""
        if not text.strip():
            return
        self.add("structure", f"{label}:extra_text")
        for w, c in (self.values(text) | _count(text, FORBIDDEN)).items():
            self.add("structure", f"{label}:{w}", c)

    def version(self, pid: str) -> tuple[X.SetData, dict[str, Any]] | None:
        k = self.keys.get(pid)
        if k is None or self.sets is None or k.get("set") not in self.sets:
            return None
        return self.sets[k["set"]], k

    def free(self, text: str, forms: bool = False) -> None:
        """The reviewers' own words (or a coder's form): words and values counted apart; an item
        id in a finding is a leak, since every rubric item id was stripped."""
        if forms:
            self.hits["forms_words"] += sum(_count(text, FORBIDDEN).values())
            return
        self.hits["findings_words"] += sum(_count(text, FORBIDDEN).values())
        self.hits["findings_values"] += sum(self.values(text).values())
        ids = len(ITEM_ID.findall(text))
        if ids:
            self.add("findings_item_ids", "findings:item_id", ids)

    def json_part(self, label: str, text: str, hidden: frozenset[str]) -> Any:  # noqa: ANN401
        for w, c in _count(text, FORBIDDEN).items():
            self.add("structure", f"{label}:{w}", c)
        try:
            obj = json.loads(text)
        except ValueError:
            self.add("structure", f"{label}:not_json")
            return None
        for k in sorted(_keys(obj) & hidden):
            self.add("structure", f"{label}:key:{k}")
        return obj

    def labels(self, label: str, region: str, sep: str) -> list[str]:
        parts = re.split(rf"(?m)^### F(\d+)\n{sep}", region)
        self.residue(f"{label}:before_F1", parts[0])
        nums = parts[1::2]
        if not nums or nums != [str(i) for i in range(1, len(nums) + 1)]:
            self.add("structure", f"{label}:labels")
        return parts[2::2]

    def coder(self, pid: str, body: str) -> None:
        head = f"# Packet {pid}\n\n{intro()}\n\n"
        adj = body.startswith(head + ADJ_FINDINGS)
        if body.startswith(head + (ADJ_FINDINGS if adj else CODER_FINDINGS)):
            rest = body[len(head + (ADJ_FINDINGS if adj else CODER_FINDINGS)) :]
        else:
            cut = body.find("\n### F1\n")
            top = body[: cut + 1] if cut >= 0 else body
            for fixed in (f"# Packet {pid}", intro(), CODER_FINDINGS, ADJ_FINDINGS):
                top = top.replace(fixed, "", 1)
            self.residue("head", top)
            adj = "## Findings and the two forms" in body
            rest = body[cut + 1 :] if cut >= 0 else ""
        d = rest.rfind(DESIGN_MARK)
        if d < 0 or not rest.endswith("\n"):
            self.add("structure", "design:missing")
            return
        found = rest[:d]
        nodes = self.json_part("design", rest[d + len(DESIGN_MARK) : -1], CODER_HIDDEN_KEYS)
        v = self.version(pid)
        if v is not None and nodes is not None:
            sd, k = v
            if nodes != shown_design(sd.version(k["pair"], k["side"])):
                self.add("structure", "design:not_the_version")
        allowed = form_keys()
        for item in self.labels("findings", found, ""):
            if not adj:
                self.free(item)
                continue
            m = re.fullmatch(r"(.*)\n\nForm A:\n([^\n]*)\n\nForm B:\n([^\n]*)\n*", item, re.S)
            if m is None:
                self.add("structure", "forms:shape")
                self.free(item)
                continue
            self.free(m.group(1))
            for f in (m.group(2), m.group(3)):
                self.free(f, forms=True)
                try:
                    obj = json.loads(f)
                except ValueError:
                    self.add("structure", "forms:not_json")
                    continue
                if not isinstance(obj, dict):
                    self.add("structure", "forms:not_an_object")
                    continue
                for key in sorted(set(obj) - allowed):
                    self.add("structure", f"forms:key:{key}")

    def reality(self, pid: str, body: str) -> None:
        import law_reality as R  # the reality module builds on this one

        v = self.version(pid)
        roles = [v[0].artefacts[v[1]["pair"]]["assigned_role"]] if v else sorted(self.roles)
        heads = [
            f"# Packet {pid}\n\n{R.INTRO}\n\n{R.ROLE_SENTENCE.format(role=r)}\n\n## Findings\n\n"
            for r in roles
        ]
        head = next((h for h in heads if body.startswith(h)), None)
        if head is not None:
            rest = body[len(head) :]
        else:
            cut = body.find("\n### F1\n")
            top = body[: cut + 1] if cut >= 0 else body
            for fixed in (f"# Packet {pid}", R.INTRO, "## Findings"):
                top = top.replace(fixed, "", 1)
            said = next((s for r in roles if (s := R.ROLE_SENTENCE.format(role=r)) in top), "")
            self.residue("head", top.replace(said, "", 1) if said else top)
            rest = body[cut + 1 :] if cut >= 0 else ""
        d = rest.rfind("\n## What the revision wrote\n")
        m = REALITY_TAIL.fullmatch(rest[d:]) if d >= 0 else None
        if m is None:
            self.add("structure", "design:missing")
            return
        patch = self.json_part("revision", m.group("patch"), ARTEFACT_KEYS)
        base = self.json_part("base", m.group("base"), ARTEFACT_KEYS)
        if v is not None:
            sd, k = v
            if patch != sd.patch(k["pair"], k["side"]) or base != sd.base:
                self.add("structure", "design:not_the_version")
        for item in self.labels("findings", rest[:d], "\n"):
            self.free(item)


def blind_counts(packets: Path, sets: dict[str, X.SetData] | None = None) -> dict[str, Any]:
    """The blind check of every packet of a dir, by part (§4, §2.3).

    The packet must be its template's text exactly, outside the findings' own words, the design
    and the sheet: anything else is a leak, and every role, error class, expected check or
    forbidden word in it is named. A coder or adjudicator packet names no role at all; a reality
    packet names its own reviewer's role in the prior adjudication's one sentence. No node shows
    an artefact's own fields, and with ``sets`` (and the dir's ``key.json``) the design is the
    packet's version exactly. An adjudicator's forms hold only the schema's fields. In the
    findings, a forbidden word, a role or a class is the reviewers' own and counted apart; an
    item id is a leak. A forbidden word in the sheet is a leak.
    """
    b = _Blind(packets, sets)
    n = 0
    for p in sorted(packets.glob("[PQ]*.md")):
        n += 1
        text = p.read_text()
        if text.count(V.SHEET_MARK) != 1:
            b.add("structure", "sheet:mark")
            continue
        body, sheet = text.split(V.SHEET_MARK, 1)
        for w, c in _count(sheet, FORBIDDEN).items():
            b.add("sheet", f"sheet:{w}", c)
        if p.name.startswith("Q"):
            b.reality(p.stem, body)
        else:
            b.coder(p.stem, body)
    leak = b.hits["structure"] + b.hits["sheet"] + b.hits["findings_item_ids"]
    return {"packets": n, "hits": b.hits, "where": b.where, "blind": leak == 0}


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["prompts"] and len(argv) >= 2:
            print(json.dumps(write_prompts(Path(argv[1]), tuple(argv[2:])), sort_keys=True))
            return 0
        if argv[:1] == ["blind"] and len(argv) == 2:
            sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
            res = blind_counts(Path(argv[1]), sets)
            print(json.dumps(res, sort_keys=True))
            return 0 if res["blind"] else 1
        if argv[:1] == ["audit"] and len(argv) == 3:
            picked = build_audit(Path(argv[1]), Path(argv[2]))
            print(json.dumps({"audit_packets": len(picked)}))
            return 0
        if argv[:1] in (["coders"], ["adjudicator"]) and len(argv) == 4:
            work, which, out = Path(argv[1]), argv[2], Path(argv[3])
            lines = X.read_jsonl(work / "lines.jsonl")
            sl = json.loads((work / "slice.json").read_text())
            in_slice = {(s, p) for s in X.SET_ORDER for p in sl["pairs"][s]}
            sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
            if argv[0] == "coders":
                pick = [
                    x for x in lines if ((x["set"], x["pair"]) in in_slice) == (which == "slice")
                ]
                k1 = build_coder_packets(pick, sets, SEED_C1, out / "c1")
                k2 = build_coder_packets(pick, sets, SEED_C2, out / "c2")
                print(
                    json.dumps({"lines": len(pick), "c1_packets": len(k1), "c2_packets": len(k2)})
                )
                return 0
            codes = X.read_jsonl(work / "codes.jsonl")
            key = build_adjudicator_packets(lines, codes, which, sets, out)
            print(json.dumps({"adjudicator_packets": len(key)}))
            return 0
    except X.Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
