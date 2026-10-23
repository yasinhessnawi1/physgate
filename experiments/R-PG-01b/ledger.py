"""R-PG-01b, CRITERIA.md §11: the round's line in the quota ledger.

Usage, in the run checkout, after a round's attempt has ended (``launch.sh`` runs it)::

    ledger.py round --round <r>

Each round's tokens, every try, are counted as the binary's own totals, summed from every
session's ``result`` line (R-PG-01's instrument has no repair resumes): every review session
under the review roots of every attempt of the round, void attempts included, and every L10
session of the round's launches, as this experiment's non-evaluation smokes. A session whose
stream has no ``result`` line is counted apart, with no tokens. L11's figures (T and 120 x T,
beside the 80 M the run account is known to carry) are put beside them.

It writes ``ledger-round-<r>.json`` and ``ledger-round-<r>.md`` (the line, in the quota ledger's
columns) under the experiment's records, recomputed from the streams each time it runs, and
prints the line. Counts only: no verdict is read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

HOME = Path(os.environ.get("HOME", "~")).expanduser()
RUNS = Path(os.environ.get("RPB_RUNS") or HOME / C.RUNS_NAME)
_SESSION = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
KINDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def result_tokens(stream: Path) -> int | None:
    """The binary's own total for one session, from its stream's last ``result`` line."""
    found: dict[str, Any] | None = None
    if stream.is_file():
        for line in stream.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                found = event
    if found is None:
        return None
    usage = found.get("usage") or {}
    return sum(int(usage.get(k) or 0) for k in KINDS)


def root_tokens(root: Path) -> tuple[int, int, int]:
    """Every session under a review root: (sessions, tokens, sessions with no result line)."""
    sessions = tokens = without = 0
    if not root.is_dir():
        return 0, 0, 0
    for d in sorted(root.rglob("session")):
        if not d.is_dir() or not _SESSION.match(d.parent.name):
            continue
        sessions += 1
        t = result_tokens(d / "stdout.jsonl")
        if t is None:
            without += 1
        else:
            tokens += t
    return sessions, tokens, without


def round_line(r: int, runs: Path = RUNS, home: Path = HOME) -> dict[str, Any]:
    """The round's ledger record and its Markdown line."""
    records = json.loads((runs / "slots.json").read_text())
    attempts = [a for a in records.get("attempts", []) if a["round"] == r]
    if not attempts:
        raise SystemExit(f"round {r} has no attempt on record")
    review = {"sessions": 0, "tokens": 0, "without_result": 0}
    for a in attempts:
        for slot in a["slots"].values():
            s, t, w = root_tokens(C.places(home, slot, runs)["scratch"])
            review["sessions"] += s
            review["tokens"] += t
            review["without_result"] += w
    smoke = {"sessions": 0, "tokens": 0, "without_result": 0}
    l11: dict[str, Any] = {}
    account = {}
    for launch in sorted(runs.glob(f"launch-{r}-*")):
        s, t, w = root_tokens(
            home / C.SCRATCH_NAME / f"rpb-smoke-{r}-{launch.name.rsplit('-', 1)[1]}"
        )
        smoke["sessions"] += s
        smoke["tokens"] += t
        smoke["without_result"] += w
        if (launch / "l11.json").is_file():
            l11 = json.loads((launch / "l11.json").read_text())
        if (launch / "L1.json").is_file():
            l1 = json.loads((launch / "L1.json").read_text())
            account = {"label": l1.get("account_label"), "token": l1.get("token_sha256_prefix")}
    started = min(a["started_utc"] for a in attempts)
    ended = max((a.get("ended_utc") or "") for a in attempts) or None
    valid = [a for a in attempts if a.get("valid") is True]
    per_review = round(review["tokens"] / review["sessions"]) if review["sessions"] else None
    found = {
        "round": r,
        "attempts": len(attempts),
        "valid_attempt": valid[-1]["attempt"] if valid else None,
        "slots": [a["slots"] for a in attempts],
        "account": account,
        "started_utc": started,
        "ended_utc": ended,
        "review_sessions": review["sessions"],
        "review_tokens": review["tokens"],
        "review_sessions_without_result": review["without_result"],
        "per_review": per_review,
        "smoke_sessions": smoke["sessions"],
        "smoke_tokens": smoke["tokens"],
        "l11": {k: l11.get(k) for k in ("T", "projected_5h", "carried_in_5h")},
    }
    slots = ", ".join(f"{a['attempt']}: {a['slots']['I']}+{a['slots']['F']}" for a in attempts)
    found["line"] = (
        f"| R-PG-01b round {r} (attempts {len(attempts)}; slots {slots}) "
        f"| {account.get('label')} (token sha256 {account.get('token')}…) "
        f"| no weekly gate (§11) | {started}–{ended} "
        f"| {review['sessions']} sessions ({review['without_result']} without a result line) "
        f"| **{review['tokens']:,}** reviews + {smoke['tokens']:,} in {smoke['sessions']} "
        f"non-evaluation smokes (L10) | {per_review if per_review is None else f'{per_review:,}'} "
        f"| `result` lines of every session under the round's review roots; L11: T = "
        f"{l11.get('T')}, 120 × T = {l11.get('projected_5h')} beside {l11.get('carried_in_5h')} |"
    )
    return found


def main(argv: list[str] | None = None) -> int:
    """Write the round's ledger record and print its line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("cmd", choices=("round",))
    parser.add_argument("--round", type=int, choices=C.ROUNDS, required=True)
    args = parser.parse_args(argv)
    found = round_line(args.round)
    (RUNS / f"ledger-round-{args.round}.json").write_text(
        json.dumps(found, indent=1, sort_keys=True) + "\n"
    )
    (RUNS / f"ledger-round-{args.round}.md").write_text(found["line"] + "\n")
    print(found["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
