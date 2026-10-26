"""R-PG-03, CRITERIA.md §10: the quota ledger of the run account, and the 5-hour projection.

Usage (on the run machine; the records directory is ``~/runs/rpg03``, or ``RP3_RUNS`` for a trial)::

    python -I ledger.py rpg01b --round <ledger-round-r.json> [--round ...]
        [--reality <R-PG-01b's reality ledger>] --account <label> --window <utc>
    python -I ledger.py block --block <b> --attempt <n> --scratch <dir> [--scratch ...]
        --account <label> --window <utc> --started <utc> --ended <utc> [--void <cause>]
    python -I ledger.py session --kind <authoring|resume|smoke> --label <name> --root <dir>
        --account <label> --window <utc> --started <utc> --ended <utc>
    python -I ledger.py reality --step <name> --sessions <dir> --account <label> --window <utc>
        --started <utc> --ended <utc>
    python -I ledger.py trailing [--now <utc>]
    python -I ledger.py project --block <b> [--now <utc>] [--w5 <tokens>]

**The ledger** (``ledger.jsonl`` in the records) covers every use of the run account. It opens with
R-PG-01b's lines, copied from R-PG-01b's own ledger as counts: each round's tokens and its start and
end times, and its reality adjudication's total and times; a step whose records give no total says
so and gives the times. Then R-PG-03's lines: one per block attempt (void attempts included), per
authoring session and per resume, per reality step, and per smoke, each written before any
scoring. Each line holds ``tokens_every_try`` (the binary's own totals, from every session's
``result`` line), the account's label, its weekly window, and the start and end times (UTC).

**The 5-hour projection** (``project``, before each block): the tokens the ledger records in the
trailing 5 hours (a line whose span overlaps them counts in full) plus the block's projection
(its reviews at the upper rates: 0.70 M for A2 and A1, 0.35 M for B) must be at most W5, 80 M
unless the owner raised it at launch (``--w5``, recorded). A line in the window with no total
cannot be counted, so the projection is refused, never assumed small. Exit 0 if the block may
start, 1 if it waits.

Counts only: no verdict is read.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

KINDS = (
    "rpg01b-round",
    "rpg01b-reality",
    "block",
    "authoring",
    "resume",
    "reality",
    "smoke",
)
LEDGER_NAME = "ledger.jsonl"


def records_dir() -> Path:
    """The experiment's records: ``~/runs/rpg03``, or the directory a trial names."""
    named = os.environ.get("RP3_RUNS")
    if named:
        return Path(named)
    return Path(os.environ.get("HOME", "~")).expanduser() / common.RUNS_NAME


def seconds(utc: str) -> float:
    """A UTC time of the form 2026-11-05T08:00:00Z, in seconds since the epoch."""
    return float(calendar.timegm(time.strptime(utc, "%Y-%m-%dT%H:%M:%SZ")))


def read(path: Path) -> list[dict[str, Any]]:
    """The ledger's lines; a ledger that does not exist has none.

    Raises:
        common.RefusedError: a line does not parse, or has no kind of the ledger's.
    """
    lines, broken = common.read_log(path)
    if broken:
        raise common.RefusedError(f"the ledger has {broken} line(s) that do not parse")
    for line in lines:
        if line.get("kind") not in KINDS:
            raise common.RefusedError("a ledger line has no kind of the ledger's")
    return lines


def append(path: Path, line: dict[str, Any]) -> dict[str, Any]:
    """Append one line, in a fixed spelling; the ledger is never rewritten."""
    if line.get("kind") not in KINDS:
        raise common.RefusedError("a ledger line has no kind of the ledger's")
    for key in ("started_utc", "ended_utc"):
        if line.get(key) is not None:
            seconds(line[key])
    read(path)  # an unreadable ledger stops the append, so no line is added to it
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as out:
        out.write(json.dumps(line, sort_keys=True) + "\n")
    return line


def root_tokens(root: Path) -> dict[str, int]:
    """Every session under a root: sessions, the sum of their totals, and those with no result.

    A session is a real ``<session id>/session`` directory under the root, at any depth (each
    lane's root), and its stream a regular file in it; no symlink is followed.
    """
    sessions = tokens = without = 0
    for parts, mode in common.walk_inside(root):
        if not stat.S_ISDIR(mode) or parts[-1] != "session" or len(parts) < 2:
            continue
        if not common.SESSION_ID.fullmatch(parts[-2]):
            continue
        sessions += 1
        data = common.read_inside(root, root.joinpath(*parts, "stdout.jsonl"))
        t = common.result_tokens(None if data is None else data.decode(errors="replace"))
        if t is None:
            without += 1
        else:
            tokens += t
    return {"sessions": sessions, "tokens": tokens, "without_result": without}


def stream_tokens(paths: list[Path]) -> dict[str, int]:
    """Each stream file's last ``result`` total: sessions, tokens, and those with no result."""
    sessions = tokens = without = 0
    for path in paths:
        sessions += 1
        data = common.read_own(path)
        t = common.result_tokens(None if data is None else data.decode(errors="replace"))
        if t is None:
            without += 1
        else:
            tokens += t
    return {"sessions": sessions, "tokens": tokens, "without_result": without}


def output_tokens(directory: Path) -> dict[str, int]:
    """Every reality session's output (``*.json``, the binary's JSON result): their totals."""
    files = sorted(
        directory.joinpath(*parts)
        for parts, mode in common.walk_inside(directory)
        if stat.S_ISREG(mode) and parts[-1].endswith(".json") and "attempt" in parts[-1]
    )
    sessions = tokens = without = 0
    for path in files:
        sessions += 1
        data = common.read_inside(directory, path)
        try:
            found = json.loads(data or b"null")
        except json.JSONDecodeError:
            found = None
        results = [
            m
            for m in (found if isinstance(found, list) else [found])
            if isinstance(m, dict) and m.get("type") == "result"
        ]
        if not results:
            without += 1
            continue
        usage = results[-1].get("usage") or {}
        kinds = (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
        tokens += sum(int(usage.get(k) or 0) for k in kinds)
    return {"sessions": sessions, "tokens": tokens, "without_result": without}


def rpg01b_lines(rounds: list[Path], reality: Path | None) -> list[dict[str, Any]]:
    """R-PG-01b's lines, as counts, from its own ledger records."""
    out = []
    for path in rounds:
        rec = json.loads(path.read_text())
        tokens = rec.get("review_tokens")
        smoke = rec.get("smoke_tokens")
        total = None if tokens is None else int(tokens) + int(smoke or 0)
        out.append(
            {
                "kind": "rpg01b-round",
                "label": f"R-PG-01b round {rec.get('round')}",
                "tokens_every_try": total,
                "no_total": total is None,
                "started_utc": rec.get("started_utc"),
                "ended_utc": rec.get("ended_utc"),
                "attempts": rec.get("attempts"),
            }
        )
    if reality is not None:
        rows, broken = common.read_log(reality)
        tokens = [r.get("tokens") for r in rows]
        known = not broken and rows and all(isinstance(t, int) for t in tokens)
        times = sorted(str(r["utc"]) for r in rows if r.get("utc"))
        out.append(
            {
                "kind": "rpg01b-reality",
                "label": "R-PG-01b reality adjudication",
                "tokens_every_try": sum(int(t) for t in tokens) if known else None,
                "no_total": not known,
                "started_utc": times[0] if times else None,
                "ended_utc": times[-1] if times else None,
            }
        )
    return out


def trailing(lines: list[dict[str, Any]], now: float) -> dict[str, Any]:
    """The tokens of every line whose span overlaps the trailing 5 hours, each counted in full."""
    since = now - common.WINDOW_5H_S
    counted = []
    unknown = []
    for line in lines:
        start = line.get("started_utc")
        end = str(line.get("ended_utc") or start)
        if start is None:
            unknown.append(line.get("label"))
            continue
        if seconds(end) >= since and seconds(str(start)) <= now:
            if line.get("tokens_every_try") is None:
                unknown.append(line.get("label"))
            else:
                counted.append(int(line["tokens_every_try"]))
    return {
        "since_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)),
        "lines_in_window": len(counted) + len(unknown),
        "tokens": sum(counted),
        "lines_without_a_total": unknown,
    }


def projection(block: str) -> dict[str, int]:
    """A block's projected tokens: each arm's reviews (items and twins) at its upper rate."""
    reviews = 2 * common.BLOCK_ITEMS[block]
    per_arm = {arm: reviews * common.RATE[arm] for arm in common.ARMS}
    return {"reviews_per_arm": reviews, **per_arm, "total": sum(per_arm.values())}


def project(lines: list[dict[str, Any]], block: str, now: float, w5: int) -> dict[str, Any]:
    """§10's rule: the trailing 5 hours and the block's projection, against W5."""
    t = trailing(lines, now)
    p = projection(block)
    found = {
        "block": block,
        "trailing_5h": t,
        "projection": p,
        "w5": w5,
        "w5_raised": w5 != common.W5,
        "sum": t["tokens"] + p["total"],
    }
    opened = any(str(x.get("kind", "")).startswith("rpg01b") for x in lines)
    found["opens_with_r_pg_01b_s_lines"] = opened
    found["may_start"] = opened and not t["lines_without_a_total"] and found["sum"] <= w5
    return found


def _base(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "account": args.account,
        "window": args.window,
        "started_utc": args.started,
        "ended_utc": args.ended,
    }


def main(argv: list[str] | None = None) -> int:
    """One subcommand; counts only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rpg01b")
    r.add_argument("--round", type=Path, action="append", default=[])
    r.add_argument("--reality", type=Path)
    b = sub.add_parser("block")
    b.add_argument("--block", choices=common.BLOCKS, required=True)
    b.add_argument("--attempt", type=int, required=True)
    b.add_argument("--scratch", type=Path, action="append", required=True)
    b.add_argument("--void")
    s = sub.add_parser("session")
    s.add_argument("--kind", choices=("authoring", "resume", "smoke"), required=True)
    s.add_argument("--label", required=True)
    s.add_argument("--stream", type=Path, action="append", default=[])
    s.add_argument("--root", type=Path)
    q = sub.add_parser("reality")
    q.add_argument("--step", required=True)
    q.add_argument("--sessions", type=Path, required=True)
    for p in (r, b, s, q):
        p.add_argument("--account", required=True)
        p.add_argument("--window", required=True)
    for p in (b, s, q):
        p.add_argument("--started", required=True)
        p.add_argument("--ended", required=True)
    t = sub.add_parser("trailing")
    t.add_argument("--now")
    j = sub.add_parser("project")
    j.add_argument("--block", choices=common.BLOCKS, required=True)
    j.add_argument("--now")
    j.add_argument("--w5", type=int, default=common.W5)
    args = parser.parse_args(argv)
    path = records_dir() / LEDGER_NAME
    try:
        if args.cmd == "rpg01b":
            if any(x["kind"].startswith("rpg01b") for x in read(path)):
                raise common.RefusedError("R-PG-01b's lines are already in the ledger")
            lines = rpg01b_lines(args.round, args.reality)
            for line in lines:
                append(path, {**line, "account": args.account, "window": args.window})
            print(json.dumps({"lines": len(lines)}))
            return 0
        if args.cmd == "block":
            counts = [root_tokens(root) for root in args.scratch]
            line = {
                **_base(args),
                "kind": "block",
                "label": f"block {args.block}, attempt {args.attempt}",
                "block": args.block,
                "attempt": args.attempt,
                "void": args.void,
                "sessions": sum(c["sessions"] for c in counts),
                "sessions_without_result": sum(c["without_result"] for c in counts),
                "tokens_every_try": sum(c["tokens"] for c in counts),
            }
        elif args.cmd == "session":
            found = root_tokens(args.root) if args.root is not None else stream_tokens(args.stream)
            line = {
                **_base(args),
                "kind": args.kind,
                "label": args.label,
                "sessions": found["sessions"],
                "sessions_without_result": found["without_result"],
                "tokens_every_try": found["tokens"],
            }
        elif args.cmd == "reality":
            found = output_tokens(args.sessions)
            line = {
                **_base(args),
                "kind": "reality",
                "label": f"reality: {args.step}",
                "sessions": found["sessions"],
                "sessions_without_result": found["without_result"],
                "tokens_every_try": found["tokens"],
            }
        else:
            now = seconds(args.now) if args.now else time.time()
            lines = read(path)
            if args.cmd == "trailing":
                print(json.dumps(trailing(lines, now), sort_keys=True))
                return 0
            found = project(lines, args.block, now, args.w5)
            print(json.dumps(found, sort_keys=True))
            return 0 if found["may_start"] else 1
        append(path, line)
        print(json.dumps({k: v for k, v in line.items() if k != "account"}, sort_keys=True))
        return 0
    except (common.RefusedError, common.FailClosedError, ValueError) as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
