"""``physgate hooks install``: write a session's settings file and configuration.

The spawner runs this before every session and starts the session with the
arguments it prints. It never writes into a worktree's own ``.claude/``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, install


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``hooks install`` on the top-level command."""
    hooks = subparsers.add_parser("hooks", help="the hook layer")
    actions = hooks.add_subparsers(dest="action", required=True)
    p = actions.add_parser("install", help="write a session's settings file and configuration")
    p.add_argument("--profile", required=True, choices=["role", "reviewer", "orchestrator"])
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
    p.add_argument("--protect", action="append", default=[])
    p.set_defaults(func=_install)


def _abs(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _install(args: argparse.Namespace) -> int:
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
        extra_protected=tuple(_abs(p) for p in args.protect),
    )
    done = install(request, REGISTRY)
    print(
        json.dumps(
            {
                "settings": str(done.settings_path),
                "config": str(done.config_path),
                "spawn_args": list(done.spawn_args),
                "spawn_env": dict(done.spawn_env),
            },
            indent=2,
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``physgate`` command."""
    parser = argparse.ArgumentParser(prog="physgate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_parser(subparsers)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result
