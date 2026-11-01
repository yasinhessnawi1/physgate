"""``physgate inject``: run the injected-error instrument over a complete corpus.

The command reviews with the reviewers the ``physgate`` command is registered with.
Given built (as in tests), they are used as they are. As shipped, the reviewer is
the Claude reviewer, built here from the instrument's own parameters file
(``--params``: the auth mode, each role's reviewer model, the bounds, the effort,
the output-token limit and the token ceiling, none with a default) and the hooks'
installation (``--install``, built there if it does not exist). The binary's
version, the auth mode, the endpoint and those parameters are recorded in the
run's ``instrument.json``. Each role's reviewer judges with its promoted rubric,
and the scratch directory is its review root.

Every artefact gets its row. A review that gave no verdict (after the one retry an
infrastructure failure gets) is recorded as ``review_unavailable`` with its cause,
and one that blocked on a blocking defect of the issued specification is a review
recorded as ``blocked``; neither is a pass or a fail, and the run goes on. The
command prints how many reviews came to each, and exits 1 if any came to neither a
pass nor a fail.

It refuses a corpus that is not complete (ten artefacts of each class, ten distinct
cross-domain propagation edges; for a corpus of the domain-standard class, that class
alone), so the measurement never runs on a partial one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from physgate.evaluation.inject.corpus import load_corpus, require_complete
from physgate.evaluation.inject.exceptions import InstrumentError, InstrumentParamsError
from physgate.evaluation.inject.runner import (
    RESULTS_NAME,
    InstrumentParams,
    Reviewing,
    require_reviewers,
    run_instrument,
)
from physgate.evaluation.inject.source_check import check_sources
from physgate.gate.exceptions import GateError
from physgate.knowledge.promote import KNOWLEDGE_ROOT
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator.cli import Registrations, ReviewerFactory, default_registrations
from physgate.orchestrator.common import first_problem
from physgate.orchestrator.credentials import Credential, credential_for
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.exceptions import OrchestratorError, ReviewerNotRegisteredError
from physgate.orchestrator.install import prepare_install, require_current
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.protocols import Reviewer
from physgate.orchestrator.run_config import endpoint_of
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import require_review_root
from physgate.reviewers.rubric import generalist_of, load_rubric


def add_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    registrations: Registrations | None = None,
) -> None:
    """Register ``inject`` on the top-level command."""
    p = subparsers.add_parser(
        "inject",
        help="review every artefact of an injected-error corpus blind, then gate each",
        description=(
            "Review every artefact of a complete corpus with its role's registered reviewer, "
            "alone and before the gate runs on anything, then gate each and its clean twin, "
            "and write one row per artefact. Reports no total."
        ),
    )
    p.add_argument("--corpus", required=True, type=Path)
    p.add_argument("--run-dir", required=True, type=Path)
    p.add_argument("--scratch", required=True, type=Path, help="where reviewers' worktrees go")
    p.add_argument("--run-id", required=True)
    p.add_argument("--seed", required=True, type=int)
    p.add_argument("--params", type=Path, help="the real reviewers' parameters file")
    p.add_argument(
        "--install",
        type=Path,
        help="the hooks' read-only installation; built there if it does not exist",
    )
    p.add_argument(
        "--review-clean-twins",
        action="store_true",
        help="also review each clean twin, blind, in the same phase (recorded in the run)",
    )
    p.add_argument(
        "--per-class",
        type=int,
        default=10,
        help="the corpus's size per class, held and recorded (risk row 1's is 10)",
    )
    p.add_argument(
        "--lanes",
        type=int,
        help="reviews at once, each lane under its own review root; with real reviewers "
        "it must equal the parameters file's",
    )
    p.add_argument(
        "--generalist",
        action="store_true",
        help="review every artefact with its role's rubric less the domain sections "
        "(ARCH-063's baseline), not the paired rubric",
    )
    p.set_defaults(func=lambda args: _inject(args, registrations))
    q = subparsers.add_parser(
        "inject-sources",
        help="hold a corpus's base and clean patches to its parts sheet, number by number",
        description=(
            "Check every number of a corpus's base and clean patches against the parts-sheet "
            "rows its source names: copied rows equal, derived numbers their arithmetic. The "
            "injected patches are never read. Prints the facts found; exits 1 on a mismatch."
        ),
    )
    q.add_argument("--corpus", required=True, type=Path)
    q.set_defaults(func=_sources)


def _inject(args: argparse.Namespace, registrations: Registrations | None) -> int:
    try:
        if registrations is None:
            registrations = default_registrations()
        corpus = load_corpus(args.corpus.resolve())
        reviewers: Mapping[str, Reviewer] = registrations.reviewers
        reviewing = None
        lanes, lane_sets = args.lanes or 1, None
        delays: tuple[float, ...] = (0.0,)
        pause_after, pause_s = 0, 0.0
        if not reviewers and registrations.reviewer_factory is not None:
            params = _params(args)
            require_complete(corpus, args.per_class)
            lanes, pause_after, pause_s = _lane_rules(args, params)
            factory = generalist_reviewers if args.generalist else registrations.reviewer_factory
            lane_sets, reviewing = _real_reviewers(args, params, factory, lanes)
            reviewers = lane_sets[0]
            delays = params.bounds.infra_retry_delays_s
        # The reviewers first: without them nothing else is worth checking.
        require_reviewers(corpus, reviewers)
        require_complete(corpus, args.per_class)
        rows = run_instrument(
            corpus,
            reviewers,
            run_dir=args.run_dir.resolve(),
            scratch=args.scratch.resolve(),
            run_id=args.run_id,
            seed=args.seed,
            review_clean_twins=args.review_clean_twins,
            reviewing=reviewing,
            per_class=args.per_class,
            lanes=lanes,
            lane_reviewers=lane_sets,
            retry_delays_s=delays,
            pause_after_failures=pause_after,
            pause_s=pause_s,
            reviewer_kind="generalist" if args.generalist else "paired",
        )
    except (InstrumentError, OrchestratorError, GateError, ReviewError) as exc:
        print(json.dumps({"error": str(exc), **exc.context}, sort_keys=True), file=sys.stderr)
        return 2
    counts = {o: 0 for o in ("pass", "fail", "blocked", "review_unavailable")}
    for row in rows:
        counts[row.reviewer_verdict] += 1
        if row.control_reviewer_verdict is not None:
            counts[row.control_reviewer_verdict] += 1
    results = str(args.run_dir.resolve() / RESULTS_NAME)
    print(json.dumps({"results": results, "reviews": counts}, sort_keys=True))
    # Every artefact has its row either way; a review without a pass or a fail says so.
    return 0 if counts["blocked"] + counts["review_unavailable"] == 0 else 1


def _sources(args: argparse.Namespace) -> int:
    try:
        found = check_sources(load_corpus(args.corpus.resolve()))
    except InstrumentError as exc:
        print(json.dumps({"error": str(exc), **exc.context}, sort_keys=True), file=sys.stderr)
        return 2
    counts = {k: sum(f.kind == k for f in found) for k in ("mismatch", "unresolved", "subtracted")}
    print(json.dumps({"counts": counts, "facts": [f.fact() for f in found]}, indent=1))
    return 1 if counts["mismatch"] else 0


def _params(args: argparse.Namespace) -> InstrumentParams:
    """The real reviewers' parameters, from the file ``--params`` names.

    Raises:
        InstrumentParamsError: there is no file or no installation named, or the
            file is not a complete set of parameters.
    """
    if args.params is None or args.install is None:
        msg = "the real reviewers run only with a parameters file and an installation"
        raise InstrumentParamsError(msg, needs="--params and --install")
    try:
        return InstrumentParams.model_validate_json(args.params.read_bytes())
    except (OSError, ValidationError) as exc:
        reason = first_problem(exc) if isinstance(exc, ValidationError) else str(exc)
        msg = "the parameters file is not a complete set of reviewer parameters"
        raise InstrumentParamsError(msg, reason=reason) from None


def _lane_rules(args: argparse.Namespace, params: InstrumentParams) -> tuple[int, int, float]:
    """The lanes and the lane-wide pause, from the parameters file, which must state them.

    Raises:
        InstrumentParamsError: the file states no lanes or pause, or ``--lanes`` says
            another number of lanes than the file.
    """
    if params.lanes is None or params.pause_after_failures is None or params.pause_s is None:
        msg = "the parameters file states the lanes and the lane-wide pause"
        raise InstrumentParamsError(msg, needs="lanes, pause_after_failures, pause_s")
    if params.repair_resumes is None:
        msg = "the parameters file states how many repair resumes a review gets"
        raise InstrumentParamsError(msg, needs="repair_resumes")
    if args.lanes is not None and args.lanes != params.lanes:
        msg = "the lanes given are not the parameters file's"
        raise InstrumentParamsError(msg, given=str(args.lanes), file=str(params.lanes))
    return params.lanes, params.pause_after_failures, params.pause_s


def generalist_reviewers(setup: ReviewerSetup) -> dict[str, Reviewer]:
    """A generalist reviewer for every role ``setup`` pins: its rubric less the domain sections.

    The same model and setup as the paired reviewers; only the rubric differs, so the
    two arms differ in pairing alone (ARCH-063).

    Raises:
        ReviewerNotRegisteredError: a role's rubric does not load.
    """
    found: dict[str, Reviewer] = {}
    for role in sorted(setup.models):
        try:
            rubric = load_rubric(setup.library / KNOWLEDGE_ROOT, role)
        except ReviewError as exc:
            msg = f"a generalist review starts from the role's rubric, which does not load: {exc}"
            raise ReviewerNotRegisteredError(msg, **{**exc.context, "role": role}) from None
        found[role] = ClaudeReviewer(role=role, setup=setup, rubric=generalist_of(rubric))
    return found


def _real_reviewers(
    args: argparse.Namespace, params: InstrumentParams, factory: ReviewerFactory, lanes: int
) -> tuple[list[Mapping[str, Reviewer]], Reviewing]:
    """The real reviewers of every lane, built from ``params``, and how they run.

    Each lane's reviewers are built for its own review root, ``scratch/lane-<k>``, or
    the scratch directory itself with one lane.
    """
    credential = credential_for(params.auth, os.environ)
    binary = claude_binary()
    version = binary_version(binary)
    install = args.install.resolve()
    if install.exists():
        require_current(install, orchestrator_cli._project_root())
    else:
        prepare_install(install, orchestrator_cli._project_root())
    # Read through the command's own seam, so the library is the one a run reads.
    library = orchestrator_cli._library_root()
    if library is None:
        msg = "the reviewers' rubrics are read from a source checkout, and there is none"
        raise ReviewerNotRegisteredError(msg)
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    roots = [args.scratch] if lanes == 1 else [args.scratch / f"lane-{k}" for k in range(lanes)]
    sets = [
        factory(_setup(args, params, version, binary, base_url, credential, library, root))
        for root in roots
    ]
    reviewing = Reviewing(
        params=params,
        claude_version=version,
        endpoint=endpoint_of(base_url),
        install=str(install),
    )
    return sets, reviewing


def _setup(
    args: argparse.Namespace,
    params: InstrumentParams,
    version: str,
    binary: str,
    base_url: str | None,
    credential: Credential,
    library: Path,
    root: Path,
) -> ReviewerSetup:
    install = args.install.resolve()
    return ReviewerSetup(
        run_id=args.run_id,
        models=dict(params.reviewers),
        claude_version=version,
        bounds=params.bounds,
        effort=params.effort,
        max_output_tokens=params.max_output_tokens,
        token_ceiling=params.token_ceiling,
        review_root=require_review_root(root),
        repo=None,
        install_bin=install / "bin" / "physgate",
        binary=binary,
        base_url=base_url,
        credential=credential,
        library=library,
        repair_resumes=params.repair_resumes or 0,
    )
