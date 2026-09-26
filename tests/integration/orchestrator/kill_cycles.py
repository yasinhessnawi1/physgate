"""Kill-and-resume cycles for the orchestrator: seeded kills per arm, then a resume each.

Run as a script, not collected as a test:

    python kill_cycles.py --arm fake --seeds 1-10 --out <dir>
    python kill_cycles.py --arm real --seeds 1-10 --out <dir>

Each cycle starts a fresh run of two subtasks through the decomposition's own
start (no model call: decomposition is outside the kill window), drives it with
``physgate run`` in a child process, sends that process SIGKILL as soon as its
event log holds a seeded number of lines, then runs ``physgate resume`` in a new
child process, and judges the result from the files alone. Both commands run
through the command's own code, with a test gate and a test reviewer registered.

Arm ``fake``: the command's session dispatcher is replaced by a stand-in that
writes into the worktree after a 0.5 s pause, so kills land inside sessions as
well as between steps. Arm ``real``: each session is a real Claude Code under the
hook layer's settings, talking to a scripted endpoint served by this parent
process, which outlives the killed orchestrator. No model is called in either
arm. The two arms are reported separately.

The kill anchor for seed ``k`` is ``random.Random(40_000 + k).randint(4, T - 1)``,
where ``T`` is the number of event lines a reference run of the same workload,
with no kill, writes. The output records the orchestrator's commit, this file's
sha256, the seed, ``T``, the anchor and the line count actually reached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

from git_rig import DispatchPort, Gate, Reviewer, config, sh, target_repo  # noqa: E402
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool  # noqa: E402

import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.cli import main as physgate_main  # noqa: E402
from physgate.orchestrator.budget import SessionEnd  # noqa: E402
from physgate.orchestrator.decompose import (  # noqa: E402
    Outcome,
    Plan,
    PlannedModule,
    mint_id,
    start_run,
)
from physgate.orchestrator.events import read_events  # noqa: E402
from physgate.orchestrator.git import head_of  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.orchestrator.ports import SessionReport, SessionRequest  # noqa: E402
from physgate.orchestrator.processes import started_at, table  # noqa: E402
from physgate.orchestrator.run_config import endpoint_of  # noqa: E402
from physgate.state.schema import Node  # noqa: E402
from physgate.state.store import journal_records_after  # noqa: E402

SEED = 1
MODULES = ("s1", "s2")
FILES = ("events.jsonl", "ledger.jsonl", "store/journal.jsonl")
SUBTASKS = tuple(mint_id(SEED, i, name) for i, name in enumerate(MODULES))


def ident(subtask_id: str) -> str:
    return subtask_id.replace("-", "_")


def node(node_id: str, kind: str = "component") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            "i": {"value": 1.5, "unit": "A", "source": "datasheet", "written_by": "electrical"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:0",
        "updated": "2026-09-26T00:00:00Z",
    }


def session_script() -> Script:
    """What every real session does, in whichever worktree it runs."""
    return Script(
        main=[
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool(
                "Bash",
                command="sleep 1; mkdir -p modules/{cwd_name} && echo 'x = 1' > "
                "modules/{cwd_name}/impl.py",
            ),
            tool(
                "Write",
                file_path="{cwd}/.physgate/proposals/electrical.node_{cwd_ident}.json",
                content=json.dumps(node("electrical.node_{cwd_ident}")),
            ),
            text("done"),
        ]
    )


def build(root: Path, url: str) -> None:
    """A fresh target repository and a run started from a fixed plan, as decomposition starts it."""
    repo = target_repo(root)
    cfg = config().model_copy(
        update={"target_head": head_of(repo, "master"), "endpoint": endpoint_of(url)}
    )
    plan = Plan(
        modules=tuple(
            PlannedModule(
                name=name, role="electrical", module_dir=f"modules/{sid}", spec=f"Build {name}."
            )
            for name, sid in zip(MODULES, SUBTASKS, strict=True)
        ),
        interface_nodes=(Node.model_validate(node("iface.bus", kind="interface")),),
    )
    outcome = Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model="claude-sonnet-5",
        num_turns=1,
    )
    start_run(outcome, config=cfg, run_dir=root / "run", target_repo=repo).close()


class SlowFakeSession:
    """The fake arm's session: after a pause, writes its module file and its proposal."""

    def __init__(self, run: RunGit) -> None:
        self.run = run

    def __call__(self, request: SessionRequest) -> SessionReport:
        time.sleep(0.5)
        worktree = self.run.open_subtask(request.subtask_id)
        module = worktree / request.module_dir
        module.mkdir(parents=True, exist_ok=True)
        (module / "impl.py").write_text("x = 1\n")
        node_id = f"electrical.node_{ident(request.subtask_id)}"
        proposal = worktree / ".physgate" / "proposals" / f"{node_id}.json"
        proposal.parent.mkdir(parents=True, exist_ok=True)
        proposal.write_text(json.dumps(node(node_id)))
        sid = f"fake-{uuid.uuid4().hex[:12]}"
        commit = commit_attempt(worktree, request.subtask_id, request.attempt, sid)
        return SessionReport(
            session_id=sid,
            end=SessionEnd(outcome="completed", cause=None),
            attempt_commit=commit,
            trajectory=f"sessions/{sid}/stdout.jsonl",
            worktree=str(worktree),
            reading_verified=True,
            node_files_halted=False,
            usage=(),
        )


def _fake_dispatcher(*, run: RunGit, **_: object) -> DispatchPort:
    return DispatchPort(SlowFakeSession(run))  # type: ignore[arg-type]


def child(root: Path, arm: str, mode: str, install: str) -> int:
    """One orchestrator process: ``physgate run`` or ``physgate resume`` on ``root``'s run."""
    if arm == "fake":
        # The command's own code, with only its session dispatcher swapped for the stand-in.
        setattr(orchestrator_cli, "ClaudeDispatcher", _fake_dispatcher)  # noqa: B010
    registrations = orchestrator_cli.Registrations(
        gate=Gate(), reviewers={"electrical": Reviewer()}
    )
    argv = [mode, "--run-dir", str(root / "run"), "--target", str(root / "target")]
    return physgate_main([*argv, "--install", install], registrations)


def lines(path: Path) -> int:
    return path.read_bytes().count(b"\n") if path.exists() else 0


def spawn(
    root: Path, arm: str, mode: str, env: dict[str, str], install: str
) -> subprocess.Popen[bytes]:
    with (root / f"{mode}.out").open("ab") as out:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__)), "child", str(root), arm, mode, install],
            stdout=out,
            stderr=out,
            env=env,
        )


def left_running(run_dir: Path) -> list[str]:
    """Every recorded session not marked ended, and every live process in a session's group."""
    found: list[str] = []
    rows = subprocess.run(
        ["ps", "-axo", "pid=,sess=,stat="], capture_output=True, text=True, check=False
    ).stdout.splitlines()
    members: dict[int, list[int]] = {}
    for row in rows:
        parts = row.split()
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit() and "Z" not in parts[2]:
            members.setdefault(int(parts[1]), []).append(int(parts[0]))
    live = table()
    for record_path in (run_dir / "sessions").glob("*/process.json"):
        record = json.loads(record_path.read_text())
        pid = int(record["pid"])
        if not (record_path.parent / "ended.json").exists():
            found.append(f"{record['session_id']}: not marked ended")
        if record.get("started") and started_at(pid) == record["started"]:
            found.append(f"{record['session_id']}: pid {pid} alive")
        # Spawned as its own session leader, so its descendants carry its pid as session id.
        alive = [p for p in members.get(pid, []) if p in live]
        if alive:
            found.append(f"{record['session_id']}: {len(alive)} process(es) of its session alive")
    return found


def judge(
    root: Path, snapshot: dict[str, bytes], ref: dict[str, Any], killed_at: int
) -> dict[str, Any]:
    run_dir = root / "run"
    checks: dict[str, bool] = {}
    for name in FILES:
        before = snapshot[name]
        whole = before[: before.rfind(b"\n") + 1]
        checks[f"prefix kept: {name}"] = (run_dir / name).read_bytes().startswith(whole)
    events = read_events(run_dir / "events.jsonl")
    attempts = sorted({a for e in events if isinstance(a := getattr(e, "attempt", None), int)})
    checks["no attempt beyond 1"] = attempts in ([], [1])
    writes: dict[str, list[dict[str, Any]]] = {}
    for record in journal_records_after(run_dir / "store", 0):
        writes.setdefault(record.node_id, []).append(record.payload)
    checks["each node written once, as in the reference"] = (
        all(len(v) == 1 for v in writes.values())
        and {k: v[0] for k, v in writes.items()} == ref["payloads"]
    )
    merges = sh(root / "target", "log", "--merges", "--format=%H", "physgate/run-1/run").split()
    checks["one merge per subtask"] = len(merges) == len(SUBTASKS)
    running = left_running(run_dir)
    checks["nothing left running"] = not running
    outcome: list[str] = []
    for e in events[killed_at:]:
        if e.kind == "resumed":
            outcome.append(f"resumed({e.subtask_id},{e.point})")
        elif e.kind == "leftover_stopped":
            outcome.append(f"leftover_stopped({e.session_id})")
        elif e.kind == "incident":
            outcome.append(f"incident({e.cause})")
        elif e.kind in ("halted", "infra_retry_scheduled", "attempt_rejected", "escalated"):
            outcome.append(e.kind)
    return {
        "checks": checks,
        "resume_outcome": outcome,
        "left_running": running,
        "attempts_seen": attempts,
        "journal_writes": {k: len(v) for k, v in writes.items()},
        "merges": len(merges),
    }


def reference_run(out: Path, arm: str, env: dict[str, str], install: str) -> dict[str, Any]:
    root = out / "reference"
    build(root, env["ANTHROPIC_BASE_URL"])
    code = spawn(root, arm, "run", env, install).wait(timeout=900)
    run_dir = root / "run"
    return {
        "exit": code,
        "T": lines(run_dir / "events.jsonl"),
        "payloads": {r.node_id: r.payload for r in journal_records_after(run_dir / "store", 0)},
    }


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def printed_step(path: Path) -> str | None:
    """The step the command printed last, if it printed one (its summary is indented JSON)."""
    text = path.read_text(errors="replace")
    decoder = json.JSONDecoder()
    found: str | None = None
    for at in [i for i in range(len(text)) if text[i] == "{" and (i == 0 or text[i - 1] == "\n")]:
        try:
            payload, _ = decoder.raw_decode(text, at)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and "step" in payload:
            found = str(payload["step"])
    return found


def cycle(
    out: Path, arm: str, seed: int, ref: dict[str, Any], env: dict[str, str], install: str
) -> dict[str, Any]:
    root = out / f"seed-{seed}"
    started = utc()
    build(root, env["ANTHROPIC_BASE_URL"])
    anchor = random.Random(40_000 + seed).randint(4, ref["T"] - 1)
    events = root / "run" / "events.jsonl"
    proc = spawn(root, arm, "run", env, install)
    deadline = time.monotonic() + 900
    while lines(events) < anchor and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.002)
    alive = proc.poll() is None
    reached = lines(events)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    snapshot = {name: (root / "run" / name).read_bytes() for name in FILES}
    killed_at = lines(events)
    resume = spawn(root, arm, "resume", env, install)
    try:
        code: int | None = resume.wait(timeout=900)
    except subprocess.TimeoutExpired:
        resume.kill()
        code = None
    step = printed_step(root / "resume.out")
    verdict = judge(root, snapshot, ref, killed_at)
    checks = {
        "the kill landed": alive and reached < ref["T"],
        "resume exited 0 with the run done": code == 0 and step == "done",
    }
    checks.update(verdict.pop("checks"))
    return {
        "seed": seed,
        "started_utc": started,
        "anchor_N": anchor,
        "lines_at_kill": reached,
        "lines_on_disk_after_kill": killed_at,
        "torn_bytes_at_kill": {n: len(b) - (b.rfind(b"\n") + 1) for n, b in snapshot.items()},
        "resume_exit": code,
        "resume_step": step,
        "checks": checks,
        "clean": all(checks.values()),
        **verdict,
    }


def seeds(spec: str) -> list[int]:
    first, _, last = spec.partition("-")
    return list(range(int(first), int(last or first) + 1))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> None:
    if sys.argv[1:2] == ["child"]:
        root, arm, mode, install = sys.argv[2:6]
        sys.exit(child(Path(root), arm, mode, install))
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["fake", "real"], required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve() / args.arm
    out.mkdir(parents=True)
    stamp = {
        "arm": args.arm,
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "claude_bin": os.environ.get("PHYSGATE_CLAUDE_BIN", ""),
        "started_utc": utc(),
    }
    print(json.dumps(stamp), flush=True)
    install = out / "install"
    if args.arm == "real":
        prepare_install(install, REPO_ROOT)
    else:
        install.mkdir()
    with serving(session_script()) as (_, url):
        env = {**os.environ, "ANTHROPIC_API_KEY": DUMMY_KEY, "ANTHROPIC_BASE_URL": url}
        ref = reference_run(out, args.arm, env, str(install))
        print(json.dumps({"reference": {"exit": ref["exit"], "T": ref["T"]}}), flush=True)
        results = []
        for seed in seeds(args.seeds):
            result = cycle(out, args.arm, seed, ref, env, str(install))
            results.append(result)
            print(json.dumps(result), flush=True)
    summary = {
        **stamp,
        "reference_exit": ref["exit"],
        "reference_T": ref["T"],
        "cycles": len(results),
        "kills_landed": sum(r["checks"]["the kill landed"] for r in results),
        "clean": sum(r["clean"] for r in results),
        "finished_utc": utc(),
    }
    (out / "results.json").write_text(json.dumps({"summary": summary, "cycles": results}, indent=1))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
