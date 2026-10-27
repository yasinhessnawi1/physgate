r"""R-PG-03, CRITERIA.md §7: every rejection read for its reason, blind to the arm.

Usage (on the run machine, from the checkout at ``R``), in this order. ``run`` has the run
account's credential in its environment, given by ``token.sh`` and never printed, under the
watcher, and every step's tokens go to the ledger (``ledger.py reality --step``) before any score::

    experiments/R-PG-03/token.sh run <log> reality <sessions dir> -- \
        uv run --frozen python -I experiments/R-PG-03/reality.py run --packets <dir> \
            --ids <file> --out <sessions dir>


    reality.py ff-count --practice round-1=<dir> --practice repeat-K=<dir>      before block 1
    reality.py lines    --records <~/runs/rpg03> --sets <dir> --work <new dir>   after the last
    reality.py packets  --work <dir> --sets <dir> --out <new dir>
    reality.py blind    --work <dir> --sets <dir> --packets <dir>
    reality.py run      --packets <dir> --ids <file> --out <sessions dir>        injected, twins
    reality.py controls --work <dir> --sets <dir> --packets <dir> --sessions <dir> --out <new dir>
    reality.py ff       --practice ... --packets <dir> --controls <dir> --out <new dir>
    reality.py confirm  --work <dir> --sets <dir> --packets <dir> --sessions <dir>
                        --controls <dir> --control-sessions <dir> --ff <dir> --ff-sessions <dir>
                        --out <new dir>
    reality.py third    --confirm <dir> --confirm-sessions <dir> --out <new dir>
    reality.py score    --work <dir> --packets <dir> --sessions <dir> --controls <dir>
                        --control-sessions <dir> --ff <dir> --ff-sessions <dir>
                        --confirm <dir> --confirm-sessions <dir> --third <dir>
                        --third-sessions <dir> --out <reading.json>

**Finding lines** are R-LAW-01 §2.2's (every ``unmet`` or ``confirmed`` entry, and the failing
item's if not among them), each with every rubric item id replaced by ``[rule]``; a line's
**locus** is the (node, quantity) pairs it names by §2.2's rule; a **changed pair** is §2.3's.
Lines are numbered in §7's order: corpus (fresh-v2's seven, then fresh-v1c's two), item id, side
(injected, then twin), arm (A2, A1, B), and the entry's position in its review's
``result.items``. The lines of every review whose outcome is ``fail`` are read; a ``blocked``
review is class B and is not adjudicated.

**Packets** are R-LAW-01's reality packets, by its own ``reality_packet`` (the prompt and schema
held to ``41438ab7…`` and ``57c3852f…``): one per design version (item and side), pooling all
three arms' lines, at most 12; a version's lines, in line order, shuffled once by one
``random.Random(37)`` (fresh-v2's injected versions in line order, then its twins), and cut into
consecutive packets; fresh-v1c's by a second ``random.Random(37)`` after. Each holds the base, the
revision, the corpus's ``parts_sheet.md`` verbatim, and, for a version of ``fresh-v2-s``, its
assigned role's ``knowledge/<domain>/standards.md`` under a heading of its own after the sheet,
held to §7's four digests. Packets are numbered ``Q0001…`` in one sequence across every step, so
no number tells a control from a reading.

**Sessions** (``run``): one per packet, ``claude-opus-5-5`` at effort high, no tools, settings,
servers or persistence, an empty working directory and home, the prompt and schema. A call that
returns is an attempt; a packet whose findings each have a valid form is done; one that lacks a
form is tried again, at most 3 attempts, each finding taking its first valid form. A call that
ends on a usage limit, or never returns a result, is not an attempt: ``STOPPED`` is written,
nothing more starts, and the call is run again whole, with the same packet bytes, once the limit
has reset (``RP3_RESUME=1``).

**Controls.** Rejection control: after the injected versions' first judgments, one eligible line
(injected, ``true_flaw``, origin ``introduced``, every locus pair a changed pair) per injected
version that holds one, by one ``random.Random(43)`` in line order (fresh-v2's), then a second for
blocks ``p1`` and ``p2``; each alone in a packet built for its clean twin. Calibration: of
fresh-v2's P reviews, the share whose error-item lines (the common cell's items) hold a
``true_flaw`` line of origin ``introduced`` or ``both``. False-finding control: §7's five keys,
counted again on the practice records held to R-LAW-01's recorded digests (each must be 1), each
line alone in its twin's packet with the tuning set's base, the clean revision and the edited
table; four cases, a22's two lines one case. Bars: 70 % with at least 10 cases; 4 of 4.

**The confirmation pass.** Every flaw-making line on a fresh-v2 twin (``true_flaw``, origin
``introduced`` or ``both``) is judged again alone (``confirm``); every confirmed line on a twin of
``fresh-v2-s`` once more, with the same packet bytes (``third``).

**The order** (§7) is held by every step: the rejection controls are drawn only when every reading
packet has ended (a verdict, or its 3 attempts); the false-finding packets are numbered after the
controls; the second judgments are built only when every reading, control and false-finding
packet has ended, and the class's third only when every second judgment has. Packet numbers
follow from that fixed order alone. A false-finding step whose practice records cannot be read at
their digests is recorded as "not checked" (an empty key and its reason).

**Score** (``score``): one class per rejection (B, P, P′, O-introduced, O-base, N, U), "other real
flaw", "planted named", the controls and the reliability, the twin statuses and the corrected-A
reading in both ways. It refuses until every packet has a verdict or has used its 3 attempts, and
until every step has run; it draws the rejection controls, the second judgments and the third
again from the final verdicts and refuses on any difference, and refuses a stand-in's sessions.
Every subcommand prints counts only, and the steps that read first judgments print that they are
built and nothing more: no verdict, or count that depends on one, is shown to a person before
``score``.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import tally3  # noqa: E402

LX = tally3.LX
LAW = tally3._load("rlaw01_reality", common.REPO / "experiments" / "R-LAW-01" / "law_reality.py")
CAP = 12
MAX_ATTEMPTS = 3
BAR = 0.70
MIN_CASES = 10
TRUE = "true_flaw"
FLAW_ORIGINS = ("introduced", "both")
VERDICTS = ("true_flaw", "not_a_flaw", "undecidable")
ORIGINS = ("introduced", "already_in_base", "both", "n/a")
SIDES = ("injected", "twin")
STANDARD_CORPUS = "fresh-v2-s"
#: The false-finding control's five keys (§7): case, R-LAW-01's run label, item, side, rubric id.
FF_KEYS = (
    ("1", "round-1", "a18", "twin", "ES-14"),
    ("2", "round-1", "a21", "twin", "D28"),
    ("3", "round-1", "a28", "twin", "MS-3"),
    ("4", "repeat-K", "a22", "twin", "DS-27"),
    ("4", "round-1", "a22", "injected", "DS-27"),
)
#: Each practice record's commit, where its rubric item ids are read for masking.
FF_COMMITS = {"round-1": common.KEPT_ROUND_TREE, "repeat-K": common.NOISE_RUN_TREE}
#: The power of the false-finding control's bar, stated in §7 (not computed here).
FF_POWER = {"(1-p)^4": {"p=0.10": 0.66, "p=0.30": 0.24, "p=0.50": 0.06}}
STANDARDS_HEADING = "\n## The {role} domain's standards\n\n"
#: The false-finding step's record that its practice records cannot be read at their digests.
NOT_CHECKED = "not_checked.json"


class RefusedError(Exception):
    """An input is not the one §7 names, or a step is run out of its order."""


class NotCheckedError(RefusedError):
    """The practice records cannot be read at their recorded digests: the control is not checked."""


# ---------------------------------------------------------------- the prompt and the packets


def prompt_and_schema(repo: Path = common.REPO) -> tuple[Path, Path]:
    """R-LAW-01's reality prompt and schema files, each held to its pinned sha256."""
    where = repo / common.REALITY_PROMPTS
    prompt, schema = where / "reality_prompt.txt", where / "reality_schema.json"
    if common.sha256_file(prompt) != common.REALITY_PROMPT_SHA256:
        raise RefusedError("the reality prompt is not R-LAW-01's (41438ab7…)")
    if common.sha256_file(schema) != common.REALITY_SCHEMA_SHA256:
        raise RefusedError("the reality schema is not R-LAW-01's (57c3852f…)")
    return prompt, schema


def standards(repo: Path, role: str) -> bytes:
    """A domain's standards file, the blob of §3.1's pinned tree, held to §7's digest."""
    tree = common.KNOWLEDGE_TREES[f"knowledge/{role}"]
    data = common.git_bytes(repo, "cat-file", "blob", f"{tree}:standards.md")
    if common.sha256_bytes(data) != common.STANDARDS_SHA256[role]:
        raise RefusedError(f"the {role} standards are not the pinned bytes")
    return data


class Corpus:
    """One corpus's design material for packets: base, patches, roles, edges and its table."""

    def __init__(self, root: Path, name: str) -> None:
        """The corpus at ``root``, held to the edited table."""
        self.name = name
        self.sd = tally3.set_data(root)
        table = (root / common.TABLE_NAME).read_bytes()
        if common.sha256_bytes(table) != common.EDITED_TABLE_SHA256:
            raise RefusedError(f"{name}'s parts_sheet.md is not the edited authors' table")
        self.sd.sheet = table

    def role(self, item: str) -> str:
        """An item's assigned role."""
        return str(self.sd.artefacts[item]["assigned_role"])


def packet_text(
    pid: str, corpus: Corpus, item: str, side: str, texts: list[str], repo: Path
) -> str:
    """R-LAW-01's reality packet, and the role's standards for a version of the class."""
    role = corpus.role(item)
    text: str = LAW.reality_packet(pid, role, texts, corpus.sd, item, side)
    if corpus.name == STANDARD_CORPUS:
        text += STANDARDS_HEADING.format(role=role) + standards(repo, role).decode()
    return text


def number(after: Iterable[Path]) -> int:
    """The last packet number any earlier step used, from their keys."""
    last = 0
    for directory in after:
        key = json.loads((directory / "key.json").read_text())
        last = max([last, *(int(pid[1:]) for pid in key)])
    return last


# ---------------------------------------------------------------- the lines


def masking_ids(repo: Path, arm: str, role: str) -> set[str]:
    """The item ids of the rubric an arm's reviews were given, for R-LAW-01's stripping."""
    commit = common.FIX_COMMIT if arm == "A2" else common.K_COMMIT
    return set(LX.rubric_ids(repo, commit, role))


def lines_of(
    block: tally3.Block, arm: str, scored: list[dict[str, Any]], repo: Path
) -> tuple[list[tuple[tuple[Any, ...], dict[str, Any]]], list[dict[str, Any]]]:
    """Every finding line of one arm's run in a block, keyed for §7's order; and its reviews."""
    run = block.runs[arm]
    rows = {r["artefact"]: r for r in run.rows}
    corpus = common.BLOCK_CORPUS[block.name]
    keyed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    reviews: list[dict[str, Any]] = []
    for p in scored:
        item = p["item"]
        row = rows[item]
        quantities = block.law.pair_quantities(item)
        for side, sid, log in (
            ("injected", row["review_id"], run.injected),
            ("twin", row["control_id"], run.controls),
        ):
            outcome = p["review"] if side == "injected" else p["twin_review"]
            cause = p["review_cause"] if side == "injected" else p["twin_review_cause"]
            reviews.append(
                {
                    "corpus": corpus,
                    "item": item,
                    "side": side,
                    "arm": arm,
                    "role": p["role"],
                    "class": p["class"],
                    "outcome": outcome,
                    "cause": cause,
                    "credited": bool(p["R_common"]) if side == "injected" else None,
                    "common_cell": p.get("common_cell"),
                }
            )
            line = log.review.get(sid)
            if line is None or line.get("kind") != "review_ran" or outcome != "fail":
                continue
            ids = masking_ids(repo, arm, p["role"])
            for pos, it in LX.rejecting_entries(line["result"]):
                text = LX.strip_ids(it.get("evidence") or "", ids)
                rec = {
                    "corpus": corpus,
                    "item": item,
                    "side": side,
                    "arm": arm,
                    "role": p["role"],
                    "class": p["class"],
                    "section": it.get("section"),
                    "rubric_item": it.get("item"),
                    "position": pos,
                    "text": text,
                    "locus": LX.locus_of(text, quantities),
                }
                key = (
                    common.CORPUS_ORDER.index(corpus),
                    item,
                    SIDES.index(side),
                    common.ARMS.index(arm),
                    pos,
                )
                keyed.append((key, rec))
    return keyed, reviews


def extract(records: Path, sets: Path, repo: Path = common.REPO) -> dict[str, Any]:
    """Every line and every review of the valid blocks, and each item's design facts."""
    rec = tally3.blocks_record(records)
    cells = tally3.Cells.at(repo)
    keyed: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    reviews: list[dict[str, Any]] = []
    design: dict[str, Any] = {}
    for name, attempt in rec["chosen"].items():
        block = tally3.read_block(name, attempt, sets, {})
        corpus = common.BLOCK_CORPUS[name]
        design[corpus] = {
            item: {
                "role": block.law.artefacts[item]["assigned_role"],
                "changed": sorted([n, q] for n, q in block.law.changed_pairs(item)),
            }
            for item in sorted(block.law.artefacts)
        }
        for arm in common.ARMS:
            scored = tally3.score(block, arm, cells)
            for p in scored:
                p["common_cell"] = list(
                    tally3.common_cell(common.ARM_KIND[arm], p["role"], p["class"], cells)
                )
            k, r = lines_of(block, arm, scored, repo)
            keyed += k
            reviews += r
    keyed.sort(key=lambda x: x[0])
    lines = [{"line_id": f"L{n:05d}", **rec} for n, (_, rec) in enumerate(keyed, 1)]
    return {"lines": lines, "reviews": reviews, "design": design, "not_run": rec["not_run"]}


def hold_sets(sets: Path, fills: dict[str, Any], names: Iterable[str]) -> None:
    """Each named corpus at the manifest digest "Set filled" records (R5).

    Raises:
        RefusedError: "Set filled" is not on record, or a corpus's manifest is not its digest.
    """
    try:
        filled = common.need_fill(fills, "sets").get("manifests") or {}
    except common.RefusedError as exc:
        raise RefusedError(str(exc)) from exc
    for name in names:
        if common.sha256_file(sets / name / "MANIFEST.json") != filled.get(name):
            raise RefusedError(f'{name}\'s manifest is not the digest "Set filled" records')


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Rows as JSON lines, keys sorted."""
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """A JSON-lines file's rows."""
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def versions(
    lines: list[dict[str, Any]], corpora: tuple[str, ...]
) -> dict[tuple[str, str, str], list[str]]:
    """Each design version's line ids in line order: the injected versions first, then twins'."""
    out: dict[tuple[str, str, str], list[str]] = {}
    for x in sorted(lines, key=lambda x: x["line_id"]):
        if x["corpus"] in corpora:
            out.setdefault((x["corpus"], x["item"], x["side"]), []).append(x["line_id"])
    order = sorted(out, key=lambda v: (SIDES.index(v[2]), common.CORPUS_ORDER.index(v[0]), v[1]))
    return {v: out[v] for v in order}


def load_corpora(sets: Path, names: Iterable[str]) -> dict[str, Corpus]:
    """The named corpora of the sets directory."""
    return {n: Corpus(sets / n, n) for n in names}


def build_packets(work: Path, sets: Path, out: Path, repo: Path = common.REPO) -> dict[str, Any]:
    """The reading packets: fresh-v2's by one ``random.Random(37)``, fresh-v1c's by a second."""
    lines = read_jsonl(work / "lines.jsonl")
    by_id = {x["line_id"]: x for x in lines}
    present = sorted({x["corpus"] for x in lines}, key=common.CORPUS_ORDER.index)
    corpora = load_corpora(sets, present)
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    lists: dict[str, list[str]] = {"injected": [], "twin": []}
    n = 0
    for group in (common.FRESH_V2, common.FRESH_V1C):
        rng = random.Random(common.PACKET_SEED)
        for (corpus, item, side), ids in versions(lines, group).items():
            ids = list(ids)
            rng.shuffle(ids)
            for start in range(0, len(ids), CAP):
                chunk = ids[start : start + CAP]
                n += 1
                pid = f"Q{n:04d}"
                texts = [by_id[i]["text"] for i in chunk]
                (out / f"{pid}.md").write_text(
                    packet_text(pid, corpora[corpus], item, side, texts, repo)
                )
                key[pid] = {
                    "corpus": corpus,
                    "item": item,
                    "side": side,
                    "kind": "reading",
                    "findings": {f"F{i}": lid for i, lid in enumerate(chunk, 1)},
                }
                lists[side].append(pid)
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    for side, ids in lists.items():
        (out / f"{side}.txt").write_text("".join(i + "\n" for i in ids))
    return {"packets": len(key), "lines": sum(len(k["findings"]) for k in key.values())}


#: Words no packet's fixed text may hold (R-PG-01b's list, with R-PG-03's own names).
FORBIDDEN = (
    "injected",
    "twin",
    "clean twin",
    "arm",
    "round",
    "error_class",
    "expected_check",
    "error class",
    "expected check",
    "verdict",
    "gate",
    "gate_ran",
    "review_ran",
    "true_flaw",
    "not_a_flaw",
    "undecidable",
    "unit error",
    "magnitude error",
    "equilibrium error",
    "propagation error",
    "rp3",
    "R-PG-03",
    "fresh-v2",
    "fresh-v1c",
    "standard class",
    "control",
    "A2",
    "A1",
    "generalist",
    "specialist",
)


def blind(work: Path, sets: Path, packets: Path, repo: Path = common.REPO) -> dict[str, Any]:
    """Every packet rebuilt from its key is its file, byte for byte; no fixed word tells."""
    import re

    lines = {x["line_id"]: x for x in read_jsonl(work / "lines.jsonl")}
    key = json.loads((packets / "key.json").read_text())
    corpora = load_corpora(sets, sorted({k["corpus"] for k in key.values()}))
    differ = 0
    for pid, k in sorted(key.items()):
        texts = (
            [k["texts"][f] for f in k["findings"]]
            if "texts" in k
            else [lines[lid]["text"] for lid in k["findings"].values()]
        )
        want = packet_text(pid, corpora[k["corpus"]], k["item"], k["side"], texts, repo)
        differ += (packets / f"{pid}.md").read_text() != want
    fixed = LAW.INTRO + " " + LAW.ROLE_SENTENCE + " " + STANDARDS_HEADING
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


# ---------------------------------------------------------------- the sessions


def structured(path: Path) -> dict[str, Any] | None:
    """A session's structured output, from the binary's JSON result."""
    data = common.read_own(path)
    if data is None:
        return None
    try:
        found = json.loads(data)
    except ValueError:
        return None
    messages = found if isinstance(found, list) else [found]
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    so = results[-1].get("structured_output") if results else None
    return so if isinstance(so, dict) else None


def valid_forms(path: Path, fids: list[str]) -> dict[str, dict[str, Any]]:
    """One attempt's valid forms, by finding id: a verdict and an origin of the schema's."""
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


def attempts(sessions: Path, pid: str) -> list[Path]:
    """A packet's attempts, in order: the calls that returned."""
    out = []
    for n in range(1, MAX_ATTEMPTS + 1):
        path = sessions / f"{pid}.attempt{n}.json"
        if path.is_file():
            out.append(path)
    return out


def verdicts(packets: Path, sessions: Path) -> dict[str, dict[str, Any]]:
    """Per line: its first valid form across the packet's attempts, else not adjudicated."""
    key = json.loads((packets / "key.json").read_text())
    out: dict[str, dict[str, Any]] = {}
    for pid in sorted(key):
        fids = list(key[pid]["findings"])
        forms: dict[str, tuple[dict[str, Any], int]] = {}
        tried = attempts(sessions, pid)
        for n, path in enumerate(tried, 1):
            for fid, f in valid_forms(path, fids).items():
                forms.setdefault(fid, (f, n))
        for fid, lid in key[pid]["findings"].items():
            got = forms.get(fid)
            out[f"{pid}:{fid}"] = {
                "packet": pid,
                "line": lid,
                "verdict": got[0]["verdict"] if got else "undecidable",
                "origin": got[0]["origin"] if got else None,
                "attempt": got[1] if got else None,
                "adjudicated": got is not None,
                "attempts_used": len(tried),
            }
    return out


def require_ended(name: str, packets: Path, sessions: Path) -> None:
    """§7's order: a step is built from another only once every packet of that one has ended.

    Raises:
        RefusedError: the step has not been built, or a packet of it has neither a verdict for
            every finding nor its 3 attempts.
    """
    if not (packets / "key.json").is_file():
        raise RefusedError(f"{name} has not been built: §7's order")
    d = done(packets, sessions)
    if d["open"]:
        raise RefusedError(f"{d['open']} packet(s) of {name} have not ended: §7's order")


def done(packets: Path, sessions: Path) -> dict[str, int]:
    """How many packets have a verdict for every finding or have used their 3 attempts."""
    key = json.loads((packets / "key.json").read_text())
    finished = open_ = 0
    for pid, k in key.items():
        tried = attempts(sessions, pid)
        have = set()
        for path in tried:
            have |= set(valid_forms(path, list(k["findings"])))
        if have >= set(k["findings"]) or len(tried) >= MAX_ATTEMPTS:
            finished += 1
        else:
            open_ += 1
    return {"packets": len(key), "finished": finished, "open": open_}


def binary_for_sessions() -> tuple[str, bool]:
    """The pinned binary, or a test's stand-in (never the pinned binary under another name)."""
    standin = os.environ.get("RP3_STANDIN")
    if standin:
        digest = common.sha256_file(Path(standin))
        if digest in (common.BINARY_SHA256, common.BINARY_SHA256_MACOS):
            raise RefusedError(
                "the stand-in is the pinned binary: a real session never runs as one"
            )
        return standin, True
    binary = os.environ.get("RP3_CLAUDE_BIN", str(Path.home() / "pinned" / "claude-2.1.301"))
    if common.sha256_file(Path(binary)) != common.BINARY_SHA256:
        raise RefusedError("the binary is not the pinned Linux build")
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    if not version.stdout.startswith(common.BINARY_VERSION + " "):
        raise RefusedError("the binary is not 2.1.301")
    return binary, False


def call(binary: str, packet: Path, out: Path, err: Path, prompt: Path, schema: Path) -> int:
    """One session: the packet on standard input, in an empty directory with an empty home.

    The credential reaches the session's environment from this process's own, and nowhere else.
    """
    token = os.environ.get(common.TOKEN_VARIABLE, "")
    with tempfile.TemporaryDirectory(prefix="rp3r.") as tmp:
        cwd, home = Path(tmp) / "cwd", Path(tmp) / "home"
        cwd.mkdir()
        home.mkdir()
        env = {
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "DISABLE_AUTOUPDATER": "1",
            common.TOKEN_VARIABLE: token,
        }
        if os.environ.get("RP3_STANDIN"):  # a test's stand-in reads its own script from these
            env.update({k: v for k, v in os.environ.items() if k.startswith("STANDIN_")})
        argv = [
            binary,
            "-p",
            "--model",
            common.REALITY_MODEL,
            "--effort",
            common.REALITY_EFFORT,
            "--tools",
            "",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            schema.read_text(),
            "--system-prompt",
            prompt.read_text(),
        ]
        with packet.open("rb") as stdin, out.open("wb") as stdout, err.open("wb") as stderr:
            done_ = subprocess.run(
                argv, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr, check=False
            )
    return done_.returncode


def failed(out: Path, err: Path, code: int) -> str | None:
    """Why a call is not an attempt (a usage limit, an error, no result), or ``None``."""
    raw = (common.read_own(out) or b"").decode(errors="replace")
    errors = (common.read_own(err) or b"").decode(errors="replace")
    if "usage_limit_reached" in raw or "usage_limit_reached" in errors:
        return "usage_limit"
    try:
        found = json.loads(raw)
    except ValueError:
        found = None
    messages = found if isinstance(found, list) else ([found] if isinstance(found, dict) else [])
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return "no_result"
    r = results[-1]
    term = r.get("terminal_reason")
    if (
        r.get("subtype") == "error_max_structured_output_retries"
        or term == "structured_output_retry_exhausted"
    ):
        return None  # a returned call with no form: an attempt, which may be tried again
    if r.get("is_error") is not False:
        status = r.get("api_error_status")
        return f"api_error ({status})" if isinstance(status, int) else "error_result"
    if term is not None and term != "completed":
        return f"terminal {term}"
    if code != 0:
        return f"exit {code}"
    return None


def _ended_by_signal(signum: int, _frame: object) -> None:
    """A signal ends ``run`` as an exception.

    The call's child is then killed, and its empty working directory and home are removed.
    """
    raise SystemExit(128 + signum)


def run(packets: Path, ids: list[str], out: Path) -> dict[str, Any]:
    """One session per packet named, until each is done or a call fails; counts only.

    A SIGTERM ends it as an exception, so the session's child is killed and its temporary working
    directory and home are removed.
    """
    previous = signal.signal(signal.SIGTERM, _ended_by_signal)
    try:
        return _run(packets, ids, out)
    finally:
        signal.signal(signal.SIGTERM, previous)


def _run(packets: Path, ids: list[str], out: Path) -> dict[str, Any]:
    prompt, schema = prompt_and_schema()
    binary, standin = binary_for_sessions()
    out.mkdir(parents=True, exist_ok=True)
    stopped = out / "STOPPED"
    if stopped.exists():
        if os.environ.get("RP3_RESUME") != "1":
            raise RefusedError(
                "STOPPED exists: run again only with RP3_RESUME=1 once the limit has reset"
            )
        stopped.rename(out / f"STOPPED.{common.utc_now()}")
    key = json.loads((packets / "key.json").read_text())
    calls = failures = 0
    for pid in ids:
        fids = list(key[pid]["findings"])
        while True:
            tried = attempts(out, pid)
            have = set()
            for path in tried:
                have |= set(valid_forms(path, fids))
            if have >= set(fids) or len(tried) >= MAX_ATTEMPTS:
                break
            n = len(tried) + 1
            part, err = out / f"{pid}.attempt{n}.part.json", out / f"{pid}.attempt{n}.err"
            code = call(binary, packets / f"{pid}.md", part, err, prompt, schema)
            calls += 1
            cause = failed(part, err, code)
            if cause is not None:
                stamp = common.utc_now().replace(":", "")
                part.rename(out / f"{pid}.attempt{n}.failed-{stamp}.json")
                failures += 1
                stopped.write_text(f"a failed call at {pid} attempt {n}: {cause}\n")
                return {
                    "calls": calls,
                    "failed_calls": failures,
                    "stopped": True,
                    "standin": standin,
                }
            part.rename(out / f"{pid}.attempt{n}.json")
            if standin:
                (out / f"{pid}.attempt{n}.standin").write_text("")
    return {"calls": calls, "failed_calls": failures, "stopped": False, "standin": standin}


# ---------------------------------------------------------------- the controls


def eligible(x: dict[str, Any], v: dict[str, Any] | None, changed: set[tuple[str, str]]) -> bool:
    """R-LAW-01 §2.3: injected, ``true_flaw``, ``introduced``, a locus of changed pairs only."""
    if x["side"] != "injected" or v is None:
        return False
    if v["verdict"] != TRUE or v["origin"] != "introduced":
        return False
    locus = {(n, q) for n, q in x["locus"]}
    return bool(locus) and locus <= changed


def by_line(got: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Verdicts keyed by line id (each line is in one reading packet)."""
    return {v["line"]: v for v in got.values()}


def control_draw(
    lines: list[dict[str, Any]], design: dict[str, Any], got: dict[str, dict[str, Any]]
) -> list[tuple[str, str, str, str]]:
    """R-LAW-01 §2.3's draw: (group, corpus, item, line) per injected version with an eligible line.

    fresh-v2's versions by one ``random.Random(43)``, in line order, then fresh-v1c's by a second.
    """
    by_id = {x["line_id"]: x for x in lines}
    drawn: list[tuple[str, str, str, str]] = []
    for group in (common.FRESH_V2, common.FRESH_V1C):
        rng = random.Random(common.CONTROL_SEED)
        for (corpus, item, side), ids in versions(lines, group).items():
            if side != "injected":
                continue
            changed = {(c[0], c[1]) for c in design[corpus][item]["changed"]}
            pool = [i for i in ids if eligible(by_id[i], got.get(i), changed)]
            if not pool:
                continue
            name = "fresh-v2" if group == common.FRESH_V2 else "fresh-v1c"
            drawn.append((name, corpus, item, rng.choice(pool)))
    return drawn


def build_controls(
    work: Path, sets: Path, packets: Path, sessions: Path, out: Path, repo: Path = common.REPO
) -> dict[str, Any]:
    """The rejection controls, drawn once every reading packet has ended (§7's order).

    Raises:
        RefusedError: a reading packet has not ended.
    """
    require_ended("the reading", packets, sessions)
    lines = read_jsonl(work / "lines.jsonl")
    design = json.loads((work / "design.json").read_text())
    got = by_line(verdicts(packets, sessions))
    by_id = {x["line_id"]: x for x in lines}
    present = sorted({x["corpus"] for x in lines}, key=common.CORPUS_ORDER.index)
    corpora = load_corpora(sets, present)
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    n = number([packets])
    for group, corpus, item, lid in control_draw(lines, design, got):
        n += 1
        pid = f"Q{n:04d}"
        text = packet_text(pid, corpora[corpus], item, "twin", [by_id[lid]["text"]], repo)
        (out / f"{pid}.md").write_text(text)
        key[pid] = {
            "corpus": corpus,
            "item": item,
            "side": "twin",
            "kind": "rejection control",
            "group": group,
            "findings": {"F1": lid},
        }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    (out / "ids.txt").write_text("".join(i + "\n" for i in sorted(key)))
    return {"built": True}


def ff_count(practice: dict[str, Path]) -> dict[str, Any]:
    """§7's five keys, counted again on the records held to R-LAW-01's digests: each must be 1.

    Raises:
        NotCheckedError: a record cannot be read at its recorded digest (the control is then not
            checked, and the reading unchecked: §7).
        RefusedError: R-LAW-01's extractor or its recorded digests are not the ones the probe read.
    """
    digests = json.loads(LX.INPUTS.read_text())
    pins = {p.label: p for p in LX.FROZEN.runs}
    if common.sha256_file(LX.INPUTS) != common.LAW_INPUTS_SHA256:
        raise RefusedError("R-LAW-01's recorded digests are not the ones the probe read")
    if common.sha256_file(Path(str(LX.__file__))) != common.LAW_EXTRACT_SHA256:
        raise RefusedError("R-LAW-01's extractor is not the one the probe imported")
    runs = {}
    for label in ("round-1", "repeat-K"):
        try:
            runs[label] = LX.load_run(LX.FROZEN, pins[label], practice[label], digests)
        except (LX.Refused, KeyError, OSError, ValueError) as exc:
            msg = f"the practice record {label} cannot be read at its digest"
            raise NotCheckedError(msg) from exc
    counts = []
    for case, label, item, side, rubric_id in FF_KEYS:
        run = runs[label]
        n = 0
        for row in (r for r in run.rows if r["artefact"] == item):
            sid = row["review_id"] if side == "injected" else row["control_id"]
            line = run.last[side].get(sid)
            if line is None or line["kind"] != "review_ran":
                continue
            n += sum(1 for _, it in LX.rejecting_entries(line["result"]) if it["item"] == rubric_id)
        counts.append(
            {
                "case": case,
                "run": label,
                "item": item,
                "side": side,
                "rubric_item": rubric_id,
                "lines": n,
            }
        )
    return {
        "keys": counts,
        "every_key_matches_one_line": all(c["lines"] == 1 for c in counts),
        "runs": runs,
    }


def build_ff(
    practice: dict[str, Path], packets: Path, controls: Path, out: Path, repo: Path = common.REPO
) -> dict[str, Any]:
    """The false-finding control's five packets, each line alone in its twin's packet.

    They are numbered after the reading's and the rejection controls' packets. Practice records
    that cannot be read at their digests leave the step "not checked": an empty key and its reason.

    Raises:
        RefusedError: the rejection controls have not been built; or a key does not match exactly
            one line.
    """
    if not (controls / "key.json").is_file():
        raise RefusedError("the rejection controls have not been built: §7's order")
    n = number([packets, controls])
    try:
        found = ff_count(practice)
    except NotCheckedError as exc:
        out.mkdir(parents=True)
        (out / "key.json").write_text("{}")
        (out / "ids.txt").write_text("")
        (out / NOT_CHECKED).write_text(json.dumps({"not_checked": str(exc)}) + "\n")
        return {"built": True, "ff_packets": 0, "not_checked": True}
    if not found["every_key_matches_one_line"]:
        raise RefusedError("a key does not match exactly one line: a defect of the script (§11)")
    tuning = repo / common.TUNING_SET
    if common.sha256_file(tuning / "MANIFEST.json") != common.TUNING_SET_MANIFEST:
        raise RefusedError("the tuning set's manifest is not e76a4904…")
    sd = tally3.set_data(tuning)
    import sheet_check

    edited, _ = sheet_check.table_facts(repo)
    sd.sheet = edited
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    for case, label, item, side, rubric_id in FF_KEYS:
        run = found["runs"][label]
        row = next(r for r in run.rows if r["artefact"] == item)
        sid = row["review_id"] if side == "injected" else row["control_id"]
        result = run.last[side][sid]["result"]
        entry = next(it for _, it in LX.rejecting_entries(result) if it["item"] == rubric_id)
        role = sd.artefacts[item]["assigned_role"]
        text = LX.strip_ids(
            entry.get("evidence") or "", set(LX.rubric_ids(repo, FF_COMMITS[label], role))
        )
        n += 1
        pid = f"Q{n:04d}"
        (out / f"{pid}.md").write_text(LAW.reality_packet(pid, role, [text], sd, item, "twin"))
        key[pid] = {
            "corpus": "the tuning set",
            "item": item,
            "side": "twin",
            "kind": "false-finding control",
            "case": case,
            "key": {"run": label, "item": item, "side": side, "rubric_item": rubric_id},
            "findings": {"F1": f"ff-{case}-{label}"},
        }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    (out / "ids.txt").write_text("".join(i + "\n" for i in sorted(key)))
    return {"built": True, "ff_packets": len(key), "not_checked": False}


# ---------------------------------------------------------------- the confirmation pass


def flaw_making(v: dict[str, Any] | None) -> bool:
    """A line judged ``true_flaw`` with origin ``introduced`` or ``both``."""
    return v is not None and v["verdict"] == TRUE and v["origin"] in FLAW_ORIGINS


def confirm_set(lines: list[dict[str, Any]], got: dict[str, dict[str, Any]]) -> list[str]:
    """Every flaw-making line on a fresh-v2 twin, in line order: the second judgments' lines."""
    return [
        x["line_id"]
        for x in sorted(lines, key=lambda x: x["line_id"])
        if x["side"] == "twin"
        and x["corpus"] in common.FRESH_V2
        and flaw_making(got.get(x["line_id"]))
    ]


def build_confirm(
    work: Path,
    sets: Path,
    packets: Path,
    sessions: Path,
    controls: Path,
    control_sessions: Path,
    ff: Path,
    ff_sessions: Path,
    out: Path,
    repo: Path = common.REPO,
) -> dict[str, Any]:
    """Every flaw-making line on a fresh-v2 twin, alone in a packet built for its twin.

    Built once every reading, control and false-finding packet has ended (§7's order), numbered
    after them.

    Raises:
        RefusedError: a packet of those steps has not ended, or a step has not been built.
    """
    require_ended("the reading", packets, sessions)
    require_ended("the rejection controls", controls, control_sessions)
    require_ended("the false-finding control", ff, ff_sessions)
    lines = read_jsonl(work / "lines.jsonl")
    by_id = {x["line_id"]: x for x in lines}
    got = by_line(verdicts(packets, sessions))
    corpora = load_corpora(
        sets, [c for c in common.FRESH_V2 if any(x["corpus"] == c for x in lines)]
    )
    n = number([packets, controls, ff])
    out.mkdir(parents=True)
    key: dict[str, Any] = {}
    for lid in confirm_set(lines, got):
        x = by_id[lid]
        n += 1
        pid = f"Q{n:04d}"
        text = packet_text(pid, corpora[x["corpus"]], x["item"], "twin", [x["text"]], repo)
        (out / f"{pid}.md").write_text(text)
        key[pid] = {
            "corpus": x["corpus"],
            "item": x["item"],
            "side": "twin",
            "kind": "second judgment",
            "findings": {"F1": x["line_id"]},
        }
    (out / "key.json").write_text(json.dumps(key, indent=1, sort_keys=True))
    (out / "ids.txt").write_text("".join(i + "\n" for i in sorted(key)))
    return {"built": True}


def third_set(key: dict[str, Any], got: dict[str, dict[str, Any]]) -> list[str]:
    """Every second-judgment packet on a twin of fresh-v2-s whose line it confirmed."""
    return [
        pid
        for pid, k in sorted(key.items())
        if k["corpus"] == STANDARD_CORPUS and flaw_making(got.get(f"{pid}:F1"))
    ]


def build_third(confirm: Path, confirm_sessions: Path, out: Path) -> dict[str, Any]:
    """Every confirmed line on a twin of fresh-v2-s, judged once more with the same bytes.

    Built once every second judgment has ended (§7's order).

    Raises:
        RefusedError: a second-judgment packet has not ended.
    """
    require_ended("the second judgments", confirm, confirm_sessions)
    key = json.loads((confirm / "key.json").read_text())
    got = verdicts(confirm, confirm_sessions)
    out.mkdir(parents=True)
    mine: dict[str, Any] = {}
    for pid in third_set(key, got):
        shutil.copyfile(confirm / f"{pid}.md", out / f"{pid}.md")
        mine[pid] = {**key[pid], "kind": "third judgment"}
    (out / "key.json").write_text(json.dumps(mine, indent=1, sort_keys=True))
    (out / "ids.txt").write_text("".join(i + "\n" for i in sorted(mine)))
    return {"built": True}


# ---------------------------------------------------------------- the score


def bar(hit: int, cases: int, need: float = BAR, minimum: int = MIN_CASES) -> dict[str, Any]:
    """A control's bar: met, missed, or not checked under its minimum of cases."""
    if cases < minimum:
        return {"cases": cases, "hit": hit, "status": "not checked"}
    return {"cases": cases, "hit": hit, "status": "met" if hit / cases >= need else "missed"}


def reliability(statuses: Iterable[str]) -> str:
    """The reading's label: unreliable if a bar is missed, else unchecked, else reliable."""
    s = list(statuses)
    if "missed" in s:
        return "unreliable"
    if "not checked" in s:
        return "unchecked"
    return "reliable"


def classify(
    review: dict[str, Any],
    lines: list[dict[str, Any]],
    got: dict[str, dict[str, Any]],
    changed: set[tuple[str, str]],
) -> str | None:
    """§7's class of one rejection, the first that holds; ``None`` if it is no rejection."""
    if review["outcome"] == "blocked":
        return "B"
    if review["outcome"] != "fail":
        return None
    if review["side"] == "injected" and review["credited"]:
        return "P"
    found = [got.get(x["line_id"]) or {"verdict": "undecidable", "origin": None} for x in lines]
    true = [(x, v) for x, v in zip(lines, found, strict=True) if v["verdict"] == TRUE]
    if review["side"] == "injected" and any(
        {(n, q) for n, q in x["locus"]} & changed for x, _ in true
    ):
        return "P′"
    if review["side"] == "injected":
        other = [
            (x, v)
            for x, v in true
            if x["locus"] and not ({(n, q) for n, q in x["locus"]} & changed)
        ]
    else:
        other = true
    if other:
        if any(v["origin"] in FLAW_ORIGINS for _, v in other):
            return "O-introduced"
        if all(v["origin"] == "already_in_base" for _, v in other):
            return "O-base"
        return "O-unsplit"
    if lines and all(v["verdict"] == "not_a_flaw" for v in found):
        return "N"
    return "U"


def _numbered_after(key: dict[str, Any], after: int, name: str) -> None:
    want = [f"Q{n:04d}" for n in range(after + 1, after + 1 + len(key))]
    if sorted(key) != want:
        raise RefusedError(f"{name}'s packets are not numbered after the steps before it")


def hold_order(work: Path, dirs: dict[str, tuple[Path, Path]]) -> None:
    """Every step is the one §7's order builds from the final verdicts of the steps before it.

    Raises:
        RefusedError: a step's packets are not the rejection controls' draw, the false-finding
            keys, the second judgments' lines or the class's third judgments that the final
            verdicts give, or are not numbered in that order.
    """
    lines = read_jsonl(work / "lines.jsonl")
    design = json.loads((work / "design.json").read_text())
    keys = {name: json.loads((d[0] / "key.json").read_text()) for name, d in dirs.items()}
    reading, controls, ff = dirs["reading"][0], dirs["controls"][0], dirs["ff"][0]
    got = by_line(verdicts(*dirs["reading"]))
    have = [
        (k["group"], k["corpus"], k["item"], k["findings"]["F1"])
        for _, k in sorted(keys["controls"].items())
    ]
    if have != control_draw(lines, design, got):
        raise RefusedError("the rejection controls are not the draw the final first judgments give")
    _numbered_after(keys["controls"], number([reading]), "the rejection controls")
    if (ff / NOT_CHECKED).is_file():
        if keys["ff"]:
            raise RefusedError("the false-finding step is both not checked and built")
    else:
        found = [
            (
                k["case"],
                k["key"]["run"],
                k["key"]["item"],
                k["key"]["side"],
                k["key"]["rubric_item"],
            )
            for _, k in sorted(keys["ff"].items())
        ]
        if found != list(FF_KEYS):
            raise RefusedError("the false-finding packets are not §7's five keys")
    _numbered_after(keys["ff"], number([reading, controls]), "the false-finding control")
    second = [k["findings"]["F1"] for _, k in sorted(keys["confirm"].items())]
    if second != confirm_set(lines, got):
        raise RefusedError(
            "the second judgments are not the lines the final first judgments make flaw-making"
        )
    _numbered_after(keys["confirm"], number([reading, controls, ff]), "the second judgments")
    third = third_set(keys["confirm"], verdicts(*dirs["confirm"]))
    if sorted(keys["third"]) != third:
        raise RefusedError("the third judgments are not the lines the second judgments confirmed")
    for pid in third:
        if (dirs["third"][0] / f"{pid}.md").read_bytes() != (
            dirs["confirm"][0] / f"{pid}.md"
        ).read_bytes():
            raise RefusedError(f"the third judgment {pid} is not its second's packet byte for byte")


def score(
    work: Path,
    dirs: dict[str, tuple[Path, Path]],
    allow_standin: bool = False,
) -> dict[str, Any]:
    """§7 in full, from every step's packets and sessions.

    Raises:
        RefusedError: a packet of any step has neither a verdict nor its 3 attempts; a step has
            not run, or is not the one §7's order builds from the final verdicts; or a session is
            a stand-in's (outside a test).
    """
    for name, (packets, sessions) in dirs.items():
        if (packets / "key.json").is_file():
            d = done(packets, sessions)
            if d["open"]:
                raise RefusedError(
                    f"{d['open']} packet(s) of {name} are not done: no verdict is read yet"
                )
    for name, (packets, sessions) in dirs.items():
        if not (packets / "key.json").is_file():
            raise RefusedError(f"the step {name} has not run: §7's order")
        if not allow_standin and sessions.is_dir() and any(sessions.glob("*.standin")):
            raise RefusedError(f"the sessions of {name} are a stand-in's: a test's, never scored")
    hold_order(work, dirs)
    lines = read_jsonl(work / "lines.jsonl")
    reviews = read_jsonl(work / "reviews.jsonl")
    design = json.loads((work / "design.json").read_text())
    got = by_line(verdicts(*dirs["reading"]))
    of: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for x in lines:
        of.setdefault((x["corpus"], x["item"], x["side"], x["arm"]), []).append(x)
    classed: dict[tuple[str, str, str, str], str | None] = {}
    for rv in reviews:
        k = (rv["corpus"], rv["item"], rv["side"], rv["arm"])
        changed = {(c[0], c[1]) for c in design[rv["corpus"]][rv["item"]]["changed"]}
        classed[k] = classify(rv, of.get(k, []), got, changed)

    def in_group(corpus: str, group: tuple[str, ...]) -> bool:
        return corpus in group

    out: dict[str, Any] = {}
    for gname, group in (("fresh-v2", common.FRESH_V2), ("fresh-v1c", common.FRESH_V1C)):
        per: dict[str, Any] = {}
        for arm in common.ARMS:
            for side in SIDES:
                c = Counter(
                    v
                    for (corpus, _, s, a), v in classed.items()
                    if v and a == arm and s == side and in_group(corpus, group)
                )
                per[f"{arm}, {side}"] = dict(c)
        # "other real flaw": O reviews, and P or P′ reviews with a located line naming no change
        other: dict[str, Any] = {}
        planted: dict[str, int] = {}
        for arm in common.ARMS:
            for side in SIDES:
                n_o = 0
                loci: set[tuple[str, str, str]] = set()
                base: set[tuple[str, str, str]] = set()
                for (corpus, item, s, a), cls in classed.items():
                    if a != arm or s != side or not in_group(corpus, group) or cls is None:
                        continue
                    changed = {(c[0], c[1]) for c in design[corpus][item]["changed"]}
                    mine = of.get((corpus, item, s, a), [])
                    real = [x for x in mine if (got.get(x["line_id"]) or {}).get("verdict") == TRUE]
                    beyond = [
                        x
                        for x in real
                        if (
                            s == "twin"
                            or (x["locus"] and not ({(n, q) for n, q in x["locus"]} & changed))
                        )
                    ]
                    if cls.startswith("O") or (cls in ("P", "P′") and beyond):
                        n_o += 1
                    for x in beyond:
                        spot = (corpus, item, json.dumps(sorted(x["locus"])))
                        if (got.get(x["line_id"]) or {}).get("origin") == "already_in_base":
                            base.add(spot)
                        else:
                            loci.add(spot)
                    if (
                        s == "injected"
                        and cls in ("P", "P′")
                        and any({(n, q) for n, q in x["locus"]} & changed for x in real)
                    ):
                        planted[arm] = planted.get(arm, 0) + 1
                other[f"{arm}, {side}"] = {
                    "reviews": n_o,
                    "distinct_by_locus": len(loci),
                    "base_flaws_apart": len(base),
                }
        out[gname] = {"classes": per, "other_real_flaw": other, "planted_named": planted}
    # ---- the controls ----
    controls: dict[str, Any] = {}
    for gname, group in (("fresh-v2", common.FRESH_V2), ("fresh-v1c", common.FRESH_V1C)):
        p_keys = [k for k, v in classed.items() if v == "P" and in_group(k[0], group)]
        cal = 0
        cell_of = {
            (r["corpus"], r["item"], r["side"], r["arm"]): set(r["common_cell"] or [])
            for r in reviews
        }
        for k in p_keys:
            err = [x for x in of.get(k, []) if x["rubric_item"] in cell_of[k]]
            cal += any(flaw_making(got.get(x["line_id"])) for x in err)
        ctl = verdicts(*dirs["controls"]) if (dirs["controls"][0] / "key.json").is_file() else {}
        ckey = json.loads((dirs["controls"][0] / "key.json").read_text()) if ctl else {}
        mine = [v for v in ctl.values() if ckey[v["packet"]]["group"] == gname]
        controls[gname] = {
            "calibration": bar(cal, len(p_keys)),
            "rejection": bar(sum(v["verdict"] == "not_a_flaw" for v in mine), len(mine)),
        }
    ff = verdicts(*dirs["ff"]) if (dirs["ff"][0] / "key.json").is_file() else {}
    fkey = json.loads((dirs["ff"][0] / "key.json").read_text()) if ff else {}
    cases: dict[str, list[bool]] = {}
    for v in ff.values():
        passed = v["adjudicated"] and not flaw_making(v)
        cases.setdefault(fkey[v["packet"]]["case"], []).append(passed)
    ff_bar = (
        {
            "cases": 4,
            "hit": sum(all(x) for x in cases.values()),
            "status": "met"
            if len(cases) == 4 and all(all(x) for x in cases.values())
            else "missed",
            "share_not_a_flaw": sum(v["verdict"] == "not_a_flaw" for v in ff.values())
            / max(len(ff), 1),
            "power": FF_POWER,
        }
        if len(ff) == len(FF_KEYS)
        else {"cases": len(cases), "status": "not checked"}
    )
    controls["fresh-v2"]["false_finding"] = ff_bar
    label = reliability(
        [
            str(controls["fresh-v2"]["calibration"]["status"]),
            str(controls["fresh-v2"]["rejection"]["status"]),
            str(ff_bar["status"]),
        ]
    )
    # ---- the confirmation pass and the twin statuses (fresh-v2 only) ----
    second = (
        by_line(verdicts(*dirs["confirm"])) if (dirs["confirm"][0] / "key.json").is_file() else {}
    )
    third = by_line(verdicts(*dirs["third"])) if (dirs["third"][0] / "key.json").is_file() else {}
    twins: list[dict[str, Any]] = []
    standard_twins: list[dict[str, Any]] = []
    confirmation: dict[str, Any] = {arm: Counter() for arm in common.ARMS}
    per_refusal: dict[str, list[int]] = {arm: [] for arm in common.ARMS}
    for corpus in common.FRESH_V2:
        for item in sorted(design.get(corpus, {})):
            flawed = undecided = False
            own: dict[str, bool] = {}
            for arm in common.ARMS:
                k = (corpus, item, "twin", arm)
                own[arm] = False
                making = [x for x in of.get(k, []) if flaw_making(got.get(x["line_id"]))]
                if making:
                    per_refusal[arm].append(len(making))
                for x in making:
                    ok2 = flaw_making(second.get(x["line_id"]))
                    ok3 = flaw_making(third.get(x["line_id"]))
                    confirmed = ok2 and (ok3 if corpus == STANDARD_CORPUS else True)
                    confirmation[arm]["flaw_making"] += 1
                    confirmation[arm]["confirmed" if ok2 else "unconfirmed"] += 1
                    if corpus == STANDARD_CORPUS and ok2:
                        confirmation[arm]["confirmed_twice" if ok3 else "confirmed_once_only"] += 1
                    if confirmed:
                        own[arm] = True
                        flawed = True
                    else:
                        undecided = True
                if classed.get(k) == "U":
                    undecided = True
            status = "flawed" if flawed else ("undecided" if undecided else "unflawed")
            row = {"corpus": corpus, "item": item, "status": status, "confirmed_by_arm": own}
            (standard_twins if corpus == STANDARD_CORPUS else twins).append(row)
    verdict_of = {
        (r["corpus"], r["item"], r["arm"]): r["outcome"] for r in reviews if r["side"] == "twin"
    }
    corrected = {}
    for arm in common.ARMS:
        corrected[arm] = {
            f"way {w}": sum(
                tally3.corrected_a(
                    t["status"],
                    verdict_of.get((t["corpus"], t["item"], arm), "missing"),
                    t["confirmed_by_arm"][arm],
                    w,
                )
                for t in twins
            )
            for w in (1, 2)
        }
    o_intro = {
        arm: {
            "first_judgments": out["fresh-v2"]["classes"]
            .get(f"{arm}, twin", {})
            .get("O-introduced", 0),
            "confirmed": sum(1 for t in twins + standard_twins if t["confirmed_by_arm"][arm]),
        }
        for arm in common.ARMS
    }
    return {
        "reliability": label,
        "classes": out,
        "controls": controls,
        "confirmation": {arm: dict(c) for arm, c in confirmation.items()},
        "flaw_making_lines_per_refused_twin_review": per_refusal,
        "twins": twins,
        "standard_twins": standard_twins,
        "twin_statuses": dict(Counter(t["status"] for t in twins)),
        "corrected_A": corrected,
        "o_introduced": o_intro,
        "blocked": [
            {k: r[k] for k in ("corpus", "item", "side", "arm", "cause")}
            for r in reviews
            if r["outcome"] == "blocked"
        ],
        "not_adjudicated_packets": sorted(
            {v["packet"] for v in verdicts(*dirs["reading"]).values() if not v["adjudicated"]}
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """One step of the reading; counts only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("ff-count")
    f.add_argument("--practice", action="append", default=[])
    li = sub.add_parser("lines")
    li.add_argument("--records", type=Path, required=True)
    li.add_argument("--sets", type=Path, required=True)
    li.add_argument("--work", type=Path, required=True)
    pk = sub.add_parser("packets")
    pk.add_argument("--work", type=Path, required=True)
    pk.add_argument("--sets", type=Path, required=True)
    pk.add_argument("--out", type=Path, required=True)
    bl = sub.add_parser("blind")
    bl.add_argument("--work", type=Path, required=True)
    bl.add_argument("--sets", type=Path, required=True)
    bl.add_argument("--packets", type=Path, required=True)
    rn = sub.add_parser("run")
    rn.add_argument("--packets", type=Path, required=True)
    rn.add_argument("--ids", type=Path, required=True)
    rn.add_argument("--out", type=Path, required=True)
    ct = sub.add_parser("controls")
    for name in ("--work", "--sets", "--packets", "--sessions", "--out"):
        ct.add_argument(name, type=Path, required=True)
    ff = sub.add_parser("ff")
    ff.add_argument("--practice", action="append", default=[])
    for name in ("--packets", "--controls", "--out"):
        ff.add_argument(name, type=Path, required=True)
    cf = sub.add_parser("confirm")
    for name in (
        "--work",
        "--sets",
        "--packets",
        "--sessions",
        "--controls",
        "--control-sessions",
        "--ff",
        "--ff-sessions",
        "--out",
    ):
        cf.add_argument(name, type=Path, required=True)
    th = sub.add_parser("third")
    for name in ("--confirm", "--confirm-sessions", "--out"):
        th.add_argument(name, type=Path, required=True)
    sc = sub.add_parser("score")
    for name in (
        "--work",
        "--packets",
        "--sessions",
        "--controls",
        "--control-sessions",
        "--ff",
        "--ff-sessions",
        "--confirm",
        "--confirm-sessions",
        "--third",
        "--third-sessions",
        "--out",
    ):
        sc.add_argument(name, type=Path, required=True)
    args = parser.parse_args(argv)

    def practice() -> dict[str, Path]:
        return {s.partition("=")[0]: Path(s.partition("=")[2]).resolve() for s in args.practice}

    try:
        if args.cmd == "ff-count":
            # 0: every key matches one line; 1: the records cannot be read at their digests (the
            # control is not checked); 2: R-LAW-01's files are not the probe's; 3: a key's count
            # is not 1 (a defect of the script, a failed precondition).
            try:
                found = ff_count(practice())
            except NotCheckedError as exc:
                print(json.dumps({"not_checked": str(exc)}))
                return 1
            except RefusedError as exc:
                print(json.dumps({"refused": str(exc)}))
                return 2
            found.pop("runs")
            print(json.dumps(found, sort_keys=True))
            return 0 if found["every_key_matches_one_line"] else 3
        if args.cmd == "lines":
            if args.work.exists():
                raise RefusedError("the work directory exists: nothing is written over")
            got = extract(args.records.resolve(), args.sets.resolve())
            hold_sets(
                args.sets.resolve(), common.fills_on(common.REPO, "origin/master"), got["design"]
            )
            args.work.mkdir(parents=True)
            write_jsonl(args.work / "lines.jsonl", got["lines"])
            write_jsonl(args.work / "reviews.jsonl", got["reviews"])
            (args.work / "design.json").write_text(
                json.dumps(got["design"], indent=1, sort_keys=True)
            )
            counts = {
                "lines": len(got["lines"]),
                "reviews": len(got["reviews"]),
                "by_corpus": dict(Counter(x["corpus"] for x in got["lines"])),
                "empty_locus": sum(1 for x in got["lines"] if not x["locus"]),
            }
            print(json.dumps(counts, sort_keys=True))
            return 0
        if args.cmd == "packets":
            prompt_and_schema()
            present = {x["corpus"] for x in read_jsonl(args.work / "lines.jsonl")}
            hold_sets(args.sets.resolve(), common.fills_on(common.REPO, "origin/master"), present)
            print(json.dumps(build_packets(args.work, args.sets, args.out), sort_keys=True))
            return 0
        if args.cmd == "blind":
            found = blind(args.work, args.sets, args.packets)
            print(json.dumps(found, sort_keys=True))
            return 0 if found["blind"] else 1
        if args.cmd == "run":
            ids = args.ids.read_text().split()
            found = run(args.packets, ids, args.out)
            print(json.dumps({**found, **done(args.packets, args.out)}, sort_keys=True))
            return 4 if found["stopped"] else 0
        if args.cmd == "controls":
            found = build_controls(args.work, args.sets, args.packets, args.sessions, args.out)
            print(json.dumps(found, sort_keys=True))
            return 0
        if args.cmd == "ff":
            found = build_ff(practice(), args.packets, args.controls, args.out)
            print(json.dumps(found, sort_keys=True))
            return 0
        if args.cmd == "confirm":
            found = build_confirm(
                args.work,
                args.sets,
                args.packets,
                args.sessions,
                args.controls,
                args.control_sessions,
                args.ff,
                args.ff_sessions,
                args.out,
            )
            print(json.dumps(found, sort_keys=True))
            return 0
        if args.cmd == "third":
            print(
                json.dumps(
                    build_third(args.confirm, args.confirm_sessions, args.out), sort_keys=True
                )
            )
            return 0
        if args.out.exists():
            raise RefusedError("the reading exists: nothing is written over")
        dirs = {
            "reading": (args.packets, args.sessions),
            "controls": (args.controls, args.control_sessions),
            "ff": (args.ff, args.ff_sessions),
            "confirm": (args.confirm, args.confirm_sessions),
            "third": (args.third, args.third_sessions),
        }
        found = score(args.work, dirs)
        text = json.dumps(found, indent=1, sort_keys=True) + "\n"
        args.out.write_text(text)
        print(json.dumps({"out": str(args.out), "sha256": common.sha256_bytes(text.encode())}))
        return 0
    except (RefusedError, common.RefusedError, tally3.RefusedError, tally3.TallyError) as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
