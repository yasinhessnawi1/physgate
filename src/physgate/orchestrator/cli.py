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
import getpass
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
from physgate.evaluation.inject.runner import CONFIG_NAME as INSTRUMENT_CONFIG_NAME
from physgate.evaluation.inject.runner import CONTROLS_DIRNAME as INSTRUMENT_CONTROLS_DIRNAME
from physgate.evaluation.inject.runner import InstrumentConfig
from physgate.gate.exceptions import GateError
from physgate.knowledge.library import LibraryError, read_library
from physgate.knowledge.promote import KNOWLEDGE_ROOT, PROMOTIONS_NAME, canaries
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.apply import GitChangeChecker, StoreKeeper
from physgate.orchestrator.canaries import CanaryCheck
from physgate.orchestrator.catches import catches, parse_time
from physgate.orchestrator.common import first_problem, render_jsonl
from physgate.orchestrator.credentials import SECRET_VARIABLE, Credential, credential_for
from physgate.orchestrator.decompose import (
    Outcome,
    binary_version,
    call,
    plan_sha256,
    require_fresh,
    require_startable,
    start_run,
)
from physgate.orchestrator.dispatch import ClaudeDispatcher, probe_interpreter
from physgate.orchestrator.events import (
    DesignUnavailable,
    Envelope,
    EnvironmentRecorded,
    Event,
    InstallChecked,
    OsLayerChecked,
    RunStarted,
    SubtaskPlanned,
    read_events,
)
from physgate.orchestrator.exceptions import (
    HeldOutExposedError,
    InvocationError,
    OrchestratorError,
    QueueError,
    ReviewerNotRegisteredError,
    ReviewUnavailableError,
    RunConfigError,
    RunStateError,
)
from physgate.orchestrator.gate_events import GateEvent, gate_events, recorded_gate_events
from physgate.orchestrator.git import harness_git, head_of
from physgate.orchestrator.install import (
    manifest_entries,
    prepare_install,
    require_current,
    require_recorded_manifest,
)
from physgate.orchestrator.invocation import claude_binary, session_search_path
from physgate.orchestrator.loop import Loop, escalation_for, refuse_unregistered, require_gate
from physgate.orchestrator.merge import GitMerger, RunGit
from physgate.orchestrator.protocols import Gate, PlanReviewer, PlanUnderReview, Reviewer
from physgate.orchestrator.queue import (
    POSITIONS,
    PersonDecision,
    ShownItem,
    queue_listing,
    record_decision,
    statuses_now,
)
from physgate.orchestrator.record import PlanReviewed, ReviewInstall
from physgate.orchestrator.replay import recorded_ledger
from physgate.orchestrator.requirements import RunFacts, refusals
from physgate.orchestrator.role_python import RolePython
from physgate.orchestrator.role_python import measure as measure_role_python
from physgate.orchestrator.run_config import (
    Network,
    RunConfig,
    endpoint_of,
    harness_root,
    harness_state,
    load_run_config,
    network_enforced,
    os_layer_refusal,
    require_endpoint,
    require_harness,
    require_reportable,
)
from physgate.oslayer.listeners import loopback_listeners
from physgate.oslayer.policy import NETWORK_UNENFORCED
from physgate.oslayer.probe import Absent, Present, judge_here
from physgate.reviewers.claude import ReviewerSetup, claude_reviewers, design_reviewer
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import require_review_root
from physgate.roles import require_registered
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
#: Builds a run's design reviewer from its setup and configuration, or ``None`` if it pins none.
PlanReviewerFactory = Callable[[ReviewerSetup, RunConfig], PlanReviewer | None]


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
    #: The design reviewer of a run that reviews its plan, built by ``decompose`` before the call.
    plan_reviewer_factory: PlanReviewerFactory | None = None


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

    return Registrations(
        gate=PhysicsGate(),
        reviewer_factory=claude_reviewers,
        plan_reviewer_factory=design_reviewer,
    )


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
        if resume:
            command.add_argument(
                "--quarantine",
                metavar="SESSION_ID",
                help=(
                    "set aside the gone stream of one leftover session, recorded as unscanned "
                    "and halting the run as an incident; refused if its stream is there"
                ),
            )
            command.add_argument(
                "--quarantine-why", help="why the stream is gone (required with --quarantine)"
            )
            command.add_argument(
                "--confirm",
                metavar="ITEM_ID",
                action="append",
                default=[],
                help=(
                    "confirm a queue decision held because it was written while a session ran "
                    "without the OS layer; recorded with your OS user, and refused for an item "
                    "whose decision is not held"
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
    d.add_argument(
        "--install",
        type=Path,
        help=(
            "the hooks' read-only installation the plan's review runs under, built there if it "
            "does not exist; required when the parameters review the plan"
        ),
    )
    d.add_argument(
        "--review-root",
        type=Path,
        help=(
            "where the plan's review is prepared, as for run; required when the parameters "
            "review the plan"
        ),
    )
    d.set_defaults(func=functools.partial(_decompose, registrations=registrations))

    q = subparsers.add_parser("queue", help="the approval queue")
    actions = q.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("list", help="print the open items")
    listing.add_argument("--run-dir", required=True, type=Path)
    listing.set_defaults(func=_queue_list)
    resolve = actions.add_parser(
        "resolve",
        help="record a decision on one item",
        description=(
            "Record a decision on one item. --approve, --reject or --choose binds it to the item "
            "line whose digest `queue list` printed (--sha256), and a run that acts on decisions "
            "takes it and does what the item says. --choose domain binds only where every "
            "transcript the listing showed held its seal; --decision records free text, which "
            "binds to nothing and never acts."
        ),
    )
    resolve.add_argument("item")
    resolve.add_argument("--run-dir", required=True, type=Path)
    form = resolve.add_mutually_exclusive_group(required=True)
    form.add_argument("--decision", help="free text, recorded only")
    form.add_argument("--approve", action="store_true", help="approve the item as shown")
    form.add_argument("--reject", action="store_true", help="reject the item as shown")
    form.add_argument(
        "--choose",
        choices=[p for kind in POSITIONS.values() for p in kind],
        help="choose a position an arbitration or a failed contract's item offers",
    )
    resolve.add_argument("--note", help="why; required to reject")
    resolve.add_argument(
        "--sha256", help="the item line's digest as `queue list` printed it; required with a verb"
    )
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

    A run directory is a driven run's, an injected-error instrument run's, or that run's
    ``controls`` directory: each run's events are stamped with its own manifest id
    (:func:`_manifest_id`) before they are counted.
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
            log = read_events(path)
            found.extend(gate_events(log, _manifest_id(resolved, log)))
        except OrchestratorError as exc:
            return _fail(str(exc), **exc.context)
    for row in catches(found, since=since, until=until):
        print(row.model_dump_json())
    return 0


def _manifest_id(run_dir: Path, log: list[Event]) -> str:
    """The manifest id a run directory's gate events are stamped with.

    A driven run's is its recorded configuration's (``RunConfig.sha256()``). The
    injected-error instrument records ``instrument.json`` in place of ``run.json``, and its
    id is that file's digest, which its log's first line carries; the controls log, in the
    ``controls`` directory beneath it, starts under the same file. The id is held to the log
    it stamps, so a configuration changed after the run is refused, never read as its own.

    Raises:
        RunConfigError: there is no configuration, there are both kinds, the instrument's is
            not one, or it is not the one the log's first line names.
    """
    driven, instrument = run_dir / "run.json", run_dir / INSTRUMENT_CONFIG_NAME
    if run_dir.name == INSTRUMENT_CONTROLS_DIRNAME and not instrument.exists():
        instrument = run_dir.parent / INSTRUMENT_CONFIG_NAME
    if not instrument.is_file():
        return load_run_config(driven).sha256()
    if driven.exists():
        msg = "the run directory holds both a run configuration and an instrument configuration"
        raise RunConfigError(msg, run_dir=str(run_dir))
    raw = instrument.read_bytes()
    try:
        InstrumentConfig.model_validate_json(raw)
    except ValidationError as exc:
        msg = "the instrument configuration is not one the instrument could have written"
        raise RunConfigError(msg, path=str(instrument), reason=first_problem(exc)) from None
    manifest_id = hashlib.sha256(raw).hexdigest()
    started = log[0] if log else None
    if not isinstance(started, RunStarted) or started.config_sha256 != manifest_id:
        msg = "the log's first line does not name the instrument configuration recorded beside it"
        raise RunConfigError(msg, path=str(instrument), manifest_id=manifest_id)
    return manifest_id


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=1, sort_keys=True))


def _say_os_layer(state: Present | Absent, network: Network, *, allowed: bool = False) -> None:
    """Say, where a person sees it, when the OS layer is absent, and whether sessions run anyway.

    ``allowed``: the run's parameters allow role sessions without the layer, for development,
    and nothing else refuses it. And say when the run asks for ``network: none``, which only the
    OS layer can enforce.
    """
    if isinstance(state, Absent):
        what = "no OS protection" if state.no_os_protection else "the OS layer is absent"
        then = (
            "role sessions' shell commands run without it, allowed for development "
            "(os_layer_absent: allow)"
            if allowed
            else "role sessions do not run without it"
        )
        print(f"physgate: {what}: {state.reason}; {then}", file=sys.stderr)
    if network_enforced(network, state) is False:
        print(
            f"physgate: {NETWORK_UNENFORCED}; role sessions' shell commands stay online",
            file=sys.stderr,
        )


def _os_layer_checked(
    envelope: Envelope,
    config: RunConfig,
    layer: Present | Absent,
    listening: Callable[[], tuple[int, ...] | None] = loopback_listeners,
) -> OsLayerChecked:
    """The run's record of the OS layer where this process runs its sessions.

    It says whether the layer is the one the run recorded, and whether the run's
    ``network: none``, if it asks for that, is enforced here. For such a run it also
    records the services listening on the machine's loopback, which the layer keeps an
    offline session from.
    """
    found = listening() if config.network == "none" else None
    _say_listeners(config.network, found)
    return OsLayerChecked(
        **envelope,
        state=layer,
        as_recorded=None if config.os_layer is None else config.os_layer == layer,
        absent_allowed=None
        if isinstance(layer, Present)
        else os_layer_refusal(config, layer) is None,
        network_enforced=network_enforced(config.network, layer),
        loopback_listeners=found,
        loopback_listeners_read=None if config.network != "none" else found is not None,
    )


def _say_listeners(network: Network, found: tuple[int, ...] | None) -> None:
    """Say, for an offline run, what listens on the machine's loopback, or that it is unread."""
    if network != "none":
        return
    if found is None:
        print(
            "physgate: the services listening on this machine's loopback could not be read",
            file=sys.stderr,
        )
    elif found:
        print(
            f"physgate: {len(found)} services listen on this machine's loopback "
            f"(ports {', '.join(map(str, found))}); offline sessions are kept from them by "
            "the OS layer, with local binding off",
            file=sys.stderr,
        )


def _fail(message: str, **context: str) -> int:
    print(json.dumps({"error": message, **context}, sort_keys=True), file=sys.stderr)
    return 2


def _config(args: argparse.Namespace) -> RunConfig:
    params = json.loads(args.params.read_text())
    # The git every harness git command will run, first: below 2.42 git ignores the attribute
    # source the harness sets, and the run is refused here. Measured, never chosen.
    found_git = harness_git()
    # Measured, never chosen: a parameters file that names the harness is overruled.
    harness = harness_state(_harness_root())
    require_reportable(harness, reportable=params.get("reportable") is True)
    layer = judge_here(
        claude_version=binary_version(), search_path=session_search_path(claude_binary())
    )
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
        "git_binary": found_git.model_dump(),
        # Measured, never chosen: whether the OS layer runs here for this binary.
        "os_layer": layer.model_dump(),
        # And so whether it enforces the network the parameters ask for.
        "network_enforced": network_enforced(str(params.get("network")), layer),
    }
    if isinstance(fields.get("role_python"), RolePython):
        fields["role_python"] = fields["role_python"].model_dump()
    config = RunConfig.model_validate_json(json.dumps(fields))
    if config.escalation_backend is None:
        # A null binding is how a run recorded before the binding existed reads back; a new
        # run names one, or it would be recorded as a run no loop drives.
        msg = "a new run names its escalation backend; none is not a binding"
        raise RunConfigError(msg)
    return config


def _harness_root() -> Path | None:
    """The source checkout this orchestrator runs from, or ``None`` if it runs from none."""
    return harness_root()


def _library_root() -> Path | None:
    """Where the curated library is copied from: the checkout this orchestrator runs from.

    Its own function so a test can name a fixture library; nothing a run is given
    on its command line or in its parameters can point it elsewhere.
    """
    return harness_root()


def _install_bin(
    install: Path, run_dir: Path | None = None
) -> tuple[Path, Literal["checked", "built"], float]:
    """The installation's binary: checked against its build, and the run's record, or built.

    Returns the binary, which of the two was done, and how many seconds it took.
    """
    started = time.monotonic()
    if not install.exists():
        return prepare_install(install, _project_root()), "built", time.monotonic() - started
    require_current(install, _project_root())
    if run_dir is not None:
        require_recorded_manifest(install, _recorded_manifest(run_dir, install))
    return install / "bin" / "physgate", "checked", time.monotonic() - started


def _reviewer_setup(
    args: argparse.Namespace,
    config: RunConfig,
    credential: Credential,
    review_root: Path,
    install_bin: Path,
) -> ReviewerSetup:
    """What a run's reviewers are built from, their rubrics read from the source checkout.

    Raises:
        ReviewerNotRegisteredError: there is no checkout to read the rubrics from.
    """
    library = _library_root()
    if library is None:
        msg = "the reviewers' rubrics are read from a source checkout, and there is none"
        raise ReviewerNotRegisteredError(msg)
    return ReviewerSetup.of_run(
        config,
        review_root=review_root,
        repo=args.target.resolve(),
        install_bin=install_bin,
        binary=claude_binary(),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        credential=credential,
        library=library,
    )


def _plan_reviewer(
    args: argparse.Namespace,
    config: RunConfig,
    credential: Credential,
    registrations: Registrations | None,
) -> tuple[PlanReviewer, ReviewInstall] | None:
    """The design reviewer of a run that reviews its plan, and its installation; ``None`` if not.

    Built before the call is spent: a review that could not run would leave the call's tokens
    spent on a run that never starts. The installation is checked against its build, or built,
    as a run's is.

    Raises:
        RunConfigError: the run reviews its plan and names no installation or review root.
        ReviewerNotRegisteredError: no design reviewer is registered, or there is no checkout
            to read its rubric from.
        ReviewRootError: the review root is not one a reviewer may read beneath.
    """
    if config.design_review == "off":
        return None
    if args.install is None or args.review_root is None:
        msg = (
            "a run that reviews its plan names the installation and the place its review "
            "runs under: --install and --review-root"
        )
        raise RunConfigError(msg, design_review=config.design_review)
    review_root = require_review_root(args.review_root)
    install = args.install.resolve()
    install_bin, action, seconds = _install_bin(install)
    setup = _reviewer_setup(args, config, credential, review_root, install_bin)
    factory = design_reviewer if registrations is None else registrations.plan_reviewer_factory
    reviewer = factory(setup, config) if factory is not None else None
    if reviewer is None:
        msg = "a run that reviews its plan needs its design reviewer, and none is registered"
        raise ReviewerNotRegisteredError(msg)
    checked = ReviewInstall(
        path=str(install), action=action, seconds=seconds, entries=manifest_entries(install)
    )
    return reviewer, checked


def _reviewed(
    reviewing: tuple[PlanReviewer, ReviewInstall],
    outcome: Outcome,
    *,
    config: RunConfig,
    brief: Path,
    stream: Path,
) -> PlanReviewed | None:
    """What the review of the call's plan came to; ``None`` when the call gave no plan.

    The reviewer is handed the brief as the run's digest names it, the plan and its digest, and
    the call's stream with the seal the call took where it wrote it. A review that is not a
    verdict, or whose stream showed held-out material, is what the review came to; anything
    else it raises fails the command, with nothing of the run recorded.

    Raises:
        RunStateError: the call gave a plan and sealed no stream.
    """
    if not outcome.ok or outcome.plan is None:
        return None  # nothing to review: the failed call is what the run records
    if outcome.stream_seal is None:
        msg = "the call gave a plan and sealed no stream, so its plan cannot be reviewed"
        raise RunStateError(msg, session_id=outcome.session_id)
    reviewer, install = reviewing
    under = PlanUnderReview(
        brief=brief.read_bytes().decode("utf-8"),
        brief_sha256=config.brief_sha256,
        plan=outcome.plan,
        plan_sha256=plan_sha256(outcome.plan),
        stream=str(stream),
        stream_seal=outcome.stream_seal,
        decomposition_model=config.models.decomposition,
        decomposition_session_id=outcome.session_id,
    )
    ending: dict[str, object]
    try:
        result = reviewer.review_plan(under)
        ending = {"session_id": result.session_id, "usage": result.usage, "result": result}
    except ReviewUnavailableError as exc:
        why = DesignUnavailable(
            cause=exc.cause,
            detail=str(exc) or exc.cause,
            session_id=exc.session_id,
            reviewer_model=exc.reviewer_model,
            spec_defects=exc.spec_defects,
        )
        ending = {"session_id": exc.session_id, "usage": exc.usage, "unavailable": why}
    except HeldOutExposedError as exc:
        ending = {"session_id": exc.session_id, "usage": exc.usage, "exposed": True}
    return PlanReviewed.model_validate(
        {"install": install, "stream_seal": outcome.stream_seal, **ending}
    )


def _decompose(args: argparse.Namespace, *, registrations: Registrations | None = None) -> int:
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
    assert config.os_layer is not None  # measured above, for every new run
    why = os_layer_refusal(config, config.os_layer)
    _say_os_layer(config.os_layer, config.network, allowed=why is None)
    if why is not None:
        return _fail(why)
    refused = refusals(
        RunFacts(config=config, os_layer=config.os_layer, shell_sessions=True, new_run=True)
    )
    if refused:
        return _fail("the run may not start", requirements="; ".join(refused))
    run_dir = args.run_dir.resolve()
    try:
        # Every role the run can plan must be in the role register and have its curated
        # content, before the one model call is spent: without either it could never be
        # dispatched.
        require_registered(config.models.roles)
        read_library(_library_root(), config.models.roles)
    except (LibraryError, OrchestratorError) as exc:
        return _fail(str(exc), **exc.context)
    try:
        require_fresh(run_dir)
        reviewing = _plan_reviewer(args, config, credential, registrations)
        brief = args.brief.read_text()
        workdir = run_dir / "decomposition"
        outcome = call(
            brief,
            config=config,
            workdir=workdir,
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            credential=credential,
        )
        if reviewing is not None and outcome.ok and outcome.plan is not None:
            # A plan the run could not start is refused before its review is spent on it.
            require_startable(
                outcome.plan,
                config=config,
                target_repo=args.target.resolve(),
                library=_library_root(),
                brief=brief,
            )
        # The plan's review, after the call and before anything of the run is written.
        reviewed = (
            _reviewed(
                reviewing,
                outcome,
                config=config,
                brief=args.brief,
                stream=workdir / "stdout.jsonl",
            )
            if reviewing is not None
            else None
        )
        record = start_run(
            outcome,
            config=config,
            run_dir=run_dir,
            target_repo=args.target.resolve(),
            library=_library_root(),
            brief=brief,
            reviewed=reviewed,
        )
    except (OrchestratorError, ReviewError) as exc:
        return _fail(str(exc), **exc.context)
    subtasks = [line.id for line in record.ledger.read_all()]
    record.close()
    printed: dict[str, object] = {
        "run_id": config.run_id,
        "decomposed": outcome.ok,
        "cause": outcome.cause,
        "detail": outcome.detail,
        "subtasks": subtasks,
    }
    if reviewed is not None:
        # Said only for a run that reviews its plan, so what any other run prints is unchanged.
        printed["plan_review"] = (
            reviewed.result.verdict
            if reviewed.result is not None
            else reviewed.unavailable.cause
            if reviewed.unavailable is not None
            else "held_out_exposed"
        )
    _print(printed)
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


def _quarantine_request(args: argparse.Namespace) -> tuple[str, str, str] | None:
    """The operator's ``--quarantine`` as (session id, who, why); who is the OS user."""
    session = getattr(args, "quarantine", None)
    why = (getattr(args, "quarantine_why", None) or "").strip()
    if session is None:
        return None
    if not why:
        msg = "--quarantine needs --quarantine-why: who set it aside is recorded with why"
        raise RunStateError(msg, session_id=session)
    return session, getpass.getuser(), why


def material_check(config: RunConfig) -> CanaryCheck:
    """What the loop holds a person's words to before they reach a role session (ARCH-133).

    The run's held-out canaries, and every canary the harness's rubric promotions recorded:
    the same sets a session's own stream is held to.
    """
    harness = harness_root()
    rubric = canaries(harness / KNOWLEDGE_ROOT / PROMOTIONS_NAME) if harness else frozenset()
    return CanaryCheck(held_out=frozenset(config.held_out_canaries), review_material=rubric)


def _confirm_request(args: argparse.Namespace) -> tuple[tuple[str, ...], str | None]:
    """The operator's ``--confirm`` items, and who confirms them: the OS user, or no one.

    A command-line flag only, never read from a file a session could write: what it confirms
    is a decision a session's own shell may have written (ARCH-133).
    """
    confirm = tuple(getattr(args, "confirm", None) or ())
    return confirm, getpass.getuser() if confirm else None


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
            setup = _reviewer_setup(
                args, config, credential, review_root, install / "bin" / "physgate"
            )
            reviewers = registrations.reviewer_factory(setup)
        refuse_unregistered(config, registrations.gate, reviewers)
        # The binding the run recorded, through the register, before anything is built.
        escalation = escalation_for(config)
        # The same provider, or the run's numbers would mean something else.
        require_endpoint(config, os.environ.get("ANTHROPIC_BASE_URL"))
        # A git at 2.42 or later, before the first guard that runs git: the floor alone. The
        # recorded binary is not held to; a run or resume uses whichever git this process
        # resolves.
        harness_git()
        # The same code: a run continued on other code is two runs under one name.
        require_harness(config, harness_state(_harness_root()))
        if not (run_dir / "events.jsonl").exists():
            msg = "the run was never started; decompose it first"
            raise RunStateError(msg, run_dir=str(run_dir))
        install_bin, action, checked_in = _install_bin(install, run_dir)
        run = RunGit(repo=args.target.resolve(), run_dir=run_dir, run_id=config.run_id)
        store_root = run_dir / "store"
        plan = [e for e in read_events(run_dir / "events.jsonl") if isinstance(e, SubtaskPlanned)]
        keeper = StoreKeeper(run, store_root)
        quarantine = _quarantine_request(args)
        dispatcher = ClaudeDispatcher(
            config=config,
            run=run,
            store_root=store_root,
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            credential=credential,
            review_root=review_root,
            quarantine=quarantine,
        )
        loop = Loop(
            config=config,
            run_dir=run_dir,
            gate=registrations.gate,
            reviewers=reviewers,
            dispatcher=dispatcher,
            changes=GitChangeChecker(run, store_root, {e.subtask_id: e.module_dir for e in plan}),
            merger=GitMerger(run, removal_timeout_s=REMOVAL_TIMEOUT_S),
            graph=keeper,
            escalation=escalation,
            material=material_check(config),
        )
    except (OrchestratorError, ReviewError) as exc:
        return _fail(str(exc), **exc.context)
    layer = dispatcher.os_layer()
    # Said here; refused by the loop, which records the layer's line first.
    _say_os_layer(layer, config.network, allowed=os_layer_refusal(config, layer) is None)
    refused = refusals(RunFacts(config=config, os_layer=layer, shell_sessions=True))
    if refused:
        loop.close()
        keeper.close()
        return _fail("the run may not continue", requirements="; ".join(refused))
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
        loop.record.emit(_os_layer_checked(loop.record.envelope(), config, layer))
        confirm, confirmed_by = _confirm_request(args)
        step = loop.resume(confirm=confirm, confirmed_by=confirmed_by) if resume else loop.run()
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
    run_dir = args.run_dir.resolve()
    try:
        if args.decision is not None:
            if args.sha256 is not None or args.note is not None:
                msg = "free text binds to nothing: give a verb to bind it, or leave out the rest"
                raise QueueError(msg, item=args.item)
            record = record_decision(
                run_dir, args.item, decision=args.decision, resolved_by=args.by
            )
        else:
            if args.sha256 is None:
                msg = "a decision with a verb names the item line it was taken on: give --sha256"
                raise QueueError(msg, item=args.item)
            try:
                person = PersonDecision(
                    verb="choose" if args.choose else "approve" if args.approve else "reject",
                    note=args.note,
                    position=args.choose,
                )
                shown = ShownItem(
                    item_sha256=args.sha256, trajectories=statuses_now(run_dir, args.item)
                )
            except ValidationError as exc:
                msg = "the decision is not one the queue can record"
                raise QueueError(msg, reason=first_problem(exc)) from None
            record = record_decision(
                run_dir, args.item, person=person, resolved_by=args.by, shown=shown
            )
    except OrchestratorError as exc:
        return _fail(str(exc), **exc.context)
    _print({"resolved": record.model_dump()})
    return 0
