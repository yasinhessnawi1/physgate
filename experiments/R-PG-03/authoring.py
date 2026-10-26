"""R-PG-03, CRITERIA.md §2.2 and §2.5: the authoring's state, sessions, checks, routes and audits.

``authoring.sh`` is the runner's command sheet; it calls this. Usage (on the run machine, from the
checkout at ``R``; ``next`` with the run account's credential in its environment, from token.sh)::

    authoring.py inputs --out <file>          every fixed input and message, with its sha256
    authoring.py status                        the state: pairs, sessions, batches, caps, next step
    authoring.py next                          the one next step of the sheet, done
    authoring.py limit-reset                   the runner's record that the usage limit has reset
    authoring.py service-back                  the owner's word that the service is back
    authoring.py owner-resume                  the owner's word to resume a turn once more
    authoring.py assemble --pair <P> --batch <b>   a batch's corpus from its passed copies

**The sheet** (§2.2, §2.5), for each author pair in turn, X, then Y, then Z, one session at a time:

1. the writer (X1) is launched: the launch message, then the fixed continuation to ``a21``-``a40``,
   then for pair X the third continuation to ``s01``-``s10``; each batch is checked after the turn
   that wrote it, and only bare facts go back, in Appendix B's template, at most 4 fact rounds per
   batch; a batch that passes has its ``base.json`` and ``clean/*.json`` copied, read-only, into
   the pair's record of passed copies (``authoring/<pair>-<attempt>/passed/``) and recorded by
   sha256; every later session's copies, and every corpus, come from that record alone;
2. the error session (X2) starts when ``a01``-``a40`` have passed: the launch message, then the
   fixed continuation; it never sees a check; its injections are checked when it has ended;
3. for pair X, session C starts when ``s01``-``s10`` have passed; X3 writes the ``s`` batch once
   more if its route calls for it.

**The checks.** The clean side (§2.5 items 1-4 and 6): the loader's own checks on the base and each
revision (whole nodes, legal sources, derivations, no telltale word in a node or a file name, no
interface rewritten, no owner changed), the gate on the base and on each revision over it (no
failing record), the source check (no ``mismatch``), the rule checks (``rules_check.py``), and the
blindness check on a packet built for every twin. The injections (items 1 and 6): each batch
assembled from the passed copies, loaded, complete by the instrument's own rule (5 per class, 5
distinct cross-domain edges, none of the first batch's in the second; for ``s``, 10 of the
``standard`` class and nothing else), and held to the blindness check on a packet for every item
and twin.

**The routes** (§2.5's table), every one recorded: a clean batch that fails after its 4th fact
round, or the writer's audit failing in a primary turn, restarts the pair from scratch (at most 2
restarts); an injection that fails, or the error session's audit failing, replaces that session
(at most 2 per error session per attempt); the ``s`` batch failing goes to X3 (once); a cap reached
stops the authoring for the owner (the primary) or leaves the ``standard`` class not run.

**A session cut short** (§2.5): a usage-limit cut is resumed with the resume message once the
limit has reset (``limit-reset``), at most 2 per session and once per turn, else it is an audit
failure in that turn; an infrastructure cut is resumed after 60, 900 and 2,700 s, then once more on
that ladder after the owner says the service is back, then only on the owner's word. None spends a
cap.

**The audit** of every turn (§2.5), from its stream: a tool other than Read, Write and Edit; a read
or write outside the session's directory that succeeded; a model other than the pinned one; a
secret; a message not from the runner's fixed files; at the turn's end, a passed copy changed or
gone. A guard refusal, and a mention of a gate or an answer, are recorded, never failures.

It prints counts, exit codes, audit summaries and the facts it forwards, nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import rules_check as rules_check  # noqa: E402
import streams  # noqa: E402

AUTHORING = common.HERE / "authoring"
R_PG_02 = common.REPO / "experiments" / "R-PG-02" / "fresh-authoring"
COMMONS = ("architecture.md", "format.md", "vocabulary.md", "risk_row_1.md")
#: R-PG-02's sandbox guard, published with its authoring record, byte for byte.
GUARD = R_PG_02 / "records" / "A" / "config" / "guard.py"
GUARD_SHA256 = "5f3616f8cdb16577c8b9b4d498538db39bd4b48bab3ec45f2b4fea283e2067cf"
CONTINUE_A = ("continue_A.txt", "4cef18d7bfa374d779b9c0888e9f181e5597d6f221e1ebcfbfeb4151dc47cd4a")
CONTINUE_B = ("continue_B.txt", "660015c32f04093d78e3a6bf39747d2e7dc2eb0c938301b9acc84fc64e7bff2b")
#: The fixed messages and briefs of Appendix A and B, as committed beside this script.
FIXED = (
    "rules.md",
    "brief_A.md",
    "brief_B.md",
    "brief_C.md",
    "launch.txt",
    "continue_third.txt",
    "launch_X3.txt",
    "resume.txt",
)
PAIRS = ("X", "Y", "Z")
BATCHES = {"1": (1, 20), "2": (21, 40)}
S_IDS = [f"s{k:02d}" for k in range(1, 11)]
MAX_FACT_ROUNDS = 4
MAX_RESTARTS = 2
MAX_REPLACEMENTS = 2
MAX_USAGE_RESUMES = 2
INFRA_LADDER = (60.0, 900.0, 2700.0)
#: R-PG-02's sandbox's turn bound (its resume script's), for every turn.
MAX_TURNS = 150
ALLOWED_TOOLS = {"Read", "Write", "Edit"}
REFUSAL = "is outside this session's working directory"
#: The model name the binary gives the messages it writes itself; excused only on the one kind of
#: such message the stream marks as the binary's own report of an API error.
SYNTHETIC_MODEL = "<synthetic>"
#: The one audit failure judged at the turn's end alone (§2.5), so never carried from a cut part.
PASSED_COPY_FAILURE = "a passed copy changed or gone at the turn's end"
GATE_WORDS = (
    "src/physgate",
    "physgate/gate",
    "check_propagation",
    "bounds_table",
    "relations.py",
    "catalogue.py",
    "evaluation/inject",
    "corpora/injected",
)
#: R-PG-01b's last session must have ended this long before the authoring starts (§10 item 3).
AFTER_RPG01B_S = 5 * 3600
#: The wait after a turn's second retry ladder: the owner resumes it once more, or stops (§2.5).
OWNER_WORD = "the owner's word: resume once more (owner-resume) or stop at the cap (owner-stop)"
#: The batch a pending turn writes, by the phase that follows it.
WRITES = {
    "W-check-1": "1",
    "W-check-2": "2",
    "W-check-s": "s",
    "X3-check-s": "s",
    "E-continue": "1",
    "E-check": "2",
    "C-check": "s",
}


class RefusedError(Exception):
    """A step cannot be taken as the sheet says, or an input is not the frozen one."""


def ids_of(batch: str) -> list[str]:
    """A batch's revision ids: ``a01``-``a20``, ``a21``-``a40``, or ``s01``-``s10``."""
    if batch == "s":
        return list(S_IDS)
    first, last = BATCHES[batch]
    return [f"a{k:02d}" for k in range(first, last + 1)]


# ---------------------------------------------------------------- the inputs


def fixed(name: str) -> bytes:
    """One fixed input, as committed."""
    return (AUTHORING / name).read_bytes()


def inputs_record(repo: Path = common.REPO) -> dict[str, str]:
    """Every fixed input and message, with its sha256, held where a frozen digest exists."""
    out = {}
    briefs = R_PG_02 / "briefs"
    pinned = dict(
        line.split()[::-1] for line in (briefs / "BRIEFS.sha256").read_text().splitlines() if line
    )
    for name in COMMONS:
        data = (briefs / "common" / name).read_bytes()
        if common.sha256_bytes(data) != pinned[f"common/{name}"]:
            raise RefusedError(f"{name} is not R-PG-02's frozen file")
        out[name] = common.sha256_bytes(data)
    for name, digest in (CONTINUE_A, CONTINUE_B):
        data = (R_PG_02 / "records" / name).read_bytes()
        if common.sha256_bytes(data) != digest:
            raise RefusedError(f"{name} is not R-PG-02's fixed continuation")
        out[name] = digest
    for name in FIXED:
        out[name] = common.sha256_bytes(fixed(name))
    import sheet_check

    edited, _ = sheet_check.table_facts(repo)
    out["parts_sheet.md"] = common.sha256_bytes(edited)
    if common.sha256_file(GUARD) != GUARD_SHA256:
        raise RefusedError("the guard is not R-PG-02's published guard")
    out["guard.py"] = GUARD_SHA256
    return out


def message_bytes(name: str) -> bytes:
    """A fixed message's bytes, by its name."""
    if name in (CONTINUE_A[0], CONTINUE_B[0]):
        return (R_PG_02 / "records" / name).read_bytes()
    return fixed(name)


# ---------------------------------------------------------------- places and the state


def records_dir() -> Path:
    """The experiment's records: ``~/runs/rpg03``, or the directory a trial names."""
    named = os.environ.get("RP3_RUNS")
    return (
        Path(named) if named else Path(os.environ.get("HOME", "~")).expanduser() / common.RUNS_NAME
    )


def state_path() -> Path:
    """The authoring's state, in the records."""
    return records_dir() / "authoring" / "state.json"


def read_state() -> dict[str, Any]:
    """The authoring's state, or a new one."""
    path = state_path()
    if not path.is_file():
        return {"pairs": {}, "log": [], "stopped": None}
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def write_state(state: dict[str, Any]) -> None:
    """The state, written whole: to a new name, then renamed over."""
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def record(state: dict[str, Any], event: str, **facts: Any) -> None:  # noqa: ANN401
    """One line of the authoring record: every failure, route, resume, replacement and restart."""
    state.setdefault("log", []).append({"utc": common.utc_now(), "event": event, **facts})


def pair_state(state: dict[str, Any], pair: str) -> dict[str, Any]:
    """One author pair's state, made new at its first step."""
    p: dict[str, Any] = state["pairs"].setdefault(
        pair,
        {
            "attempt": 1,
            "restarts": 0,
            "status": "active",
            "sessions": {},
            "batches": {},
            "passed": {},
            "injections": {},
            "replacements": {},
            "x3_used": False,
            "s_status": "pending" if pair == "X" else "none",
        },
    )
    return p


def prepare(root: Path, files: dict[str, bytes]) -> tuple[Path, Path]:
    """A new session's directory: ``scratch/`` with its inputs only, and ``config/`` beside it.

    R-PG-02's sandbox: no user or project settings, no servers, Read, Write and Edit only, and the
    PreToolUse guard, R-PG-02's published file byte for byte, refusing any other path or tool.

    Raises:
        RefusedError: the root exists, or a memory file stands above it (the binary would load it).
    """
    if root.exists():
        raise RefusedError(f"{root.name} exists: a session's directory is always new")
    for parent in [root.resolve().parent, *root.resolve().parents]:
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            if (parent / name).exists():
                raise RefusedError("a memory file stands above the session's directory")
    scratch, config = root / "scratch", root / "config"
    scratch.mkdir(parents=True)
    for rel, data in sorted(files.items()):
        (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
        (scratch / rel).write_bytes(data)
    (config / "home").mkdir(parents=True)
    (config / "claude").mkdir()
    shutil.copyfile(GUARD, config / "guard.py")
    command = f"{sys.executable} -I {config / 'guard.py'} {scratch}"
    settings = {
        "disableAllHooks": False,
        "hooks": {
            "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}]
        },
    }
    (config / "settings.json").write_text(json.dumps(settings, indent=1))
    (config / "mcp.json").write_text(json.dumps({"mcpServers": {}}))
    digests = {rel: common.sha256_bytes(data) for rel, data in sorted(files.items())}
    (root / "inputs.json").write_text(json.dumps(digests, indent=1, sort_keys=True) + "\n")
    (root / "turns").mkdir()
    return scratch, config


def argv(binary: str, config: Path, prompt: str, resume: str | None) -> list[str]:
    """R-PG-02's session command line; the prompt is a fixed message, never a secret."""
    out = [
        binary,
        "-p",
        prompt,
        "--setting-sources",
        "",
        "--settings",
        str(config / "settings.json"),
        "--strict-mcp-config",
        "--mcp-config",
        str(config / "mcp.json"),
        "--tools",
        "Read,Write,Edit",
        "--model",
        common.AUTHOR_MODEL,
        "--max-turns",
        str(MAX_TURNS),
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        "--permission-mode",
        "bypassPermissions",
    ]
    if resume is not None:
        out += ["--resume", resume]
    return out


def env(config: Path) -> dict[str, str]:
    """The session's environment: its own home and config, and the credential from this process."""
    out = {
        "HOME": str(config / "home"),
        "CLAUDE_CONFIG_DIR": str(config / "claude"),
        "PATH": "/usr/bin:/bin",
        "TERM": "dumb",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        common.TOKEN_VARIABLE: os.environ.get(common.TOKEN_VARIABLE, ""),
    }
    for name in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_MAX_RETRIES"):
        if os.environ.get("RP3_SCRIPTED_ENDPOINT") and os.environ.get(name):
            out[name] = os.environ[name]
    return out


def binary() -> str:
    """The pinned binary; on a laptop's scripted endpoint, the macOS build of the same version."""
    path = os.environ.get("PHYSGATE_CLAUDE_BIN", str(Path.home() / "pinned" / "claude-2.1.301"))
    digest = common.sha256_file(Path(path))
    allowed = {common.BINARY_SHA256}
    if os.environ.get("RP3_SCRIPTED_ENDPOINT"):
        allowed.add(common.BINARY_SHA256_MACOS)
    if digest not in allowed:
        raise RefusedError("the binary is not the pinned build")
    return path


def secret_scan(root: Path) -> dict[str, int]:
    """Counts of the credential's value, ``sk-ant-`` and ``oat01`` in every file under ``root``."""
    token = os.environ.get(common.TOKEN_VARIABLE, "").encode()
    counts = {"token_value": 0, "sk_ant_prefix": 0, "oat_prefix": 0, "files_scanned": 0}
    for parts, mode in common.walk_inside(root):
        if not stat.S_ISREG(mode):
            continue
        data = common.read_inside(root, root.joinpath(*parts)) or b""
        counts["files_scanned"] += 1
        if token:
            counts["token_value"] += data.count(token)
        counts["sk_ant_prefix"] += data.count(b"sk-ant-")
        counts["oat_prefix"] += data.count(b"oat01")
    return counts


def turn(root: Path, label: str, message: str, resume: str | None) -> dict[str, Any]:
    """One turn of a session: the message given, the stream kept, the outcome and the scan."""
    config = root / "config"
    data = message_bytes(message) if not message.startswith("/") else Path(message).read_bytes()
    turns = root / "turns"
    n = len(list(turns.glob("*.outcome.json"))) + 1
    stem = turns / f"{n:02d}-{label}"
    (stem.with_suffix(".message.txt")).write_bytes(data)
    stream, err = stem.with_suffix(".stream.jsonl"), stem.with_suffix(".stderr.txt")
    started = common.utc_now()
    with stream.open("wb") as out, err.open("wb") as e:
        proc = subprocess.run(
            argv(binary(), config, data.decode(), resume),
            cwd=root / "scratch",
            env=env(config),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=e,
            check=False,
            timeout=6 * 3600,
        )
    text = stream.read_text(errors="replace")
    end = streams.author_end(text, err.read_text(errors="replace"), proc.returncode)
    result: dict[str, Any] = {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    outcome = {
        "turn": n,
        "label": label,
        "message": message if not message.startswith("/") else Path(message).name,
        "message_sha256": common.sha256_bytes(data),
        "started_utc": started,
        "ended_utc": common.utc_now(),
        "exit": proc.returncode,
        "ended": end["ended"],
        "stream_sha256": common.sha256_file(stream),
        "session_id": result.get("session_id"),
        "num_turns": result.get("num_turns"),
        "tokens": common.result_tokens(text),
        "secret_scan": secret_scan(root),
    }
    stem.with_suffix(".outcome.json").write_text(
        json.dumps(outcome, indent=1, sort_keys=True) + "\n"
    )
    return outcome


# ---------------------------------------------------------------- the audit


def audit(
    root: Path, outcome: dict[str, Any], passed: dict[str, str], fixed_names: set[str]
) -> dict[str, Any]:
    """One turn's audit, from its stream alone; ``failed`` names every failure of §2.5."""
    stem = root / "turns" / f"{outcome['turn']:02d}-{outcome['label']}"
    text = stem.with_suffix(".stream.jsonl").read_text(errors="replace")
    scratch = os.path.realpath(root / "scratch")
    tools: Counter[str] = Counter()
    outside: dict[str, str] = {}
    refused: set[str] = set()
    errors = 0
    models: set[str] = set()
    results: dict[str, bool] = {}
    calls: dict[str, str] = {}
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message: dict[str, Any] = event["message"] if isinstance(event.get("message"), dict) else {}
        content: list[Any] = message["content"] if isinstance(message.get("content"), list) else []
        if event.get("type") == "assistant":
            api_error = event.get("is_api_error_message") is True
            if message.get("model") and not (message["model"] == SYNTHETIC_MODEL and api_error):
                models.add(str(message["model"]))
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                tools[str(block.get("name"))] += 1
                calls[str(block.get("id"))] = str(block.get("name"))
                path = (block.get("input") or {}).get("file_path")
                if isinstance(path, str):
                    resolved = os.path.realpath(os.path.join(scratch, os.path.expanduser(path)))
                    if os.path.commonpath([resolved, scratch]) != scratch:
                        outside[str(block.get("id"))] = path
        elif event.get("type") == "user":
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = str(block.get("tool_use_id"))
                    is_error = bool(block.get("is_error"))
                    results[tid] = is_error
                    if is_error and REFUSAL in json.dumps(block.get("content")):
                        refused.add(tid)
                    elif is_error:
                        errors += 1
    mentions = {w: text.count(w) for w in GATE_WORDS if w in text}
    succeeded_outside = [tid for tid in outside if results.get(tid) is False]
    used_not_allowed = sorted(
        {
            name
            for tid, name in calls.items()
            if name not in ALLOWED_TOOLS and results.get(tid) is False
        }
    )
    copies = rules_check.copies(root / "scratch", passed)
    scan = outcome["secret_scan"]
    failed = []
    if used_not_allowed:
        failed.append("a tool other than Read, Write and Edit was used")
    if succeeded_outside:
        failed.append("a read or write outside the session's directory succeeded")
    if models - {common.AUTHOR_MODEL}:
        failed.append("a model other than the pinned one")
    if scan["token_value"] or scan["sk_ant_prefix"] or scan["oat_prefix"]:
        failed.append("a secret in the session's files")
    if outcome["message"] not in fixed_names and not outcome["message"].startswith("facts"):
        failed.append("a message from anyone but the runner's fixed files")
    if not copies["holds"]:
        failed.append(PASSED_COPY_FAILURE)
    found = {
        "tool_calls": dict(tools),
        "tools_not_allowed_tried": sorted(set(tools) - ALLOWED_TOOLS),
        "tools_not_allowed_used": used_not_allowed,
        "paths_outside_tried": len(outside),
        "paths_outside_succeeded": len(succeeded_outside),
        "guard_refusals": len(refused),
        "other_tool_errors": errors,
        "models": sorted(models),
        "gate_or_answer_mentions": mentions,
        "passed_copies": copies,
        "failed": failed,
    }
    stem.with_suffix(".audit.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


# ---------------------------------------------------------------- the checks


def passed_dir(pair: str, p: dict[str, Any]) -> Path:
    """A pair attempt's record of its passed copies, read-only, never written over (§2.2)."""
    return records_dir() / "authoring" / f"{pair}-{p['attempt']}" / "passed"


def record_passed(pair: str, p: dict[str, Any], scratch: Path, rels: list[str]) -> None:
    """A passed batch's files, copied from the writer's directory into the record, with digests.

    Every corpus and every later session's copies are taken from this record, so the writer
    changing a file afterwards (an audit failure in a later turn) leaves the passed bytes intact.

    Raises:
        RefusedError: a passed file cannot be read, or the record holds it already with other bytes.
    """
    where = passed_dir(pair, p)
    for rel in rels:
        data = common.read_inside(scratch, scratch / rel)
        if data is None:
            raise RefusedError(f"{rel} passed its check but cannot be read")
        dest = where / rel
        if dest.exists():
            if dest.read_bytes() != data:
                raise RefusedError(f"the record holds the passed copy {rel} with other bytes")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            dest.chmod(0o444)
        p["passed"][rel] = common.sha256_bytes(data)


def check_clean(scratch: Path, ids: list[str], sheet: bytes, work: Path) -> list[dict[str, str]]:
    """§2.5 items 1-4 and 6 on the base and the named clean revisions: the bare facts found."""
    from physgate.evaluation.inject.corpus import (
        Base,
        Patch,
        _derivations_hold,
        _numbers,
        name_telltales,
        read_sheet,
    )
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import _gate, check_base, control_id
    from physgate.evaluation.inject.source_check import _check_node
    from physgate.gate.runner import PhysicsGate

    facts: list[dict[str, str]] = []

    def add(check: str, place: str, node: str, quantity: str, message: str) -> None:
        facts.append(rules_check.fact(check, place, node, quantity, message))

    sources = read_sheet(sheet)
    numbers = _numbers(sources)
    by_url: dict[str, list[Any]] = {}
    for row_id, row in sources.rows.items():
        if row_id in numbers:
            by_url.setdefault(row.url, []).append(numbers[row_id])
    for rid in ids:
        # The corpus names each revision's file by its id: the one file name a reviewer is listed.
        if name_telltales(rid):
            add(
                "the loader",
                f"clean/{rid}.json",
                "-",
                "-",
                f"the id holds a telltale word: {name_telltales(rid)}",
            )
    try:
        base = Base.model_validate_json((scratch / "base.json").read_bytes(), strict=False)
        _derivations_hold(numbers, "base", base.nodes, dimension=True)
    except Exception as exc:  # noqa: BLE001 - the loader's refusal is the fact returned
        add("the loader", "base.json", "-", "-", f"the base does not load: {exc}")
        return facts
    given = {n["id"]: n for n in base.nodes}
    gate = PhysicsGate()
    work.mkdir(parents=True, exist_ok=True)
    for r in check_base(base, work / "base", gate).checks:
        if r.outcome == "fail":
            add(f"the gate's {r.name} check", "base.json", r.node or "-", "-", r.message or "fails")
    for payload in base.nodes:
        for f in _check_node("base", payload, numbers, by_url):
            if f.kind == "mismatch":
                add("the source check", "base.json", f.node, f.quantity, f.fact())
    for rid in ids:
        place = f"clean/{rid}.json"
        try:
            raw = json.loads((scratch / "clean" / f"{rid}.json").read_text())
            if raw.get("id") != rid:
                raise ValueError("the file's id is not its name")
            patch = Patch.model_validate(raw["clean"], strict=False)
            _derivations_hold(numbers, rid, patch.nodes, dimension=True)
            for node in patch.nodes:
                before = given.get(node["id"])
                if before is not None and before["kind"] == "interface":
                    raise ValueError(f"{node['id']} rewrites an interface node of the base")
                if before is not None and before["owner_role"] != node["owner_role"]:
                    raise ValueError(f"{node['id']} gives a node of the base another owner")
        except Exception as exc:  # noqa: BLE001 - the loader's refusal is the fact returned
            add("the loader", place, "-", "-", f"the revision does not load: {exc}")
            continue
        # Materialised under a neutral id, as the instrument names a review's place.
        made = materialise(base, patch, work / control_id(0, rid), sheet)
        for r in _gate(gate, made, rid).checks:
            if r.outcome == "fail":
                add(f"the gate's {r.name} check", place, r.node or "-", "-", r.message or "fails")
        for payload in patch.nodes:
            for f in _check_node(f"revision {rid}", payload, numbers, by_url):
                if f.kind == "mismatch":
                    add("the source check", place, f.node, f.quantity, f.fact())
        try:
            require_blind(made, (rid,))
        except Exception as exc:  # noqa: BLE001 - the blindness check's refusal is the fact
            add("the blindness check", place, "-", "-", str(exc))
    found = rules_check.check(scratch, ids, rules_check.Sheet(sheet))
    facts += found["facts"]
    (work / "listed.json").write_text(json.dumps(found["listed"], indent=1) + "\n")
    return facts


def injected_nodes(
    key: str, clean: list[dict[str, Any]], injection: dict[str, Any]
) -> list[dict[str, Any]]:
    """R-PG-02's assembly rule: the revision's nodes in order, each replaced or dropped as told.

    Raises:
        RefusedError: a replacement or a drop names a node the revision does not have, a node
            is both replaced and dropped or replaced twice, or the injection changes nothing.
    """
    ids = [n["id"] for n in clean]
    replace = {n["id"]: n for n in injection.get("replace", [])}
    drop = set(injection.get("drop", []))
    if len(replace) != len(injection.get("replace", [])):
        raise RefusedError(f"{key}: a node is replaced twice")
    unknown = (set(replace) | drop) - set(ids)
    if unknown or set(replace) & drop or not (replace or drop):
        raise RefusedError(
            f"{key}: replace and drop name nodes of the revision, apart, and at least one"
        )
    return [replace.get(i, n) for i, n in zip(ids, clean, strict=True) if i not in drop]


def assemble(
    pair: str,
    batch: str,
    clean_dir: Path,
    injection_dir: Path,
    passed: dict[str, str],
    injections: dict[str, str],
    out: Path,
    sheet: bytes,
    table: bytes,
) -> Path:
    """One batch's corpus, from the passed copies and the recorded injections alone.

    Raises:
        RefusedError: a copy or an injection is not at its recorded digest, or the corpus exists.
    """
    from physgate.evaluation.inject.corpus import manifest_for, write_manifest

    if out.exists():
        raise RefusedError(f"{out.name} exists: a corpus is never written over")

    def held(directory: Path, rel: str, record_: dict[str, str]) -> bytes:
        data = common.read_inside(directory, directory / rel)
        if data is None or common.sha256_bytes(data) != record_.get(rel):
            raise RefusedError(f"{rel} is not at its recorded digest")
        return data

    (out / "artefacts").mkdir(parents=True)
    (out / "base.json").write_bytes(held(clean_dir, "base.json", passed))
    for rid in ids_of(batch):
        c = json.loads(held(clean_dir, f"clean/{rid}.json", passed))
        i = json.loads(held(injection_dir, f"injections/{rid}.json", injections))
        if c.get("id") != rid or i.get("id") != rid:
            raise RefusedError(f"{rid}: a file's id is not its name")
        artefact = {
            "id": rid,
            "error_class": i.get("error_class"),
            "expected_check": i.get("expected_check"),
            "assigned_role": c.get("assigned_role"),
            "description": i.get("description"),
            "edge": i.get("edge"),
            "clean": c.get("clean"),
            "injected": {"nodes": injected_nodes(rid, c["clean"]["nodes"], i)},
        }
        (out / "artefacts" / f"{rid}.json").write_text(json.dumps(artefact, indent=1) + "\n")
    (out / common.TABLE_NAME).write_bytes(table)
    (out / common.SHEET_NAME).write_bytes(sheet)
    name = out.name
    first, last = ids_of(batch)[0], ids_of(batch)[-1]
    label = f"{name}: author pair {pair}'s batch {first} to {last}, with the complete sheet"
    write_manifest(out, manifest_for(out, label=label, author_model=common.AUTHOR_MODEL))
    return out


def check_injections(
    corpus_dir: Path, batch: str, earlier_edges: set[tuple[str, str]], work: Path
) -> list[str]:
    """§2.5 items 1 and 6 on an assembled batch: what fails, never returned to an author."""
    from physgate.evaluation.inject.corpus import load_corpus, require_complete
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import control_id, review_id

    problems: list[str] = []
    try:
        corpus = load_corpus(corpus_dir)
        if batch == "s":
            # The instrument's rule for a corpus of the standard class: that class alone, ten of
            # it, none naming an edge (its loader refuses an edge on any class but propagation).
            require_complete(corpus, per_class=common.PER_CLASS_S)
        else:
            require_complete(corpus, per_class=common.PER_CLASS_BATCH)
            edges = {(a.edge.source, a.edge.target) for a in corpus.artefacts if a.edge is not None}
            if edges & earlier_edges:
                problems.append("an edge of the second batch is one of the first batch's")
    except Exception as exc:  # noqa: BLE001 - the loader's refusal is recorded, never returned
        return [f"the loader or completeness: {type(exc).__name__}"]
    work.mkdir(parents=True, exist_ok=True)
    for a in corpus.artefacts:
        for side, patch, place in (
            ("item", a.injected, review_id(0, a.id)),
            ("twin", a.clean, control_id(0, a.id)),
        ):
            made = materialise(corpus.base, patch, work / place, corpus.parts_sheet)
            try:
                require_blind(made, (a.id, a.description))
            except Exception:  # noqa: BLE001 - recorded by kind only
                problems.append(f"the blindness check on an {side}")
    return problems


def accept(
    corpus_dir: Path,
    batch: str,
    first: Path | None,
    sheet_sha256: str,
    work: Path,
    items: tuple[int, ...] = (1, 2, 3, 4, 5, 6),
) -> dict[str, Any]:
    """§2.5's acceptance checks on one assembled corpus, before its manifest is filled.

    Items 1 to 6 for a corpus of fresh-v2 (item 7, the audits, is the authoring's own record); items
    1, 2, 5 and 6 for a batch of ``fresh-v1c``, which is not authored. Counts only.
    """
    import tempfile as _tempfile

    import sheet_check

    from physgate.evaluation.inject.corpus import load_corpus, name_telltales
    from physgate.evaluation.inject.materialise import materialise
    from physgate.evaluation.inject.runner import _gate, check_base, control_id
    from physgate.evaluation.inject.source_check import check_sources
    from physgate.gate.runner import PhysicsGate

    work.mkdir(parents=True)
    found: dict[str, Any] = {"corpus": corpus_dir.name}
    earlier = edges_of(first) if first is not None else set()
    if 1 in items or 6 in items:
        problems = check_injections(corpus_dir, batch, earlier, work / "packets")
        corpus = load_corpus(corpus_dir)
        named = [a.id for a in corpus.artefacts if name_telltales(a.id)]
        found["item 1 and 6"] = {"problems": problems, "telltale_file_names": len(named)}
    corpus = load_corpus(corpus_dir)
    if 2 in items:
        gate = PhysicsGate()
        fails = sum(
            r.outcome == "fail" for r in check_base(corpus.base, work / "base", gate).checks
        )
        twins = 0
        for a in corpus.artefacts:
            made = materialise(corpus.base, a.clean, work / control_id(0, a.id))
            twins += any(r.outcome == "fail" for r in _gate(gate, made, a.id).checks)
        found["item 2"] = {"base_failing_records": fails, "twins_with_a_failing_record": twins}
    if 3 in items:
        kinds = Counter(f.kind for f in check_sources(corpus))
        found["item 3"] = {k: kinds.get(k, 0) for k in ("mismatch", "subtracted", "unresolved")}
    if 4 in items:
        author = work / "author-form"
        (author / "clean").mkdir(parents=True)
        shutil.copyfile(corpus_dir / "base.json", author / "base.json")
        for a in corpus.artefacts:
            rev = {
                "id": a.id,
                "assigned_role": a.assigned_role,
                "clean": {"nodes": list(a.clean.nodes)},
            }
            (author / "clean" / f"{a.id}.json").write_text(json.dumps(rev))
        got = rules_check.check(
            author, [a.id for a in corpus.artefacts], rules_check.Sheet(corpus.parts_sheet)
        )
        found["item 4"] = {
            "facts": len(got["facts"]),
            "listed": {k: len(v) for k, v in got["listed"].items()},
        }
    if 5 in items:
        found["item 5"] = sheet_check.corpus_check(
            common.REPO, corpus_dir, sheet_sha256, work / "sheet"
        )
    if 6 in items:
        scan = sys.modules.get("rpg02_r3") or _load_r3()
        root = Path(_tempfile.mkdtemp(prefix="rp3a-")) / "no-review-root-yet"
        r3 = scan.scan(common.REPO, [root], {corpus_dir.name: corpus_dir}, [])
        found["item 6 R3"] = {
            "problems": r3["problems"],
            "library_files_checked": r3["library_files_checked"],
        }
    holds = True
    if "item 1 and 6" in found:
        holds &= (
            not found["item 1 and 6"]["problems"]
            and not found["item 1 and 6"]["telltale_file_names"]
        )
    if "item 2" in found:
        holds &= found["item 2"] == {"base_failing_records": 0, "twins_with_a_failing_record": 0}
    if "item 3" in found:
        holds &= found["item 3"]["mismatch"] == 0
    if "item 4" in found:
        holds &= found["item 4"]["facts"] == 0
    if "item 5" in found:
        holds &= bool(found["item 5"]["holds"])
    if "item 6 R3" in found:
        holds &= not found["item 6 R3"]["problems"]
    found["manifest_sha256"] = corpus.manifest_sha256
    found["holds"] = bool(holds)
    return found


def _load_r3() -> Any:  # noqa: ANN401 - a module
    import importlib.util

    path = common.REPO / "experiments" / "R-PG-02" / "r3_scan.py"
    spec = importlib.util.spec_from_file_location("rpg02_r3", path)
    if spec is None or spec.loader is None:
        raise ImportError("R-PG-02's r3_scan.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rpg02_r3"] = module
    spec.loader.exec_module(module)
    return module


def edges_of(corpus_dir: Path) -> set[tuple[str, str]]:
    """A corpus's propagation edges."""
    from physgate.evaluation.inject.corpus import load_corpus

    return {(a.edge.source, a.edge.target) for a in load_corpus(corpus_dir).artefacts if a.edge}


# ---------------------------------------------------------------- the sheet of steps


def sheet_bytes(repo: Path = common.REPO) -> tuple[bytes, bytes]:
    """The authors' table (edited) and the reviewers' sheet at "Sheet filled"'s digest.

    Raises:
        RefusedError: "Sheet filled" is not on record, or the sheet is not at its digest.
    """
    import sheet_check

    edited, _ = sheet_check.table_facts(repo)
    filled = common.need_fill(common.fills_on(repo, "origin/master"), "sheet")
    path = records_dir() / "sheet" / common.SHEET_NAME
    data = common.read_own(path)
    if data is None or common.sha256_bytes(data) != filled.get("sha256"):
        raise RefusedError("the reviewers' sheet in the records is not \"Sheet filled\"'s")
    return edited, data


def session_files(
    kind: str, p: dict[str, Any], pair: str, repo: Path = common.REPO
) -> dict[str, bytes]:
    """A session's inputs, each its own copy.

    Its brief as ``brief.md``, the commons, the rules and the table; and for an error session, C
    or X3, its own copies of the pair's passed files, from the pair's record of passed copies, each
    held to its recorded digest.
    """
    import sheet_check

    briefs = R_PG_02 / "briefs" / "common"
    files = {name: (briefs / name).read_bytes() for name in COMMONS}
    files["rules.md"] = fixed("rules.md")
    files["parts_sheet.md"] = sheet_check.table_facts(repo)[0]
    files["brief.md"] = fixed(
        {"W": "brief_A.md", "E": "brief_B.md", "C": "brief_C.md", "X3": "brief_A.md"}[kind]
    )
    if kind in ("E", "X3", "C"):
        src = passed_dir(pair, p)
        wanted = ["base.json"]
        if kind in ("E", "X3"):
            wanted += [f"clean/{i}.json" for i in ids_of("1") + ids_of("2")]
        if kind == "C":
            wanted += [f"clean/{i}.json" for i in S_IDS]
        for rel in wanted:
            data = common.read_inside(src, src / rel)
            if data is None or common.sha256_bytes(data) != p["passed"].get(rel):
                raise RefusedError(f"the passed copy {rel} is not at its recorded digest")
            files[rel] = data
    if kind == "C":
        import reality

        for role in common.ROLES:
            files[f"standards/{role}.md"] = reality.standards(repo, role)
    return files


def status(state: dict[str, Any]) -> dict[str, Any]:
    """The state, counts only."""
    return {
        "stopped": state.get("stopped"),
        "pairs": {
            pair: {
                k: p[k]
                for k in ("attempt", "restarts", "status", "x3_used", "s_status", "replacements")
            }
            | {"batches": p["batches"], "sessions": sorted(p["sessions"])}
            for pair, p in state["pairs"].items()
        },
        "events": len(state.get("log", [])),
        "waiting": state.get("waiting"),
    }


def runs_allowed(now: float | None = None) -> None:
    """§10 item 3: at least 5 hours after R-PG-01b's last session; never beside a block.

    Raises:
        RefusedError: R-PG-01b's lines are not in the ledger, its last ended under 5 hours ago, or a
            block attempt is open.
    """
    import ledger

    lines = ledger.read(records_dir() / ledger.LEDGER_NAME)
    rpb = [x for x in lines if str(x.get("kind", "")).startswith("rpg01b")]
    if not rpb:
        raise RefusedError(
            "R-PG-01b's lines are not in the ledger: the authoring starts after them"
        )
    last = max(ledger.seconds(x.get("ended_utc") or x["started_utc"]) for x in rpb)
    now = time.time() if now is None else now
    if now < last + AFTER_RPG01B_S:
        raise RefusedError("R-PG-01b's last session ended less than 5 hours ago (§10 item 3)")
    blocks = common.read_own(records_dir() / "blocks.json")
    if blocks and any(a.get("valid") is None for a in json.loads(blocks).get("attempts", [])):
        raise RefusedError("a block attempt is open: the authoring never overlaps a block")


def next_step(state: dict[str, Any]) -> dict[str, Any]:
    """The one next step of the sheet, taken: for the first pair not done, its phase's action."""
    if state.get("stopped"):
        return {"step": "stopped for the owner", "why": state["stopped"]}
    for pair in PAIRS:
        p = pair_state(state, pair)
        if p["status"] in ("done", "cap"):
            continue
        return _pair_step(state, pair, p)
    return {"step": "done: every pair's batches have passed or reached their caps"}


#: Each phase's action, and the phase that follows a turn of it (§2.2's order).
TURN_PHASES = {
    "W-launch": ("W", "launch", "launch.txt", "W-check-1"),
    "W-continue": ("W", "continue", CONTINUE_A[0], "W-check-2"),
    "W-third": ("W", "third", "continue_third.txt", "W-check-s"),
    "X3-launch": ("X3", "launch", "launch_X3.txt", "X3-check-s"),
    "E-launch": ("E", "launch", "launch.txt", "E-continue"),
    "E-continue": ("E", "continue", CONTINUE_B[0], "E-check"),
    "C-launch": ("C", "launch", "launch.txt", "C-check"),
}
#: The clean checks: the session, the batch, and the phase after a pass.
CHECK_PHASES = {
    "W-check-1": ("W", "1"),
    "W-check-2": ("W", "2"),
    "W-check-s": ("W", "s"),
    "X3-check-s": ("X3", "s"),
}


def _after_clean_pass(pair: str, phase: str) -> str:
    if phase == "W-check-1":
        return "W-continue"
    if phase == "W-check-2":
        return "W-third" if pair == "X" else "E-launch"
    return "E-launch"


def _pair_step(state: dict[str, Any], pair: str, p: dict[str, Any]) -> dict[str, Any]:
    phase = p.setdefault("phase", "W-launch")
    pend = p.get("pending")
    if pend is not None:
        return _resolve(state, pair, p, pend)
    if phase in TURN_PHASES:
        role, label, message, after = TURN_PHASES[phase]
        if phase.endswith("launch"):
            out = _launch(state, pair, p, role, message)
        else:
            out = _turn(state, pair, p, role, label, message)
        p["pending"] = {
            "role": role,
            "label": label,
            "next": after,
            "usage_cut": False,
            "infra": 0,
            "ladders": 1,
        }
        return out
    if phase in CHECK_PHASES:
        role, batch = CHECK_PHASES[phase]
        return _clean_batch(state, pair, p, role, batch, phase)
    if phase == "E-check":
        return _check_errors(state, pair, p, "E", ["1", "2"])
    if phase == "C-check":
        return _check_errors(state, pair, p, "C", ["s"])
    p["status"] = "done"
    record(state, "pair done", pair=pair, s_status=p["s_status"])
    return {"step": "pair done", "pair": pair, "s_status": p["s_status"]}


def _resolve(
    state: dict[str, Any], pair: str, p: dict[str, Any], pend: dict[str, Any]
) -> dict[str, Any]:
    """The turn that just ran: resumed if it was cut short, routed if its audit failed.

    A turn and every resume of it are one turn (§2.5), so an audit failure in a part that was cut
    is carried until the turn ends and routed then, with the failures of the rest. A passed copy
    is judged at the turn's end alone, so that failure is not carried from a cut part.
    """
    role = pend["role"]
    s = p["sessions"][role]
    last = s["last"]
    if last["ended"] in ("usage_limit", "infrastructure"):
        carried = pend.setdefault("cut_failed", [])
        for f in last.get("audit_failed") or []:
            if f != PASSED_COPY_FAILURE and f not in carried:
                carried.append(f)
    if last["ended"] == "usage_limit":
        if pend["usage_cut"] or s["usage_resumes"] >= MAX_USAGE_RESUMES:
            record(state, "a usage limit counted as an audit failure", pair=pair, session=role)
            p["pending"] = None
            why = "a usage-limit cut twice in one turn, or past 2"
            return _route(state, pair, p, role, pend, "; ".join([*pend["cut_failed"], why]))
        if not _released(state, "the usage limit's reset (authoring.sh limit-reset)", pair, role):
            return {"step": "waiting", "for": state["waiting"]["for"]}
        pend["usage_cut"] = True
        s["usage_resumes"] += 1
        record(state, "resume after a usage limit", pair=pair, session=role)
        return _turn(state, pair, p, role, f"resume-{pend['label']}", "resume.txt")
    if last["ended"] == "infrastructure":
        n, ladders = pend["infra"], pend["ladders"]
        if n >= 3 * ladders or (ladders > 2 and n >= 6):
            why = (
                "the owner's word that the service is back (authoring.sh service-back)"
                if ladders == 1
                else OWNER_WORD
            )
            if not _released(state, why, pair, role):
                return {"step": "waiting", "for": why}
            pend["ladders"] = ladders + 1
        delay = INFRA_LADDER[min(n % 3, 2)] if pend["ladders"] <= 2 else 0.0
        if not os.environ.get("RP3_NO_WAIT"):
            time.sleep(delay)
        pend["infra"] = n + 1
        record(state, "resume after an infrastructure cut", pair=pair, session=role, delay_s=delay)
        return _turn(state, pair, p, role, f"resume-{pend['label']}", "resume.txt")
    p["pending"] = None
    carried = pend.get("cut_failed") or []
    failed = [*carried, *(f for f in last.get("audit_failed") or [] if f not in carried)]
    if failed:
        return _route(state, pair, p, role, pend, "; ".join(failed))
    p["phase"] = pend["next"]
    return {"step": "turn resolved", "pair": pair, "session": role, "next": p["phase"]}


def owner_stop(state: dict[str, Any], batch: str) -> dict[str, Any]:
    """The owner stops the authoring as at the cap of the batch the waiting turn writes (§2.5).

    Only after a turn's second retry ladder is spent may the owner stop it, and only at the cap of
    the batch that turn writes: the primary's cap stops the authoring for the owner;
    ``fresh-v2-s``'s leaves the standard class not run, and the primary goes on (the writer's
    phase moves on to its error session, or C's pair is done).

    Raises:
        RefusedError: nothing waits for the owner's word, or the waiting turn writes another batch.
    """
    waiting = state.get("waiting") or {}
    if waiting.get("for") != OWNER_WORD:
        raise RefusedError(
            "the owner stops at a cap only where a turn waits for the owner's word after its "
            "second retry ladder (§2.5)"
        )
    pair = waiting["pair"]
    p = state["pairs"][pair]
    pend = p.get("pending") or {}
    written = WRITES.get(pend.get("next", ""))
    if written != batch:
        raise RefusedError(f"the waiting turn writes batch {written}, not batch {batch}")
    state["waiting"] = None
    if batch == "s":
        p["s_status"] = "cap"
        p["pending"] = None
        p["phase"] = "done" if pend["role"] == "C" else "E-launch"
        record(state, "owner-stop", pair=pair, batch="s", why="fresh-v2-s's cap: not run")
        return {"owner-stop": "s", "pair": pair, "standard class": "not run"}
    p["status"] = "cap"
    state["stopped"] = f"the owner stopped the authoring at the primary's cap (batch {batch})"
    record(state, "owner-stop", pair=pair, batch=batch)
    return {"stopped": state["stopped"]}


def _released(state: dict[str, Any], why: str, pair: str, role: str) -> bool:
    """Whether the runner or the owner has released this wait; if not, the wait is recorded."""
    waiting = state.get("waiting")
    if waiting is not None and waiting.get("for") == why and waiting.get("released"):
        state["waiting"] = None
        return True
    state["waiting"] = {"for": why, "pair": pair, "session": role}
    return False


def _route(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, pend: dict[str, Any], why: str
) -> dict[str, Any]:
    """§2.5's route for an audit failure: by the session and the turn it falls in."""
    if role == "W":
        if pend["next"] == "W-check-s" or p["phase"] == "W-check-s":
            return _s_route(state, pair, p, f"the writer's audit failed in its s turn: {why}")
        return _restart(state, pair, p, f"the writer's audit failed in a primary turn: {why}")
    if role == "X3":
        p["s_status"] = "cap"
        p["phase"] = "E-launch"
        record(state, "cap", pair=pair, batch="s", why=f"X3's audit failed: {why}")
        return {"step": "the standard class is not run (X3's audit failed)"}
    return _replace(state, pair, p, role, f"the {role} session's audit failed: {why}")


def _launch(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, message: str
) -> dict[str, Any]:
    k = p["replacements"].get(role, 0) + 1
    base = records_dir() / "authoring" / f"{pair}-{p['attempt']}"
    name = {"W": f"{pair}1", "E": f"{pair}2", "C": "C", "X3": "X3"}[role]
    root = base / f"{name}-{k}"
    prepare(root, session_files(role, p, pair))
    p["sessions"][role] = {"root": str(root), "session_id": None, "turns": 0, "usage_resumes": 0}
    record(state, "launch", pair=pair, attempt=p["attempt"], session=name, k=k)
    return _turn(state, pair, p, role, "launch", message)


def _turn(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, label: str, message: str
) -> dict[str, Any]:
    s = p["sessions"][role]
    root = Path(s["root"])
    outcome = turn(root, label, message, s["session_id"])
    s["session_id"] = s["session_id"] or outcome["session_id"]
    s["turns"] += 1
    given = json.loads((root / "inputs.json").read_text())
    passed = {rel: d for rel, d in p["passed"].items() if role == "W" or rel in given}
    fixed_names = {*FIXED, CONTINUE_A[0], CONTINUE_B[0]}
    found = audit(root, outcome, passed, fixed_names)
    s["last"] = {
        "label": label,
        "ended": outcome["ended"],
        "turn": outcome["turn"],
        "audit_failed": found["failed"],
    }
    record(
        state,
        "turn",
        pair=pair,
        session=role,
        label=label,
        ended=outcome["ended"],
        audit_failed=found["failed"],
        tokens=outcome["tokens"],
    )
    return {
        "step": "turn",
        "pair": pair,
        "session": role,
        "label": label,
        "ended": outcome["ended"],
        "audit": {k: found[k] for k in ("tool_calls", "guard_refusals", "models", "failed")},
    }


def _restart(state: dict[str, Any], pair: str, p: dict[str, Any], why: str) -> dict[str, Any]:
    if p["restarts"] >= MAX_RESTARTS:
        p["status"] = "cap"
        state["stopped"] = (
            f"pair {pair}'s restarts are spent ({why}): the authoring stops for the owner"
        )
        record(state, "cap", pair=pair, why=why)
        return {"step": "stopped for the owner", "why": state["stopped"]}
    p["restarts"] += 1
    p["attempt"] += 1
    p.update(
        sessions={},
        batches={},
        passed={},
        injections={},
        replacements={},
        x3_used=False,
        phase="W-launch",
        pending=None,
    )
    p["s_status"] = "pending" if pair == "X" else "none"
    record(state, "restart", pair=pair, attempt=p["attempt"], why=why)
    return {"step": "restart", "pair": pair, "attempt": p["attempt"], "why": why}


def _replace(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, why: str
) -> dict[str, Any]:
    used = p["replacements"].get(role, 0)
    if used >= MAX_REPLACEMENTS:
        record(state, "cap", pair=pair, session=role, why=why)
        if role == "C":
            p["s_status"] = "cap"
            p["phase"] = "done"
            return {"step": "the standard class is not run (C's replacements are spent)"}
        p["status"] = "cap"
        state["stopped"] = (
            f"pair {pair}'s error session's replacements are spent: the authoring stops for the "
            "owner"
        )
        return {"step": "stopped for the owner", "why": state["stopped"]}
    p["replacements"][role] = used + 1
    p["sessions"].pop(role, None)
    p["phase"] = f"{role}-launch"
    record(state, "replace", pair=pair, session=role, replacement=used + 1, why=why)
    return {"step": "replace", "pair": pair, "session": role, "why": why}


def _clean_batch(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, batch: str, phase: str
) -> dict[str, Any]:
    """A clean batch's check: the copies recorded, or the bare facts back, or its route."""
    s = p["sessions"][role]
    root = Path(s["root"])
    key = f"{role}:{batch}"
    b = p["batches"].setdefault(key, {"status": "written", "fact_rounds": 0, "checks": 0})
    _, sheet = sheet_bytes()
    ids = ids_of(batch)
    facts = check_clean(
        root / "scratch", ids, sheet, root / "checks" / f"{batch}-{b['checks'] + 1}"
    )
    b["checks"] += 1
    if not facts:
        b["status"] = "passed"
        rels = [f"clean/{i}.json" for i in ids] + (["base.json"] if batch == "1" else [])
        record_passed(pair, p, root / "scratch", rels)
        if batch == "s":
            p["s_source"] = str(root)
            p["s_status"] = "clean passed"
        p["phase"] = _after_clean_pass(pair, phase)
        record(state, "batch passed", pair=pair, session=role, batch=batch, checks=b["checks"])
        return {"step": "check", "pair": pair, "batch": batch, "passed": True}
    record(state, "batch failed its check", pair=pair, session=role, batch=batch, facts=len(facts))
    if b["fact_rounds"] >= MAX_FACT_ROUNDS:
        b["status"] = "failed"
        if role == "X3":
            p["s_status"] = "cap"
            p["phase"] = "E-launch"
            record(
                state, "cap", pair=pair, batch="s", why="X3's batch failed after its 4th fact round"
            )
            return {"step": "the standard class is not run (X3's batch failed)"}
        if batch == "s":
            return _s_route(state, pair, p, "the s batch failed its check after its 4th fact round")
        return _restart(state, pair, p, f"batch {batch} failed its check after its 4th fact round")
    b["fact_rounds"] += 1
    (root / "checks").mkdir(exist_ok=True)
    path = root / "checks" / f"facts-{batch}-{b['fact_rounds']}.txt"
    path.write_text(rules_check.message(facts))
    (path.with_suffix(".json")).write_text(json.dumps(facts, indent=1) + "\n")
    b["status"] = "facts"
    out = _turn(state, pair, p, role, f"facts-{batch}-{b['fact_rounds']}", str(path))
    p["pending"] = {
        "role": role,
        "label": f"facts-{batch}-{b['fact_rounds']}",
        "next": phase,
        "usage_cut": False,
        "infra": 0,
        "ladders": 1,
    }
    out["facts_forwarded"] = [rules_check.fact_line(f) for f in facts]
    return out


def _s_route(state: dict[str, Any], pair: str, p: dict[str, Any], why: str) -> dict[str, Any]:
    if p["x3_used"]:
        p["s_status"] = "cap"
        p["phase"] = "E-launch"
        record(state, "cap", pair=pair, batch="s", why=why)
        return {"step": "the standard class is not run (X3 has run)", "why": why}
    p["x3_used"] = True
    p["phase"] = "X3-launch"
    record(state, "X3", pair=pair, why=why)
    return {"step": "route to X3", "why": why}


def _check_errors(
    state: dict[str, Any], pair: str, p: dict[str, Any], role: str, batches: list[str]
) -> dict[str, Any]:
    """The error session has ended: its injections recorded, each batch assembled and checked."""
    from physgate.evaluation.inject.corpus import load_corpus

    s = p["sessions"][role]
    root = Path(s["root"])
    table, sheet = sheet_bytes()
    record_: dict[str, str] = {}
    for batch in batches:
        for rid in ids_of(batch):
            rel = f"injections/{rid}.json"
            data = common.read_inside(root / "scratch", root / "scratch" / rel)
            if data is None:
                return _replace(state, pair, p, role, f"{rel} was not written")
            record_[rel] = common.sha256_bytes(data)
    k = p["replacements"].get(role, 0) + 1
    sets = records_dir() / "authoring" / f"{pair}-{p['attempt']}" / f"sets-{role}-{k}"
    problems: list[str] = []
    earlier: set[tuple[str, str]] = set()
    built: dict[str, Path] = {}
    for batch in batches:
        name = "fresh-v2-s" if batch == "s" else f"fresh-v2-{pair.lower()}{batch}"
        out = assemble(
            pair,
            batch,
            passed_dir(pair, p),
            root / "scratch",
            p["passed"],
            record_,
            sets / name,
            sheet,
            table,
        )
        problems += check_injections(out, batch, earlier, sets / f"work-{name}")
        if not problems and batch == "1":
            earlier = edges_of(out)
        built[name] = out
    if problems:
        return _replace(state, pair, p, role, "; ".join(sorted(set(problems))))
    p["injections"]["s" if batches == ["s"] else "primary"] = record_
    for name, out in built.items():
        final = records_dir() / "sets" / name
        if final.exists():
            raise RefusedError(f"{name} exists in the sets: a corpus is assembled once")
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(out, final)
    if batches == ["s"]:
        p["s_status"] = "passed"
        p["phase"] = "done"
    else:
        p["phase"] = "C-launch" if pair == "X" and p["s_status"] == "clean passed" else "done"
    record(state, "injections passed", pair=pair, session=role, corpora=sorted(built))
    return {
        "step": "corpora assembled",
        "pair": pair,
        "manifests": {n: load_corpus(records_dir() / "sets" / n).manifest_sha256 for n in built},
    }


def prove(out: Path) -> dict[str, Any]:
    """The sandbox proven on the scripted endpoint before any launch (§2.2): no model is called.

    Two sessions of the pinned binary run one scripted turn each, with a dummy credential: the
    sandbox as every author session runs it, and a control with no guard. The script tries every
    way out: a file outside by its absolute path, through ``..``, through a symlink inside, through
    ``~``; a write and an edit outside; the shell and the web; and one read inside. The sandbox
    holds if every way out is refused or unavailable under the guard, the read inside works, and
    the control shows the same reads reaching the file (so the probe can see a hole).
    """
    for extra in (common.REPO / "tests" / "integration" / "orchestrator",):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    import scripted_endpoint as endpoint

    if out.exists():
        raise RefusedError("the proof's directory exists: a proof is never written over")
    outside = out / "outside"
    outside.mkdir(parents=True)
    planted = outside / "planted.txt"
    planted.write_text("A PLANTED FILE OUTSIDE\n")
    found: dict[str, Any] = {}
    for kind in ("guarded", "control"):
        root = out / kind
        prepare(root, {"brief.md": b"THE BRIEF\n"})
        if kind == "control":
            (root / "config" / "settings.json").write_text(json.dumps({"disableAllHooks": False}))
        (root / "scratch" / "link.txt").symlink_to(planted)
        (root / "config" / "home" / "planted.txt").write_text("A PLANTED FILE IN HOME\n")
        rel = os.path.relpath(planted, root / "scratch")
        script = endpoint.Script(
            main=[
                endpoint.tool("Read", file_path=str(planted)),
                endpoint.tool("Read", file_path="{cwd}/" + rel),
                endpoint.tool("Read", file_path="{cwd}/link.txt"),
                endpoint.tool("Read", file_path="~/planted.txt"),
                endpoint.tool(
                    "Write", file_path=str(outside / "new.txt"), content="written outside"
                ),
                endpoint.tool(
                    "Edit", file_path=str(planted), old_string="PLANTED", new_string="EDITED"
                ),
                endpoint.tool("Bash", command="echo shell"),
                endpoint.tool("WebFetch", url="https://example.invalid/", prompt="fetch"),
                endpoint.tool("Read", file_path="{cwd}/brief.md"),
                endpoint.text("done"),
            ]
        )
        saved = {
            k: os.environ.get(k)
            for k in (
                "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_MAX_RETRIES",
                "RP3_SCRIPTED_ENDPOINT",
                common.TOKEN_VARIABLE,
            )
        }
        with endpoint.serving(script) as (api, url):
            os.environ.update(
                ANTHROPIC_BASE_URL=url, CLAUDE_CODE_MAX_RETRIES="0", RP3_SCRIPTED_ENDPOINT="1"
            )
            os.environ[common.TOKEN_VARIABLE] = endpoint.DUMMY_OAUTH_TOKEN
            try:
                outcome = turn(root, "proof", "launch.txt", None)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        text = (root / "turns" / "01-proof.stream.jsonl").read_text(errors="replace")
        reached = text.count("A PLANTED FILE")
        result = audit(
            root,
            {**outcome, "secret_scan": {"token_value": 0, "sk_ant_prefix": 0, "oat_prefix": 0}},
            {},
            {"launch.txt"},
        )
        found[kind] = {
            "binary_exit": outcome["exit"],
            "served": len(api.requests),
            "offered_tools": sorted({t for r in api.requests for t in r.offered_tools}),
            "planted_text_reached_the_model": reached,
            "written_outside": (outside / "new.txt").exists(),
            "planted_edited": "EDITED" in planted.read_text(),
            "inside_read": "THE BRIEF" in text,
            "audit": {
                k: result[k]
                for k in (
                    "paths_outside_tried",
                    "paths_outside_succeeded",
                    "guard_refusals",
                    "tools_not_allowed_used",
                    "failed",
                )
            },
        }
        (outside / "new.txt").unlink(missing_ok=True)
        planted.write_text("A PLANTED FILE OUTSIDE\n")
    g, c = found["guarded"], found["control"]
    found["holds"] = (
        g["planted_text_reached_the_model"] == 0
        and not g["written_outside"]
        and not g["planted_edited"]
        and g["inside_read"]
        and g["audit"]["paths_outside_succeeded"] == 0
        and not g["audit"]["tools_not_allowed_used"]
        and g["offered_tools"] == ["Edit", "Read", "Write"]
        and c["planted_text_reached_the_model"] > 0
    )
    (out / "proof.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


def main(argv_: list[str] | None = None) -> int:
    """One subcommand; counts, exit codes, audit summaries and forwarded facts only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inputs")
    i.add_argument("--out", type=Path)
    sub.add_parser("status")
    sub.add_parser("next")
    pr = sub.add_parser("prove")
    pr.add_argument("--out", type=Path, required=True)
    ac = sub.add_parser("accept")
    ac.add_argument("--corpus", type=Path, required=True)
    ac.add_argument("--batch", choices=("1", "2", "s"), required=True)
    ac.add_argument("--first", type=Path)
    ac.add_argument("--sheet-sha256", required=True)
    ac.add_argument("--work", type=Path, required=True)
    ac.add_argument("--fresh-v1c", action="store_true", help="items 1, 2, 5 and 6 alone")
    sub.add_parser("limit-reset")
    sub.add_parser("service-back")
    sub.add_parser("owner-resume")
    os_ = sub.add_parser("owner-stop")
    os_.add_argument("--batch", choices=("1", "2", "s"), required=True)
    args = parser.parse_args(argv_)
    try:
        if args.cmd == "inputs":
            found: dict[str, Any] = inputs_record()
            if args.out is not None:
                args.out.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
            print(
                json.dumps(
                    {
                        "inputs": len(found),
                        "sha256": hashlib.sha256(
                            json.dumps(found, sort_keys=True).encode()
                        ).hexdigest(),
                    }
                )
            )
            return 0
        if args.cmd == "accept":
            got = accept(
                args.corpus.resolve(),
                args.batch,
                args.first.resolve() if args.first else None,
                args.sheet_sha256,
                args.work.resolve(),
                (1, 2, 5, 6) if args.fresh_v1c else (1, 2, 3, 4, 5, 6),
            )
            print(json.dumps(got, sort_keys=True, default=str))
            return 0 if got["holds"] else 1
        if args.cmd == "prove":
            found = prove(args.out.resolve())
            print(
                json.dumps({k: found[k] for k in ("guarded", "control", "holds")}, sort_keys=True)
            )
            return 0 if found["holds"] else 1
        state = read_state()
        if args.cmd == "status":
            print(json.dumps(status(state), sort_keys=True))
            return 0
        if args.cmd in ("limit-reset", "service-back", "owner-resume"):
            waiting = state.get("waiting")
            if waiting is None:
                raise RefusedError("nothing is waiting")
            waiting["released"] = True
            record(state, args.cmd, waiting=waiting["for"])
            write_state(state)
            print(json.dumps({"released": waiting["for"]}))
            return 0
        if args.cmd == "owner-stop":
            found = owner_stop(state, args.batch)
            write_state(state)
            print(json.dumps(found))
            return 0
        runs_allowed()
        inputs_record()
        found = next_step(state)
        write_state(state)
        print(json.dumps(found, sort_keys=True, default=str))
        return 0 if found["step"] not in ("stopped for the owner",) else 1
    except (RefusedError, common.RefusedError, common.FailClosedError) as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
