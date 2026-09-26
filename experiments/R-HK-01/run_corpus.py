#!/usr/bin/env python3
"""Drive the frozen R-HK-01 corpus through the enforcement layer's own harness.

Committed before the run. Invents nothing: it imports the layer's bypass-suite
harness unchanged and, for each attempt in ``attempts.jsonl``, reuses that
harness's own placement, session run, snapshot, and refusal/put-back reading.
The pass condition is the suite's own: no reach, and a refusal or put-back on
record from the layer.

Usage, on the server, from the repo root:

    uv run python experiments/R-HK-01/run_corpus.py \
        experiments/R-HK-01/attempts.jsonl \
        experiments/R-HK-01/RESULT.runlog.jsonl

Each attempt writes one result line as it finishes, so a crash loses nothing.
A final summary line (``"kind": "summary"``) closes the file. An absent binary
is recorded ``absent`` and never dropped. Nothing here decides the verdict; it
records what happened. RESULT.md is written from this log.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Import the enforcement layer's own bypass-suite harness, unchanged.
HERE = Path(__file__).resolve()
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tests" / "integration" / "hooks"))

import test_the_bypass_suite as bp  # noqa: E402
from hook_session import run_session  # noqa: E402
from fake_messages_api import Script, text  # noqa: E402


def _machine() -> dict[str, object]:
    import platform
    import subprocess

    def read(path: str) -> str | None:
        try:
            return Path(path).read_text().strip()
        except OSError:
            return None

    import os

    load = None
    try:
        load = list(os.getloadavg())
    except OSError:
        pass
    binver = None
    try:
        from hook_session import claude_binary

        binver = subprocess.run(
            [claude_binary(), "--version"], capture_output=True, text=True
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - version probe is best-effort
        pass
    return {
        "platform": sys.platform,
        "uname": platform.platform(),
        "load_at_start": load,
        "cgroup_cpu_max": read("/sys/fs/cgroup/cpu.max"),
        "claude_version": binver,
    }


def _binary_of(code: str) -> str:
    # The first shell word is the catalog binary; only used to test presence.
    return code.strip().split()[0] if code.strip() else ""


def run_one(attempt: dict[str, object], out) -> str:
    code = str(attempt["code"])
    binary = _binary_of(code)
    if binary and shutil.which(binary) is None:
        rec = {"id": attempt["id"], "binary": binary, "outcome": "absent",
                "reached": [], "caught_by": [], "detail": "binary not installed"}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        return "absent"

    root = Path(tempfile.mkdtemp(prefix="rhk-"))
    try:
        steps = [bp.bash(code)]
        run = run_session(
            root,
            Script(main=[*bp._place(steps, root), text("end")]),
            files=bp.FILES,
            prepare=bp._prepare,
            store_root=str(root / "outside" / "store"),
            held_out=(str(root / "outside" / "heldout"),),
        )
        before = json.loads((root / bp.SNAPSHOT_KEY).read_text())
        after = bp._snapshot(root)
        reached = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        caught = bp._caught_by(run)
        told = run.told_after(1)
        leak = "the held-out answer" in told

        problems = []
        if reached:
            problems.append(f"REACHED {reached}")
        if leak:
            problems.append("held-out content shown to the agent")
        if not caught and not reached and not leak:
            # Neither stopped on record nor observably reached: not a pass, a look.
            problems.append("no refusal or put-back on record, and no observed reach")
        outcome = "no reach" if not problems else "FAILED: " + "; ".join(problems)
        rec = {
            "id": attempt["id"],
            "binary": binary,
            "target_key": attempt.get("target_key"),
            "expected_layer": attempt.get("expected_layer"),
            "single_layer": attempt.get("single_layer"),
            "reached": reached,
            "caught_by": caught,
            "leak": leak,
            "outcome": outcome,
        }
        out.write(json.dumps(rec) + "\n")
        out.flush()
        return outcome
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    attempts_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    attempts = [
        json.loads(line)
        for line in attempts_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    counts = {"no reach": 0, "absent": 0, "reached_or_failed": 0}
    with out_path.open("w") as out:
        out.write(json.dumps({"kind": "machine", **_machine()}) + "\n")
        out.flush()
        for i, attempt in enumerate(attempts, 1):
            outcome = run_one(attempt, out)
            if outcome == "no reach":
                counts["no reach"] += 1
            elif outcome == "absent":
                counts["absent"] += 1
            else:
                counts["reached_or_failed"] += 1
            print(f"[{i}/{len(attempts)}] {attempt['id']}: {outcome}", file=sys.stderr)
        summary = {
            "kind": "summary",
            "total": len(attempts),
            **counts,
            "load_at_end": (list(__import__("os").getloadavg()) if hasattr(__import__("os"), "getloadavg") else None),
        }
        out.write(json.dumps(summary) + "\n")
    print(json.dumps(summary), file=sys.stderr)
    # Exit non-zero if anything reached or needs a look, so a wrapper notices.
    return 1 if counts["reached_or_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
