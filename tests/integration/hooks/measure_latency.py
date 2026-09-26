"""Time every generated hook command on a realistic role session, beside a same-day control.

Usage: ``uv run python tests/integration/hooks/measure_latency.py <out.json>``

A hook has 200 ms. This measures what an agent's tool call actually pays: each
event is run through the exact command the settings generator wrote,
trampoline included, with a realistic event description on stdin, in rounds
interleaved with two controls (a bare isolated interpreter start, and the
trampoline around one), so that every figure has its reference taken on the
same machine in the same minutes. The first hook of a session also takes the
sentinel's record, so it is timed apart, over fresh sessions.

The fixture is what a role session protects: a copy of the repository's
experiments tree (the largest thing the sentinel records), a gate directory of
twelve files, a graph store built by the store itself from the seed-0 workload
(200 nodes), a held-out file, and three required-reading files that are also
the always-loaded set.

The machine is recorded with the numbers: the load average before and after
(on a shared host that is the host's load, not this process's), the thread
caps threaded libraries honour, the control group's CPU limit, throttling and
pressure where the kernel exposes them, and how many files of the interpreter's
environment have more than one link, which on Linux is how the installer
places them.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HERE / "tests" / "integration" / "state"))

import generator  # noqa: E402

from physgate.hooks.registry import REGISTRY  # noqa: E402
from physgate.hooks.settings import InstallRequest, install  # noqa: E402
from physgate.state.store import Store  # noqa: E402

ROUNDS = 21
FRESH_SESSIONS = 7
BUDGET_MS = 200.0


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _machine() -> dict[str, Any]:
    """What the numbers were taken on, read now, so a before and an after can be compared."""
    affinity = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    return {
        "loadavg": list(os.getloadavg()),
        "cgroup_cpu_max": _read("/sys/fs/cgroup/cpu.max"),
        "cgroup_cpu_stat": _read("/sys/fs/cgroup/cpu.stat"),
        "cgroup_cpu_pressure": _read("/sys/fs/cgroup/cpu.pressure"),
        "cpu_count": os.cpu_count(),
        "affinity": len(affinity) if affinity is not None else None,
    }


def _links(root: str) -> dict[str, int]:
    """Regular files under ``root``, and how many of them have more than one name on disk."""
    files = linked = 0
    for directory, _, names in os.walk(root):
        for name in names:
            st = os.lstat(os.path.join(directory, name))
            if not os.path.islink(os.path.join(directory, name)):
                files += 1
                linked += st.st_nlink > 1
    return {"files": files, "more_than_one_link": linked}


def _fixture() -> tuple[Path, Path, list[str], dict[str, list[str]]]:
    root = Path(tempfile.mkdtemp(prefix="hook-latency"))
    worktree = root / "worktree"
    shutil.copytree(HERE / "experiments", worktree / "experiments")
    gate = worktree / "src" / "physgate" / "gate"
    gate.mkdir(parents=True)
    for n in range(12):
        (gate / f"check_{n}.py").write_text(f"CHECK_{n} = True\n" * 40)
    (worktree / "src" / "physgate" / "electrical").mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()
    reading = []
    for name in ("standards.md", "module_spec.md", "skill.md"):
        (docs / name).write_text("A line of required reading.\n" * 300)
        reading.append(str(docs / name))
    store_root = root / "outside" / "store"
    store = Store(store_root)
    for op in generator.build(0).ops:
        if op.kind in ("create", "write") and op.payload is not None:
            store.write_node(op.payload, op.actor_role)
    store.close()
    (root / "outside" / "heldout").mkdir(parents=True)
    (root / "outside" / "heldout" / "scenario.json").write_text("{}\n")
    done = install(
        InstallRequest(
            profile="role",
            role="electrical",
            worktree=str(worktree),
            own_branch="subtask/electrical-1",
            store_root=str(store_root),
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=100_000,
            required_reading=tuple(reading),
            always_loaded=tuple(reading),
            held_out=(str(root / "outside" / "heldout"),),
        ),
        REGISTRY,
    )
    settings = json.loads(done.settings_path.read_text())
    commands = {e: shlex.split(g[0]["hooks"][0]["command"]) for e, g in settings["hooks"].items()}
    return root, worktree, reading, commands


def _run(argv: list[str], stdin: str) -> tuple[float, int]:
    start = time.perf_counter()
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, check=False)
    return (time.perf_counter() - start) * 1000, proc.returncode


def _summary(values: list[float]) -> dict[str, float]:
    """Median, spread and tail of ``values``.

    Quantiles are the inclusive kind, which interpolate between observed
    values and so never fall outside them: the default method extrapolates past
    the extremes of a small sample, which put a p90 above the maximum at n = 7.
    The count over the budget is given beside the median, because a median can
    pass while calls still miss.
    """
    ordered = sorted(values)
    deciles = statistics.quantiles(ordered, n=10, method="inclusive")
    quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
    return {
        "median": statistics.median(ordered),
        "p10": deciles[0],
        "p90": deciles[-1],
        "iqr": quartiles[-1] - quartiles[0],
        "min": ordered[0],
        "max": ordered[-1],
        "n": len(ordered),
        "over_budget": sum(v > BUDGET_MS for v in ordered),
    }


def measure() -> dict[str, Any]:
    """Build the fixture, time every event and both controls, and return the record."""
    before = _machine()
    root, worktree, reading, commands = _fixture()

    def event(name: str, session: str, **fields: object) -> str:
        return json.dumps(
            {"session_id": session, "cwd": str(worktree), "hook_event_name": name} | fields
        )

    bash = {"command": "python3 -m pytest -q tests/", "description": "run the tests"}
    write = {"file_path": str(worktree / "src/physgate/electrical/driver.py"), "content": "x = 1\n"}
    read_response = {
        "type": "text",
        "file": {"filePath": reading[0], "numLines": 301, "startLine": 1, "totalLines": 301},
    }
    cases: dict[str, tuple[str, dict[str, object]]] = {
        "PreToolUse Bash": ("PreToolUse", {"tool_name": "Bash", "tool_input": bash}),
        "PreToolUse Write": ("PreToolUse", {"tool_name": "Write", "tool_input": write}),
        "PreToolUse Read": (
            "PreToolUse",
            {"tool_name": "Read", "tool_input": {"file_path": reading[0]}},
        ),
        "PostToolUse Bash": (
            "PostToolUse",
            {"tool_name": "Bash", "tool_input": bash, "tool_response": {"stdout": ""}},
        ),
        "PostToolUse Read": (
            "PostToolUse",
            {
                "tool_name": "Read",
                "tool_input": {"file_path": reading[0]},
                "tool_response": read_response,
            },
        ),
        "PostToolUseFailure Bash": (
            "PostToolUseFailure",
            {
                "tool_name": "Bash",
                "tool_input": bash,
                "error": "Exit code 1",
                "is_interrupt": False,
            },
        ),
        "Stop": ("Stop", {"stop_hook_active": False}),
        "SessionEnd": ("SessionEnd", {"reason": "other"}),
    }
    interpreter = commands["PreToolUse"][3]
    trampoline = commands["PreToolUse"][:3]
    controls = {
        "control: interpreter start": [interpreter, "-I", "-c", "pass"],
        "control: trampoline + interpreter start": [*trampoline, interpreter, "-I", "-c", "pass"],
    }

    first: list[float] = []
    for _ in range(FRESH_SESSIONS):
        ms, rc = _run(
            commands["SessionStart"], event("SessionStart", str(uuid.uuid4()), source="startup")
        )
        assert rc in (0, 2), rc
        first.append(ms)

    session = str(uuid.uuid4())
    _run(commands["SessionStart"], event("SessionStart", session, source="startup"))
    for path in reading:
        lines = len(Path(path).read_text().splitlines()) + 1
        response = {
            "type": "text",
            "file": {"filePath": path, "numLines": lines, "startLine": 1, "totalLines": lines},
        }
        _run(
            commands["PostToolUse"],
            event(
                "PostToolUse",
                session,
                tool_name="Read",
                tool_input={"file_path": path},
                tool_response=response,
            ),
        )

    samples: dict[str, list[float]] = {name: [] for name in [*cases, *controls]}
    codes: dict[str, set[int]] = {name: set() for name in cases}
    for _ in range(ROUNDS):
        for name, argv in controls.items():
            samples[name].append(_run(argv, "")[0])
        for name, (ev, fields) in cases.items():
            ms, rc = _run(commands[ev], event(ev, session, **fields))
            samples[name].append(ms)
            codes[name].add(rc)

    return {
        "machine": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "python": sys.version.split()[0],
        "thread_caps": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")},
        "sha": os.environ.get("PHYSGATE_SHA") or _git_sha(),
        "before": before,
        "after": _machine(),
        "environment_links": _links(sys.prefix),
        "fixture": {
            "experiments_files": sum(len(f) for _, _, f in os.walk(worktree / "experiments")),
            "store_nodes": len(os.listdir(root / "outside" / "store" / "nodes")),
            "journal_lines": len(
                (root / "outside" / "store" / "journal.jsonl").read_bytes().splitlines()
            ),
        },
        "first_hook_of_a_session_takes_the_record": _summary(first),
        "steady": {name: _summary(v) for name, v in samples.items()},
        # Every call, in the order taken, so a later reader can recompute any
        # statistic instead of trusting these.
        "raw_ms": {"first_hook_of_a_session_takes_the_record": first, **samples},
        "exit_codes": {name: sorted(c) for name, c in codes.items()},
    }


def _git_sha() -> str | None:
    done = subprocess.run(
        ["git", "-C", str(HERE), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or None


def table(result: dict[str, Any]) -> str:
    """The record as log lines: the machine, then one line per hook and control."""
    b, a = result["before"], result["after"]
    lines = [
        f"machine: {result['machine']} ({result['processor']}), python {result['python']}, "
        f"sha {result['sha']}",
        f"thread caps: {result['thread_caps']}  cpu_count {b['cpu_count']}  "
        f"affinity {b['affinity']}  cgroup cpu.max {b['cgroup_cpu_max']}",
        f"load average: before {b['loadavg']}  after {a['loadavg']}",
        f"environment {sys.prefix}: {result['environment_links']['files']} files, "
        f"{result['environment_links']['more_than_one_link']} with more than one link",
        f"fixture: {result['fixture']}",
    ]
    f = result["first_hook_of_a_session_takes_the_record"]
    lines.append(_line("first SessionStart (takes the record)", f, ""))
    for name, s in result["steady"].items():
        codes = result["exit_codes"].get(name)
        verdict = "" if codes is None else ("under" if s["median"] < BUDGET_MS else "OVER")
        lines.append(_line(name, s, f"exit {codes}  {verdict}" if codes is not None else ""))
    return "\n".join(lines)


def _line(name: str, s: dict[str, float], tail: str) -> str:
    return (
        f"{name:42} median {s['median']:6.1f}  p10 {s['p10']:6.1f}  p90 {s['p90']:6.1f}  "
        f"iqr {s['iqr']:6.1f}  max {s['max']:6.1f}  n={s['n']:.0f}  "
        f">{BUDGET_MS:.0f} ms: {s['over_budget']:.0f}  {tail}"
    ).rstrip()


if __name__ == "__main__":
    record = measure()
    Path(sys.argv[1]).write_text(json.dumps(record, indent=1))
    print(table(record))
