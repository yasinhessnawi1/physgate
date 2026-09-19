"""Driver: five seeds, two implementations, metrics as JSON. Shared scaffolding."""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import generator
import harness
from stores import open_store

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ACK_THRESHOLD = 250


def workload_run(impl: str, seed: int, runs_dir: Path, metrics_dir: Path) -> dict:
    """One seed of the main workload against one implementation."""
    store_root = runs_dir / impl / f"seed{seed}"
    if store_root.exists():
        shutil.rmtree(store_root)
    store_root.mkdir(parents=True)
    work = generator.build(seed)
    store = open_store(impl, store_root)
    metrics = harness.run(store, work)
    store.close()
    metrics["impl"] = impl
    out = metrics_dir / f"{impl}-seed{seed}.json"
    out.write_text(json.dumps(metrics, indent=2, default=str))
    print(f"[{impl} seed {seed}] failures={metrics['failure_count']} "
          f"diff_p95={metrics['c2_diff_ms']['p95']:.3f}ms "
          f"traverse_p95={metrics['c3_traverse_ms']['p95']:.3f}ms "
          f"wall={metrics['wall_s']}s", flush=True)
    return metrics


def crash_run(impl: str, seed: int, runs_dir: Path, metrics_dir: Path) -> dict:
    """Kill a writing process with SIGKILL, restart, score C4."""
    store_root = runs_dir / impl / f"crash{seed}"
    if store_root.exists():
        shutil.rmtree(store_root)
    store_root.mkdir(parents=True)
    ack_path = store_root / "acks.jsonl"
    ack_path.touch()

    child = subprocess.Popen(
        [sys.executable, str(HERE / "crash_child.py"), impl, str(seed),
         str(store_root), str(ack_path)],
        cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    deadline = time.time() + 900
    while time.time() < deadline:
        if child.poll() is not None:
            break
        with ack_path.open() as fh:
            n = sum(1 for _ in fh)
        if n >= ACK_THRESHOLD:
            break
        time.sleep(0.05)

    delay = random.Random(10_000 + seed).uniform(0.05, 0.40)
    time.sleep(delay)
    killed = child.poll() is None
    if killed:
        os.kill(child.pid, signal.SIGKILL)
    child.wait()

    verify = subprocess.run(
        [sys.executable, str(HERE / "crash_verify.py"), impl, str(seed),
         str(store_root), str(ack_path)],
        cwd=HERE, capture_output=True, text=True, check=False,
    )
    last = [ln for ln in verify.stdout.splitlines() if ln.startswith("{")]
    report = json.loads(last[-1]) if last else {
        "impl": impl, "seed": seed, "consistent": False,
        "error": verify.stderr[-2000:] or "verifier produced no report",
    }
    report["killed_mid_write"] = killed
    report["kill_delay_s"] = round(delay, 3)
    (metrics_dir / f"{impl}-seed{seed}-crash.json").write_text(json.dumps(report, indent=2))
    print(f"[{impl} seed {seed} crash] consistent={report.get('consistent')} "
          f"recover={report.get('open_and_recover_ms')}ms "
          f"acks={report.get('acknowledged_ops')} killed={killed}", flush=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", required=True)
    ap.add_argument("--seeds", default="1,2,3,4,5")
    ap.add_argument("--phase", default="all", choices=["all", "workload", "crash"])
    args = ap.parse_args()

    runs_dir = ROOT / "runs"
    metrics_dir = ROOT / "metrics"
    metrics_dir.mkdir(exist_ok=True)
    seeds = [int(s) for s in args.seeds.split(",")]

    for seed in seeds:
        if args.phase in ("all", "workload"):
            workload_run(args.impl, seed, runs_dir, metrics_dir)
        if args.phase in ("all", "crash"):
            crash_run(args.impl, seed, runs_dir, metrics_dir)


if __name__ == "__main__":
    main()
