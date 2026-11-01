"""``physgate hooks install``: write a session's settings file and configuration.

The spawner runs this before every session and starts the session with the
arguments it prints. It never writes into a worktree's own ``.claude/``.

A role session's settings carry the OS layer's sandbox (``--os-layer-temp``). Without it they
are written only for a run whose recorded configuration (``--run-config``) passes the check
the run itself is held to: one that allows the layer's absence, and never one that acts on
queue decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``hooks install`` on the top-level command."""
    hooks = subparsers.add_parser("hooks", help="the hook layer")
    actions = hooks.add_subparsers(dest="action", required=True)
    p = actions.add_parser("install", help="write a session's settings file and configuration")
    p.add_argument(
        "--profile", required=True, choices=["role", "reviewer", "orchestrator", "baseline"]
    )
    p.add_argument("--role")
    p.add_argument("--worktree", required=True)
    p.add_argument("--own-branch")
    p.add_argument("--store-root")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--target", required=True, help="directory for the two generated files")
    p.add_argument("--claude-config-dir", required=True)
    p.add_argument("--user-home", default=str(Path.home()))
    p.add_argument("--ceiling", required=True, type=int, help="token ceiling, no default")
    p.add_argument("--reading", action="append", default=[])
    p.add_argument("--always-loaded", action="append", default=[])
    p.add_argument("--held-out", action="append", default=[])
    p.add_argument(
        "--answer-key",
        action="append",
        default=[],
        help="a corpus carrying its answers: written by no session, read by no reviewer",
    )
    p.add_argument("--protect", action="append", default=[])
    p.add_argument(
        "--protect-refuse-only",
        action="append",
        default=[],
        help="a path no tool may write that the runtime writes during the session (not reverted)",
    )
    p.add_argument(
        "--harness",
        help="the source checkout the orchestrator runs from: refused whole, its trusted trees "
        "put back",
    )
    p.add_argument(
        "--harness-site-packages",
        action="append",
        default=[],
        help="the orchestrator's interpreter's site-packages: its startup files are put back",
    )
    p.add_argument(
        "--read-root",
        action="append",
        default=[],
        help="a directory a reviewer may read; a reviewer reads nothing else (reviewer only)",
    )
    p.add_argument(
        "--review-material",
        action="append",
        default=[],
        help="a further place only reviewers read, withheld from every other session",
    )
    p.add_argument("--api-key-helper", help="a script printing the API key, named in the settings")
    p.add_argument(
        "--os-layer-readable",
        action="append",
        default=[],
        help="a place of the session's own its shell commands read, inside a withheld root",
    )
    p.add_argument(
        "--os-layer-temp",
        help="the session's own temporary directory: its shell commands run inside the OS "
        "layer (Claude Code's sandbox), writing only there, in the worktree and in its home",
    )
    p.add_argument(
        "--run-config",
        help="the run's recorded configuration (run.json): a role session's settings without "
        "the OS layer (no --os-layer-temp) are written only where it allows the layer's absence",
    )
    p.add_argument(
        "--os-layer-network",
        choices=["open", "none"],
        default="open",
        help="with the OS layer: 'none' refuses the session's shell commands every remote "
        "host and every loopback service; without it, 'none' cannot be enforced, "
        "and the install says so on stderr and in what it prints",
    )
    p.add_argument(
        "--spawns-with-canary",
        action="store_true",
        help="the spawner exports the session's own pid as the survivor reaper's canary "
        "before it execs the binary (the dispatcher's held spawn does); required on macOS "
        "with the OS layer, where every command runs under the reaper",
    )
    p.set_defaults(func=_install)


def _abs(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _os_layer_refusal(args: argparse.Namespace) -> str | None:
    """Why a role session's settings may not be written without the sandbox, or ``None``.

    Without ``--os-layer-temp`` the settings carry no sandbox, so the OS layer is absent for
    that session. They are written only for a run whose recorded configuration passes the
    check the run itself is held to at its configuration, run and resume.
    """
    if args.profile != "role" or args.os_layer_temp:
        return None
    # Only here: the hook layer's own modules import nothing of the orchestrator.
    from physgate.orchestrator.exceptions import RunConfigError  # noqa: PLC0415
    from physgate.orchestrator.run_config import load_run_config, os_layer_refusal  # noqa: PLC0415
    from physgate.oslayer.probe import Absent  # noqa: PLC0415

    if args.run_config is None:
        return (
            "a role session's settings are written only with the OS layer (--os-layer-temp), or "
            "for a run whose recorded configuration (--run-config) allows the layer's absence "
            "(os_layer_absent: allow, for development only)"
        )
    try:
        config = load_run_config(Path(args.run_config))
    except (RunConfigError, OSError) as exc:
        return f"the run configuration named cannot be read, so nothing is written: {exc}"
    absent = Absent(reason="the settings carry no sandbox: no --os-layer-temp was given")
    return os_layer_refusal(config, absent)


def _install(args: argparse.Namespace) -> int:
    refused = _os_layer_refusal(args)
    if refused is not None:
        print(json.dumps({"error": refused}), file=sys.stderr)
        return 2
    request = InstallRequest(
        profile=args.profile,
        role=args.role,
        worktree=_abs(args.worktree),
        own_branch=args.own_branch,
        store_root=_abs(args.store_root) if args.store_root else None,
        state_dir=_abs(args.state_dir),
        target_dir=_abs(args.target),
        claude_config_dir=_abs(args.claude_config_dir),
        user_home=_abs(args.user_home),
        token_ceiling=args.ceiling,
        required_reading=tuple(_abs(p) for p in args.reading),
        always_loaded=tuple(_abs(p) for p in args.always_loaded),
        held_out=tuple(_abs(p) for p in args.held_out),
        answer_keys=tuple(_abs(p) for p in args.answer_key),
        read_roots=tuple(_abs(p) for p in args.read_root),
        extra_review_material=tuple(_abs(p) for p in args.review_material),
        extra_protected=tuple(_abs(p) for p in args.protect),
        extra_protected_refuse_only=tuple(_abs(p) for p in args.protect_refuse_only),
        api_key_helper=_abs(args.api_key_helper) if args.api_key_helper else None,
        harness_root=_abs(args.harness) if args.harness else None,
        harness_site_packages=tuple(_abs(p) for p in args.harness_site_packages),
        os_layer_temp_dir=_abs(args.os_layer_temp) if args.os_layer_temp else None,
        os_layer_readable=tuple(_abs(p) for p in args.os_layer_readable),
        os_layer_network=args.os_layer_network,
        spawns_with_canary=args.spawns_with_canary,
    )
    done = install(request, REGISTRY)
    printed: dict[str, object] = {
        "settings": str(done.settings_path),
        "config": str(done.config_path),
        "spawn_args": list(done.spawn_args),
        "spawn_env": dict(done.spawn_env),
    }
    if done.network_unenforced is not None:
        # Never silent: where a person sees it, and in the record the caller keeps.
        print(f"physgate: {done.network_unenforced}", file=sys.stderr)
        printed["network_unenforced"] = done.network_unenforced
    print(json.dumps(printed, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``physgate`` command."""
    parser = argparse.ArgumentParser(prog="physgate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_parser(subparsers)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result
