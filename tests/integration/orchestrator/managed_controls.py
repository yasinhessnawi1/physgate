"""Two controls that size the managed-settings hole: is the override honoured, are hooks kept.

Run as a script, never collected as a test, and never without saying which kind:

    python managed_controls.py --control d1 --dry-run --out <dir>
    python managed_controls.py --control d2 --real --out <dir>

Each control is one role session under the hook layer, through the orchestrator's own
dispatcher, with the run's managed-settings override holding the control's content:

- ``d1``: ``{"env": {"PHYSGATE_OVERRIDE_PROBE": "seen"}}``; the specification says to write
  the variable into ``modules/power/probe.txt``. ``seen`` in the attempt's commit means the
  binary took the override as the managed tier.
- ``d2``: ``{"disableAllHooks": true}``; the prompt says to run one Bash command before the
  required reading. The reading hook's refusal in the stream means hooks survive the managed
  tier; the command running means the tier can switch every hook off.

With ``--real`` the token is read from the env file's one line, held in memory, handed to
the session only as its login file (the dispatcher's own route), never printed; at the
end the files holding it are counted and only the count is printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))

from git_rig import config, run_layout  # noqa: E402
from scripted_endpoint import DUMMY_OAUTH_TOKEN, Script, serving, text, tool  # noqa: E402
from spot_check import files_holding, load_token, stream_stats  # noqa: E402

from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.dispatch import ClaudeDispatcher  # noqa: E402
from physgate.orchestrator.git import commit_all, git  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary  # noqa: E402
from physgate.orchestrator.managed import write_override  # noqa: E402
from physgate.orchestrator.ports import SessionRequest  # noqa: E402
from physgate.orchestrator.run_config import RunBounds, endpoint_of  # noqa: E402
from physgate.state.store import Store  # noqa: E402

MODEL = "claude-sonnet-5"
SPEC = ".physgate/specs/s1.md"
REFUSAL = "Required reading is not complete"
OVERRIDES = {
    "d1": {"env": {"PHYSGATE_OVERRIDE_PROBE": "seen"}},
    "d2": {"disableAllHooks": True},
}
SPECS = {
    "d1": (
        "Run exactly this one Bash command, from the repository root:\n\n"
        'echo "$PHYSGATE_OVERRIDE_PROBE" > modules/power/probe.txt\n\n'
        "Then reply with the single word done. Do nothing else.\n"
    ),
    "d2": "Reply with the single word done. Do nothing else.\n",
}
FIRST = {
    "d1": None,
    "d2": (
        "Before anything else, before you read your specification, run exactly this one Bash "
        "command from the repository root: echo early > modules/power/early.txt\n"
        "Then read the specification and follow it."
    ),
}


def dry_script(control: str, worktree: str) -> Script:
    read = tool("Read", file_path=f"{worktree}/{SPEC}")
    if control == "d1":
        bash = tool("Bash", command='echo "$PHYSGATE_OVERRIDE_PROBE" > modules/power/probe.txt')
        return Script(main=[read, bash, text("done")])
    early = tool("Bash", command="echo early > modules/power/early.txt")
    return Script(main=[early, read, text("done")])


def first_bash(stream: Path) -> dict[str, Any]:
    """The first Bash call in the captured stream and the tool result it got."""
    calls: dict[str, str] = {}
    for line in stream.read_text(errors="replace").splitlines() if stream.exists() else []:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        content = (event.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            kind = (event.get("type"), block.get("type"))
            if kind == ("assistant", "tool_use") and block.get("name") == "Bash" and not calls:
                calls[str(block.get("id"))] = str((block.get("input") or {}).get("command"))
            if kind == ("user", "tool_result") and str(block.get("tool_use_id")) in calls:
                result = block.get("content")
                return {
                    "command": next(iter(calls.values())),
                    "result": str(result)[:300],
                    "refused_by_reading_hook": REFUSAL in str(result),
                }
    if calls:
        return {
            "command": next(iter(calls.values())),
            "result": None,
            "refused_by_reading_hook": None,
        }
    return {"command": None, "result": None, "refused_by_reading_hook": None}


def tools_in_order(stream: Path) -> list[str]:
    names: list[str] = []
    for line in stream.read_text(errors="replace").splitlines() if stream.exists() else []:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "assistant":
            for block in (event.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    names.append(str(block.get("name")))
    return names


def run_control(
    control: str, root: Path, install_bin: Path, credential: Credential, url: str | None
) -> dict[str, Any]:
    run = run_layout(root)
    (run.integration / ".physgate" / "specs").mkdir(parents=True)
    (run.integration / SPEC).write_text(SPECS[control])
    commit_all(run.integration, "specification\n")
    store_root = run.run_dir / "store"
    Store(store_root).close()
    content = (json.dumps(OVERRIDES[control]) + "\n").encode()
    write_override(run.run_dir, content)
    bounds = RunBounds(
        binary_max_retries=0,
        session_wall_clock_s=600.0,
        session_max_turns=15,
        infra_retry_delays_s=(),
    )
    cfg = config().model_copy(
        update={
            "auth": "subscription",
            "endpoint": endpoint_of(url),
            "managed_override_sha256": hashlib.sha256(content).hexdigest(),
            "claude_version": binary_version(),
            "bounds": bounds,
            "token_ceiling": 400_000,
        }
    )
    dispatcher = ClaudeDispatcher(
        config=cfg,
        run=run,
        store_root=store_root,
        install_bin=install_bin,
        binary=claude_binary(),
        base_url=url,
        credential=credential,
    )
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="electrical",
        spec_path=SPEC,
        module_dir="modules/power",
        model=MODEL,
        repair_instruction=FIRST[control],
        bounds=bounds,
    )
    error = None
    report = None
    try:
        report = dispatcher.run(request)
    except Exception as exc:  # noqa: BLE001 - recorded, the control reports what happened
        error = {"type": type(exc).__name__, "message": str(exc)[:300]}
    sdir = next((run.run_dir / "sessions").iterdir())
    stream = sdir / "stdout.jsonl"
    worktree = run.subtask_worktree("s1")
    committed: dict[str, str | None] = {}
    for name in ("probe.txt", "early.txt"):
        path = f"modules/power/{name}"
        if report is not None and report.attempt_commit:
            shown = subprocess.run(
                ["git", "show", f"{report.attempt_commit}:{path}"],
                cwd=run.repo,
                capture_output=True,
                text=True,
                check=False,
            )
            committed[name] = shown.stdout if shown.returncode == 0 else None
        else:
            on_disk = worktree / path
            committed[name] = on_disk.read_text() if on_disk.exists() else None
    config_dir = sdir / "config"
    return {
        "control": control,
        "override": OVERRIDES[control],
        "error": error,
        "session_end": report.end.model_dump() if report else None,
        "attempt_commit": report.attempt_commit if report else None,
        "reading_verified": report.reading_verified if report else None,
        "managed_drift": report.managed_drift if report else None,
        "first_bash": first_bash(stream),
        "tools_in_order": tools_in_order(stream),
        "files": committed,
        "stream": stream_stats(stream),
        "config_files": sorted(
            str(p.relative_to(config_dir))
            for p in config_dir.rglob("*")
            if p.is_file() and "projects" not in p.parts and "backups" not in p.parts
        ),
        "remote_settings_cached": (config_dir / "remote-settings.json").read_text()
        if (config_dir / "remote-settings.json").exists()
        else None,
        "head_commits": git(run.repo, "log", "--all", "--format=%h %s").splitlines()[:5],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control", choices=["d1", "d2"], required=True)
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--dry-run", action="store_true", help="scripted endpoint, dummy token")
    kind.add_argument("--real", action="store_true", help="the real API, on the subscription")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path.home() / "dev" / "physgate" / ".env")
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True)
    token = DUMMY_OAUTH_TOKEN if args.dry_run else load_token(args.env_file)
    stamp = {
        "control": args.control,
        "kind": "dry-run" if args.dry_run else "real",
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "binary_version": binary_version(),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    print(json.dumps(stamp), flush=True)
    install_bin = prepare_install(root / "install", REPO_ROOT)
    credential = Credential("subscription", token)
    if args.dry_run:
        worktree = str(root / "cycle" / "run" / "worktrees" / "s1")
        with serving(dry_script(args.control, worktree)) as (_, url):
            result = run_control(args.control, root / "cycle", install_bin, credential, url)
    else:
        result = run_control(args.control, root / "cycle", install_bin, credential, None)
    result["files_holding_the_token"] = files_holding(root, token)
    out = {**stamp, **result, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    (root / "result.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1), flush=True)


if __name__ == "__main__":
    main()
