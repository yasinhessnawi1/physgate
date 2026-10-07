"""One real run and its rerun, compared on their decisions: reproducibility on a real model.

Run as a script, never collected as a test, and never without saying which kind:

    python real_rerun.py --dry-run --criteria <stamp> --out <dir>  # scripted endpoint, dummy token
    python real_rerun.py --real --criteria <stamp> --out <dir>     # the real API, the subscription

**A labelled stand-in, not the reference design.**
- The brief prescribes one module with a fixed specification: the drive power module of the
  self-balancing robot, with the two deliberate errors of the gate's three-mode test removed, so
  the six proposals are physically sound.
- The gate is the real registered one.
- The reviewer is a stub. It passes every attempt on its pinned model string and spends nothing,
  because no reviewer is registered by default yet.

**What it does.** The run is ``physgate decompose`` then ``physgate run``, through the command. The
rerun is the observability layer's ``rerun`` from the first run's record, against the same target
and installation. Then comes the comparison.
- Scored: the decision sequence. On the real endpoint the comparison's rule is ``decisions``.
- Reported, never scored: every exact record, the tokens and cost of both runs, the per-invocation
  token cross-check against the binary's own totals, and the served catalog, feature flags and
  policy limits each invocation saw.

**The token.** With ``--real``, the script reads ``CLAUDE_CODE_OAUTH_TOKEN`` from the env file,
that line only, holds it in memory and puts it in this process's environment for the orchestrator.
- It is never printed, never put on a command line and never written by this script.
- At the end, every file under the output directory is scanned for the token, for ``sk-ant-`` and
  for ``oat01``, and email addresses are replaced. Only the counts are printed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import scripted_endpoint  # noqa: E402
from gate_fixtures import node  # noqa: E402
from gate_run import INTERFACE  # noqa: E402
from git_rig import Reviewer, target_repo  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402

import physgate.orchestrator.cli as orchestrator_cli  # noqa: E402
from physgate.cli import main as physgate_main  # noqa: E402
from physgate.evaluation.observe.cost import (  # noqa: E402
    append_cost_line,
    load_price_sheet,
    price_run,
)
from physgate.evaluation.observe.manifest import read_manifest  # noqa: E402
from physgate.evaluation.observe.rerun import rerun, through_the_command  # noqa: E402
from physgate.evaluation.observe.trace import read_traces  # noqa: E402
from physgate.gate.runner import PhysicsGate  # noqa: E402
from physgate.knowledge import loader  # noqa: E402
from physgate.orchestrator.cli import Registrations  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.events import (  # noqa: E402
    Decomposed,
    Incident,
    SessionEnded,
    read_events,
)
from physgate.orchestrator.git import commit_all  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.run_config import ModelStrings, RunBounds  # noqa: E402

VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
#: The evaluation pins: Opus implements and decomposes, Sonnet reviews (here a stub).
MODEL = "claude-opus-5-5"
REVIEWER = "claude-sonnet-5"
SEED = 7
PRICES = "2026-09-27"
MODULE_DIR = "modules/power"
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: The three-mode test's drive power module with its two errors removed: the motors
#: draw 2 x 5 W of the module's 10 W, and the driver dissipates 2 W, so it runs at
#: 25 + 40 * 2 = 105 degC against its 125 degC limit.
PROPOSALS: tuple[dict[str, Any], ...] = (
    node(
        "electrical.battery",
        quantities={"power_supply": (20, "W"), "energy_capacity": (20, "W*h")},
    ),
    node(
        "electrical.drive",
        kind="module",
        quantities={"power_supply": (10, "W"), "power_draw": (10, "W"), "mass": (0.4, "kg")},
        constrains=["electrical.battery"],
    ),
    *(
        node(
            f"electrical.motor_{side}",
            quantities={"power_draw": (5, "W"), "stall_current": (2.4, "A"), "mass": (0.2, "kg")},
            constrains=["electrical.drive", "electrical.driver"],
        )
        for side in ("left", "right")
    ),
    node(
        "electrical.driver",
        quantities={
            "current_limit": (3, "A"),
            "thermal_resistance": (40, "K/W"),
            "heat_dissipation": (2, "W"),
            "ambient_temperature": (25, "degC"),
            "max_temperature": (125, "degC"),
        },
        constrains=["electrical.drive"],
    ),
)

SPEC = (
    "Propose these nodes, and do nothing else. For each JSON object below, write it exactly, "
    "as the whole content of the file .physgate/proposals/<its id>.json:\n\n"
    + "\n\n".join(json.dumps(p) for p in PROPOSALS)
    + "\n\nWhen every file is written, reply with the single word done.\n"
)
BRIEF = (
    "STAND-IN BRIEF for the reproducibility check, not the reference design's brief.\n\n"
    "Plan exactly one module: name 'drive', role 'electrical', module_dir "
    f"'{MODULE_DIR}', and use the text between the markers below, verbatim, as its "
    "specification.\n<<<\n"
    f"{SPEC}>>>\n"
    "Plan exactly one interface node, this one, verbatim:\n"
    f"{json.dumps(INTERFACE)}\n"
)


def params() -> dict[str, Any]:
    """The run parameters, as the parameters file holds them."""
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
        "reportable": True,
        "effort": "high",
        "max_output_tokens": 64000,
        "thinking_display": "summarized",
    }


def registrations() -> Registrations:
    """The real registered gate, and the stub reviewer: always passes, spends nothing."""
    return Registrations(gate=PhysicsGate(), reviewers={"electrical": Reviewer(model=REVIEWER)})


def utc() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_token(env_file: Path) -> str:
    """The token's value from the env file; only that line is read. Never printed."""
    for raw in env_file.read_text().splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if line.startswith(f"{VARIABLE}="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            if value:
                return value
    msg = f"{VARIABLE} is not set in the env file"
    raise SystemExit(msg)


def command(argv: list[str], log: Path) -> int:
    """One ``physgate`` command in this process, its output kept in ``log``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = physgate_main(argv, registrations())
    with log.open("a") as f:
        f.write(
            json.dumps(
                {"argv": argv[:1], "code": code, "out": out.getvalue(), "err": err.getvalue()}
            )
            + "\n"
        )
    return code


def model_usage(stream: Path) -> dict[str, int] | None:
    """The binary's own totals for one invocation, from its result line, summed over models."""
    if not stream.exists():
        return None
    for line in reversed(stream.read_text(errors="replace").splitlines()):
        with contextlib.suppress(json.JSONDecodeError):
            event = json.loads(line)
            if isinstance(event, dict) and event.get("type") == "result":
                usage = event.get("modelUsage") or {}
                keys = (
                    "inputTokens",
                    "outputTokens",
                    "cacheReadInputTokens",
                    "cacheCreationInputTokens",
                )
                return {k: sum(int(m.get(k) or 0) for m in usage.values()) for k in keys}
    return None


def cross_check(run_dir: Path) -> list[dict[str, Any]]:
    """Per invocation: the run's token account against the binary's own ``modelUsage`` totals."""
    trace = read_traces(run_dir)
    events = read_events(run_dir / "events.jsonl")
    decomposed = next(e for e in events if isinstance(e, Decomposed))
    rows = [
        (
            "decomposition",
            decomposed.session_id,
            run_dir / "decomposition" / "stdout.jsonl",
            trace.decomposition_tokens,
        )
    ]
    rows += [
        ("session", s.session_id, run_dir / "sessions" / s.session_id / "stdout.jsonl", s.tokens)
        for s in trace.sessions
    ]
    out = []
    for kind, sid, stream, usage in rows:
        account = {
            "inputTokens": usage.input_tokens,
            "outputTokens": usage.output_tokens,
            "cacheReadInputTokens": usage.cache_read_input_tokens,
            "cacheCreationInputTokens": usage.cache_creation_input_tokens,
        }
        binary = model_usage(stream)
        out.append(
            {
                "kind": kind,
                "session_id": sid,
                "account": account,
                "binary": binary,
                "equal": binary == account,
            }
        )
    return out


def managed(run_dir: Path) -> dict[str, Any]:
    """The served catalog, feature flags and policy limits every invocation of the run saw."""
    events = read_events(run_dir / "events.jsonl")
    decomposed = next(e for e in events if isinstance(e, Decomposed))
    ended = [e for e in events if isinstance(e, SessionEnded)]
    traffic = decomposed.observed_traffic
    return {
        "observed_traffic": None if traffic is None else traffic.model_dump(),
        "traffic_all_off": traffic is not None and traffic.all_off(),
        "policy_limits_decomposition": decomposed.policy_limits_sha256,
        "policy_limits_sessions": [e.policy_limits_sha256 for e in ended],
        "policy_limits_held": all(
            e.policy_limits_sha256 == decomposed.policy_limits_sha256 for e in ended
        ),
        "managed_settings_incidents": sum(
            1 for e in events if isinstance(e, Incident) and e.cause == "managed_settings_changed"
        ),
    }


def summary(run_dir: Path, trend: Path) -> dict[str, Any]:
    manifest = read_manifest(run_dir)
    line = price_run(run_dir, load_price_sheet(PRICES))
    append_cost_line(trend, line)
    trace = read_traces(run_dir)
    return {
        "manifest_id": manifest.manifest_id,
        "run_id": manifest.config.run_id,
        "endpoint": manifest.config.endpoint,
        "tokens": {
            "decomposition": trace.decomposition_tokens.model_dump(),
            "sessions": [
                {
                    "session_id": s.session_id,
                    **s.tokens.model_dump(),
                    "wall_clock_s_incl_setup": s.wall_clock_s,
                }
                for s in trace.sessions
            ],
            "reviewer_stub": {k: v.total() for k, v in trace.reviewer_tokens.items()},
            "routing": trace.routing_tokens.total(),
        },
        "cost": {
            "basis": line.basis,
            "usd": str(line.usd),
            "nok": str(line.nok),
            "prices": line.prices_date,
        },
        "token_cross_check": cross_check(run_dir),
        "managed": managed(run_dir),
    }


def scan(root: Path, token: str) -> dict[str, int]:
    """Counts only: files holding the token, ``sk-ant-`` or ``oat01``; emails replaced.

    Every file is read. Emails are replaced only in the run's own records: the
    read-only installation is a copy of the package, and is not evidence.
    """
    files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
    counts = {"token": 0, "sk-ant-": 0, "oat01": 0, "emails_replaced": 0}
    for path in files:
        data = path.read_bytes()
        counts["token"] += token.encode() in data
        counts["sk-ant-"] += b"sk-ant-" in data
        counts["oat01"] += b"oat01" in data
        found = len(EMAIL.findall(data))
        records = (root / "install") not in path.parents
        if found and records and path.suffix in (".json", ".jsonl", ".log", ".txt", ".md", ".out"):
            path.write_bytes(EMAIL.sub(b"<email>", data))
            counts["emails_replaced"] += found
    return counts


#: What the binary asked for, per request, on the scripted endpoint: the fields besides the
#: conversation, and the beta header, so a model's defaults are measured, not assumed.
SETTINGS: list[dict[str, Any]] = []
_ANSWER = scripted_endpoint.FakeMessagesApi.answer


def _recording(self: Any, path: str, headers: Any, body: dict[str, Any]) -> Any:  # noqa: ANN401
    SETTINGS.append(
        {
            "model": body.get("model"),
            "max_tokens": body.get("max_tokens"),
            "thinking": body.get("thinking"),
            "output_config": body.get("output_config"),
            "context_management": body.get("context_management"),
            "sampling": sorted(k for k in ("temperature", "top_p", "top_k") if k in body),
            "anthropic_beta": sorted((headers.get("anthropic-beta") or "").split(",")),
        }
    )
    return _ANSWER(self, path, headers, body)


def dry_script(api: Any) -> None:  # noqa: ANN401
    """The scripted endpoint as the model: the plan to the decomposition, the writes after."""
    plan = tool(
        "StructuredOutput",
        modules=[{"name": "drive", "role": "electrical", "module_dir": MODULE_DIR, "spec": SPEC}],
        interface_nodes=[INTERFACE],
    )
    writes = [
        tool(
            "Write", file_path=f"{{cwd}}/.physgate/proposals/{p['id']}.json", content=json.dumps(p)
        )
        for p in PROPOSALS
    ]
    reads = [
        tool("Read", file_path=f"{{cwd}}/{relative.as_posix()}")
        for relative in loader.always_loaded("electrical")
    ]
    api.script = Script(
        main=[
            *reads,
            tool("Read", file_path="{cwd}/.physgate/specs/{cwd_name}.md"),
            *writes,
            text("done"),
        ]
    )
    api.on_request = lambda thread, cwd, done: (
        plan if cwd.endswith("/decomposition/cwd") and done == 0 else None
    )


def both_runs(root: Path) -> dict[str, Any]:
    repo = target_repo(root)
    for relative in loader.always_loaded("electrical"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {relative.name}\n\nFixture content for the real-rerun driver.\n")
    commit_all(repo, "curated knowledge fixture\n")
    # The orchestrator copies each planned role's curated files into the target at
    # decomposition, and the real library carries no ``electrical`` content. This
    # stand-in's library is the fixture content just committed to the target, so
    # the copy finds it identical and leaves it.
    orchestrator_cli._library_root = lambda: repo
    # Built before either run, so both check it: a run that built the installation
    # records "built" where its rerun records "checked", a real difference.
    install = root / "install"
    prepare_install(install, REPO_ROOT)
    (root / "brief.md").write_text(BRIEF)
    (root / "params.json").write_text(json.dumps(params()))
    log = root / "commands.jsonl"
    common = ["--target", str(repo)]
    code = command(
        [
            "decompose",
            str(root / "brief.md"),
            "--seed",
            str(SEED),
            "--run-id",
            "e1-real-a",
            "--params",
            str(root / "params.json"),
            *common,
            "--run-dir",
            str(root / "e1-real-a"),
        ],
        log,
    )
    result: dict[str, Any] = {"decompose_exit": code}
    if code != 0:
        result["stopped"] = (
            "the first run's decomposition did not start a run; nothing more was called"
        )
        return result
    result["run_exit"] = command(
        [
            "run",
            "--run-dir",
            str(root / "e1-real-a"),
            *common,
            "--install",
            str(install),
            "--review-root",
            str(root / "review-scratch"),
        ],
        log,
    )
    result["rerun_started_utc"] = utc()
    comparison = rerun(
        root / "e1-real-a",
        brief=root / "brief.md",
        run_id="e1-real-b",
        run_dir=root / "e1-real-b",
        target=repo,
        install=install,
        review_root=root / "review-scratch",
        driver=through_the_command(registrations()),
    )
    first = comparison.first
    result["comparison"] = {
        **json.loads(comparison.model_dump_json()),
        "rule": comparison.rule,
        "reproduced": comparison.reproduced,
        "first": None if first is None else json.loads(first.model_dump_json()),
    }
    trend = root / "cost_trend.jsonl"
    result["runs"] = [summary(root / r, trend) for r in ("e1-real-a", "e1-real-b")]
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--criteria", type=Path, required=True, help="the criteria stamped first")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True)
    version = binary_version()  # refused unless it is the pinned one

    def git(*a: str) -> str:
        return subprocess.run(
            ["git", *a], cwd=REPO_ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()

    stamp = {
        "kind": "dry-run" if args.dry_run else "real",
        "commit": git("rev-parse", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "script_sha256": sha256(Path(__file__)),
        "criteria_sha256": sha256(args.criteria),
        "binary_version": version,
        "binary_sha256": sha256(Path(shutil.which(claude_binary()) or claude_binary())),
        "started_utc": utc(),
    }
    print(json.dumps(stamp), flush=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        os.environ.pop(name, None)
    os.environ[VARIABLE] = token
    os.environ["DISABLE_AUTOUPDATER"] = "1"
    try:
        if args.dry_run:
            scripted_endpoint.FakeMessagesApi.answer = _recording  # type: ignore[method-assign]
            with serving(Script(main=[])) as (api, url):
                dry_script(api)
                os.environ["ANTHROPIC_BASE_URL"] = url
                result = both_runs(root)
                result["endpoint_failures"] = list(api.failures)
                result["endpoint_requests"] = len(api.requests)
            distinct = {json.dumps(s, sort_keys=True) for s in SETTINGS}
            result["request_settings"] = [json.loads(s) for s in sorted(distinct)]
        else:
            result = both_runs(root)
    finally:
        os.environ.pop(VARIABLE, None)
    result["finished_utc"] = utc()
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    result["scan"] = scan(root, token)
    (root / "result.json").write_text(json.dumps({**stamp, **result}, indent=1, sort_keys=True))
    print(
        json.dumps(
            {"scan": result["scan"], "reproduced": result.get("comparison", {}).get("reproduced")}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
