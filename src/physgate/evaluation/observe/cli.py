"""The observability commands: every number printed with the manifest id it came from.

Each command reads through the one reader of its format and prints JSON. A
refusal, or a record that does not hold, prints the error and its context on
standard error and exits 2, as the orchestrator's commands do. ``rerun`` prints
the rule that judged it and the divergence that decided, and exits 1 when the
rerun did not reproduce the run.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from physgate.evaluation.observe.compare import compare
from physgate.evaluation.observe.cost import append_cost_line, load_price_sheet, price_run
from physgate.evaluation.observe.exceptions import ObserveError
from physgate.evaluation.observe.manifest import read_manifest
from physgate.evaluation.observe.rerun import rerun, through_the_command
from physgate.evaluation.observe.trace import read_traces
from physgate.evaluation.observe.variance import measure_variance, repeat_run
from physgate.orchestrator.exceptions import OrchestratorError

if TYPE_CHECKING:
    from physgate.orchestrator.cli import Registrations

#: What each basis means, printed beside every cost figure.
BASIS_LABEL = {
    "list_price": "the tokens at the sheet's list prices",
    "list_price_estimate": (
        "a list-price estimate: the subscription is not billed per token, so no such sum was paid"
    ),
}


def _print(model: BaseModel, **extra: object) -> None:
    payload = json.loads(model.model_dump_json())
    print(json.dumps({**payload, **extra}, indent=1, sort_keys=True))


def _guarded(command: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    @functools.wraps(command)
    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except (ObserveError, OrchestratorError) as exc:
            error = {"error": str(exc), **exc.context}
            print(json.dumps(error, sort_keys=True), file=sys.stderr)
            return 2

    return run


def _manifest(args: argparse.Namespace) -> int:
    _print(read_manifest(args.run_dir))
    return 0


def _trace(args: argparse.Namespace) -> int:
    _print(read_traces(args.run_dir))
    return 0


def _cost(args: argparse.Namespace) -> int:
    line = price_run(args.run_dir, load_price_sheet(args.prices))
    if args.append is not None:
        append_cost_line(args.append, line)
    _print(line, basis_label=BASIS_LABEL[line.basis], appended_to=str(args.append or ""))
    return 0


def _rerun(args: argparse.Namespace, *, registrations: Registrations | None) -> int:
    result = rerun(
        args.recorded,
        brief=args.brief,
        run_id=args.run_id,
        run_dir=args.run_dir,
        target=args.target,
        install=args.install,
        review_root=args.review_root,
        driver=through_the_command(registrations),
    )
    first = result.first
    _print(
        result,
        reproduced=result.reproduced,
        rule=result.rule,
        first=None if first is None else json.loads(first.model_dump_json()),
    )
    return 0 if result.reproduced else 1


def _variance(args: argparse.Namespace, *, registrations: Registrations | None) -> int:
    if args.runs:
        report = measure_variance(args.runs)
    else:
        missing = [
            n
            for n in ("n", "brief", "target", "install", "runs_dir", "review_root")
            if not getattr(args, n)
        ]
        if missing:
            msg = (
                "repeating a run needs -n, --brief, --target, --install, --runs-dir and "
                "--review-root"
            )
            raise ObserveError(msg, missing=",".join(missing))
        report = repeat_run(
            args.repeat,
            n=args.n,
            brief=args.brief,
            target=args.target,
            install=args.install,
            runs_dir=args.runs_dir,
            review_root=args.review_root,
            driver=through_the_command(registrations),
        )
    _print(report)
    return 0


def _compare(args: argparse.Namespace) -> int:
    _print(compare(args.baseline, args.candidate))
    return 0


def add_parsers(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    registrations: Registrations | None = None,
) -> None:
    """Register the observability commands on the top-level command."""
    m = subparsers.add_parser("manifest", help="print a run's manifest: its inputs and artefacts")
    m.add_argument("--run-dir", required=True, type=Path)
    m.set_defaults(func=_guarded(_manifest))

    t = subparsers.add_parser("trace", help="print a run's stages, sessions, tokens and checks")
    t.add_argument("--run-dir", required=True, type=Path)
    t.set_defaults(func=_guarded(_trace))

    c = subparsers.add_parser(
        "cost", help="price a run's tokens at a dated price sheet; optionally append to a trend"
    )
    c.add_argument("--run-dir", required=True, type=Path)
    c.add_argument("--prices", required=True, help="the price sheet's date, e.g. 2026-09-27")
    c.add_argument("--append", type=Path, help="the trend file to append the cost line to")
    c.set_defaults(func=_guarded(_cost))

    r = subparsers.add_parser(
        "rerun", help="make a recorded run again from its record and compare the two"
    )
    r.add_argument("recorded", type=Path, help="the recorded run's directory")
    r.add_argument("--brief", required=True, type=Path)
    r.add_argument("--run-id", required=True, help="the rerun's own run id")
    r.add_argument("--run-dir", required=True, type=Path, help="the rerun's run directory")
    r.add_argument("--target", required=True, type=Path, help="the target repository")
    r.add_argument("--install", required=True, type=Path, help="the hooks' installation")
    r.add_argument("--review-root", required=True, type=Path, help="where reviews are prepared")
    r.set_defaults(func=_guarded(functools.partial(_rerun, registrations=registrations)))

    v = subparsers.add_parser(
        "variance", help="ordering and merge-decision variance over repeated runs"
    )
    which = v.add_mutually_exclusive_group(required=True)
    which.add_argument("--runs", nargs="+", type=Path, help="recorded runs of one configuration")
    which.add_argument("--repeat", type=Path, help="a recorded run to repeat n - 1 more times")
    v.add_argument("-n", type=int, help="with --repeat: how many runs in all")
    v.add_argument("--brief", type=Path, help="with --repeat: the recorded run's brief")
    v.add_argument("--target", type=Path, help="with --repeat: the target repository")
    v.add_argument("--install", type=Path, help="with --repeat: the hooks' installation")
    v.add_argument("--runs-dir", type=Path, help="with --repeat: where the repeats are made")
    v.add_argument("--review-root", type=Path, help="with --repeat: where reviews are prepared")
    v.set_defaults(func=_guarded(functools.partial(_variance, registrations=registrations)))

    p = subparsers.add_parser(
        "compare", help="two runs' numbers side by side; refused across drifted pins"
    )
    p.add_argument("baseline", type=Path)
    p.add_argument("candidate", type=Path)
    p.set_defaults(func=_guarded(_compare))

    g = subparsers.add_parser(
        "generalist",
        help="review one reviewed attempt again with the generalist rubric, and print the ratio",
        description=(
            "Review a finished run's attempt again, as its paired review read it, with the "
            "role's rubric less its domain sections, and print paired over generalist tokens "
            "and cost (n = 1)."
        ),
    )
    g.add_argument("--run-dir", required=True, type=Path, help="the finished run")
    g.add_argument("--subtask", required=True)
    g.add_argument("--attempt", required=True, type=int)
    g.add_argument("--target", required=True, type=Path, help="the run's target repository")
    g.add_argument("--install", required=True, type=Path, help="the hooks' installation")
    g.add_argument("--review-root", required=True, type=Path, help="the run's review root")
    g.add_argument("--out", required=True, type=Path, help="a new directory for the review")
    g.add_argument("--run-id", required=True, help="the generalist review's own run id")
    g.add_argument("--prices", required=True, help="the price sheet's date, e.g. 2026-09-27")
    g.set_defaults(func=_guarded(_generalist))


def _generalist(args: argparse.Namespace) -> int:
    import os

    from physgate.evaluation.observe.generalist import (
        BASELINE_NAME,
        paired_review,
        read_packet,
        review_ratio,
        run_generalist,
    )
    from physgate.orchestrator.cli import _library_root
    from physgate.orchestrator.credentials import credential_for
    from physgate.orchestrator.exceptions import ReviewerNotRegisteredError
    from physgate.orchestrator.invocation import claude_binary
    from physgate.orchestrator.run_config import load_run_config, require_endpoint
    from physgate.reviewers.exceptions import ReviewError
    from physgate.reviewers.places import require_review_root

    run_dir = args.run_dir.resolve()
    config = load_run_config(run_dir / "run.json")
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    require_endpoint(config, base_url)
    prices = load_price_sheet(args.prices)
    library = _library_root()
    if library is None:
        msg = "the rubrics are read from a source checkout, and there is none"
        raise ReviewerNotRegisteredError(msg)
    try:
        review_root = require_review_root(args.review_root)
        install_bin = args.install.resolve() / "bin" / "physgate"
        ran, packet = run_generalist(
            run_dir=run_dir,
            subtask_id=args.subtask,
            attempt=args.attempt,
            out=args.out.resolve(),
            run_id=args.run_id,
            review_root=review_root,
            target=args.target.resolve(),
            install_bin=install_bin,
            binary=claude_binary(),
            base_url=base_url,
            credential=credential_for(config.auth, os.environ),
            library=library,
        )
    except ReviewError as exc:
        print(json.dumps({"error": str(exc), **exc.context}, sort_keys=True), file=sys.stderr)
        return 2
    paired, _ = paired_review(run_dir, args.subtask, args.attempt)
    ratio = review_ratio(
        (paired.result, read_packet(review_root, paired.result)), (ran.result, packet), prices
    )
    (args.out.resolve() / BASELINE_NAME).write_text(ratio.model_dump_json(indent=1) + "\n")
    _print(ratio)
    return 0
