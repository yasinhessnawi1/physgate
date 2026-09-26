"""Kill-and-resume cycles for the orchestrator: seeded kills per arm, then a resume each.

Run as a script, not collected as a test:

    python kill_cycles.py --arm fake --seeds 1-10 --out <dir>
    python kill_cycles.py --arm real --seeds 1-10 --out <dir>
    python kill_cycles.py --arm tool --seeds 1-10 --out <dir>

Each cycle starts a fresh run of two subtasks through the decomposition's own
start (no model call: decomposition is outside the kill window), drives it with
``physgate run`` in a child process, sends that process SIGKILL at a seeded
point, then runs ``physgate resume`` in a new child process, and judges the
result from the files alone. Both commands run through the command's own code,
with a test gate and a test reviewer registered. No model is called in either
arm, and the two arms are reported separately.

Arm ``fake``: the command's session dispatcher is replaced by a stand-in that
writes into the worktree after a 0.5 s pause. The kill anchor for seed ``k`` is
``random.Random(40_000 + k).randint(4, T - 1)`` event lines, where ``T`` is the
number of lines a reference run of the same workload, with no kill, writes.

Arm ``real``: each session is a real Claude Code under the hook layer's
settings, talking to a scripted endpoint served by this parent process, which
outlives the killed orchestrator. No event line is written while a session
runs, so this arm's kills are anchored on the endpoint instead: for seed ``k``,
``rng = random.Random(50_000 + k)`` picks the subtask (``rng.randrange(2)``) and
the request of its first session (``rng.randint(1, R)``, ``R`` the script's
requests). The endpoint holds that request open, the orchestrator is sent
SIGKILL while the binary waits on it, and the request is released only once the
session is dead. A kill is counted as mid-task only if the session's pid was
alive with its recorded start time just before and just after the kill;
otherwise the cycle is a harness miss, reported as one and never re-drawn.

Arm ``tool``: as ``real``, but the kill lands while the session's Bash tool
runs. For seed ``k``, ``rng = random.Random(60_000 + k)`` picks the subtask
(``rng.randrange(2)``) and a delay ``d = rng.randint(0, 20) / 10`` seconds. The
endpoint answers request 2 of that subtask's first session (the Bash step) with
a foreground loop that appends a timestamp to a heartbeat file outside the
worktree every 0.1 s; the file's path is unique to the cycle and marks the
command's process. Once a process carrying it is seen in the session's tree (by
parent pid: measured on 2.1.272, the tool's shell runs in a session of its own,
so the binary's session group does not hold it), the harness waits ``d`` and
sends the orchestrator SIGKILL. After the resume, every process of the tree at
the kill must be gone, nothing may carry the marker, and the heartbeat must hold
no line stamped after the resume stopped the session, nor grow afterwards.

The output records the orchestrator's commit, this file's sha256 and, per
cycle, the seed, the anchor and what the kill actually hit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
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
from physgate.orchestrator.processes import started_at, table, tree  # noqa: E402
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


def cycle_fake(
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


#: How long the endpoint holds the anchored request, at most, and how long the
#: harness waits for it to be reached.
HOLD_S = 300.0
REACH_S = 600.0


def utc_ms() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Anchor:
    """The endpoint side of a real-arm kill: fire on one request, hold it open."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.target: tuple[str, int] | None = None
        self.fired = threading.Event()
        self.release = threading.Event()
        self.fired_utc: str | None = None

    def arm(self, subtask_id: str, request: int) -> None:
        with self._lock:
            self.target = (subtask_id, request)
            self.fired_utc = None
        self.fired.clear()
        self.release.clear()

    def __call__(self, thread: str, cwd: str, results: int) -> dict[str, Any] | None:
        with self._lock:
            hit = self.target == (Path(cwd).name, results + 1) and thread == "main"
            if hit:
                self.target = None
                self.fired_utc = utc_ms()
        if hit:
            self.fired.set()
            self.release.wait(timeout=HOLD_S)
        return None


def session_of(run_dir: Path, subtask_id: str) -> dict[str, Any] | None:
    """The recorded session of ``subtask_id`` not yet marked ended, if there is one."""
    for record_path in sorted((run_dir / "sessions").glob("*/process.json")):
        if (record_path.parent / "ended.json").exists():
            continue
        record: dict[str, Any] = json.loads(record_path.read_text())
        if any(f"subtask {subtask_id} " in part for part in record["argv"]):
            return record
    return None


def cycle_real(
    out: Path,
    seed: int,
    ref: dict[str, Any],
    env: dict[str, str],
    install: str,
    anchor: Anchor,
    requests: int,
) -> dict[str, Any]:
    root = out / f"seed-{seed}"
    started = utc()
    build(root, env["ANTHROPIC_BASE_URL"])
    rng = random.Random(50_000 + seed)
    subtask = SUBTASKS[rng.randrange(2)]
    request = rng.randint(1, requests)
    anchor.arm(subtask, request)
    events = root / "run" / "events.jsonl"
    proc = spawn(root, "real", "run", env, install)
    deadline = time.monotonic() + REACH_S
    while not anchor.fired.wait(timeout=0.05):
        if proc.poll() is not None or time.monotonic() > deadline:
            break
    reached = anchor.fired.is_set()
    held_utc = anchor.fired_utc
    orchestrator_alive = proc.poll() is None
    session = session_of(root / "run", subtask) if reached else None
    pid = int(session["pid"]) if session else None
    recorded_start = session.get("started") if session else None

    def alive() -> bool:
        return pid is not None and recorded_start is not None and started_at(pid) == recorded_start

    alive_before = alive()
    tree_at_kill = len(tree(pid)) if pid is not None and alive_before else 0
    kill_utc = utc_ms()
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    alive_after = alive()
    snapshot = {name: (root / "run" / name).read_bytes() for name in FILES}
    killed_at = lines(events)
    died: list[str] = []

    def watch() -> None:
        # The held request is let go only once the session is gone, so the resume
        # finds it alive and has to stop it.
        while alive() and not anchor.release.is_set():
            time.sleep(0.05)
        died.append(utc_ms())
        anchor.release.set()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    resume = spawn(root, "real", "resume", env, install)
    try:
        code: int | None = resume.wait(timeout=900)
    except subprocess.TimeoutExpired:
        resume.kill()
        code = None
    anchor.arm("", 0)  # disarm, and release anything still held
    anchor.release.set()
    watcher.join(timeout=10)
    step = printed_step(root / "resume.out")
    verdict = judge(root, snapshot, ref, killed_at)
    after = read_events(events)[killed_at:]
    killed_id = str(session["session_id"]) if session else None
    stopped = [e for e in after if e.kind == "leftover_stopped" and e.session_id == killed_id]
    fresh = [
        e
        for e in after
        if e.kind == "session_ended"
        and e.subtask_id == subtask
        and e.session_id != killed_id
        and e.attempt == 1
        and e.outcome == "completed"
    ]
    mid_task = reached and orchestrator_alive and alive_before and alive_after
    checks = {
        "the kill landed mid-session": mid_task,
        "resume exited 0 with the run done": code == 0 and step == "done",
        "the live session was stopped as a leftover": len(stopped) == 1,
        "a fresh session on the same attempt completed": len(fresh) == 1,
    }
    checks.update(verdict.pop("checks"))
    return {
        "seed": seed,
        "started_utc": started,
        "anchor": {"subtask": subtask, "request": request},
        "harness_miss": not mid_task,
        "request_held_utc": held_utc,
        "kill_utc": kill_utc,
        "orchestrator_alive_at_kill": orchestrator_alive,
        "session": {
            "session_id": killed_id,
            "pid": pid,
            "recorded_start": recorded_start,
            "alive_just_before_kill": alive_before,
            "alive_just_after_kill": alive_after,
            "processes_in_tree_at_kill": tree_at_kill,
            "seen_dead_utc": died[0] if died else None,
            "leftover_stopped": [{"pid": e.pid, "killed": e.killed, "ts": e.ts} for e in stopped],
        },
        "lines_on_disk_after_kill": killed_at,
        "torn_bytes_at_kill": {n: len(b) - (b.rfind(b"\n") + 1) for n, b in snapshot.items()},
        "resume_exit": code,
        "resume_step": step,
        "fresh_session": fresh[0].session_id if fresh else None,
        "checks": checks,
        "clean": all(checks.values()),
        **verdict,
    }


#: The script's only Bash step, the one arm ``tool`` swaps for a long command.
TOOL_REQUEST = 2
#: How long the harness waits for the swapped command's process to appear, and
#: how long after the resume's exit it watches the heartbeat for growth.
SEEN_S = 120.0
QUIET_S = 3.0


class ToolAnchor:
    """The endpoint side of a tool-arm kill: serve a long command, once, in place of one step."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.target: tuple[str, int] | None = None
        self.step: dict[str, Any] | None = None
        self.fired = threading.Event()
        self.fired_utc: str | None = None

    def arm(self, subtask_id: str, request: int, step: dict[str, Any] | None) -> None:
        with self._lock:
            self.target = (subtask_id, request) if step is not None else None
            self.step = step
            self.fired_utc = None
        self.fired.clear()

    def __call__(self, thread: str, cwd: str, results: int) -> dict[str, Any] | None:
        with self._lock:
            hit = self.target == (Path(cwd).name, results + 1) and thread == "main"
            if not hit:
                return None
            self.target = None
            self.fired_utc = utc_ms()
            step = self.step
        self.fired.set()
        return step


def commands(pids: list[int]) -> dict[int, str]:
    """The command line of each of ``pids`` still running, from one ``ps`` call."""
    if not pids:
        return {}
    out = subprocess.run(
        ["ps", "-ww", "-o", "pid=,command=", "-p", ",".join(str(p) for p in pids)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    ).stdout
    found: dict[int, str] = {}
    for row in out.splitlines():
        pid, _, command = row.strip().partition(" ")
        if pid.isdigit():
            found[int(pid)] = command.strip()
    return found


def carrying(marker: str) -> list[int]:
    """Every process on the machine whose command line carries ``marker``."""
    out = subprocess.run(
        ["ps", "-axww", "-o", "pid=,command="],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    ).stdout
    me = os.getpid()
    return [
        int(pid)
        for pid, _, command in (row.strip().partition(" ") for row in out.splitlines())
        if pid.isdigit() and int(pid) != me and marker in command
    ]


def heartbeat(path: Path) -> tuple[int, int, float | None]:
    """The heartbeat file's size, its line count, and its last line's stamp (epoch seconds)."""
    if not path.exists():
        return 0, 0, None
    data = path.read_bytes()
    rows = [r for r in data.split(b"\n") if r.strip()]
    last: float | None = None
    for row in reversed(rows):
        try:
            last = float(row)
            break
        except ValueError:
            continue
    return len(data), data.count(b"\n"), last


def epoch_of(ts: str) -> float:
    """An event line's timestamp as epoch seconds."""
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp()


def cycle_tool(
    out: Path,
    seed: int,
    ref: dict[str, Any],
    env: dict[str, str],
    install: str,
    anchor: ToolAnchor,
) -> dict[str, Any]:
    root = out / f"seed-{seed}"
    started = utc()
    build(root, env["ANTHROPIC_BASE_URL"])
    rng = random.Random(60_000 + seed)
    subtask = SUBTASKS[rng.randrange(2)]
    delay = rng.randint(0, 20) / 10
    beat = root / "tool" / f"r-or-01-heartbeat-seed-{seed}.log"
    beat.parent.mkdir(parents=True)
    marker = str(beat)
    command = f"i=0; while [ $i -lt 3000 ]; do date +%s.%N >> {marker}; sleep 0.1; i=$((i+1)); done"
    anchor.arm(subtask, TOOL_REQUEST, tool("Bash", command=command))
    events = root / "run" / "events.jsonl"
    proc = spawn(root, "tool", "run", env, install)
    deadline = time.monotonic() + REACH_S
    while not anchor.fired.wait(timeout=0.05):
        if proc.poll() is not None or time.monotonic() > deadline:
            break
    reached = anchor.fired.is_set()
    served_utc = anchor.fired_utc
    session = session_of(root / "run", subtask) if reached else None
    pid = int(session["pid"]) if session else None
    recorded_start = session.get("started") if session else None
    seen_utc: str | None = None
    if pid is not None:
        deadline = time.monotonic() + SEEN_S
        while proc.poll() is None and time.monotonic() < deadline:
            if any(marker in c for c in commands([p.pid for p in tree(pid)]).values()):
                seen_utc = utc_ms()
                break
            time.sleep(0.02)
    if seen_utc is not None:
        time.sleep(delay)

    def alive() -> bool:
        return pid is not None and recorded_start is not None and started_at(pid) == recorded_start

    orchestrator_alive = proc.poll() is None
    at_kill = tree(pid) if pid is not None and alive() else []
    named = commands([p.pid for p in at_kill])
    marked = [p for p in at_kill if marker in named.get(p.pid, "")]
    alive_before = alive()
    marked_before = bool(marked) and all(started_at(p.pid) == p.started for p in marked)
    beats_at_kill = heartbeat(beat)[1]
    kill_utc = utc_ms()
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    alive_after = alive()
    marked_after = bool(marked) and all(started_at(p.pid) == p.started for p in marked)
    snapshot = {name: (root / "run" / name).read_bytes() for name in FILES}
    killed_at = lines(events)
    resume = spawn(root, "tool", "resume", env, install)
    try:
        code: int | None = resume.wait(timeout=900)
    except subprocess.TimeoutExpired:
        resume.kill()
        code = None
    anchor.arm("", 0, None)  # disarm
    resumed_utc = utc_ms()
    size_at_exit, _, _ = heartbeat(beat)
    time.sleep(QUIET_S)
    size_later, beats_total, last_beat = heartbeat(beat)
    still_there = [p for p in at_kill if started_at(p.pid) == p.started]
    carriers = carrying(marker)
    step = printed_step(root / "resume.out")
    verdict = judge(root, snapshot, ref, killed_at)
    after = read_events(events)[killed_at:]
    killed_id = str(session["session_id"]) if session else None
    stopped = [e for e in after if e.kind == "leftover_stopped" and e.session_id == killed_id]
    fresh = [
        e
        for e in after
        if e.kind == "session_ended"
        and e.subtask_id == subtask
        and e.session_id != killed_id
        and e.attempt == 1
        and e.outcome == "completed"
    ]
    stop_epoch = epoch_of(stopped[0].ts) if stopped else None
    mid_tool = (
        reached
        and seen_utc is not None
        and orchestrator_alive
        and alive_before
        and alive_after
        and marked_before
        and marked_after
    )
    checks = {
        "the kill landed mid-tool": mid_tool,
        "resume exited 0 with the run done": code == 0 and step == "done",
        "the live session was stopped as a leftover": len(stopped) == 1,
        "a fresh session on the same attempt completed": len(fresh) == 1,
    }
    checks.update(verdict.pop("checks"))
    checks["every process of the tree at the kill is gone"] = bool(at_kill) and not still_there
    checks["no process carries the marker"] = not carriers
    checks["no heartbeat after the stop"] = stop_epoch is not None and (
        last_beat is None or last_beat <= stop_epoch
    )
    checks["the heartbeat did not grow after the resume"] = size_at_exit == size_later
    return {
        "seed": seed,
        "started_utc": started,
        "anchor": {"subtask": subtask, "request": TOOL_REQUEST, "delay_s": delay},
        "harness_miss": not mid_tool,
        "bash_served_utc": served_utc,
        "marker_seen_utc": seen_utc,
        "kill_utc": kill_utc,
        "orchestrator_alive_at_kill": orchestrator_alive,
        "session": {
            "session_id": killed_id,
            "pid": pid,
            "recorded_start": recorded_start,
            "alive_just_before_kill": alive_before,
            "alive_just_after_kill": alive_after,
            "leftover_stopped": [{"pid": e.pid, "killed": e.killed, "ts": e.ts} for e in stopped],
        },
        "tree_at_kill": [
            {
                "pid": p.pid,
                "ppid": p.ppid,
                "started": p.started,
                "carries_marker": p in marked,
                "command": named.get(p.pid, "")[:160],
            }
            for p in at_kill
        ],
        "marker_alive_just_before_kill": marked_before,
        "marker_alive_just_after_kill": marked_after,
        "heartbeat": {
            "path": marker,
            "lines_at_kill": beats_at_kill,
            "lines_total": beats_total,
            "last_stamp": last_beat,
            "stop_stamp": stop_epoch,
            "size_at_resume_exit": size_at_exit,
            "size_after_quiet": size_later,
        },
        "after_resume": {
            "resume_exit_utc": resumed_utc,
            "tree_processes_still_alive": [p.pid for p in still_there],
            "marker_carriers": carriers,
        },
        "lines_on_disk_after_kill": killed_at,
        "torn_bytes_at_kill": {n: len(b) - (b.rfind(b"\n") + 1) for n, b in snapshot.items()},
        "resume_exit": code,
        "resume_step": step,
        "fresh_session": fresh[0].session_id if fresh else None,
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


#: The orchestrator code under test: ``src/`` must be this commit's ``src/``.
SRC_COMMIT = "5cb2a40"
#: The pinned runtime, as its release manifest lists it (linux-x64, 2.1.272).
BINARY_SHA256 = "d81396a668eb76fbddb49a2a5841f1b5d7af96b4c1f6500ced92f2c988f5bcd4"
#: Credentials the driver never passes on: only the dummy key reaches a session.
OTHER_CREDENTIALS = ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _machine() -> dict[str, Any]:
    found: dict[str, Any] = {
        "host": platform.node(),
        "platform": platform.platform(),
        "loadavg": list(os.getloadavg()),
    }
    for name in ("cpu.stat", "cpu.pressure"):
        cgroup = Path("/sys/fs/cgroup") / name
        if cgroup.is_file():
            found[f"cgroup_{name}"] = cgroup.read_text().strip()
    return found


def main() -> None:
    if sys.argv[1:2] == ["child"]:
        root, arm, mode, install = sys.argv[2:6]
        sys.exit(child(Path(root), arm, mode, install))
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["fake", "real", "tool"], required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve() / args.arm
    binary = os.environ.get("PHYSGATE_CLAUDE_BIN", "")
    stamp = {
        "arm": args.arm,
        "seeds": args.seeds,
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "src_is_src_of": SRC_COMMIT
        if _git("rev-parse", "HEAD:src") == _git("rev-parse", f"{SRC_COMMIT}:src")
        else None,
        "harness_sha256": _sha256(Path(__file__)),
        "endpoint_sha256": _sha256(HERE / "scripted_endpoint.py"),
        "claude_bin": binary,
        "claude_bin_sha256": _sha256(Path(binary)) if binary else "",
        "machine": _machine(),
        "started_utc": utc(),
    }
    refused = []
    if stamp["dirty"]:
        refused.append("the tree is not clean")
    if stamp["src_is_src_of"] != SRC_COMMIT:
        refused.append(f"src/ is not src/ at {SRC_COMMIT}")
    if args.arm != "fake" and stamp["claude_bin_sha256"] != BINARY_SHA256:
        refused.append("the Claude Code binary is not the pinned one")
    if refused:
        print(json.dumps({"refused": refused, **stamp}), flush=True)
        sys.exit(2)
    out.mkdir(parents=True)
    print(json.dumps(stamp), flush=True)
    install = out / "install"
    # Both arms: the command checks a reused installation against the source, and
    # the fake arm's sessions never use it.
    prepare_install(install, REPO_ROOT)
    script = session_script()
    anchor = Anchor()
    tool_anchor = ToolAnchor()
    with serving(script) as (api, url):
        env = {
            **{k: v for k, v in os.environ.items() if k not in OTHER_CREDENTIALS},
            "ANTHROPIC_API_KEY": DUMMY_KEY,
            "ANTHROPIC_BASE_URL": url,
            "DISABLE_AUTOUPDATER": "1",
        }
        ref = reference_run(out, args.arm, env, str(install))
        print(json.dumps({"reference": {"exit": ref["exit"], "T": ref["T"]}}), flush=True)
        api.on_request = tool_anchor if args.arm == "tool" else anchor
        results = []
        for seed in seeds(args.seeds):
            if args.arm == "real":
                result = cycle_real(out, seed, ref, env, str(install), anchor, len(script.main))
            elif args.arm == "tool":
                result = cycle_tool(out, seed, ref, env, str(install), tool_anchor)
            else:
                result = cycle_fake(out, args.arm, seed, ref, env, str(install))
            results.append(result)
            print(json.dumps(result), flush=True)
        requests = list(api.requests)
        failures = list(api.failures)
    landed = {
        "real": "the kill landed mid-session",
        "tool": "the kill landed mid-tool",
    }.get(args.arm, "the kill landed")
    summary = {
        **stamp,
        "reference_exit": ref["exit"],
        "reference_T": ref["T"],
        "cycles": len(results),
        "kills_landed": sum(r["checks"][landed] for r in results),
        "harness_misses": sum(not r["checks"][landed] for r in results),
        "clean": sum(r["clean"] for r in results),
        "endpoint_requests": len(requests),
        "requests_with_another_credential": sum(r.carried_other_credential for r in requests),
        "endpoint_failures": failures,
        "machine_at_end": _machine(),
        "finished_utc": utc(),
    }
    (out / "results.json").write_text(json.dumps({"summary": summary, "cycles": results}, indent=1))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
