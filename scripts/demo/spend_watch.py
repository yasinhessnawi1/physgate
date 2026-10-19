r"""Watch a run's tokens at list price, from its own streams, and stop it at a set figure.

No part of the harness enforces a USD cap: a run's bounds are turns, wall clock and output
tokens per session, and the repair budget. This watcher reads the stream of every model call
the run writes (its decomposition, its role sessions, and its reviews under the review root),
sums their tokens at list price, and stops the run's process tree when the sum reaches
``--kill-at-usd``. A finished call counts at the binary's own figure (``total_cost_usd`` on its
result line); a call still running counts at the list price of the usage its assistant
messages have reported so far, so a session is never invisible until it ends. On the
subscription nothing is billed per token, and the binary's figure is itself a list-price
estimate: the sum is what the tokens would cost, not what was paid. The stop is set below the
cap by a reserve, because one request can complete between two readings.

Every reading is appended to ``--log`` as a JSON line; the last line is the readout. Exit 0
when the run's process ends on its own, 3 when the watcher stopped it.

    python scripts/demo/spend_watch.py --pid <physgate run> --run-dir <run> \\
        --review-root <root> --cap-usd 43 --kill-at-usd 40 --log spend.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from physgate.evaluation.observe.calls import (
    DECOMPOSITION_DIRNAME,
    REVIEW_SESSION_DIRNAME,
    SESSIONS_DIRNAME,
    STREAM_NAME,
)
from physgate.evaluation.observe.cost import DatedSheet, load_price_sheet

MTOK = Decimal(1_000_000)
#: The files a session's credential is put in, removed here when the run is stopped.
CREDENTIAL_FILES = ("key", "key-helper.sh", ".credentials.json")


def streams(run_dir: Path, review_root: Path) -> list[Path]:
    """Every model call's stream the run has written so far."""
    found = [run_dir / DECOMPOSITION_DIRNAME / STREAM_NAME]
    found += sorted((run_dir / SESSIONS_DIRNAME).glob(f"*/{STREAM_NAME}"))
    if review_root.is_dir():
        found += sorted(review_root.glob(f"*/{REVIEW_SESSION_DIRNAME}/{STREAM_NAME}"))
    return [p for p in found if p.is_file()]


def price(model: str, usage: dict[str, Any], sheet: DatedSheet) -> Decimal:
    """List price of one message's usage; a one-hour cache write at its own rate where known."""
    rates = sheet.sheet.usd_per_mtok.get(model)
    if rates is None:
        msg = f"the price sheet has no price for {model!r}"
        raise SystemExit(msg)
    creation = usage.get("cache_creation") or {}
    one_hour = int(creation.get("ephemeral_1h_input_tokens") or 0)
    written = int(usage.get("cache_creation_input_tokens") or 0)
    five_minute = max(written - one_hour, 0)
    usd = (
        Decimal(int(usage.get("input_tokens") or 0)) * rates.input
        + Decimal(int(usage.get("cache_read_input_tokens") or 0)) * rates.cache_read
        + Decimal(five_minute) * rates.cache_write
        + Decimal(one_hour) * (rates.cache_write_1h or rates.cache_write)
        + Decimal(int(usage.get("output_tokens") or 0)) * rates.output
    )
    return usd / MTOK


def read_stream(path: Path, sheet: DatedSheet) -> dict[str, Any]:
    """One stream's spend: the binary's figure if it has ended, else a list-price estimate.

    A message's usage is reported on each of its assistant lines; the largest figure per
    message id counts, so a message is never counted twice.
    """
    binary: Decimal | None = None
    messages: dict[str, tuple[str, dict[str, int]]] = {}
    with path.open("rb") as handle:
        for raw in handle:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            if line.get("type") == "result" and line.get("total_cost_usd") is not None:
                binary = Decimal(str(line["total_cost_usd"]))
            elif line.get("type") == "assistant":
                message = line.get("message") or {}
                usage = message.get("usage") or {}
                model = message.get("model")
                if not isinstance(model, str) or not usage:
                    continue
                key = str(message.get("id") or line.get("uuid"))
                held = messages.get(key, (model, {}))[1]
                merged = dict(held)
                for name in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_input_tokens",
                    "cache_creation_input_tokens",
                ):
                    merged[name] = max(int(held.get(name) or 0), int(usage.get(name) or 0))
                creation = usage.get("cache_creation") or {}
                merged["one_hour"] = max(
                    int(held.get("one_hour") or 0),
                    int(creation.get("ephemeral_1h_input_tokens") or 0),
                )
                messages[key] = (model, merged)
    estimate = sum(
        (
            price(
                model,
                {**u, "cache_creation": {"ephemeral_1h_input_tokens": u.get("one_hour", 0)}},
                sheet,
            )
            for model, u in messages.values()
        ),
        Decimal(0),
    )
    return {
        "stream": str(path),
        "ended": binary is not None,
        "binary_usd": None if binary is None else str(binary),
        "estimate_usd": str(estimate),
        "messages": len(messages),
        "counted_usd": str(binary if binary is not None else estimate),
    }


def reading(run_dir: Path, review_root: Path, sheet: DatedSheet) -> dict[str, Any]:
    """What the run has spent so far, over every stream it has written."""
    rows = [read_stream(p, sheet) for p in streams(run_dir, review_root)]
    counted = sum((Decimal(r["counted_usd"]) for r in rows), Decimal(0))
    estimate = sum((Decimal(r["estimate_usd"]) for r in rows), Decimal(0))
    binary = sum((Decimal(r["binary_usd"]) for r in rows if r["binary_usd"]), Decimal(0))
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "spent_usd": str(counted),
        "binary_usd_ended_calls": str(binary),
        "list_price_usd_all_calls": str(estimate),
        "calls": len(rows),
        "calls_running": sum(1 for r in rows if not r["ended"]),
    }


def alive(pid: int) -> bool:
    """Whether ``pid`` is a live process (a zombie counts as ended)."""
    done = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    state = done.stdout.strip()
    return bool(state) and not state.startswith("Z")


def descendants(pid: int) -> list[int]:
    """Every process below ``pid``, deepest last; read before the parent is signalled."""
    done = subprocess.run(
        ["ps", "-e", "-o", "pid=,ppid="], capture_output=True, text=True, check=False
    )
    children: dict[int, list[int]] = {}
    for row in done.stdout.splitlines():
        parts = row.split()
        if len(parts) == 2:
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
    found: list[int] = []
    queue = [pid]
    while queue:
        parent = queue.pop(0)
        for child in children.get(parent, []):
            found.append(child)
            queue.append(child)
    return found


def signal_all(pids: list[int], sig: signal.Signals) -> None:
    """Send ``sig`` to each of ``pids`` that still exists."""
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue


def remove_credentials(run_dir: Path, review_root: Path) -> list[str]:
    """Remove the credential files a stopped session may have left; return what was removed."""
    removed: list[str] = []
    roots = [run_dir / SESSIONS_DIRNAME]
    if review_root.is_dir():
        roots.append(review_root)
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.name in CREDENTIAL_FILES and path.is_file() and not path.is_symlink():
                path.unlink()
                removed.append(str(path))
    return removed


def stop(pid: int, grace_s: float) -> dict[str, Any]:
    """Stop the run: the orchestrator first, then everything it spawned, then force."""
    tree = descendants(pid)
    signal_all([pid], signal.SIGINT)
    deadline = time.monotonic() + grace_s
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(1)
    survivors = [p for p in [pid, *tree] if alive(p)]
    signal_all(survivors, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while any(alive(p) for p in survivors) and time.monotonic() < deadline:
        time.sleep(1)
    forced = [p for p in survivors if alive(p)]
    signal_all(forced, signal.SIGKILL)
    time.sleep(1)
    return {"tree": [pid, *tree], "terminated": survivors, "killed": forced}


def main() -> int:
    """Watch the run until it ends or reaches the stop; return 3 if the watcher stopped it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True, help="the `physgate run` process")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--cap-usd", type=Decimal, required=True, help="the run's hard cap")
    parser.add_argument("--kill-at-usd", type=Decimal, required=True, help="where the stop fires")
    parser.add_argument("--prices", default="2026-10-16", help="the price sheet's date")
    parser.add_argument("--interval", type=float, default=20.0)
    parser.add_argument("--grace", type=float, default=30.0, help="seconds given to a clean stop")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.kill_at_usd > args.cap_usd:
        parser.error("the stop fires at or below the cap")
    sheet = load_price_sheet(args.prices)
    run_dir, review_root = args.run_dir.resolve(), args.review_root.resolve()
    code = 0
    with args.log.open("a") as log:
        while True:
            found = reading(run_dir, review_root, sheet)
            found["cap_usd"], found["kill_at_usd"] = str(args.cap_usd), str(args.kill_at_usd)
            running = alive(args.pid)
            over = Decimal(found["spent_usd"]) >= args.kill_at_usd
            if over and running:
                found["stopped"] = stop(args.pid, args.grace)
                found["credentials_removed"] = remove_credentials(run_dir, review_root)
                found["outcome"] = "stopped at the cap"
                code = 3
            elif not running:
                found["outcome"] = "the run ended on its own"
            log.write(json.dumps(found) + "\n")
            log.flush()
            if "outcome" in found:
                print(json.dumps(found), flush=True)
                return code
            time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
