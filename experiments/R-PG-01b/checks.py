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

L5 to L7 are ``packets_identity.py``, L9's scans are R-PG-01's ``r3_scan.py`` and ``r3_scan_f.py``,
L10 is ``smoke.py``; ``launch.sh`` runs them. Every check prints one JSON line of counts, digests
and facts, and exits 0 only if it holds. ``--master-ref`` names where the filled CRITERIA.md and
the "scripts" and "sheet" commits are read; it is ``origin/master`` for a run, and ``launch.sh``
takes another only for a check-only trial (``--checks-only``).

The records of the experiment's slots and attempts are ``~/runs/rpg01b/slots.json``; the owner's
statement for a round (the account's label, and the confirmation that no other session runs on
the run account during it) is ``~/runs/rpg01b/owner-<r>.json``, written by the owner before the
round's launch. Nothing here reads a verdict: the round's end reads causes and counts only (R7).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

HOME = Path(os.environ.get("HOME", "~")).expanduser()
#: The experiment's records. ``launch.sh`` lets ``RPB_RUNS`` name another only for a check-only
#: trial, so a trial never writes into the run's records.
RUNS = Path(os.environ.get("RPB_RUNS") or HOME / C.RUNS_NAME)
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


def read_slots(path: Path = SLOTS) -> dict[str, Any]:
    """The slot records, or none yet."""
    return json.loads(path.read_text()) if path.is_file() else {}


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


def l1(r: int, checkout: Path, master_ref: str, dry: bool) -> dict[str, Any]:
    """L1: the host, the checkout at the tag, clean; the account, the owner's word, the slots."""
    found: dict[str, Any] = {"check": "L1", "round": r}
    found["machine"] = {
        "uname": " ".join(platform.uname()),
        "os": _os_release(),
        "git": C.git(checkout, "--version"),
    }
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        raise Refused("the run machine is Oracle's ARM Linux VM (§10)")
    _equal(found, "checkout", str(checkout), str(HOME / C.CHECKOUT_NAME))
    C.git(checkout, "fetch", "-q", "--tags", "origin")
    head = C.git(checkout, "rev-parse", "HEAD")
    tag = C.git(checkout, "rev-parse", f"refs/tags/{C.RUN_TAG}^{{commit}}")
    remote = C.git(checkout, "ls-remote", "origin", f"refs/tags/{C.RUN_TAG}").split()
    _equal(found, "head", head, tag)
    _equal(found, "the tag as pushed", remote[0] if remote else None, tag)
    if C.git(checkout, "status", "--porcelain"):
        raise Refused("the checkout is not clean")
    found["clean"] = True
    found["token_sha256_prefix"] = token_prefix(HOME / C.TOKEN_FILE)
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
    records = read_slots()
    if not records:
        if r != 1:
            raise Refused("the slots are drawn and recorded before round 1")
        records = {"seed": C.SLOT_SEED, "draw": draw_slots(), "drawn_utc": utc(), "attempts": []}
        if not dry:
            RUNS.mkdir(parents=True, exist_ok=True)
            SLOTS.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n")
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
    _equal(
        found,
        "experiments/R-PG-01b tree",
        C.git(checkout, "rev-parse", "HEAD:experiments/R-PG-01b"),
        C.git(checkout, "rev-parse", f"{scripts}:experiments/R-PG-01b"),
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
    SLOTS.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n")
    return {"check": "start", **row}


def final_lines(path: Path) -> dict[str, dict[str, Any]]:
    """Each subtask's last review line in a run log (``review_ran`` or ``review_unavailable``)."""
    last: dict[str, dict[str, Any]] = {}
    for line in C.read_jsonl(path) if path.is_file() else []:
        if line.get("kind") in ("review_ran", "review_unavailable"):
            last[line["subtask_id"]] = line
    return last


def cascade(run: Path) -> int:
    """How many reviews of a run end ``review_unavailable`` for infrastructure after their retry."""
    n = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        for line in final_lines(log).values():
            n += line["kind"] == "review_unavailable" and line.get("cause") == "infrastructure"
    return n


def rubric_mismatches(run: Path) -> tuple[int, int]:
    """Review lines whose ``rubric_sha256`` is not their role's pinned digest; and lines read."""
    bad = seen = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        lines = C.read_jsonl(log) if log.is_file() else []
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
        for x in C.read_jsonl(log) if log.is_file() else []:
            if x.get("kind") == "gate_ran":
                out[f"{name}:{x['subtask_id']}"] = json.dumps(x["result"], sort_keys=True)
    return out


def after(r: int, launch: Path, checkout: Path) -> dict[str, Any]:
    """The round's end (§12, after each round): causes and counts, and the attempt's validity."""
    import streams as S  # noqa: PLC0415

    records = read_slots()
    attempt = next(
        a for a in reversed(records["attempts"]) if a["round"] == r and a["launch"] == str(launch)
    )
    exits = (
        json.loads((launch / "exits.json").read_text()) if (launch / "exits.json").is_file() else {}
    )
    watcher = (launch / "watcher.log").read_text() if (launch / "watcher.log").is_file() else ""
    found: dict[str, Any] = {"check": "after", "round": r, "attempt": attempt["attempt"]}
    causes: list[str] = []
    if "ABORT" in watcher:
        causes.append("usage limit")
    if any(int(code) not in (0, 1) for code in exits.values()) or len(exits) != 2:
        causes.append("a crashed or killed process")
    per_arm: dict[str, Any] = {}
    cuts = 0
    gates = {}
    for arm, slot in attempt["slots"].items():
        p = C.places(HOME, slot, RUNS)
        reads = S.round_counts(p["run"], p["scratch"], arm) if p["run"].is_dir() else {"cut": 0}
        cuts += reads["cut"]
        bad, seen = rubric_mismatches(p["run"])
        regate = subprocess.run(
            [
                sys.executable, "-I", str(checkout / "experiments/R-PG-01/regate_r6.py"),
                str(checkout / (C.ARM_I_CORPUS if arm == "I" else C.ARM_F_CORPUS)),
                str(p["run"]), str(C.SEED), str(launch / f"regate-{slot}"),
            ],
            capture_output=True, text=True, check=False,
        ) if (p["run"] / "events.jsonl").is_file() else None  # fmt: skip
        differ = None
        if regate is not None and regate.returncode == 0:
            differ = json.loads(regate.stdout.strip().splitlines()[-1]).get("differ")
        gates[arm] = gate_records(p["run"])
        per_arm[f"slot {slot}"] = {
            "exit": exits.get(str(slot)),
            "reads": reads,
            "infrastructure_unavailable": cascade(p["run"]),
            "rubric_lines": seen,
            "rubric_mismatches": bad,
            "regate_differ": differ,
        }
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
    found["deviations"] = deviations
    attempt.update(
        {"ended_utc": utc(), "void_causes": causes, "valid": not causes, "deviations": deviations}
    )
    SLOTS.write_text(json.dumps(records, indent=1, sort_keys=True) + "\n")
    (launch / "after.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


def main(argv: list[str] | None = None) -> int:
    """Run one check; print its JSON line; exit 0 if it holds, 1 if not."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("check", choices=("L1", "L2", "L3", "L4", "L8", "L11", "start", "after"))
    parser.add_argument("--round", type=int, choices=C.ROUNDS)
    parser.add_argument("--master-ref", default="origin/master")
    parser.add_argument("--checks-only", action="store_true")
    parser.add_argument("--into", type=Path)
    parser.add_argument("--smoke", type=Path)
    parser.add_argument("--slots")
    parser.add_argument("--launch", type=Path)
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
        else:
            found = after(args.round, args.launch, checkout)
    except Refused as exc:
        print(json.dumps({"check": args.check, "refused": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(found, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
