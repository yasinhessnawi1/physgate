"""``physgate decompose`` and ``physgate queue``: starting a run, and deciding for it.

``decompose`` builds the run's configuration from explicit inputs (the seed on
the command line, the brief's digest, the target repository's head, and a
parameters file holding the model strings, bounds, gate mode and token ceiling),
makes the run's one model call and starts the run from its plan. Nothing it
records has a default. The API key and an optional endpoint come from the
environment and are never written anywhere.

``queue list`` prints the open approval items; ``queue resolve`` records a
person's decision on one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from physgate.orchestrator.common import first_problem
from physgate.orchestrator.decompose import binary_version, call, require_fresh, start_run
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.run_config import RunConfig


def add_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the orchestrator's commands on the top-level command."""
    d = subparsers.add_parser("decompose", help="make the run's one model call and start it")
    d.add_argument("brief", type=Path)
    d.add_argument("--seed", required=True, type=int)
    d.add_argument("--run-id", required=True)
    d.add_argument("--params", required=True, type=Path, help="models, bounds, gate mode, ceiling")
    d.add_argument("--target", required=True, type=Path, help="the target repository")
    d.add_argument("--run-dir", required=True, type=Path)
    d.set_defaults(func=_decompose)

    q = subparsers.add_parser("queue", help="the approval queue")
    actions = q.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="print the open items")
    listing.add_argument("--run-dir", required=True, type=Path)
    listing.set_defaults(func=_queue_list)
    resolve = actions.add_parser("resolve", help="record a decision on one item")
    resolve.add_argument("item")
    resolve.add_argument("--run-dir", required=True, type=Path)
    resolve.add_argument("--decision", required=True)
    resolve.add_argument("--by", required=True)
    resolve.set_defaults(func=_queue_resolve)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=1, sort_keys=True))


def _fail(message: str, **context: str) -> int:
    print(json.dumps({"error": message, **context}, sort_keys=True), file=sys.stderr)
    return 2


def _config(args: argparse.Namespace) -> RunConfig:
    params = json.loads(args.params.read_text())
    fields = {
        **params,
        "run_id": args.run_id,
        "seed": args.seed,
        "brief_sha256": hashlib.sha256(args.brief.read_bytes()).hexdigest(),
        "target_head": head_of(args.target.resolve(), "HEAD"),
        "claude_version": binary_version(),
    }
    return RunConfig.model_validate_json(json.dumps(fields))


def _decompose(args: argparse.Namespace) -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return _fail("ANTHROPIC_API_KEY is not set; the one model call needs it")
    try:
        config = _config(args)
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    except ValidationError as exc:
        return _fail(
            "the run parameters are not a complete configuration", reason=first_problem(exc)
        )
    run_dir = args.run_dir.resolve()
    try:
        require_fresh(run_dir)
        outcome = call(
            args.brief.read_text(),
            config=config,
            workdir=run_dir / "decomposition",
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            api_key=api_key,
        )
        record = start_run(
            outcome, config=config, run_dir=run_dir, target_repo=args.target.resolve()
        )
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    subtasks = [line.id for line in record.ledger.read_all()]
    record.close()
    _print(
        {
            "run_id": config.run_id,
            "decomposed": outcome.ok,
            "cause": outcome.cause,
            "detail": outcome.detail,
            "subtasks": subtasks,
        }
    )
    return 0 if outcome.ok else 1


def _queue_list(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(args.run_dir.resolve() / "queue.jsonl")
    _print({"open": [item.model_dump() for item in queue.open_items()]})
    return 0


def _queue_resolve(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(args.run_dir.resolve() / "queue.jsonl")
    try:
        record = queue.resolve(args.item, decision=args.decision, resolved_by=args.by)
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    _print({"resolved": record.model_dump()})
    return 0
