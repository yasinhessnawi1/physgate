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
cross-domain propagation edges), so the measurement never runs on a partial one.
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
from physgate.gate.exceptions import GateError
from physgate.orchestrator import cli as orchestrator_cli
from physgate.orchestrator.cli import Registrations, ReviewerFactory, default_registrations
from physgate.orchestrator.common import first_problem
from physgate.orchestrator.credentials import credential_for
from physgate.orchestrator.decompose import binary_version
from physgate.orchestrator.exceptions import OrchestratorError, ReviewerNotRegisteredError
from physgate.orchestrator.install import prepare_install, require_current
from physgate.orchestrator.invocation import claude_binary
from physgate.orchestrator.protocols import Reviewer
from physgate.orchestrator.run_config import endpoint_of
from physgate.reviewers.claude import ReviewerSetup
from physgate.reviewers.exceptions import ReviewError
from physgate.reviewers.places import require_review_root


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
    p.set_defaults(func=lambda args: _inject(args, registrations))


def _inject(args: argparse.Namespace, registrations: Registrations | None) -> int:
    try:
        if registrations is None:
            registrations = default_registrations()
        corpus = load_corpus(args.corpus.resolve())
        reviewers: Mapping[str, Reviewer] = registrations.reviewers
        reviewing = None
        if not reviewers and registrations.reviewer_factory is not None:
            params = _params(args)
            require_complete(corpus)
            reviewers, reviewing = _real_reviewers(args, params, registrations.reviewer_factory)
        # The reviewers first: without them nothing else is worth checking.
        require_reviewers(corpus, reviewers)
        require_complete(corpus)
        rows = run_instrument(
            corpus,
            reviewers,
            run_dir=args.run_dir.resolve(),
            scratch=args.scratch.resolve(),
            run_id=args.run_id,
            seed=args.seed,
            review_clean_twins=args.review_clean_twins,
            reviewing=reviewing,
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


def _real_reviewers(
    args: argparse.Namespace, params: InstrumentParams, factory: ReviewerFactory
) -> tuple[Mapping[str, Reviewer], Reviewing]:
    """The real reviewers, built from ``params``, and the record of how they run."""
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
    setup = ReviewerSetup(
        run_id=args.run_id,
        models=dict(params.reviewers),
        claude_version=version,
        bounds=params.bounds,
        effort=params.effort,
        max_output_tokens=params.max_output_tokens,
        token_ceiling=params.token_ceiling,
        review_root=require_review_root(args.scratch),
        repo=None,
        install_bin=install / "bin" / "physgate",
        binary=binary,
        base_url=base_url,
        credential=credential,
        library=library,
    )
    reviewing = Reviewing(
        params=params,
        claude_version=version,
        endpoint=endpoint_of(base_url),
        install=str(install),
    )
    return factory(setup), reviewing
