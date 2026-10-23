"""R-PG-01b, CRITERIA.md §14: the launch checks L1 to L9 and L11, the slots, and the round's end.

Usage, in the run checkout, as ``launch.sh`` calls it (``uv run --frozen python -I``)::

    checks.py L1 --round <r> [--master-ref <ref>]      the checkout, host, account and slots
    checks.py L2 [--master-ref <ref>]                   the run commit's paths, against master
    checks.py L3 [--master-ref <ref>]                   every pin of §2.2
    checks.py L4 [--master-ref <ref>]                   both arms' corpora
    checks.py L8 --into <new dir>                       R4, by R-PG-01's r4_twins.py
    checks.py L11 --round <r> --smoke <smoke.json> --into <file>
    checks.py start --round <r> --slots <I>,<F> --launch <dir>
    checks.py after --round <r> --launch <dir>          the round's end: §5.5, rubrics, R6, voids
    checks.py stop --round <r> --reason <text>          §12: the experiment stops, for the owner
    checks.py second-arm --launch <dir> --since <utc>   §11's fallback: when the second arm starts
    checks.py stop-sessions --root <dir> [--root ...]   the watcher's abort: the run's sessions

L5 to L7 are ``packets_identity.py``, L9's scans are R-PG-01's ``r3_scan.py`` and ``r3_scan_f.py``,
L10 is ``smoke.py``; ``launch.sh`` runs them. Every check prints one JSON line of counts, digests
and facts, and exits 0 only if it holds. ``--master-ref`` names where the filled CRITERIA.md and
the "scripts" and "sheet" commits are read; it is ``origin/master`` for a run, and ``launch.sh``
takes another only for a check-only trial (``--checks-only``).

The records of the experiment's slots and attempts are ``~/runs/rpg01b/slots.json``; the owner's
statement for a round (the account's label, and the confirmation that no other session runs on
the run account during it) is ``~/runs/rpg01b/owner-<r>.json``, written by the owner before the
round's launch. When §12 stops the experiment (a second cut read in a round, or L10's cut or
inapplicability), the records say so and every later L1 refuses. Nothing here reads a verdict:
the round's end reads causes and counts only (R7).

Only processes this run started are ever signalled, each proven from the run's own records, and
on the run machine alone (Linux): off it, ``stop-sessions`` refuses and signals nothing.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import json
import math
import os
import platform
import random
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

HOME = Path(os.environ.get("HOME", "~")).expanduser()
#: The experiment's records. ``launch.sh`` lets ``RPB_RUNS`` name another only for a check-only
#: trial, so a trial never writes into the run's records.
RUNS = C.records_dir(os.environ.get("RPB_RUNS"), HOME)
SLOTS = RUNS / "slots.json"
#: The run commit may differ from 8bc03fc in these paths alone (§2.4).
ALLOWED_FILES = frozenset(
    {
        "src/physgate/evaluation/inject/corpus.py",
        "src/physgate/evaluation/inject/materialise.py",
        "tests/unit/evaluation/test_a_sheet_row_gives_its_value_as_written_and_its_note.py",
        "tests/unit/evaluation/test_every_review_is_given_the_parts_sheet_its_numbers_cite.py",
    }
)
ALLOWED_DIRS = (f"{C.ARM_F_CORPUS}/", "experiments/R-PG-01b/")
SHEET_COPY = "experiments/R-PG-01b/sheet/"


class Refused(Exception):
    """A launch check does not hold."""


def utc() -> str:
    """The time now, UTC, to the second."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _equal(found: dict[str, Any], name: str, have: object, want: object) -> None:
    found[name] = have
    if have != want:
        raise Refused(f"{name} is {have}, not {want}")


# ---- the slots (§2.6) ----


def draw_slots() -> dict[str, int]:
    """§2.6's draw: slots 1 to 4 for (I, 1), (F, 1), (I, 2), (F, 2), with ``random.Random(29)``."""
    slots = [1, 2, 3, 4]
    random.Random(C.SLOT_SEED).shuffle(slots)
    return dict(zip(("I1", "F1", "I2", "F2"), slots, strict=True))


def read_slots(path: Path | None = None) -> dict[str, Any]:
    """The slot records, or none yet."""
    path = SLOTS if path is None else path
    return json.loads(path.read_text()) if path.is_file() else {}


def write_slots(records: dict[str, Any]) -> None:
    """The slot records, written whole."""
    SLOTS.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n")


def refuse_if_stopped(records: dict[str, Any]) -> None:
    """§12: once the experiment has stopped, no round starts; the owner decides.

    Raises:
        Refused: the records say the experiment stopped.
    """
    stopped = records.get("stopped")
    if stopped:
        raise Refused(
            f"the experiment has stopped: {stopped.get('reason')} (§12); the owner decides"
        )


def stop(r: int, reason: str) -> dict[str, Any]:
    """Record that §12 stops the experiment, in round ``r``, for ``reason``."""
    records = read_slots()
    records.setdefault("stopped", {"round": r, "reason": reason, "utc": utc()})
    RUNS.mkdir(parents=True, exist_ok=True)
    write_slots(records)
    return {"check": "stop", "stopped": records["stopped"]}


def slots_for(records: dict[str, Any], r: int) -> dict[str, int]:
    """The slots the next attempt of round ``r`` takes (§2.6).

    The first attempt takes the drawn slots. A re-attempt takes the next unused slots from 5 up,
    the two arms in the order of their first slots.
    """
    draw = records["draw"]
    attempts = [a for a in records.get("attempts", []) if a["round"] == r]
    if not attempts:
        return {"I": draw[f"I{r}"], "F": draw[f"F{r}"]}
    used = set(draw.values()) | {s for a in records["attempts"] for s in a["slots"].values()}
    free = [k for k in range(5, 5 + len(used) + 3) if k not in used][:2]
    first = sorted(("I", "F"), key=lambda arm: draw[f"{arm}{r}"])
    return {first[0]: free[0], first[1]: free[1]}


def arm_order() -> list[str]:
    """§11's fallback: the order the two arms of a round run in, by ``random.Random(31)``."""
    order = list(C.ARMS)
    random.Random(C.ARM_ORDER_SEED).shuffle(order)
    return order


def usage_limit_voids(records: dict[str, Any], r: int) -> int:
    """How many of round ``r``'s attempts a usage limit voided."""
    return sum(
        1
        for a in records.get("attempts", [])
        if a["round"] == r and "usage limit" in (a.get("void_causes") or [])
    )


# ---- L1 ----


def token_prefix(env_file: Path) -> str:
    """The first 8 hex digits of the run account's token's sha256; the token is never shown.

    The env file's shape is token.sh's: exactly one line names the variable, and it is the
    name, ``=`` and a value of the token's shape, nothing else (no ``export``, no quotes, no
    space). Nothing of the file is quoted in a refusal.

    Raises:
        Refused: the file is missing or not of that shape.
    """
    if not env_file.is_file():
        raise Refused("the run account's env file is not there")
    lines = env_file.read_text().splitlines()
    named = [ln for ln in lines if C.TOKEN_NAMED.match(ln)]
    shaped = [ln for ln in lines if C.TOKEN_LINE.match(ln)]
    if len(named) != 1 or len(shaped) != 1:
        raise Refused("the env file does not hold exactly one token line of the token's shape")
    return C.sha256_bytes(shaped[0].split("=", 1)[1].encode())[:8]


#: A claude process: the pinned binary or any ``claude`` by its file name, wherever it stands
#: among the first arguments (a holding wrapper puts it after its interpreter).
_CLAUDE = re.compile(r"^claude(-[0-9][\w.]*)?$")


def live_sessions(procs: Iterable[tuple[int, list[str]]]) -> list[int]:
    """The pids among ``procs`` that are a claude process or a ``physgate inject``."""
    found = []
    for pid, argv in procs:
        names = [os.path.basename(a) for a in argv]
        claude = any(_CLAUDE.match(n) for n in names[:4])
        inject = any(
            n == "physgate" and argv[k + 1 : k + 2] == ["inject"] for k, n in enumerate(names)
        )
        if claude or inject:
            found.append(pid)
    return found


def own_processes() -> list[tuple[int, list[str]]]:
    """Every live process of this account on the run machine, with its arguments (``/proc``)."""
    uid = os.getuid()
    found = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == os.getpid():
            continue
        try:
            if d.stat().st_uid != uid:
                continue
            argv = [a.decode(errors="replace") for a in (d / "cmdline").read_bytes().split(b"\0")]
        except OSError:
            continue
        if argv and argv[-1] == "":
            argv.pop()
        if argv:
            found.append((int(d.name), argv))
    return found


def l1(r: int, checkout: Path, master_ref: str, dry: bool) -> dict[str, Any]:
    """L1: the host, the checkout, the account, the owner's word, the slots.

    The checkout is at the tag and at the filled run commit, clean; no claude or inject process
    of the account is alive. A check-only trial (``dry``) never reads the token and writes no
    record.
    """
    found: dict[str, Any] = {"check": "L1", "round": r}
    found["machine"] = {
        "uname": " ".join(platform.uname()),
        "os": _os_release(),
        "git": C.git(checkout, "--version"),
    }
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        raise Refused("the run machine is Oracle's ARM Linux VM (§10)")
    _equal(found, "checkout", str(checkout), str(HOME / C.CHECKOUT_NAME))
    records = read_slots()
    refuse_if_stopped(records)
    alive = live_sessions(own_processes())
    if alive:
        raise Refused(f"{len(alive)} claude or inject process(es) of the run account are alive")
    found["claude_or_inject_processes_alive"] = 0
    C.git(checkout, "fetch", "-q", "--tags", "origin")
    head = C.git(checkout, "rev-parse", "HEAD")
    tag = C.git(checkout, "rev-parse", f"refs/tags/{C.RUN_TAG}^{{commit}}")
    remote = C.git(checkout, "ls-remote", "origin", f"refs/tags/{C.RUN_TAG}").split()
    _equal(found, "head", head, tag)
    _equal(found, "the tag as pushed", remote[0] if remote else None, tag)
    _equal(
        found, "the filled run commit", C.filled_on(checkout, master_ref).get("run_commit"), head
    )
    if C.git(checkout, "status", "--porcelain"):
        raise Refused("the checkout is not clean")
    found["clean"] = True
    found["token_sha256_prefix"] = (
        "not read: checks only" if dry else token_prefix(HOME / C.TOKEN_FILE)
    )
    owner = RUNS / f"owner-{r}.json"
    if not owner.is_file():
        raise Refused(f"no owner statement for round {r} at {owner}")
    said = json.loads(owner.read_text())
    if not str(said.get("account_label", "")).strip():
        raise Refused("the owner statement names no account label")
    if said.get("no_other_session_during_round") is not True:
        raise Refused("the owner has not confirmed that no other session runs during the round")
    found["account_label"] = said["account_label"]
    found["owner_confirmed_no_other_session"] = True
    if not records:
        if r != 1:
            raise Refused("the slots are drawn and recorded before round 1")
        records = {"seed": C.SLOT_SEED, "draw": draw_slots(), "drawn_utc": utc(), "attempts": []}
        if not dry:
            RUNS.mkdir(parents=True, exist_ok=True)
            write_slots(records)
    found["slot_draw"] = records["draw"]
    done = [a for a in records.get("attempts", []) if a["round"] == r]
    if any(a.get("valid") is True for a in done):
        raise Refused(f"round {r} already has a valid attempt")
    if len(done) >= C.MAX_ATTEMPTS:
        raise Refused(f"round {r} has had {len(done)} attempts; at most {C.MAX_ATTEMPTS}")
    if r == 2 and not any(
        a["round"] == 1 and a.get("ended_utc") for a in records.get("attempts", [])
    ):
        raise Refused("round 2 starts after round 1 has ended")
    found["attempt"] = len(done) + 1
    found["slots"] = slots_for(records, r)
    found["sequential"] = usage_limit_voids(records, r) >= 2
    if found["sequential"]:
        found["arm_order"] = arm_order()
    found["master_ref"] = master_ref
    return found


def _os_release() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return platform.platform()


# ---- L2 ----


def last_commit(checkout: Path, ref: str, *paths: str) -> str:
    """The last commit on ``ref`` that changed ``paths``."""
    found = C.git(checkout, "log", "-1", "--format=%H", ref, "--", *paths)
    if not found:
        raise Refused(f"{ref} holds no commit that changed {paths[0]}")
    return found


CRITERIA = "experiments/R-PG-01b/CRITERIA.md"
#: Under experiments/R-PG-01b/, what the "scripts" commit does not decide.
NOT_SCRIPTS = (CRITERIA, "experiments/R-PG-01b/RESULT.md", SHEET_COPY)


def _blobs(checkout: Path, ref: str) -> dict[str, str]:
    """Every blob under experiments/R-PG-01b/ at ``ref`` but CRITERIA.md, RESULT.md and sheet/."""
    out = {}
    for line in C.git(checkout, "ls-tree", "-r", ref, "--", "experiments/R-PG-01b").splitlines():
        meta, _, path = line.partition("\t")
        if not path.startswith(NOT_SCRIPTS):
            out[path] = meta.split()[2]
    return out


def l2(checkout: Path, master_ref: str) -> dict[str, Any]:
    """L2: the run commit differs from 8bc03fc only in §2.4's paths, and they are master's."""
    found: dict[str, Any] = {"check": "L2", "master_ref": master_ref}
    names = C.git(checkout, "diff", "--name-only", C.R_PG_01_COMMIT, "HEAD").splitlines()
    outside = [
        n
        for n in names
        if (n not in ALLOWED_FILES and not n.startswith(ALLOWED_DIRS)) or n.startswith(SHEET_COPY)
    ]
    found["paths_changed"] = len(names)
    _equal(found, "paths outside §2.4", outside, [])
    _equal(
        found,
        "the run commit holds experiments/R-PG-01b/sheet/",
        bool(C.git(checkout, "ls-tree", "HEAD", SHEET_COPY.rstrip("/"))),
        False,
    )
    scripts = last_commit(
        checkout,
        master_ref,
        "experiments/R-PG-01b",
        ":(exclude)experiments/R-PG-01b/CRITERIA.md",
        ":(exclude)experiments/R-PG-01b/sheet",
        ":(exclude)experiments/R-PG-01b/RESULT.md",
    )
    sheet = last_commit(checkout, master_ref, C.ARM_F_CORPUS)
    found["scripts_commit"], found["sheet_commit"] = scripts, sheet
    # Every blob but CRITERIA.md is the last "scripts" commit's; CRITERIA.md is the freeze's, its
    # placeholders included, whatever fills master has had since (§2.4, the file's own preamble).
    have, want = _blobs(checkout, "HEAD"), _blobs(checkout, scripts)
    _equal(
        found,
        "experiments/R-PG-01b blobs that differ from the scripts commit",
        sorted(k for k in have.keys() | want.keys() if have.get(k) != want.get(k)),
        [],
    )
    _equal(
        found,
        "the frozen CRITERIA.md",
        C.git(checkout, "rev-parse", f"HEAD:{CRITERIA}"),
        C.git(checkout, "rev-parse", f"{C.FREEZE_COMMIT}:{CRITERIA}"),
    )
    _equal(
        found,
        "arm F's corpus tree",
        C.git(checkout, "rev-parse", f"HEAD:{C.ARM_F_CORPUS}"),
        C.git(checkout, "rev-parse", f"{sheet}:{C.ARM_F_CORPUS}"),
    )
    return found


# ---- L3 ----


def l3(checkout: Path, master_ref: str, binary: Path) -> dict[str, Any]:
    """L3: every pin of §2.2 at the run commit, the instrument tree §2.4 filled, the binary."""
    found: dict[str, Any] = {"check": "L3"}

    def tree(path: str) -> str:
        return C.git(checkout, "rev-parse", f"HEAD:{path}")

    filled = C.filled_on(checkout, master_ref)
    if "instrument_tree" not in filled:
        raise Refused(f"the instrument tree is not filled in CRITERIA.md at {master_ref}")
    _equal(found, "gate tree", tree("src/physgate/gate"), C.GATE_TREE)
    _equal(found, "bounds blob", tree("knowledge/electrical/bounds.toml"), C.BOUNDS_BLOB)
    _equal(
        found,
        "bounds sha256",
        C.sha256_file(checkout / "knowledge/electrical/bounds.toml"),
        C.BOUNDS_SHA256,
    )
    _equal(found, "spelling blob", tree("src/physgate/unit_spelling.py"), C.SPELLING_BLOB)
    _equal(found, "reviewers tree", tree("src/physgate/reviewers"), C.REVIEWERS_TREE)
    _equal(found, "rubrics tree", tree("knowledge/reviewers"), C.RUBRICS_TREE)
    for role, digest in C.RUBRIC_SHA256.items():
        _equal(
            found,
            f"{role} rubric",
            C.sha256_file(checkout / "knowledge/reviewers" / role / "rubric.md"),
            digest,
        )
    _equal(
        found, "instrument tree", tree("src/physgate/evaluation/inject"), filled["instrument_tree"]
    )
    _equal(found, "params.json blob", tree("experiments/R-PG-01/params.json"), C.PARAMS_BLOB)
    for name, blob in C.R_PG_01_SCRIPTS.items():
        _equal(found, f"R-PG-01 {name}", tree(f"experiments/R-PG-01/{name}"), blob)
    from physgate.gate.catalogue import catalogue_digest

    _equal(found, "catalogue digest", catalogue_digest(), C.CATALOGUE_SHA256)
    import physgate

    where = Path(physgate.__file__).resolve()
    _equal(found, "physgate resolves under the checkout", checkout.resolve() in where.parents, True)
    _equal(found, "binary sha256", C.sha256_file(binary), C.BINARY_SHA256)
    version = (
        subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, check=True, timeout=120
        )
        .stdout.split(" ")[0]
        .strip()
    )
    _equal(found, "binary version", version, C.BINARY_VERSION)
    return found


# ---- L4 ----


def l4(checkout: Path, master_ref: str) -> dict[str, Any]:
    """L4: arm I's manifest; arm F's manifest and sheet, its base and artefacts arm I's."""
    from physgate.evaluation.inject.corpus import load_corpus, require_complete

    found: dict[str, Any] = {"check": "L4"}
    filled = C.filled_on(checkout, master_ref)
    if "arm_f_manifest" not in filled:
        raise Refused(f"arm F's manifest digest is not filled in CRITERIA.md at {master_ref}")
    i, f = checkout / C.ARM_I_CORPUS, checkout / C.ARM_F_CORPUS
    _equal(found, "arm I manifest", C.sha256_file(i / "MANIFEST.json"), C.ARM_I_MANIFEST_SHA256)
    _equal(found, "arm F manifest", C.sha256_file(f / "MANIFEST.json"), filled["arm_f_manifest"])
    _equal(found, "arm F sheet", C.sha256_file(f / "sources.json"), C.ARM_F_SHEET_SHA256)
    ci, cf = load_corpus(i), load_corpus(f)
    require_complete(ci)
    require_complete(cf)
    if "arm_f_label" in filled:
        _equal(found, "arm F label", cf.manifest.label, filled["arm_f_label"])
    same = [rel for rel in ci.manifest.files if rel == "base.json" or rel.startswith("artefacts/")]
    differ = [rel for rel in same if ci.manifest.files[rel] != cf.manifest.files.get(rel)]
    found["base_and_artefacts"] = len(same)
    _equal(found, "base and artefacts that differ", differ, [])
    return found


# ---- L8 ----


def l8(checkout: Path, into: Path) -> dict[str, Any]:
    """L8: R4 by R-PG-01's r4_twins.py, unchanged, on arm I's corpus (one measure for both arms)."""
    done = subprocess.run(
        [
            sys.executable, "-I", str(checkout / "experiments/R-PG-01/r4_twins.py"),
            str(checkout / C.ARM_I_CORPUS), str(into), C.R4_RECORDS_SHA256,
        ],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    found: dict[str, Any] = {"check": "L8", "r4": done.stdout.strip()[-600:]}
    if done.returncode != 0:
        raise Refused(
            f"R4 does not hold: {done.stdout.strip()[-300:]} {done.stderr.strip()[-300:]}"
        )
    return found


# ---- L11 ----


def l11(r: int, smoke: Path, launch: Path) -> dict[str, Any]:
    """L11: T, the projected tokens per review, and 120 x T beside the 80 M carried (§11)."""
    record = json.loads(smoke.read_text()) if smoke.is_file() else {}
    smoke_tokens = int(record.get("smoke_tokens_max") or 0)
    rates = [C.FLOOR_TOKENS_PER_REVIEW, smoke_tokens]
    round_1 = None
    if r == 2:
        round_1 = round_one_rate()
        if round_1 is not None:
            rates.append(round_1)
    t = max(rates)
    found = {
        "check": "L11",
        "round": r,
        "smoke_tokens": smoke_tokens,
        "floor": C.FLOOR_TOKENS_PER_REVIEW,
        "round_1_rate": round_1,
        "T": t,
        "projected_5h": C.REVIEWS_PER_5H * t,
        "carried_in_5h": C.CARRIED_TOKENS,
        "a_gate": False,
    }
    (launch / "l11.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


def round_one_rate() -> int | None:
    """Round 1's measured tokens per review session, from its ledger record, if it has one."""
    path = RUNS / "ledger-round-1.json"
    if not path.is_file():
        return None
    found = json.loads(path.read_text())
    sessions = int(found.get("review_sessions") or 0)
    return round(int(found["review_tokens"]) / sessions) if sessions else None


# ---- the attempt's start and the round's end ----


def start(r: int, slots: dict[str, int], launch: Path) -> dict[str, Any]:
    """Record that round ``r``'s attempt starts now, into ``slots``."""
    records = read_slots()
    attempt = 1 + sum(a["round"] == r for a in records.get("attempts", []))
    row = {
        "round": r,
        "attempt": attempt,
        "slots": slots,
        "launch": str(launch),
        "started_utc": utc(),
    }
    records.setdefault("attempts", []).append(row)
    write_slots(records)
    return {"check": "start", **row}


def log_lines(path: Path) -> tuple[list[dict[str, Any]], int]:
    """A run log's lines, and how many did not parse (:func:`common.read_log`)."""
    return C.read_log(path)


def final_lines(path: Path) -> dict[str, dict[str, Any]]:
    """Each subtask's last review line in a run log (``review_ran`` or ``review_unavailable``)."""
    last: dict[str, dict[str, Any]] = {}
    for line in log_lines(path)[0]:
        if line.get("kind") in ("review_ran", "review_unavailable"):
            last[line["subtask_id"]] = line
    return last


def _final(line: dict[str, Any] | None) -> bool:
    """Whether a subtask's last review line ends its review: a verdict, or no retry to come."""
    if line is None:
        return False
    return line["kind"] == "review_ran" or line.get("retry") is False


def complete(run: Path) -> dict[str, Any]:
    """§12's test of a finished run, whatever its exit.

    Its results file holds 40 rows, and each log plans 40 subtasks and gives every one a final
    review line and a gate line. Anything less is the trace of a crashed or killed process.
    """
    results = run / "results.jsonl"
    rows, broken_rows = log_lines(results)
    found: dict[str, Any] = {"results_rows": len(rows) if results.is_file() else None}
    holds = results.is_file() and len(rows) == C.DENOMINATOR and not broken_rows
    for side, log in (
        ("injected", run / "events.jsonl"),
        ("twin", run / "controls" / "events.jsonl"),
    ):
        lines, broken = log_lines(log)
        planned = [x["subtask_id"] for x in lines if x.get("kind") == "subtask_planned"]
        last = final_lines(log)
        gated = {x["subtask_id"] for x in lines if x.get("kind") == "gate_ran"}
        part = {
            "planned": len(planned),
            "without_a_final_review_line": sum(not _final(last.get(sid)) for sid in planned),
            "without_a_gate_line": sum(sid not in gated for sid in planned),
            "lines_unparsed": broken,
        }
        found[side] = part
        holds = (
            holds
            and log.is_file()
            and part["planned"] == C.DENOMINATOR
            and not (
                part["without_a_final_review_line"]
                or part["without_a_gate_line"]
                or part["lines_unparsed"]
            )
        )
    found["holds"] = bool(holds)
    return found


#: The files the watcher searches for a usage limit, and the words it looks for (§11).
LIMIT_SUFFIXES = (".jsonl", ".json", ".err", ".txt")
LIMIT_WORD = b"usage_limit_reached"
STATUS_429 = re.compile(rb'"api_error_status": *429')


def usage_limit_files(paths: Iterable[Path]) -> tuple[int, int]:
    """The files under ``paths`` that name a usage limit, and the 429 statuses in the streams.

    No symlink is followed, to a directory or a file: only what lies inside each path is read.
    """
    files = statuses = 0
    for root in paths:
        for parts, mode in C.walk_inside(root):
            if not stat.S_ISREG(mode) or Path(parts[-1]).suffix not in LIMIT_SUFFIXES:
                continue
            data = C.read_inside(root, root.joinpath(*parts))
            if data is None:
                continue
            files += LIMIT_WORD in data
            if parts[-1].endswith(".jsonl"):
                statuses += len(STATUS_429.findall(data))
    return files, statuses


def regate_count(checkout: Path, arm: str, run: Path, into: Path) -> int | None:
    """``regate_r6.py``'s count of records that differ on a run, or ``None`` if it did not run."""
    if not (run / "events.jsonl").is_file():
        return None
    done = subprocess.run(
        [
            sys.executable, "-I", str(checkout / "experiments/R-PG-01/regate_r6.py"),
            str(checkout / (C.ARM_I_CORPUS if arm == "I" else C.ARM_F_CORPUS)),
            str(run), str(C.SEED), str(into),
        ],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        return None
    return int(json.loads(done.stdout.strip().splitlines()[-1]).get("differ"))


def cascade(run: Path) -> int:
    """How many reviews of a run end ``review_unavailable`` for infrastructure after their retry."""
    n = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        for line in final_lines(log).values():
            n += (
                line["kind"] == "review_unavailable"
                and line.get("cause") == "infrastructure"
                and line.get("retry") is False
            )
    return n


def rubric_mismatches(run: Path) -> tuple[int, int]:
    """Review lines whose ``rubric_sha256`` is not their role's pinned digest; and lines read."""
    bad = seen = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        lines = log_lines(log)[0]
        role = {
            x["subtask_id"]: x["assigned_role"] for x in lines if x.get("kind") == "subtask_planned"
        }
        for x in lines:
            if x.get("kind") == "review_ran":
                seen += 1
                bad += (x.get("result") or {}).get("rubric_sha256") != C.RUBRIC_SHA256.get(
                    role.get(x["subtask_id"], "")
                )
    return bad, seen


def gate_records(run: Path) -> dict[str, str]:
    """Every gate line's result, as one canonical string per subtask, both logs."""
    out = {}
    for name, log in (("i", run / "events.jsonl"), ("t", run / "controls" / "events.jsonl")):
        for x in log_lines(log)[0]:
            if x.get("kind") == "gate_ran":
                out[f"{name}:{x['subtask_id']}"] = json.dumps(x["result"], sort_keys=True)
    return out


def after(r: int, launch: Path, checkout: Path) -> dict[str, Any]:
    """The round's end (§12, after each round): causes and counts, and the attempt's validity.

    Void causes: a usage limit (the watcher's abort, or this check's own search of both arms' run
    directories and review roots); a crashed or killed process (an exit other than 0 or 1, an arm
    with no exit, or a run that is not :func:`complete`); an infrastructure cascade (3 or more
    reviews of the round); a cut read (§5.5). A second cut read in the same round stops the
    experiment (§12). Deviations, which void nothing here: a rubric digest, and R6.
    """
    import streams as S  # noqa: PLC0415

    records = read_slots()
    attempt = next(
        a for a in reversed(records["attempts"]) if a["round"] == r and a["launch"] == str(launch)
    )
    raw_exits = C.read_own(launch / "exits.json")
    shown = json.loads(raw_exits) if raw_exits else {}
    # An arm §11's fallback never started, after the first arm's abort, has no exit (null).
    exits = {k: v for k, v in shown.items() if v is not None}
    raw_watcher = C.read_own(launch / "watcher.log")
    watcher = raw_watcher.decode(errors="replace") if raw_watcher else ""
    found: dict[str, Any] = {"check": "after", "round": r, "attempt": attempt["attempt"]}
    causes: list[str] = []
    places = {arm: C.places(HOME, slot, RUNS) for arm, slot in attempt["slots"].items()}
    limits, statuses = usage_limit_files(p[k] for p in places.values() for k in ("run", "scratch"))
    found["usage_limit_files"], found["status_429s"] = limits, statuses
    if "ABORT" in watcher or limits:
        causes.append("usage limit")
    if any(int(code) not in (0, 1) for code in exits.values()) or len(exits) != 2:
        causes.append("a crashed or killed process")
    per_arm: dict[str, Any] = {}
    cuts = 0
    gates = {}
    for arm, slot in attempt["slots"].items():
        p = places[arm]
        reads = S.round_counts(p["run"], p["scratch"], arm) if p["run"].is_dir() else {"cut": 0}
        cuts += reads["cut"]
        bad, seen = rubric_mismatches(p["run"])
        done = complete(p["run"])
        differ = regate_count(checkout, arm, p["run"], launch / f"regate-{slot}")
        gates[arm] = gate_records(p["run"])
        per_arm[f"slot {slot}"] = {
            "arm_exit": exits.get(str(slot)),
            "started": str(slot) in exits,
            "complete": done,
            "reads": reads,
            "infrastructure_unavailable": cascade(p["run"]),
            "rubric_lines": seen,
            "rubric_mismatches": bad,
            "regate_differ": differ,
        }
    incomplete = not all(v["complete"]["holds"] for v in per_arm.values())
    if incomplete and "a crashed or killed process" not in causes:
        causes.append("a crashed or killed process")
    infra = sum(v["infrastructure_unavailable"] for v in per_arm.values())
    if infra >= C.CASCADE:
        causes.append("an infrastructure cascade")
    if cuts:
        causes.append("a cut read")
    a, b = gates.values() if len(gates) == 2 else ({}, {})
    found["gate_records_identical_across_arms"] = bool(a) and a == b
    found["per_slot"] = per_arm
    found["void_causes"] = causes
    found["valid"] = not causes
    deviations = []
    if any(v["rubric_mismatches"] for v in per_arm.values()):
        deviations.append("a review line's rubric_sha256 is not its role's pinned digest")
    if any(v["regate_differ"] not in (0, None) for v in per_arm.values()) or (
        found["valid"] and not found["gate_records_identical_across_arms"]
    ):
        deviations.append("the gate's records differ")
    if any(v["complete"]["holds"] and v["regate_differ"] is None for v in per_arm.values()):
        deviations.append("regate_r6.py did not run on a complete run")
    found["deviations"] = deviations
    attempt.update(
        {"ended_utc": utc(), "void_causes": causes, "valid": not causes, "deviations": deviations}
    )
    earlier_cut = any(
        "a cut read" in (x.get("void_causes") or [])
        for x in records["attempts"]
        if x["round"] == r and x is not attempt
    )
    if cuts and earlier_cut:
        reason = f"a second cut read in round {r} (§12)"
        records.setdefault("stopped", {"round": r, "reason": reason, "utc": utc()})
        found["experiment_stopped"] = reason
    write_slots(records)
    (launch / "after.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


# ---- §11's fallback: the second arm, in the next window ----

WINDOW_S = 5 * 3600.0


def second_arm(launch: Path, since: float, now: float | None = None) -> float | None:
    """§11's fallback: the seconds to wait before the second arm starts, or ``None``.

    ``None`` if the first arm's watcher stopped it: the second arm does not start. Else the wait
    until the first 5-hour boundary, counted from ``since`` (the round's first session, L10's
    first smoke), at or after now.
    """
    log = C.read_own(launch / "watcher.log")
    if log is not None and b"ABORT" in log:
        return None
    now = time.time() if now is None else now
    k = max(1, math.ceil((now - since) / WINDOW_S - 1e-9))
    return max(0.0, since + k * WINDOW_S - now)


# ---- the watcher's abort: every session this run started, proven from its own records ----

GRACE_S = 5.0


def _review_roots(roots: Iterable[Path]) -> list[Path]:
    """The roots, each held to a review root's own name (``rpb-<slot>``) and not a symlink.

    Raises:
        Refused: a root is of another form.
    """
    out = []
    for root in roots:
        root = Path(root)
        if not C.ROOT_NAME.fullmatch(root.name) or os.path.islink(root):
            raise Refused(f"{root.name!r} is not a review root of the run's form (rpb-<slot>)")
        out.append(root)
    return out


def proven_session(root: Path, sdir: Path) -> tuple[int, str, str] | None:
    """The session a process record proves this run started and still running, or ``None``.

    The record (``<root>/<session id>/session/process.json``, written by this run's instrument
    when it spawned the session) is read through no symlink and trusted for nothing: its pid
    must be a number above 1 and not this process; its session id the directory's own; and the
    process at that pid must have the recorded start time, carry the recorded session id on its
    command line (the instrument's own test), and lead its own process group.
    """
    from physgate.orchestrator.dispatch import process_group_of  # noqa: PLC0415
    from physgate.orchestrator.processes import is_session  # noqa: PLC0415

    if sdir.name != "session" or sdir.parent.parent != root:
        return None
    raw = C.read_inside(root, sdir / "process.json")
    if raw is None:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict):
        return None
    pid, started, sid = record.get("pid"), record.get("started"), record.get("session_id")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or pid == os.getpid():
        return None
    if not isinstance(started, str) or not isinstance(sid, str):
        return None
    if not C.SESSION_ID.fullmatch(sid) or sdir.parent.name != sid:
        return None
    if not is_session(pid, started, sid) or process_group_of(pid) != pid:
        return None
    return pid, started, sid


def remove_credentials(roots: Iterable[Path]) -> dict[str, int]:
    """Remove every session's credential directory under the review roots, following no symlink.

    The directories are ``<session id>/session/config``. A session directory, a ``session`` or
    a ``config`` that is a symlink is refused and left as it is: nothing outside a root is
    touched.

    Raises:
        Refused: a root is not a review root of the run's form.
    """
    removed = refused = 0
    for root in _review_roots(roots):
        sids, links = C.session_dirs(root)
        refused += links
        for sid in sids:
            done = C.remove_inside(root, (sid, "session", "config"))
            removed += done == "removed"
            refused += done == "refused"
    return {"configs_removed": removed, "refused_symlinks": refused}


def stop_sessions(roots: Iterable[Path]) -> dict[str, Any]:
    """Stop every session the review roots prove still running; remove their credentials.

    A session is signalled only if :func:`proven_session` proves it from the run's own record:
    its group is sent SIGTERM, and SIGKILL after a grace if the same process still leads it.
    Nothing else is signalled. Then :func:`remove_credentials`. On the run machine (Linux)
    alone.

    Raises:
        Refused: not on the run machine, or a root not of the run's form.
    """
    if platform.system() != "Linux":
        raise Refused("sessions are stopped on the run machine alone: nothing signalled here")
    from physgate.orchestrator.dispatch import process_group_of  # noqa: PLC0415
    from physgate.orchestrator.processes import is_session  # noqa: PLC0415

    checked = _review_roots(roots)
    proven: list[tuple[int, str, str]] = []
    not_proven = ended = no_record = 0
    for root in checked:
        for sid in C.session_dirs(root)[0]:
            sdir = root / sid / "session"
            if C.exists_inside(root, sdir / "ended.json"):
                ended += 1
            elif not C.exists_inside(root, sdir / "process.json"):
                no_record += 1
            elif (found := proven_session(root, sdir)) is not None:
                proven.append(found)
            else:
                not_proven += 1
    for pid, _, _ in proven:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + GRACE_S
    while time.monotonic() < deadline and any(is_session(*x) for x in proven):
        time.sleep(0.1)
    killed = 0
    for pid, started, sid in proven:
        if is_session(pid, started, sid) and process_group_of(pid) == pid:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
                killed += 1
    return {
        "check": "stop-sessions",
        "stopped": len(proven),
        "needed_sigkill": killed,
        "not_proven": not_proven,
        "no_record": no_record,
        "already_ended": ended,
        **remove_credentials(checked),
    }


def main(argv: list[str] | None = None) -> int:
    """Run one check; print its JSON line; exit 0 if it holds, 1 if not."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "check",
        choices=(
            "L1", "L2", "L3", "L4", "L8", "L11", "start", "after", "stop", "second-arm",
            "stop-sessions",
        ),
    )  # fmt: skip
    parser.add_argument("--round", type=int, choices=C.ROUNDS)
    parser.add_argument("--master-ref", default="origin/master")
    parser.add_argument("--checks-only", action="store_true")
    parser.add_argument("--into", type=Path)
    parser.add_argument("--smoke", type=Path)
    parser.add_argument("--slots")
    parser.add_argument("--launch", type=Path)
    parser.add_argument("--reason")
    parser.add_argument("--since", help="UTC, as %%Y-%%m-%%dT%%H:%%M:%%SZ")
    parser.add_argument("--root", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    checkout = C.REPO
    binary = Path(os.environ.get("PHYSGATE_CLAUDE_BIN", str(HOME / "pinned/claude-2.1.301")))
    try:
        if args.check == "L1":
            found = l1(args.round, checkout, args.master_ref, args.checks_only)
        elif args.check == "L2":
            found = l2(checkout, args.master_ref)
        elif args.check == "L3":
            found = l3(checkout, args.master_ref, binary)
        elif args.check == "L4":
            found = l4(checkout, args.master_ref)
        elif args.check == "L8":
            found = l8(checkout, args.into)
        elif args.check == "L11":
            found = l11(args.round, args.smoke, args.launch)
        elif args.check == "start":
            i, f = (int(x) for x in args.slots.split(","))
            found = start(args.round, {"I": i, "F": f}, args.launch)
        elif args.check == "stop":
            found = stop(args.round, args.reason)
        elif args.check == "second-arm":
            since = float(calendar.timegm(time.strptime(args.since, "%Y-%m-%dT%H:%M:%SZ")))
            wait = second_arm(args.launch, since)
            found = {"check": "second-arm", "wait_s": None if wait is None else round(wait)}
        elif args.check == "stop-sessions":
            found = stop_sessions(args.root)
        else:
            found = after(args.round, args.launch, checkout)
    except Refused as exc:
        print(json.dumps({"check": args.check, "refused": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(found, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
