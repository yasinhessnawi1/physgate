"""One real-model kill-and-resume cycle on the subscription: the close-out spot check.

Run as a script, never collected as a test, and never without saying which kind:

    python spot_check.py --variant a --dry-run --out <dir>   # scripted endpoint, dummy token
    python spot_check.py --variant a --real --out <dir>      # the real API, the subscription

Variant ``a`` starts the run from a fixed plan, as the kill harness does (no
decomposition call). Variant ``b`` makes the run's one real decomposition call
first, with a brief that prescribes the same plan.

The run is one electrical subtask whose specification says exactly which file
to write and which node to propose. ``physgate run`` is driven in a child
process and killed as soon as the role session's captured stream shows its
first tool result, if the session's pid is alive with its recorded start time
just before and just after the kill; otherwise the cycle is a harness miss and
nothing is repeated. ``physgate resume`` then runs in a new child process.

With ``--real`` the token is read from the env file (``CLAUDE_CODE_OAUTH_TOKEN``
only), held in memory, and handed to the orchestrator's child processes in
their environment. It is never printed, never put on a command line and never
written by this script; the orchestrator writes it only into a session's login
file. At the end every file this script's run left is scanned for it, and only
the count is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

from git_rig import Gate, Reviewer, config, sh, target_repo  # noqa: E402
from kill_cycles import left_running, node, printed_step  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.cli import main as physgate_main  # noqa: E402
from physgate.orchestrator.accounting import TokenAccount  # noqa: E402
from physgate.orchestrator.decompose import (  # noqa: E402
    Outcome,
    Plan,
    PlannedModule,
    binary_version,
    start_run,
)
from physgate.orchestrator.events import read_events  # noqa: E402
from physgate.orchestrator.git import head_of  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.processes import started_at, tree  # noqa: E402
from physgate.orchestrator.run_config import (  # noqa: E402
    ModelStrings,
    RunBounds,
    RunConfig,
    endpoint_of,
)
from physgate.state.schema import Node  # noqa: E402
from physgate.state.store import journal_records_after  # noqa: E402

VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
MODEL = "claude-sonnet-5"
REVIEWER = "claude-opus-5-5"
MODULE_DIR = "modules/driver"
PROPOSAL = "electrical.driver"
REACH_S = 900.0
RESUME_S = 1800.0

SPEC = (
    f"Create the file {MODULE_DIR}/driver.py containing exactly these two lines:\n\n"
    "def current_limit_a() -> float:\n"
    "    return 1.5\n\n"
    f"Then propose one node by writing the JSON below, exactly, to "
    f".physgate/proposals/{PROPOSAL}.json:\n\n"
    f"{json.dumps(node(PROPOSAL), indent=1)}\n\n"
    "Do nothing else. When both files are written, reply with the single word done.\n"
)
INTERFACE = node("iface.bus", kind="interface")
BRIEF = (
    "Plan exactly one module: name 'driver', role 'electrical', module_dir "
    f"'{MODULE_DIR}', and use the text between the markers below, verbatim, as its "
    "specification.\n<<<\n"
    f"{SPEC}>>>\n"
    "Plan exactly one interface node, this one, verbatim:\n"
    f"{json.dumps(INTERFACE)}\n"
)


def utc_ms() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def load_token(env_file: Path) -> str:
    """The token's value from the env file; only that line is read. Never printed."""
    for raw in env_file.read_text().splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if line.startswith(f"{VARIABLE}="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            if value:
                return value
    msg = f"{VARIABLE} is not set in {env_file}"
    raise SystemExit(msg)


def params() -> dict[str, Any]:
    """The run parameters, as a parameters file holds them."""
    return {
        "auth": "subscription",
        "gate_mode": "on",
        "models": ModelStrings(
            decomposition=MODEL, roles={"electrical": MODEL}, reviewers={"electrical": REVIEWER}
        ).model_dump(),
        "bounds": RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=900.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ).model_dump(mode="json"),
        "token_ceiling": 400_000,
    }


def start_fixed(root: Path, endpoint: str, version: str) -> None:
    """Variant (a): the run started from the fixed plan, with no model call."""
    repo = target_repo(root)
    cfg = RunConfig.model_validate_json(
        json.dumps(
            {
                **config().model_dump(mode="json"),
                **params(),
                "target_head": head_of(repo, "master"),
                "endpoint": endpoint,
                "claude_version": version,
            }
        )
    )
    plan = Plan(
        modules=(
            PlannedModule(name="driver", role="electrical", module_dir=MODULE_DIR, spec=SPEC),
        ),
        interface_nodes=(Node.model_validate(INTERFACE),),
    )
    outcome = Outcome(
        session_id="no-call",
        ok=True,
        cause=None,
        detail="",
        plan=plan,
        usage=(),
        model=MODEL,
        num_turns=1,
    )
    start_run(outcome, config=cfg, run_dir=root / "run", target_repo=repo).close()


def child(root: Path, mode: str, install: str) -> int:
    """One orchestrator process: ``physgate decompose``, ``run`` or ``resume``."""
    if mode == "decompose":
        return physgate_main(
            [
                "decompose",
                str(root / "brief.md"),
                "--seed",
                "1",
                "--run-id",
                "run-1",
                "--params",
                str(root / "params.json"),
                "--target",
                str(root / "target"),
                "--run-dir",
                str(root / "run"),
            ]
        )
    registrations = orchestrator_cli.Registrations(
        gate=Gate(), reviewers={"electrical": Reviewer(model=REVIEWER)}
    )
    argv = [mode, "--run-dir", str(root / "run"), "--target", str(root / "target")]
    return physgate_main([*argv, "--install", install], registrations)


def spawn(root: Path, mode: str, env: dict[str, str], install: str) -> subprocess.Popen[bytes]:
    with (root / f"{mode}.out").open("ab") as out:
        return subprocess.Popen(
            [sys.executable, str(Path(__file__)), "child", str(root), mode, install],
            stdout=out,
            stderr=out,
            env=env,
        )


def stream_stats(path: Path) -> dict[str, Any]:
    """Requests, answering models and tokens from one captured stream."""
    by_id: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "assistant":
                continue
            message = event.get("message") or {}
            if message.get("id"):
                by_id[message["id"]] = {
                    "model": message.get("model"),
                    "usage": message.get("usage") or {},
                }
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens")
    totals = {k: sum(int(m["usage"].get(k) or 0) for m in by_id.values()) for k in keys}
    totals["cache_creation_input_tokens"] = sum(
        int(m["usage"].get("cache_creation_input_tokens") or 0) for m in by_id.values()
    )
    return {
        "requests": len(by_id),
        "models": [m["model"] for m in by_id.values()],
        "tokens": totals,
    }


def live_session(run_dir: Path) -> tuple[dict[str, Any], Path] | None:
    """The role session not yet marked ended, and its captured stream."""
    for record_path in sorted((run_dir / "sessions").glob("*/process.json")):
        if not (record_path.parent / "ended.json").exists():
            return json.loads(record_path.read_text()), record_path.parent / "stdout.jsonl"
    return None


def has_tool_result(stream: Path) -> bool:
    if not stream.exists():
        return False
    for line in stream.read_text(errors="replace").splitlines():
        if '"tool_result"' in line and '"type":"user"' in line.replace(" ", ""):
            return True
    return False


def files_holding(root: Path, secret: str) -> int:
    needle = secret.encode()
    return sum(1 for p in root.rglob("*") if p.is_file() and needle in p.read_bytes())


def session_script() -> Script:
    """The dry run's stand-in for the model: what the specification asks, with a pause."""
    return Script(
        main=[
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            tool(
                "Bash",
                command=f"sleep 3; mkdir -p {MODULE_DIR} && printf 'def current_limit_a() "
                f"-> float:\\n    return 1.5\\n' > {MODULE_DIR}/driver.py",
            ),
            tool(
                "Write",
                file_path=f"{{cwd}}/.physgate/proposals/{PROPOSAL}.json",
                content=json.dumps(node(PROPOSAL), indent=1),
            ),
            text("done"),
        ]
    )


def run_cycle(
    root: Path,
    variant: str,
    env: dict[str, str],
    install: str,
    version: str,
    api: Any,  # noqa: ANN401
) -> dict[str, Any]:
    run_dir = root / "run"
    decomposition: dict[str, Any] | None = None
    if variant == "b":
        target_repo(root)
        (root / "brief.md").write_text(BRIEF)
        (root / "params.json").write_text(json.dumps(params()))
        code = spawn(root, "decompose", env, install).wait(timeout=900)
        decomposition = {
            "exit": code,
            **stream_stats(run_dir / "decomposition" / "stdout.jsonl"),
            "planned": [
                {"subtask": e.subtask_id, "module_dir": e.module_dir}
                for e in read_events(run_dir / "events.jsonl")
                if e.kind == "subtask_planned"
            ]
            if (run_dir / "events.jsonl").exists()
            else [],
        }
        if api is not None:
            api.script = session_script()
        if code != 0:
            return {"decomposition": decomposition, "stopped": "decomposition did not start a run"}
    else:
        start_fixed(root, endpoint_of(env.get("ANTHROPIC_BASE_URL")), version)

    proc = spawn(root, "run", env, install)
    deadline = time.monotonic() + REACH_S
    found: tuple[dict[str, Any], Path] | None = None
    while proc.poll() is None and time.monotonic() < deadline:
        found = live_session(run_dir)
        if found is not None and has_tool_result(found[1]):
            break
        time.sleep(0.02)
    orchestrator_alive = proc.poll() is None
    record = found[0] if found else None
    pid = int(record["pid"]) if record else None
    recorded_start = record.get("started") if record else None

    def alive() -> bool:
        return pid is not None and recorded_start is not None and started_at(pid) == recorded_start

    reached = found is not None and has_tool_result(found[1])
    alive_before = alive()
    tree_at_kill = len(tree(pid)) if pid is not None and alive_before else 0
    kill_utc = utc_ms()
    if orchestrator_alive:
        proc.send_signal(signal.SIGKILL)
    proc.wait()
    alive_after = alive()
    killed_at = (run_dir / "events.jsonl").read_bytes().count(b"\n")
    mid_task = reached and orchestrator_alive and alive_before and alive_after

    resume = spawn(root, "resume", env, install)
    try:
        code_resume: int | None = resume.wait(timeout=RESUME_S)
    except subprocess.TimeoutExpired:
        resume.kill()
        code_resume = None
    events = read_events(run_dir / "events.jsonl")
    after = events[killed_at:]
    killed_id = str(record["session_id"]) if record else None
    sessions = {
        p.parent.name: stream_stats(p.parent / "stdout.jsonl")
        for p in sorted((run_dir / "sessions").glob("*/process.json"))
    }
    ended = [e for e in events if e.kind == "session_ended"]
    stopped = [e for e in after if e.kind == "leftover_stopped" and e.session_id == killed_id]
    fresh = [
        e
        for e in after
        if e.kind == "session_ended"
        and e.session_id != killed_id
        and e.attempt == 1
        and e.outcome == "completed"
    ]
    writes: dict[str, int] = {}
    for line in journal_records_after(run_dir / "store", 0):
        writes[line.node_id] = writes.get(line.node_id, 0) + 1
    merges = sh(root / "target", "log", "--merges", "--format=%H", "physgate/run-1/run").split()
    account = TokenAccount.from_events(events)
    models = [m for s in sessions.values() for m in s["models"]]
    if decomposition is not None:
        models += decomposition["models"]
    refused = [e.cause for e in ended if e.cause == "credential_refused"]
    checks = {
        "1 credential accepted": not refused
        and not any(e.kind == "halted" and e.reason == "credential_refused" for e in events),
        "2 kill mid-session": mid_task,
        "3 resume exited 0, run done": code_resume == 0
        and printed_step(root / "resume.out") == "done",
        "4 leftover stopped, nothing left running": len(stopped) == 1 and not left_running(run_dir),
        "5 a fresh session completed attempt 1": len(fresh) >= 1,
        "6 every request answered by the pinned model": bool(models)
        and all(m == MODEL for m in models),
        "7 routing tokens 0": account.by_kind().get("routing") is None
        or account.by_kind()["routing"].total() == 0,
        "9 one journal write per node, one merge": all(n == 1 for n in writes.values())
        and PROPOSAL in writes
        and len(merges) == 1,
    }
    if decomposition is not None:
        planned = decomposition["planned"]
        checks["10 one decomposition request, pinned model, one module"] = (
            decomposition["exit"] == 0
            and decomposition["requests"] == 1
            and decomposition["models"] == [MODEL]
            and len(planned) == 1
        )
    return {
        "decomposition": decomposition,
        "kill": {
            "reached_first_tool_result": reached,
            "orchestrator_alive_at_kill": orchestrator_alive,
            "kill_utc": kill_utc,
            "session_id": killed_id,
            "pid": pid,
            "recorded_start": recorded_start,
            "alive_just_before_kill": alive_before,
            "alive_just_after_kill": alive_after,
            "processes_in_tree_at_kill": tree_at_kill,
            "harness_miss": not mid_task,
        },
        "sessions": sessions,
        "session_ends": [
            {
                "session_id": e.session_id,
                "attempt": e.attempt,
                "outcome": e.outcome,
                "cause": e.cause,
            }
            for e in ended
        ],
        "resume_events": [
            e.kind + (f"({e.point})" if e.kind == "resumed" else "")
            for e in after
            if e.kind in ("leftover_stopped", "resumed", "halted", "incident", "session_ended")
        ],
        "resume_exit": code_resume,
        "journal_writes": writes,
        "merges": len(merges),
        "tokens_by_kind": {k: v.total() for k, v in account.by_kind().items()},
        "checks": checks,
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> None:
    if sys.argv[1:2] == ["child"]:
        root, mode, install = sys.argv[2:5]
        sys.exit(child(Path(root), mode, install))
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["a", "b"], required=True)
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True)
    version = binary_version()  # refused unless it is the pinned one
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    stamp = {
        "variant": args.variant,
        "kind": "dry-run" if args.dry_run else "real",
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "binary_version": version,
        "started_utc": utc_ms(),
    }
    print(json.dumps(stamp), flush=True)
    install = root / "install"
    prepare_install(install, REPO_ROOT)
    run_root = root / "cycle"
    run_root.mkdir()
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", VARIABLE)
    }
    env = {**base, VARIABLE: token, "DISABLE_AUTOUPDATER": "1"}
    if args.dry_run:
        first = (
            Script(
                main=[
                    tool(
                        "StructuredOutput",
                        modules=[
                            {
                                "name": "driver",
                                "role": "electrical",
                                "module_dir": MODULE_DIR,
                                "spec": SPEC,
                            }
                        ],
                        interface_nodes=[INTERFACE],
                    )
                ]
            )
            if args.variant == "b"
            else session_script()
        )
        with serving(first) as (api, url):
            env["ANTHROPIC_BASE_URL"] = url
            result = run_cycle(run_root, args.variant, env, str(install), version, api)
            result["endpoint_failures"] = list(api.failures)
    else:
        result = run_cycle(run_root, args.variant, env, str(install), version, None)
    result["files_holding_the_token"] = files_holding(root, token)
    checks = result.get("checks", {})
    checks["8 the token in no file"] = result["files_holding_the_token"] == 0
    result["passed"] = bool(checks) and all(checks.values())
    result["finished_utc"] = utc_ms()
    out = {**stamp, **result}
    (root / "result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1), flush=True)


if __name__ == "__main__":
    main()
