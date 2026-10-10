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
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

import physgate
from physgate.gate.exceptions import GateError
from physgate.knowledge.library import LibraryError, read_library
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.catches import catches, parse_time
from physgate.orchestrator.common import first_problem, render_jsonl
from physgate.orchestrator.credentials import SECRET_VARIABLE, credential_for
from physgate.orchestrator.decompose import binary_version, call, require_fresh, start_run
from physgate.orchestrator.dispatch import ClaudeDispatcher, probe_interpreter
from physgate.orchestrator.events import (
    EnvironmentRecorded,
    InstallChecked,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import (
    InvocationError,
    OrchestratorError,
    ReviewerNotRegisteredError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.gate_events import GateEvent, gate_events, recorded_gate_events
from physgate.orchestrator.git import head_of
from physgate.orchestrator.install import (
    manifest_entries,
    prepare_install,
    require_current,
    require_recorded_manifest,
)
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.loop import Loop, refuse_unregistered, require_gate
from physgate.orchestrator.merge import GitMerger, RunGit
from physgate.orchestrator.protocols import Gate, Reviewer
from physgate.orchestrator.queue import ApprovalQueue, queue_listing
from physgate.orchestrator.replay import recorded_ledger
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.role_python import measure as measure_role_python
from physgate.orchestrator.run_config import (
    RunConfig,
    endpoint_of,
    harness_root,
    harness_state,
    load_run_config,
    require_endpoint,
    require_harness,
    require_reportable,
)
from physgate.reviewers.claude import ReviewerSetup, claude_reviewers
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import require_review_root
from physgate.state.exceptions import DesignStateError

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


#: Builds a driven run's reviewers from its setup, once the run's facts are known.
ReviewerFactory = Callable[[ReviewerSetup], Mapping[str, Reviewer]]


@dataclass(frozen=True)
class Registrations:
    """The gate and the reviewers a run may use.

    There is no pass-through default: with none registered, a run in a gate mode
    that needs a gate, or with a role that has no reviewer, refuses to start. The
    reviewers are given built, or as a factory the run calls with its own setup
    (its binary, credential, installation and review root); the factory is used
    only when none are given built.
    """

    gate: Gate | None = None
    reviewers: Mapping[str, Reviewer] = field(default_factory=dict)
    reviewer_factory: ReviewerFactory | None = None


def default_registrations() -> Registrations:
    """The registrations the ``physgate`` command runs with.

    The physics gate and a paired Claude reviewer per role, each registered here as
    a plain import a reader can follow. Built only when a run is driven: the gate
    loads its bounds table and its unit and symbolic tools, which no other command
    needs; the reviewers are built by the run itself, which loads each role's
    promoted rubric before anything is dispatched.

    Raises:
        BoundsTableError: the gate's bounds table does not load; no gate is built.
    """
    from physgate.gate.runner import PhysicsGate

    return Registrations(gate=PhysicsGate(), reviewer_factory=claude_reviewers)


def add_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    registrations: Registrations | None = None,
) -> None:
    """Register the orchestrator's commands on the top-level command."""
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
        command.add_argument(
            "--review-root",
            required=True,
            type=Path,
            help=(
                "where reviews are prepared (by convention ~/review-scratch): outside every "
                "checkout, and named so that no path in it says what is measured"
            ),
        )
        command.set_defaults(
            func=functools.partial(_drive, resume=resume, registrations=registrations)
        )

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

    g = subparsers.add_parser(
        "gate-events",
        help="print one line per gate check the run recorded, for catch accounting",
    )
    g.add_argument("--run-dir", required=True, type=Path)
    g.set_defaults(func=_gate_events)

    ledger = subparsers.add_parser(
        "ledger", help="print the task ledger as recorded, held to the run-event log"
    )
    ledger.add_argument("--run-dir", required=True, type=Path)
    ledger.set_defaults(func=_ledger)

    c = subparsers.add_parser(
        "catches",
        help="count the blocking gate failures on work a reviewer had passed, per check",
        description=(
            "Count, per gate mode and per check, the blocking gate failures and the distinct "
            "artefacts caught, and of those the ones a reviewer had passed (ARCH-083), over "
            "one or more runs and an optional window. Prints one JSON line per row; a run with "
            "no gate events prints nothing."
        ),
    )
    c.add_argument("--run-dir", required=True, type=Path, action="append", dest="run_dirs")
    c.add_argument("--since", help="UTC date or time the window starts at, included")
    c.add_argument("--until", help="UTC date or time the window ends at, excluded")
    c.set_defaults(func=_catches)


def _gate_events(args: argparse.Namespace) -> int:
    """Print every gate check the run recorded, one JSON line each, in log order.

    Every line carries the run's manifest id (``RunConfig.sha256()``), the same
    digest ``run``/``resume`` print, so a reader can tie a line back to the run
    it came from.
    """
    run_dir = args.run_dir.resolve()
    try:
        found = recorded_gate_events(run_dir / "events.jsonl", run_dir / "run.json")
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    sys.stdout.write(render_jsonl(found))
    return 0


def _ledger(args: argparse.Namespace) -> int:
    """Print the task ledger as recorded, one JSON line each, held to the event log.

    Read without writing: a ledger the event log does not imply is refused, not shown.
    """
    run_dir = args.run_dir.resolve()
    try:
        lines = recorded_ledger(run_dir / "events.jsonl", run_dir / "ledger.jsonl")
    except (OrchestratorError, DesignStateError) as exc:
        return _fail(str(exc), **exc.context)
    sys.stdout.write(render_jsonl(lines))
    return 0


def _catches(args: argparse.Namespace) -> int:
    """Print the catch count over every run named, in the window, one JSON line per row.

    A row is aggregated over every run named, per gate mode and check, so unlike
    ``gate-events`` it names no single run's manifest id: an artefact is already
    kept distinct by its own run id (``artefact()`` in ``catches.py``), and a row
    spanning several runs has no one id to attribute to.
    """
    try:
        since = parse_time(args.since) if args.since else None
        until = parse_time(args.until) if args.until else None
    except ValueError as exc:
        return _fail(f"the window is not a UTC date or time: {exc}")
    found: list[GateEvent] = []
    for run_dir in args.run_dirs:
        resolved = run_dir.resolve()
        path = resolved / "events.jsonl"
        if not path.is_file():
            return _fail("no run-event log in the run directory", run_dir=str(run_dir))
        try:
            manifest_id = load_run_config(resolved / "run.json").sha256()
            found.extend(gate_events(read_events(path), manifest_id))
        except OrchestratorError as exc:
            return _fail(str(exc), **exc.context)
    for row in catches(found, since=since, until=until):
        print(row.model_dump_json())
    return 0


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=1, sort_keys=True))


def _fail(message: str, **context: str) -> int:
    print(json.dumps({"error": message, **context}, sort_keys=True), file=sys.stderr)
    return 2


def _config(args: argparse.Namespace) -> RunConfig:
    params = json.loads(args.params.read_text())
    # Measured, never chosen: a parameters file that names the harness is overruled.
    harness = harness_state(_harness_root())
    require_reportable(harness, reportable=params.get("reportable") is True)
    if params.get("role_python") is not None:
        # Measured, never taken from the parameters: only the path is theirs to name.
        named = params["role_python"]
        if not isinstance(named, str):
            msg = "role_python names the role sessions' interpreter by its path, or is null"
            raise RunConfigError(msg)
        measured = measure_role_python(named, probe=probe_interpreter, harness=_harness_root())
        params = {**params, "role_python": measured}
    fields = {
        **params,
        "run_id": args.run_id,
        "seed": args.seed,
        "brief_sha256": hashlib.sha256(args.brief.read_bytes()).hexdigest(),
        "target_head": head_of(args.target.resolve(), "HEAD"),
        "claude_version": binary_version(),
        "endpoint": endpoint_of(os.environ.get("ANTHROPIC_BASE_URL")),
        "harness": harness.model_dump(),
    }
    if isinstance(fields.get("role_python"), RolePython):
        fields["role_python"] = fields["role_python"].model_dump()
    return RunConfig.model_validate_json(json.dumps(fields))


def _harness_root() -> Path | None:
    """The source checkout this orchestrator runs from, or ``None`` if it runs from none."""
    return harness_root()


def _library_root() -> Path | None:
    """Where the curated library is copied from: the checkout this orchestrator runs from.

    Its own function so a test can name a fixture library; nothing a run is given
    on its command line or in its parameters can point it elsewhere.
    """
    return harness_root()


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
        # Every role the run can plan must have its curated content, before the one
        # model call is spent: a role without it could never be dispatched.
        read_library(_library_root(), config.models.roles)
    except LibraryError as exc:
        return _fail(str(exc), **exc.context)
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
            outcome,
            config=config,
            run_dir=run_dir,
            target_repo=args.target.resolve(),
            library=_library_root(),
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


def _recorded_manifest(run_dir: Path, install: Path) -> str | None:
    """The manifest digest this run first recorded for ``install``, if it recorded one."""
    for event in read_events(run_dir / "events.jsonl"):
        if (
            isinstance(event, EnvironmentRecorded)
            and event.facts.path == str(install)
            and event.facts.manifest_sha256 is not None
        ):
            return event.facts.manifest_sha256
    return None


def _drive(args: argparse.Namespace, *, resume: bool, registrations: Registrations | None) -> int:
    if registrations is None:
        try:
            registrations = default_registrations()
        except GateError as exc:  # a gate that cannot be built stops the run here
            return _fail(str(exc), **exc.context)
    run_dir = args.run_dir.resolve()
    try:
        config = load_run_config(run_dir / "run.json")
        # The recorded mode decides which secret the run needs; a resume cannot change it.
        credential = credential_for(config.auth, os.environ)
        # The gate and the reviewers first: without them nothing else is worth building.
        require_gate(config, registrations.gate)
        # Where reviews are prepared: refused before any is, if a reviewer reading a path
        # beneath it could tell what it is reading, or it sits inside a checkout.
        review_root = require_review_root(args.review_root)
        install = args.install.resolve()
        reviewers = registrations.reviewers
        if not reviewers and registrations.reviewer_factory is not None:
            library = _library_root()
            if library is None:
                msg = "the reviewers' rubrics are read from a source checkout, and there is none"
                raise ReviewerNotRegisteredError(msg)
            reviewers = registrations.reviewer_factory(
                ReviewerSetup.of_run(
                    config,
                    review_root=review_root,
                    repo=args.target.resolve(),
                    install_bin=install / "bin" / "physgate",
                    binary=claude_binary(),
                    base_url=os.environ.get("ANTHROPIC_BASE_URL"),
                    credential=credential,
                    library=library,
                )
            )
        refuse_unregistered(config, registrations.gate, reviewers)
        # The same provider, or the run's numbers would mean something else.
        require_endpoint(config, os.environ.get("ANTHROPIC_BASE_URL"))
        # The same code: a run continued on other code is two runs under one name.
        require_harness(config, harness_state(_harness_root()))
        if not (run_dir / "events.jsonl").exists():
            msg = "the run was never started; decompose it first"
            raise RunStateError(msg, run_dir=str(run_dir))
        started = time.monotonic()
        action: Literal["checked", "built"] = "checked" if install.exists() else "built"
        if action == "checked":
            require_current(install, _project_root())
            require_recorded_manifest(install, _recorded_manifest(run_dir, install))
            install_bin = install / "bin" / "physgate"
        else:
            install_bin = prepare_install(install, _project_root())
        checked_in = time.monotonic() - started
        run = RunGit(repo=args.target.resolve(), run_dir=run_dir, run_id=config.run_id)
        store_root = run_dir / "store"
        plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
        keeper = StoreKeeper(run, store_root)
        loop = Loop(
            config=config,
            run_dir=run_dir,
            gate=registrations.gate,
            reviewers=reviewers,
            dispatcher=ClaudeDispatcher(
                config=config,
                run=run,
                store_root=store_root,
                install_bin=install_bin,
                binary=claude_binary(),
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
                credential=credential,
                review_root=review_root,
            ),
            changes=GitChangeChecker(run, store_root, {e.subtask_id: e.module_dir for e in plan}),
            merger=GitMerger(run, removal_timeout_s=REMOVAL_TIMEOUT_S),
            graph=keeper,
        )
    except (OrchestratorError, ReviewError) as exc:
        return _fail(str(exc), **exc.context)
    try:
        # The check ran before the log was open; it is recorded now, before any spawn.
        loop.record.emit(
            InstallChecked(
                **loop.record.envelope(),
                path=str(install),
                action=action,
                seconds=checked_in,
                entries=manifest_entries(install),
            )
        )
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
            # Every number printed here names the record it came from: the run
            # configuration's digest, which the run's first line also carries.
            "manifest_id": config.sha256(),
            "step": step.kind,
            "subtasks": {k: v.status for k, v in loop.state.subtasks.items()},
            "open_queue_items": [item.item_id for item in loop.queue.open_items()],
            "tokens": {k: v.total() for k, v in account.by_kind().items()},
        }
    )
    return 0 if step.kind == "done" else 1


def _queue_list(args: argparse.Namespace) -> int:
    try:
        listing = queue_listing(args.run_dir.resolve())
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    _print(listing)
    return 0


def _queue_resolve(args: argparse.Namespace) -> int:
    queue = ApprovalQueue(args.run_dir.resolve() / "queue.jsonl")
    try:
        record = queue.resolve(args.item, decision=args.decision, resolved_by=args.by)
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    _print({"resolved": record.model_dump()})
    return 0
