"""R-PG-03, CRITERIA.md §3.2, §5 R3 and R8, §10 and §11: the launch's checks and the block record.

Usage, as ``launch.sh`` calls each (``uv run --frozen python -I``), one JSON line each, exit 0 only
if it holds::

    checks.py host                                   the machine, no session alive, no login left
    checks.py order --block <b>                      the fixed order, the void attempts, the dates
    checks.py owner --block <b> --attempt <n>        the owner's confirmations (§10)
    checks.py smoke-ready --block <b>                the smoke's own step may run (§2.4, §10)
    checks.py smoke-record --code <n> --started <utc> --ended <utc> --ff <status> --dir <dir>
        [--figure <status>]
    checks.py ff-status --practice round-1=<dir> --practice repeat-K=<dir>   §7's keys, counted
    checks.py commits --r <dir> --r-k <dir> [--block <b>]   R and R_K against §3.2 and the fills
    checks.py generalist --into <file>               at R_K: generalist_of's four digests
    checks.py binary                                 the pinned binary's digest and version
    checks.py sets --sets <dir> --block <b>          the block's manifest and sheet, as filled
    checks.py r3 --checkout <dir> --root <dir>... --sets <dir> [--place <dir>...]
    checks.py start --block <b> --attempt <n> --runs <json>
    checks.py after --block <b> --attempt <n> --launch <dir>
    checks.py classify --block <b> --attempt <n> --route defect --test <path> --correction <id>
        | --route impossible
    checks.py stop-sessions --scratch <dir> [--scratch ...]
    checks.py credentials

The block record (``blocks.json`` in the records) holds every attempt of every block: its runs,
its start and end, whether it is valid, its void causes and deviations, and its stream check.
``tally3.py`` reads it and refuses before the last block has ended (R8). Nothing here reads a
verdict: the end of an attempt reads causes, counts and digests only.

Only processes this run started are ever signalled, each proven from the run's own records, and
on the run machine alone (Linux): off it, ``stop-sessions`` refuses and signals nothing.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

HOME = Path(os.environ.get("HOME", "~")).expanduser()
#: The block may not start before this date (§10 item 4), nor before the next window's if
#: R-PG-01b ran into a second weekly window: if a line of R-PG-01b's ends (or starts) on 5.11 or
#: later, midnight UTC standing for that day's reset, which errs toward the later start.
EARLIEST = "2026-11-05T00:00:00Z"
EARLIEST_IF_RPG01B_RAN_ON = "2026-11-12T00:00:00Z"
ARM_FIRST_MINUTE_S = 60
#: §11's two routes for a deviation found before any number: an instrument defect a test that
#: depends on no verdict shows (the block is re-run at the corrected commit, both runs reported),
#: or anything else impossible as specified (the decisions it feeds are not taken).
ROUTES = {"defect": "instrument defect", "impossible": "anything else impossible as specified"}
#: A review root of this experiment's form, under ~/review-scratch.
ROOT_NAME = re.compile(r"rp3-[a-z0-9]{1,3}-[0-9]{1,2}-(a2|a1|b)")
_CLAUDE = re.compile(r"^claude(-[0-9][\w.]*)?$")


class RefusedError(Exception):
    """A launch check does not hold."""


def records_dir() -> Path:
    """The experiment's records: ``~/runs/rpg03``, or the directory a trial names."""
    named = os.environ.get("RP3_RUNS")
    return Path(named) if named else HOME / common.RUNS_NAME


def _equal(found: dict[str, Any], name: str, have: object, want: object) -> None:
    found[name] = have
    if have != want:
        raise RefusedError(f"{name} is {have}, not {want}")


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{path.name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the block record


def read_blocks(path: Path | None = None) -> dict[str, Any]:
    """The block record, or an empty one."""
    path = records_dir() / "blocks.json" if path is None else path
    data = common.read_own(path)
    return json.loads(data) if data else {"attempts": [], "not_run": {}}


def write_blocks(record: dict[str, Any]) -> None:
    """The block record, written whole: to a new name, then renamed over."""
    path = records_dir() / "blocks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)


def attempts_of(record: dict[str, Any], block: str) -> list[dict[str, Any]]:
    """Every attempt of one block, in the order they started."""
    return [a for a in record.get("attempts", []) if a.get("block") == block]


def current(record: dict[str, Any], block: str) -> list[dict[str, Any]]:
    """A block's attempts after the last one a correction touches (§11); all, if none is."""
    mine = attempts_of(record, block)
    return mine[common.corrected_from(mine, block, None)[0] :]


def order(
    block: str, now: float | None = None, ledger: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The fixed order (§10), the void attempts (§11) and the earliest start of a block.

    A block a correction touches (§11) runs once more, at the corrected commit, until it has a
    valid attempt after the one the correction touches; the blocks after it wait for that.

    Raises:
        RefusedError: an earlier block has no valid attempt, or none after the one a correction
            touches, and is not recorded as not run; this block already has a valid attempt (after
            the one a correction touches, if one does), or three void ones; it is recorded as not
            run; or it is before its earliest start.
    """
    rec = read_blocks()
    stopped = rec.get("stopped")
    if stopped:
        raise RefusedError(f"the experiment has stopped for the owner: {stopped.get('reason')}")
    not_run = rec.get("not_run") or {}
    if block in not_run:
        raise RefusedError(f"block {block} is recorded as not run ({not_run[block]})")
    k = common.BLOCKS.index(block)
    for earlier in common.BLOCKS[:k]:
        if earlier in not_run:
            continue
        if not any(a.get("valid") is True for a in current(rec, earlier)):
            raise RefusedError(
                f"block {earlier} comes first and has no valid attempt (§10's order), or none at "
                "the corrected commit of a correction that touches it (§11)"
            )
    mine, fresh = attempts_of(rec, block), current(rec, block)
    if any(a.get("valid") is True for a in fresh):
        at = " at its corrected commit (§11)" if len(fresh) < len(mine) else ""
        raise RefusedError(f"block {block} already has a valid attempt{at}")
    if any(a.get("valid") is None for a in mine):
        raise RefusedError(f"an attempt of block {block} has not been closed by its end check")
    for a in mine:
        dev = a.get("deviation") or {}
        if dev and dev.get("classification") is None:
            raise RefusedError(
                f"block {block}'s attempt {a.get('attempt')} is a deviation "
                f"({'; '.join(dev.get('causes', []))}): no further attempt until the owner "
                "classifies it (checks.py classify, §11)"
            )
        if dev.get("classification") == ROUTES["impossible"]:
            raise RefusedError(
                f"block {block}'s attempt {a.get('attempt')} is classified as anything else "
                "impossible as specified: the decisions it feeds are not taken, and it is not "
                "attempted again (§11)"
            )
    voids = sum(1 for a in mine if a.get("valid") is False and not a.get("deviation"))
    if voids >= common.MAX_VOID_ATTEMPTS:
        raise RefusedError(
            f"block {block} has had {voids} void attempts: the owner declares whether it is "
            "impossible as specified (§11)"
        )
    earliest = earliest_start(ledger or [])
    now = time.time() if now is None else now
    if now < _seconds(earliest):
        raise RefusedError(f"no block starts before {earliest} (§10)")
    return {"check": "order", "block": block, "attempt": len(mine) + 1, "earliest": earliest}


def earliest_start(ledger: list[dict[str, Any]]) -> str:
    """§10 item 4: 5.11, or 12.11 if R-PG-01b ran into a second weekly window.

    R-PG-01b's ledger gives a round's earliest attempt's start, so a round voided before 5.11 and
    re-attempted after that reset keeps an older start: its end is what shows it ran on.
    """
    for line in ledger:
        if not str(line.get("kind", "")).startswith("rpg01b"):
            continue
        if max(str(line.get("started_utc") or ""), str(line.get("ended_utc") or "")) >= EARLIEST:
            return EARLIEST_IF_RPG01B_RAN_ON
    return EARLIEST


def _seconds(utc: str) -> float:
    import calendar

    return float(calendar.timegm(time.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")))


SMOKE_RECORD = "smoke.json"


def read_smokes() -> list[dict[str, Any]]:
    """Every smoke's record, in the order they ran."""
    data = common.read_own(records_dir() / SMOKE_RECORD)
    found: list[dict[str, Any]] = json.loads(data).get("attempts", []) if data else []
    return found


def smoke_ready(block: str) -> dict[str, Any]:
    """The smoke's own step may run: before the first block, before the window's confirmation.

    §10 item 4 lets nothing run on the run account between the owner's confirmation that a weekly
    window has begun and the first block, so the whole-read smoke (§2.4), which runs on that
    account, is a step of its own before that confirmation.

    Raises:
        RefusedError: the block is not the first, an attempt has started, the window is already
            confirmed, or the owner's account file names no label or weekly reset.
    """
    said = _json_or_none(records_dir() / "owner" / "account.json") or {}
    label, reset = str(said.get("account_label", "")).strip(), str(said.get("weekly_reset_utc", ""))
    if not label or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", reset):
        raise RefusedError("the owner's account file names no account label or weekly reset (UTC)")
    if block != common.BLOCKS[0]:
        raise RefusedError(f"the smoke runs before the first block, {common.BLOCKS[0]}")
    if read_blocks().get("attempts"):
        raise RefusedError("a block attempt has started: the smoke runs before the first block")
    if (records_dir() / "owner" / "window.json").exists():
        raise RefusedError(
            "the window is confirmed: the smoke runs before the owner's confirmation (§10 item 4)"
        )
    return {"check": "smoke-ready", "account_label": label, "weekly_reset_utc": reset}


def smoke_record(
    code: int, started: str, ended: str, ff: str, where: Path, figure: str | None = None
) -> dict[str, Any]:
    """One smoke's record.

    Its exit code, its start and end, the false-finding keys' status, and Q4's practice figure's.
    """
    for utc in (started, ended):
        _seconds(utc)
    row = {
        "code": code,
        "passed": code == 0,
        "started_utc": started,
        "ended_utc": ended,
        "false_finding_keys": ff,
        "practice_figure": figure,
        "dir": str(where),
    }
    rec = {"attempts": [*read_smokes(), row]}
    path = records_dir() / SMOKE_RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return {"check": "smoke-record", **row}


def ff_status(practice: dict[str, Path]) -> dict[str, Any]:
    """§7's five keys, counted again before the first block.

    Records that cannot be read at their digests are "not checked" (the reading is then
    unchecked), never a refusal.

    Raises:
        RefusedError: a key's count is not 1, or R-LAW-01's files are not the probe's: a failed
            precondition (§11).
    """
    import reality

    try:
        found = reality.ff_count(practice)
    except reality.NotCheckedError as exc:
        return {"check": "ff-status", "status": "not checked", "why": str(exc)}
    except reality.RefusedError as exc:
        raise RefusedError(str(exc)) from exc
    if not found["every_key_matches_one_line"]:
        raise RefusedError("a key does not match exactly one line: a defect of the script (§11)")
    return {"check": "ff-status", "status": "every key matches one line", "keys": found["keys"]}


def _json_or_none(path: Path) -> dict[str, Any] | None:
    data = common.read_own(path)
    if data is None:
        return None
    found = json.loads(data)
    return found if isinstance(found, dict) else None


def owner(
    block: str, attempt: int, ledger: list[dict[str, Any]], now: float | None = None
) -> dict[str, Any]:
    """The owner's per-block confirmation; for the first block, the window's, with nothing after.

    The first block also needs the smoke's own step to have passed, its last attempt ended before
    the window's confirmation, so that nothing runs on the run account between that confirmation
    and the first block (§10 item 4).

    Raises:
        RefusedError: a confirmation is missing or incomplete, a ledger line starts after the
            window's confirmation before the first block, or the first block has no passed smoke
            ended before that confirmation.
    """
    where = records_dir() / "owner"
    said = (
        json.loads((where / f"block-{block}-{attempt}.json").read_text())
        if (where / f"block-{block}-{attempt}.json").is_file()
        else None
    )
    if said is None:
        raise RefusedError(f"no owner confirmation for block {block}, attempt {attempt}")
    if not str(said.get("account_label", "")).strip():
        raise RefusedError("the owner's confirmation names no account label")
    if said.get("no_other_session_on_the_run_account") is not True:
        raise RefusedError(
            "the owner has not confirmed that no other session runs during the block"
        )
    found: dict[str, Any] = {"check": "owner", "account_label": said["account_label"]}
    first = not any(a.get("valid") is not None for a in read_blocks().get("attempts", []))
    if first:
        win = where / "window.json"
        if not win.is_file():
            raise RefusedError("the first block needs the owner's UTC-stamped window confirmation")
        w = json.loads(win.read_text())
        utc = w.get("weekly_limit_reset_confirmed_utc", "")
        if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(utc)):
            raise RefusedError("the window's confirmation is not stamped in UTC")
        now = time.time() if now is None else now
        if _seconds(utc) > now:
            raise RefusedError("the window's confirmation is stamped after now")
        if utc < earliest_start(ledger):
            raise RefusedError(
                f"the window's confirmation is stamped before {earliest_start(ledger)}, the "
                "blocks' earliest start (§10 item 4)"
            )
        later = [x for x in ledger if (x.get("started_utc") or "") > utc]
        if later:
            raise RefusedError(
                f"{len(later)} ledger line(s) start after the window's confirmation: nothing else "
                "runs on the run account before the first block (§10)"
            )
        smokes = read_smokes()
        if not smokes:
            raise RefusedError(
                "no smoke on record: the whole-read smoke runs first, as its own step "
                "(launch.sh --smoke), before the owner confirms the window"
            )
        last = smokes[-1]
        if not last.get("passed"):
            raise RefusedError("the last smoke did not pass: the first block does not start")
        if str(last.get("ended_utc") or "9") > utc:
            raise RefusedError(
                "the last smoke ended after the window's confirmation: the smoke runs before it"
            )
        found["window_confirmed_utc"] = utc
        found["smoke"] = {
            "passed": True,
            "ended_utc": last["ended_utc"],
            "false_finding_keys": last.get("false_finding_keys"),
        }
    found["first_block"] = first
    return found


def start(block: str, attempt: int, runs: dict[str, Any]) -> dict[str, Any]:
    """Record that a block's attempt starts now, with its run directories and review roots."""
    rec = read_blocks()
    if any(a.get("valid") is None for a in attempts_of(rec, block)):
        raise RefusedError(f"an attempt of block {block} is still open")
    row = {
        "block": block,
        "attempt": attempt,
        "started_utc": common.utc_now(),
        "runs": runs["runs"],
        "scratch": runs["scratch"],
        "valid": None,
    }
    rec.setdefault("attempts", []).append(row)
    write_blocks(rec)
    return {"check": "start", **row}


def not_run(block: str, cause: str) -> dict[str, Any]:
    """Record that ``s``, ``p1`` or ``p2`` is not run (§2.5's caps; §6.4 item 10)."""
    if block not in ("s", "p1", "p2"):
        raise RefusedError("only blocks s, p1 and p2 may be not run")
    rec = read_blocks()
    if any(a.get("valid") is True for a in attempts_of(rec, block)):
        raise RefusedError(f"block {block} already has a valid attempt")
    rec.setdefault("not_run", {})[block] = cause
    write_blocks(rec)
    return {"check": "not-run", "block": block, "cause": cause}


# ---------------------------------------------------------------- the attempt's end


def complete(run: Path, items: int) -> dict[str, Any]:
    """Whether a finished run is whole: its rows, and every planned subtask's review and gate."""
    rows, broken_rows = common.read_log(run / "results.jsonl")
    found: dict[str, Any] = {"results_rows": len(rows)}
    holds = len(rows) == items and not broken_rows
    for side, log in (
        ("injected", run / "events.jsonl"),
        ("twin", run / "controls" / "events.jsonl"),
    ):
        lines, broken = common.read_log(log)
        planned = [x["subtask_id"] for x in lines if x.get("kind") == "subtask_planned"]
        last: dict[str, dict[str, Any]] = {}
        for x in lines:
            if x.get("kind") in ("review_ran", "review_unavailable"):
                last[x["subtask_id"]] = x
        gated = {x["subtask_id"] for x in lines if x.get("kind") == "gate_ran"}
        final = sum(
            1
            for sid in planned
            if last.get(sid) is not None
            and (last[sid]["kind"] == "review_ran" or last[sid].get("retry") is False)
        )
        part = {
            "planned": len(planned),
            "without_a_final_review_line": len(planned) - final,
            "without_a_gate_line": sum(sid not in gated for sid in planned),
            "lines_unparsed": broken,
        }
        found[side] = part
        holds = (
            holds
            and part["planned"] == items
            and not (part["without_a_final_review_line"] or part["without_a_gate_line"] or broken)
        )
    found["holds"] = bool(holds)
    return found


def rubric_mismatches(run: Path, arm: str) -> tuple[int, int]:
    """Review lines whose rubric digest is not their arm's for their role; and lines read."""
    bad = seen = 0
    for log in (run / "events.jsonl", run / "controls" / "events.jsonl"):
        lines = common.read_log(log)[0]
        role = {
            x["subtask_id"]: x["assigned_role"] for x in lines if x.get("kind") == "subtask_planned"
        }
        for x in lines:
            if x.get("kind") == "review_ran":
                seen += 1
                bad += (x.get("result") or {}).get("rubric_sha256") != common.RUBRIC_SHA256[
                    arm
                ].get(role.get(x["subtask_id"], ""))
    return bad, seen


def after(block: str, attempt: int, launch: Path, sheet: bytes, sets: Path) -> dict[str, Any]:
    """An attempt's end: its void causes, its stream check, its digests, R6 and its lanes.

    Void causes, §11's list, closed: a usage limit; an arm that stopped in its first minute; a cut
    read; a rubric or knowledge digest on a review that is not its arm's. A crashed or killed
    process (an exit other than 0 or 1, or none) or a run that is not whole is none of them: with
    no void cause beside it, the attempt is a deviation, recorded unclassified, and the block is
    not attempted again until the owner classifies it (:func:`classify`). R6 and a review off its
    lane are deviations for the gate's figures and the lanes, which void nothing.
    """
    import lanes
    import regate
    import streams

    rec = read_blocks()
    row = next(
        a for a in reversed(rec["attempts"]) if a["block"] == block and a["attempt"] == attempt
    )
    exits_raw = common.read_own(launch / "exits.json")
    exits = json.loads(exits_raw) if exits_raw else {}
    watcher_raw = common.read_own(launch / "watcher.log")
    watcher = watcher_raw.decode(errors="replace") if watcher_raw else ""
    causes: list[str] = []
    runs = {arm: Path(row["runs"][arm]) for arm in common.ARMS}
    scratch = {arm: Path(row["scratch"][arm]) for arm in common.ARMS}
    limits = streams.limit_counts([*runs.values(), *scratch.values()])
    if "ABORT" in watcher or limits["usage_limit_files"]:
        causes.append("usage limit")
    if (launch / "first_minute.txt").is_file():
        causes.append("an arm stopped in its first minute")
    crashed: list[str] = []
    if set(exits) != set(common.ARMS) or any(int(c) not in (0, 1) for c in exits.values()):
        crashed.append("a crashed or killed process")
    per_arm: dict[str, Any] = {}
    cut = 0
    items = common.BLOCK_ITEMS[block]
    corpus = sets / common.BLOCK_CORPUS[block]
    for arm in common.ARMS:
        reads = (
            streams.block_counts(runs[arm], scratch[arm], arm, sheet)
            if runs[arm].is_dir()
            else {"cut": 0}
        )
        cut += reads["cut"]
        bad, seen = rubric_mismatches(runs[arm], arm)
        whole = complete(runs[arm], items)
        lane = lanes.check(runs[arm], corpus, block, arm) if whole["holds"] else {"holds": None}
        per_arm[arm] = {
            "exit": exits.get(arm),
            "complete": whole,
            "reads": reads,
            "rubric_lines": seen,
            "rubric_mismatches": bad,
            "lanes": lane,
        }
    every_run_whole = all(v["complete"]["holds"] for v in per_arm.values())
    if not every_run_whole:
        crashed.append("a run that is not whole")
    if cut:
        causes.append("a cut read")
    if any(v["rubric_mismatches"] for v in per_arm.values()):
        causes.append("a review line's rubric digest is not its arm's")
    knowledge = knowledge_digests(block, corpus, runs, scratch)
    if knowledge["mismatch"]:
        causes.append("a review's knowledge digests are not its arm's")
    deviation = {"causes": crashed, "classification": None} if crashed and not causes else None
    deviations: list[str] = []
    regated: dict[str, Any] | None = None
    if not causes and deviation is None:
        regated = regate.block(block, corpus, runs, launch / "regate")
        if not regated["holds"]:
            deviations.append("the gate's records differ (R6): a deviation for the gate's figures")
        if not all(v["lanes"].get("holds") for v in per_arm.values()):
            deviations.append("a review ran off its planned lane")
    stream_check = {"cut": cut, "per_arm": {a: v["reads"] for a, v in per_arm.items()}}
    valid = not causes and deviation is None
    row.update(
        {
            "ended_utc": common.utc_now(),
            "launch": str(launch),
            "valid": valid,
            "void_causes": causes,
            "deviation": deviation,
            "crashed_or_not_whole": crashed,
            "deviations": deviations,
            "stream_check": {"cut": cut},
            "usage_limit_files": limits["usage_limit_files"],
            "status_429s": limits["status_429s"],
        }
    )
    write_blocks(rec)
    found = {
        "check": "after",
        "block": block,
        "attempt": attempt,
        "valid": valid,
        "void_causes": causes,
        "deviation": deviation,
        "deviations": deviations,
        "per_arm": per_arm,
        "stream_check": stream_check,
        "regate": regated,
        "knowledge": knowledge,
        **limits,
    }
    (launch / "after.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


def classify(
    block: str,
    attempt: int,
    route: str,
    test: str | None,
    correction: str | None = None,
    repo: Path = common.REPO,
) -> dict[str, Any]:
    """The owner's classification of a deviation, or of a valid attempt a correction touches (§11).

    ``route`` is ``instrument defect`` (with ``test``, the repository path of a tracked test that
    depends on no verdict and shows the defect in the block's own records, and ``correction``, the
    id of the correction that names the block: the block is then re-run at its corrected commit,
    and both runs are reported) or ``anything else impossible as specified`` (the decisions it
    feeds are not taken). A deviation is classified on the attempt's logs and the ledger only,
    before any tally (R8); a defect also classifies the valid attempt of every block its
    correction names. It is written once, next to the attempt (``classification.json``), and in
    the block record; the launch refuses any further attempt of a deviation's block until it exists.

    Raises:
        RefusedError: the route is neither; a defect names no tracked test file or no correction,
            or the other route names either; the attempt records no deviation and is not a valid
            attempt a defect touches; the correction classifies an attempt of the block already;
            or the attempt is classified already.
    """
    if route not in ROUTES.values():
        raise RefusedError(f"the route is {ROUTES['defect']!r} or {ROUTES['impossible']!r}")
    found: dict[str, Any] = {
        "check": "classify",
        "block": block,
        "attempt": attempt,
        "route": route,
        "recorded_utc": common.utc_now(),
        "on": "the attempt's logs and the ledger only, before any tally (R8)",
    }
    if route == ROUTES["defect"]:
        name = Path(test or "").name
        if not test or not (name.startswith("test_") and name.endswith(".py")):
            raise RefusedError(
                "an instrument defect names the path of a test (test_*.py) that depends on no "
                "verdict and shows it (§11)"
            )
        try:
            common.git(repo, "ls-files", "--error-unmatch", "--", test)
            blob = common.git(repo, "rev-parse", f"HEAD:{test}")
        except subprocess.CalledProcessError:
            raise RefusedError(f"{test} is not a tracked test at the checkout's HEAD") from None
        if not correction:
            raise RefusedError(
                "an instrument defect names the correction that re-runs it: its id in the "
                "fills' corrections (§11)"
            )
        head = common.git(repo, "rev-parse", "HEAD")
        found.update(test=test, test_commit=head, test_blob=blob, correction=correction)
    elif test or correction:
        raise RefusedError("a test and a correction are named for an instrument defect alone")
    rec = read_blocks()
    row = next(
        (
            a
            for a in rec.get("attempts", [])
            if a.get("block") == block and a.get("attempt") == attempt
        ),
        None,
    )
    touched = row is not None and row.get("valid") is True and correction is not None
    if row is None or not (row.get("deviation") or touched):
        raise RefusedError(
            f"block {block}'s attempt {attempt} records no deviation, and is not a valid attempt "
            "an instrument defect touches"
        )
    if correction and any(a.get("correction") == correction for a in attempts_of(rec, block)):
        raise RefusedError(
            f"correction {correction} classifies an attempt of block {block} already: a further "
            "defect is a correction of its own"
        )
    where = Path(row.get("launch") or records_dir() / "blocks" / f"{block}-{attempt}")
    deviation = row.get("deviation") or {}
    if (
        deviation.get("classification") is not None
        or row.get("correction")
        or (where / "classification.json").exists()
    ):
        raise RefusedError(f"block {block}'s attempt {attempt} is classified already")
    found["causes"] = deviation.get("causes", [])
    if touched:
        found["on"] = "the test it names, which depends on no verdict (§11)"
    where.mkdir(parents=True, exist_ok=True)
    (where / "classification.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    if deviation:
        deviation["classification"] = route
    if correction:
        row["correction"] = correction
    write_blocks(rec)
    return found


def knowledge_digests(
    block: str, corpus: Path, runs: dict[str, Path], scratch: dict[str, Path]
) -> dict[str, Any]:
    """Every review's packet against its arm's and role's pinned knowledge (§3.1, §11)."""
    import tally3

    found: dict[str, Any] = {"mismatch": False, "per_arm": {}}
    for arm in common.ARMS:
        if not (runs[arm] / "events.jsonl").is_file():
            continue
        run = tally3.T.Run.read(runs[arm], any_count=True)
        one = tally3.Block(block, corpus, {arm: run}, None, None, {arm: scratch[arm]})
        try:
            found["per_arm"][arm] = tally3.check_knowledge(common.REPO, one, arm)
        except tally3.RefusedError as exc:
            found["per_arm"][arm] = {"refused": str(exc)}
            found["mismatch"] = True
    return found


# ---------------------------------------------------------------- the pins


def _bytes(repo: Path, rev: str, path: str) -> bytes | None:
    """A path's bytes at a revision, or ``None`` if it is not there."""
    try:
        return common.git_bytes(repo, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def readme_problem(frozen: bytes, have: bytes | None) -> str | None:
    """Why a README is not the freeze's bytes followed by exactly one appended readings section.

    ``None`` if it is.
    """
    if have is None:
        return "it is not there"
    if not have.startswith(frozen):
        return "its frozen part is not the freeze's bytes"
    rest = have[len(frozen) :]
    head = b"\n" + common.READINGS_HEADING + b"\n"
    if not rest.startswith(head):
        return "it does not hold exactly one appended section, its readings, after its frozen part"
    if any(line.startswith((b"# ", b"## ")) for line in rest[len(head) :].split(b"\n")):
        return "it holds more than the one appended section of its readings"
    return None


def _blob(repo: Path, rev: str, path: str) -> str | None:
    """A path's blob id at a revision, or ``None`` if it is not there."""
    try:
        return common.git(repo, "rev-parse", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None


def run_pins(
    r_dir: Path, fills: dict[str, Any], block: str | None
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """The commits an attempt of ``block`` runs at, and the correction that names them, if any.

    Every block runs at R and R_K, as "Commits filled" records them, except a block a correction
    touches (§11): its attempts after the one the owner classified an instrument defect with the
    correction's id run at the corrected commit, R' and R_K', which the correction's entry names
    with the block's test. R' descends from R; R_K' is one commit above R' (held below as R_K is
    above R).

    Raises:
        RefusedError: the corrections that name the block are not those its attempts are
            classified with; the classification beside the attempt is not that correction's
            instrument defect with the test it names for the block; or R' is R, or does not
            descend from R.
    """
    filled = common.need_fill(fills, "commits")
    base = {"R": str(filled.get("R")), "R_K": str(filled.get("R_K"))}
    if block is None:
        return base, None
    mine = attempts_of(read_blocks(), block)
    since, entry = common.corrected_from(mine, block, fills)
    if entry is None:
        return base, None
    touched = mine[since - 1]
    said = _json_or_none(Path(str(touched.get("launch") or "")) / "classification.json") or {}
    if [said.get(k) for k in ("route", "block", "correction", "test")] != [
        ROUTES["defect"],
        block,
        entry["id"],
        entry["blocks"][block],
    ]:
        raise RefusedError(
            f"the classification next to block {block}'s attempt {touched.get('attempt')} is not "
            f"an instrument defect of correction {entry['id']} with the test it names for the block"
        )
    if entry["R"] == base["R"]:
        raise RefusedError(f"the correction of block {block} names R itself, not a corrected R'")
    try:
        common.git(r_dir, "merge-base", "--is-ancestor", base["R"], entry["R"])
    except subprocess.CalledProcessError:
        raise RefusedError(
            f'the corrected R\' of block {block} does not descend from R ("Commits filled")'
        ) from None
    return {"R": entry["R"], "R_K": entry["R_K"]}, entry


def commits(
    r_dir: Path,
    r_k_dir: Path,
    fills: dict[str, Any],
    master_ref: str = "origin/master",
    block: str | None = None,
) -> dict[str, Any]:
    """R and R_K against §3.2 and "Commits filled"; the frozen files at R, R_K and master.

    ``CRITERIA.md`` is the freeze's blob at all three for good: the fills are a record of their own
    (``fills.json``), never written into it. The README is the freeze's bytes followed by exactly
    one appended section, its readings, and is the same bytes at all three, so the readings are
    final at "Commits filled" and nothing in it moves during the run. For an attempt of a
    block a correction touches, after its attempt classified an instrument defect, R and R_K are
    the corrected commit's (:func:`run_pins`), held by the same checks but for the trees, blobs and
    digests "Commits filled" records for R, which the correction replaces.

    Raises:
        RefusedError: anything differs.
    """
    filled = common.need_fill(fills, "commits")
    pins, corrected = run_pins(r_dir, fills, block)
    found: dict[str, Any] = {"check": "commits", "corrected": corrected}
    r = common.git(r_dir, "rev-parse", "HEAD")
    r_k = common.git(r_k_dir, "rev-parse", "HEAD")
    for name, d, rev in (
        ("R's", r_dir, r),
        ("R_K's", r_k_dir, r_k),
        ("the master ref's", r_dir, master_ref),
    ):
        criteria = f"{common.EXPERIMENT}/CRITERIA.md"
        _equal(found, f"{name} {criteria}", _blob(d, rev, criteria), common.FROZEN_BLOBS[criteria])
    readme = f"{common.EXPERIMENT}/README.md"
    readme_at_r = _bytes(r_dir, r, readme)
    why = readme_problem(
        common.git_bytes(r_dir, "cat-file", "blob", common.FROZEN_BLOBS[readme]), readme_at_r
    )
    if why is not None:
        raise RefusedError(f"R's {readme}: {why}")
    found[f"R's {readme}"] = "the freeze's bytes and one appended section"
    for name, d, rev in (("R_K's", r_k_dir, r_k), ("the master ref's", r_dir, master_ref)):
        if _bytes(d, rev, readme) != readme_at_r:
            raise RefusedError(f"{name} {readme} is not R's byte for byte")
    _equal(found, "R", r, pins["R"])
    _equal(found, "R_K", r_k, pins["R_K"])
    for name, d in (("R", r_dir), ("R_K", r_k_dir)):
        if common.git(d, "status", "--porcelain"):
            raise RefusedError(f"the {name} checkout is not clean")
    try:
        common.git(r_dir, "merge-base", "--is-ancestor", common.R_FLOOR, r)
    except subprocess.CalledProcessError:
        raise RefusedError("R does not descend from master at fc28f32 or later (§3.2)") from None
    _equal(found, "R_K's parent", common.git(r_k_dir, "rev-parse", "HEAD^"), r)
    names = sorted(common.git(r_dir, "diff", "--name-only", r, r_k).splitlines())
    _equal(found, "the paths R_K differs from R in", names, sorted(common.R_K_PATHS))
    for path in common.RUBRIC_PATHS:
        _equal(
            found,
            f"R_K's {path}",
            common.git(r_dir, "rev-parse", f"{r_k}:{path}"),
            common.git(r_dir, "rev-parse", f"{common.K_COMMIT}:{path}"),
        )
    ours = common.git_bytes(r_dir, "show", f"{r}:{common.PROMOTIONS}").decode().splitlines()
    theirs = common.git_bytes(r_dir, "show", f"{r_k}:{common.PROMOTIONS}").decode().splitlines()
    added = [
        line[1:]
        for line in common.git(
            r_dir, "show", "--format=", "-U0", common.FIX_COMMIT, "--", common.PROMOTIONS
        ).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    if len(added) != 4:
        raise RefusedError("the fix's commit does not add exactly four promotion lines")
    want = [line for line in ours if line not in added]
    if len(want) != len(ours) - 4:
        raise RefusedError("R's promotions do not hold the fix's four lines once each")
    _equal(found, "R_K's promotions, line for line", theirs, want)
    for arm, d, rev in (("A2", r_dir, r), ("A1", r_k_dir, r_k)):
        for role in common.ROLES:
            blob = common.git_bytes(d, "show", f"{rev}:knowledge/reviewers/{role}/rubric.md")
            _equal(
                found,
                f"{arm} {role} rubric",
                common.sha256_bytes(blob),
                common.RUBRIC_SHA256[arm][role],
            )
    for name, d, rev in (("R", r_dir, r), ("R_K", r_k_dir, r_k)):
        for path, tree in common.KNOWLEDGE_TREES.items():
            _equal(found, f"{name} {path}", common.git(d, "rev-parse", f"{rev}:{path}"), tree)
    held = {} if corrected else filled
    for kind in ("trees", "blobs"):
        for path, value in (held.get(kind) or {}).items():
            for name, d, rev in (("R", r_dir, r), ("R_K", r_k_dir, r_k)):
                _equal(
                    found,
                    f"{name} {kind[:-1]} {path}",
                    common.git(d, "rev-parse", f"{rev}:{path}"),
                    value,
                )
    for path, digest in (held.get("sha256") or {}).items():
        for name, d in (("R", r_dir), ("R_K", r_k_dir)):
            _equal(found, f"{name} sha256 {path}", common.sha256_file(d / path), digest)
    from physgate.evaluation.inject.materialise import ACCOUNT_SHA256

    # §3.3: the account's three paragraphs, unchanged, held before the run (R's code; R_K's is held
    # by its generalist check, which runs in R_K's checkout).
    _equal(found, "R's account paragraphs", ACCOUNT_SHA256, common.ACCOUNT_SHA256)
    return {k: v for k, v in found.items() if not isinstance(v, list) or k.startswith("the paths")}


def generalist() -> dict[str, Any]:
    """At R_K: each role's generalist rubric, by code, against §3.1's digests; and the account."""
    from physgate.evaluation.inject.materialise import ACCOUNT_SHA256
    from physgate.knowledge.promote import KNOWLEDGE_ROOT
    from physgate.reviewers.rubric import generalist_of, load_rubric

    found: dict[str, Any] = {"check": "generalist"}
    _equal(found, "account paragraphs", ACCOUNT_SHA256, common.ACCOUNT_SHA256)
    for role in common.ROLES:
        g = generalist_of(load_rubric(common.REPO / KNOWLEDGE_ROOT, role))
        _equal(found, f"B {role}", g.sha256, common.RUBRIC_SHA256["B"][role])
    return found


def binary(path: Path) -> dict[str, Any]:
    """The pinned binary: its sha256 and its version."""
    found: dict[str, Any] = {"check": "binary"}
    _equal(found, "binary sha256", common.sha256_file(path), common.BINARY_SHA256)
    out = subprocess.run(
        [str(path), "--version"], capture_output=True, text=True, check=False, timeout=120
    )
    _equal(found, "binary version", out.stdout.split(" ")[0].strip(), common.BINARY_VERSION)
    return found


def sets_check(sets: Path, block: str, fills: dict[str, Any]) -> dict[str, Any]:
    """The block's corpus: its manifest as "Set filled" records it, its sheet as "Sheet filled"."""
    from physgate.evaluation.inject.corpus import load_corpus

    filled_sets = common.need_fill(fills, "sets").get("manifests") or {}
    sheet = common.need_fill(fills, "sheet")
    name = common.BLOCK_CORPUS[block]
    corpus = sets / name
    found: dict[str, Any] = {"check": "sets", "corpus": name}
    _equal(found, "manifest", common.sha256_file(corpus / "MANIFEST.json"), filled_sets.get(name))
    loaded = load_corpus(corpus)
    _equal(found, "sheet", common.sha256_bytes(loaded.parts_sheet), sheet.get("sha256"))
    _equal(
        found, "table", common.sha256_file(corpus / common.TABLE_NAME), common.EDITED_TABLE_SHA256
    )
    _equal(found, "items", len(loaded.artefacts), common.BLOCK_ITEMS[block])
    return found


def r3(
    checkout: Path, roots: list[Path], sets: Path, places: list[Path], r_k: Path | None
) -> dict[str, Any]:
    """R3 (§5): R-PG-02's scan, unedited, over every set this experiment and its precedents hold.

    The sets read are fresh-v2's, fresh-v1c's, the tuning set and practice/v1; every other named
    place (R-PG-01b's corpora and runs, the practice cycle's and R-PG-02's runs, this experiment's
    earlier attempts, authoring directories and reality packets, the dry runs) is held by placement
    alone: no review root inside it, and it inside no review root. R-PG-01's corpus, which
    R-PG-01b reviews, is never opened (§1's exclusion).
    """
    scan = _load("rpg02_r3", common.REPO / "experiments" / "R-PG-02" / "r3_scan.py")
    named = {name: sets / name for name in common.CORPUS_ORDER if (sets / name).is_dir()}
    named["tuning-set"] = checkout / common.TUNING_SET
    named["practice-v1"] = checkout / "experiments" / "R-PG-02" / "practice" / "corpus-v1"
    excluded = [
        checkout / "corpora" / "injected-errors" / "v1",
        checkout / "corpora" / "injected-errors" / "v1-fullsheet",
    ]
    every_place = [*places, *excluded, *([r_k] if r_k is not None else [])]
    found: dict[str, Any] = scan.scan(checkout, roots, named, every_place)
    found["check"] = "r3"
    found["sets_read"] = sorted(named)
    if found["problems"]:
        raise RefusedError("; ".join(found["problems"]))
    return found


# ---------------------------------------------------------------- sessions and credentials


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
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            msg = f"process {d.name}'s arguments could not be read ({exc.strerror})"
            raise common.FailClosedError(msg) from exc
        if argv and argv[-1] == "":
            argv.pop()
        if argv:
            found.append((int(d.name), argv))
    return found


LOGIN_FILES = {"config": (".credentials.json",), "state": ("key", "key-helper.sh")}


def login_files(root: Path) -> dict[str, int]:
    """What may still hold a session's login under ``root``: a bounded walk, through no symlink."""
    left = unconfirmed = 0
    for parts, mode in common.walk_inside(root):
        name = parts[-1]
        in_session = len(parts) >= 3 and parts[-3] == "session"
        if in_session and name in LOGIN_FILES.get(parts[-2], ()):
            left += 1
        elif stat.S_ISLNK(mode) and (
            common.SESSION_ID.fullmatch(name) or name == "session" or name in LOGIN_FILES
        ):
            unconfirmed += 1
    return {"left": left, "unconfirmed": unconfirmed}


def run_login_files(home: Path) -> dict[str, int]:
    """Every login file of this experiment's sessions still under its review roots."""
    scratch = Path(home) / common.SCRATCH_NAME
    left = unconfirmed = roots = 0
    for name, mode in common.list_inside(scratch):
        if not (ROOT_NAME.fullmatch(name) or name.startswith("rp3-")):
            continue
        roots += 1
        if not stat.S_ISDIR(mode):
            unconfirmed += 1
            continue
        found = login_files(scratch / name)
        left += found["left"]
        unconfirmed += found["unconfirmed"]
    return {"roots": roots, "left": left, "unconfirmed": unconfirmed}


def host() -> dict[str, Any]:
    """The run machine, no claude or inject process of the account alive, no login file left."""
    found: dict[str, Any] = {"check": "host", "uname": " ".join(platform.uname())}
    if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
        raise RefusedError("the run machine is the ARM Linux virtual machine (§3.4)")
    alive = live_sessions(own_processes())
    if alive:
        raise RefusedError(
            f"{len(alive)} claude or inject process(es) of the run account are alive"
        )
    files = run_login_files(HOME)
    if files["left"] or files["unconfirmed"]:
        raise RefusedError("a login file of an earlier session is left, or not confirmed removed")
    found.update(claude_or_inject_alive=0, login_files_left=0)
    return found


def proven_session(root: Path, sdir: Path) -> tuple[int, str, str] | None:
    """The session a process record proves this run started and still running, or ``None``."""
    from physgate.orchestrator.dispatch import process_group_of
    from physgate.orchestrator.processes import is_session

    raw = common.read_inside(root, sdir / "process.json")
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
    if not common.SESSION_ID.fullmatch(sid) or sdir.parent.name != sid:
        return None
    if not is_session(pid, started, sid) or process_group_of(pid) != pid:
        return None
    return pid, started, sid


def stop_sessions(scratches: Iterable[Path]) -> dict[str, Any]:
    """The watcher's abort: every session the review roots prove still running, stopped.

    A session is signalled only if its own process record proves it; nothing else is signalled.
    Then every session's credential directory is removed, following no symlink, and what is left
    is confirmed by a walk of its own.

    Raises:
        RefusedError: not on the run machine, or a root not of the run's form.
    """
    if platform.system() != "Linux":
        raise RefusedError("sessions are stopped on the run machine alone: nothing signalled here")
    from physgate.orchestrator.dispatch import process_group_of
    from physgate.orchestrator.processes import is_session

    roots: list[Path] = []
    for s in scratches:
        if not ROOT_NAME.fullmatch(Path(s).name) or os.path.islink(s):
            raise RefusedError(f"{Path(s).name!r} is not a review root of the run's form")
        roots += common.lane_roots(Path(s))
    proven: list[tuple[int, str, str]] = []
    for root in roots:
        for sid in common.session_dirs(root)[0]:
            sdir = root / sid / "session"
            if common.exists_inside(root, sdir / "ended.json"):
                continue
            if (found := proven_session(root, sdir)) is not None:
                proven.append(found)
    for pid, _, _ in proven:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and any(is_session(*x) for x in proven):
        time.sleep(0.1)
    killed = 0
    for pid, started, sid in proven:
        if is_session(pid, started, sid) and process_group_of(pid) == pid:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGKILL)
                killed += 1
    removed = refused = 0
    for root in roots:
        for sid in common.session_dirs(root)[0]:
            done = common.remove_inside(root, (sid, "session", "config"))
            removed += done == "removed"
            refused += done == "refused"
            for name in LOGIN_FILES["state"]:
                refused += common.unlink_inside(root, (sid, "session", "state", name)) == "refused"
    left = [login_files(root) for root in roots]
    return {
        "check": "stop-sessions",
        "stopped": len(proven),
        "needed_sigkill": killed,
        "configs_removed": removed,
        "refused": refused,
        "login_files_left": sum(x["left"] for x in left),
        "unconfirmed": sum(x["unconfirmed"] for x in left),
    }


def main(argv: list[str] | None = None) -> int:
    """Run one check; print its JSON line; exit 0 if it holds, 1 if not."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("host")
    o = sub.add_parser("order")
    o.add_argument("--block", choices=common.BLOCKS, required=True)
    w = sub.add_parser("owner")
    w.add_argument("--block", choices=common.BLOCKS, required=True)
    w.add_argument("--attempt", type=int, required=True)
    sr = sub.add_parser("smoke-ready")
    sr.add_argument("--block", choices=common.BLOCKS, required=True)
    sd = sub.add_parser("smoke-record")
    sd.add_argument("--code", type=int, required=True)
    sd.add_argument("--started", required=True)
    sd.add_argument("--ended", required=True)
    sd.add_argument("--ff", required=True)
    sd.add_argument("--figure")
    sd.add_argument("--dir", type=Path, required=True)
    fs = sub.add_parser("ff-status")
    fs.add_argument("--practice", action="append", default=[], help="<run label>=<dir>")
    c = sub.add_parser("commits")
    c.add_argument("--r", type=Path, required=True)
    c.add_argument("--r-k", type=Path, required=True)
    c.add_argument("--block", choices=common.BLOCKS)
    sub.add_parser("generalist")
    sub.add_parser("binary")
    s = sub.add_parser("sets")
    s.add_argument("--sets", type=Path, required=True)
    s.add_argument("--block", choices=common.BLOCKS, required=True)
    r = sub.add_parser("r3")
    r.add_argument("--checkout", type=Path, required=True)
    r.add_argument("--r-k", type=Path)
    r.add_argument("--root", type=Path, action="append", default=[])
    r.add_argument("--sets", type=Path, required=True)
    r.add_argument("--place", type=Path, action="append", default=[])
    st = sub.add_parser("start")
    st.add_argument("--block", choices=common.BLOCKS, required=True)
    st.add_argument("--attempt", type=int, required=True)
    st.add_argument("--runs", type=Path, required=True)
    af = sub.add_parser("after")
    af.add_argument("--block", choices=common.BLOCKS, required=True)
    af.add_argument("--attempt", type=int, required=True)
    af.add_argument("--launch", type=Path, required=True)
    af.add_argument("--sheet", type=Path, required=True)
    af.add_argument("--sets", type=Path, required=True)
    cl = sub.add_parser("classify")
    cl.add_argument("--block", choices=common.BLOCKS, required=True)
    cl.add_argument("--attempt", type=int, required=True)
    cl.add_argument("--route", choices=sorted(ROUTES), required=True)
    cl.add_argument("--test", help="defect: the path of a tracked test that depends on no verdict")
    cl.add_argument("--correction", help="defect: the id of the correction that names the block")
    nr = sub.add_parser("not-run")
    nr.add_argument("--block", choices=("s", "p1", "p2"), required=True)
    nr.add_argument("--cause", required=True)
    ss = sub.add_parser("stop-sessions")
    ss.add_argument("--scratch", type=Path, action="append", default=[])
    sub.add_parser("credentials")
    parser.add_argument("--master-ref", default="origin/master")
    args = parser.parse_args(argv)
    import ledger

    try:

        def fills() -> dict[str, Any]:
            return common.fills_on(common.REPO, args.master_ref)

        if args.cmd == "host":
            found = host()
        elif args.cmd == "order":
            found = order(args.block, ledger=ledger.read(records_dir() / ledger.LEDGER_NAME))
        elif args.cmd == "owner":
            found = owner(args.block, args.attempt, ledger.read(records_dir() / ledger.LEDGER_NAME))
        elif args.cmd == "smoke-ready":
            found = smoke_ready(args.block)
        elif args.cmd == "smoke-record":
            found = smoke_record(
                args.code, args.started, args.ended, args.ff, args.dir, args.figure
            )
        elif args.cmd == "ff-status":
            practice = {
                spec.partition("=")[0]: Path(spec.partition("=")[2]).resolve()
                for spec in args.practice
            }
            found = ff_status(practice)
        elif args.cmd == "commits":
            found = commits(
                args.r.resolve(), args.r_k.resolve(), fills(), args.master_ref, args.block
            )
        elif args.cmd == "generalist":
            found = generalist()
        elif args.cmd == "binary":
            found = binary(
                Path(os.environ.get("PHYSGATE_CLAUDE_BIN", str(HOME / "pinned/claude-2.1.301")))
            )
        elif args.cmd == "sets":
            found = sets_check(args.sets.resolve(), args.block, fills())
        elif args.cmd == "r3":
            found = r3(
                args.checkout.resolve(),
                [p.expanduser() for p in args.root],
                args.sets.resolve(),
                [p.expanduser() for p in args.place],
                args.r_k,
            )
        elif args.cmd == "start":
            found = start(args.block, args.attempt, json.loads(args.runs.read_text()))
        elif args.cmd == "after":
            found = after(args.block, args.attempt, args.launch, args.sheet.read_bytes(), args.sets)
            print(
                json.dumps(
                    {k: found[k] for k in ("valid", "void_causes", "deviation", "deviations")},
                    sort_keys=True,
                )
            )
            return 0 if found["valid"] else 1
        elif args.cmd == "classify":
            found = classify(
                args.block, args.attempt, ROUTES[args.route], args.test, args.correction
            )
        elif args.cmd == "not-run":
            found = not_run(args.block, args.cause)
        elif args.cmd == "stop-sessions":
            found = stop_sessions(args.scratch)
            if found["login_files_left"] or found["unconfirmed"]:
                print(
                    json.dumps(
                        {**found, "refused": "login files are not confirmed removed"},
                        sort_keys=True,
                    )
                )
                return 1
        else:
            left = run_login_files(HOME)
            if left["left"] or left["unconfirmed"]:
                raise RefusedError(
                    "a login file of the run's sessions remains, or is not confirmed removed"
                )
            found = {"check": "credentials", **left}
    except (RefusedError, common.RefusedError, common.FailClosedError) as exc:
        print(json.dumps({"check": args.cmd, "refused": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(found, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
