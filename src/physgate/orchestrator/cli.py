"""``physgate decompose`` and ``physgate queue``: starting a run, and deciding for it.

``decompose`` builds the run's configuration from explicit inputs (the seed on
the command line, the brief's digest, the target repository's head, and a
parameters file holding the auth mode, model strings, bounds, gate mode and token
ceiling), makes the run's one model call and starts the run from its plan.
Nothing it records has a default. The auth mode names where the secret comes
from (``CLAUDE_CODE_OAUTH_TOKEN`` for ``subscription``, ``ANTHROPIC_API_KEY``
for ``api_key``); the secret is read from the environment and never written into
any record. The endpoint (``ANTHROPIC_BASE_URL``, or the binary's default)
is recorded without any credential in it, and ``run`` and ``resume`` refuse a
different one.

``queue list`` prints the open approval items; ``queue resolve`` records a
person's decision on one.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

import physgate
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.common import first_problem
from physgate.orchestrator.credentials import SECRET_VARIABLE, credential_for
from physgate.orchestrator.decompose import binary_version, call, require_fresh, start_run
from physgate.orchestrator.dispatch import ClaudeDispatcher
from physgate.orchestrator.events import SubtaskPlanned, read_events
from physgate.orchestrator.exceptions import InvocationError, OrchestratorError, RunStateError
from physgate.orchestrator.git import head_of
from physgate.orchestrator.install import prepare_install
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.loop import Loop, refuse_unregistered
from physgate.orchestrator.merge import GitMerger, RunGit
from physgate.orchestrator.protocols import Gate, Reviewer
from physgate.orchestrator.queue import ApprovalQueue
from physgate.orchestrator.run_config import (
    RunConfig,
    endpoint_of,
    load_run_config,
    require_endpoint,
)

#: Example parameters files, one per auth mode.
EXAMPLES = Path(__file__).resolve().parent / "examples"

#: One worktree removal's bound. One removal on the server's network volume was
#: measured at 266 s; past this it is recorded as timed out and left, and the run
#: goes on.
REMOVAL_TIMEOUT_S = 300.0

RUN_GUIDANCE = (
    "Put the run directory on a local disk where the machine has one: removing a worktree on "
    "a network volume was measured at up to 266 s, and the first hook of a session costs more "
    "there. The run records the filesystem its session state lives on; nothing enforces this."
)


@dataclass(frozen=True)
class Registrations:
    """The gate and the reviewers a run may use.

    There is no pass-through default: with none registered, a run in a gate mode
    that needs a gate, or with a role that has no reviewer, refuses to start.
    """

    gate: Gate | None = None
    reviewers: Mapping[str, Reviewer] = field(default_factory=dict)


def default_registrations() -> Registrations:
    """The registrations the ``physgate`` command runs with.

    Empty: the physics gate registers its gate here, and the reviewers register
    theirs, as plain imports that a reader can follow.
    """
    return Registrations()


def add_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    registrations: Registrations | None = None,
) -> None:
    """Register the orchestrator's commands on the top-level command."""
    found = registrations or default_registrations()
    for name, resume, text in (
        ("run", False, "drive a decomposed run's plan until it is done or halts"),
        ("resume", True, "take over a run a previous process left, then drive it"),
    ):
        command = subparsers.add_parser(name, help=text, description=f"{text}. {RUN_GUIDANCE}")
        command.add_argument("--run-dir", required=True, type=Path)
        command.add_argument("--target", required=True, type=Path, help="the target repository")
        command.add_argument(
            "--install",
            required=True,
            type=Path,
            help="the hooks' read-only installation; built there if it does not exist",
        )
        command.set_defaults(func=functools.partial(_drive, resume=resume, registrations=found))

    d = subparsers.add_parser("decompose", help="make the run's one model call and start it")
    d.add_argument("brief", type=Path)
    d.add_argument("--seed", required=True, type=int)
    d.add_argument("--run-id", required=True)
    d.add_argument(
        "--params",
        required=True,
        type=Path,
        help=(
            "auth mode, models, bounds, gate mode, ceiling; examples for both auth modes are "
            f"in {EXAMPLES}"
        ),
    )
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


def _print(payload: dict[str, object]) -> None:
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
        "endpoint": endpoint_of(os.environ.get("ANTHROPIC_BASE_URL")),
    }
    return RunConfig.model_validate_json(json.dumps(fields))


def _decompose(args: argparse.Namespace) -> int:
    try:
        # The credential first, from the mode the parameters name: a run whose mode
        # has no secret in the environment is refused before anything else happens.
        mode = json.loads(args.params.read_text()).get("auth")
        known = isinstance(mode, str) and mode in SECRET_VARIABLE
        credential = credential_for(mode, os.environ) if known else None
        config = _config(args)
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    except ValidationError as exc:
        return _fail(
            "the run parameters are not a complete configuration", reason=first_problem(exc)
        )
    if credential is None:  # the configuration validated, so the mode is a known one
        return _fail("the run parameters name no auth mode")
    run_dir = args.run_dir.resolve()
    try:
        require_fresh(run_dir)
        outcome = call(
            args.brief.read_text(),
            config=config,
            workdir=run_dir / "decomposition",
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            credential=credential,
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


def _project_root() -> Path:
    """The source checkout the installation is built from."""
    root = Path(physgate.__file__).resolve().parents[2]
    if not (root / "pyproject.toml").exists():
        msg = "no source checkout to build the hooks' installation from; build it first"
        raise InvocationError(msg, looked_in=str(root))
    return root


def _drive(args: argparse.Namespace, *, resume: bool, registrations: Registrations) -> int:
    run_dir = args.run_dir.resolve()
    try:
        config = load_run_config(run_dir / "run.json")
        # The recorded mode decides which secret the run needs; a resume cannot change it.
        credential = credential_for(config.auth, os.environ)
        # The gate and the reviewers first: without them nothing else is worth building.
        refuse_unregistered(config, registrations.gate, registrations.reviewers)
        # The same provider, or the run's numbers would mean something else.
        require_endpoint(config, os.environ.get("ANTHROPIC_BASE_URL"))
        if not (run_dir / "events.jsonl").exists():
            msg = "the run was never started; decompose it first"
            raise RunStateError(msg, run_dir=str(run_dir))
        install = args.install.resolve()
        install_bin = (
            install / "bin" / "physgate"
            if install.exists()
            else prepare_install(install, _project_root())
        )
        run = RunGit(repo=args.target.resolve(), run_dir=run_dir, run_id=config.run_id)
        store_root = run_dir / "store"
        plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
        keeper = StoreKeeper(run, store_root)
        loop = Loop(
            config=config,
            run_dir=run_dir,
            gate=registrations.gate,
            reviewers=registrations.reviewers,
            dispatcher=ClaudeDispatcher(
                config=config,
                run=run,
                store_root=store_root,
                install_bin=install_bin,
                binary=claude_binary(),
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
                credential=credential,
            ),
            changes=GitChangeChecker(run, store_root, {e.subtask_id: e.module_dir for e in plan}),
            merger=GitMerger(run, removal_timeout_s=REMOVAL_TIMEOUT_S),
            graph=keeper,
        )
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    try:
        step = loop.resume() if resume else loop.run()
        account = TokenAccount.from_events(loop.log.events)
        account.assert_no_routing()
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    finally:
        loop.close()
        keeper.close()
    _print(
        {
            "run_id": config.run_id,
            "step": step.kind,
            "subtasks": {k: v.status for k, v in loop.state.subtasks.items()},
            "open_queue_items": [item.item_id for item in loop.queue.open_items()],
            "tokens": {k: v.total() for k, v in account.by_kind().items()},
        }
    )
    return 0 if step.kind == "done" else 1


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
