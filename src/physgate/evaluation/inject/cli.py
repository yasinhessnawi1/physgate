"""``physgate inject``: run the injected-error instrument over a complete corpus.

The command takes the reviewers the ``physgate`` command is registered with,
and there are none yet, so today it refuses to start, naming the first role
without one. A reviewer is registered where the loop's are; the instrument then
runs without any change here. It refuses a corpus that is not complete (ten
artefacts of each class, ten distinct cross-domain propagation edges), so the measurement
never runs on a partial one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from physgate.evaluation.inject.corpus import load_corpus, require_complete
from physgate.evaluation.inject.exceptions import InstrumentError
from physgate.evaluation.inject.runner import RESULTS_NAME, require_reviewers, run_instrument
from physgate.gate.exceptions import GateError
from physgate.orchestrator.cli import Registrations, default_registrations
from physgate.orchestrator.exceptions import OrchestratorError


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
        # The reviewers first: without them nothing else is worth checking.
        require_reviewers(corpus, registrations.reviewers)
        require_complete(corpus)
        run_instrument(
            corpus,
            registrations.reviewers,
            run_dir=args.run_dir.resolve(),
            scratch=args.scratch.resolve(),
            run_id=args.run_id,
            seed=args.seed,
            review_clean_twins=args.review_clean_twins,
        )
    except (InstrumentError, OrchestratorError, GateError) as exc:
        print(json.dumps({"error": str(exc), **exc.context}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"results": str(args.run_dir.resolve() / RESULTS_NAME)}))
    return 0
