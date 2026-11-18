"""The ``physgate`` command: hooks, orchestrator, observability, instruments, tiers, gaps, UI."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from physgate.evaluation import evidence, gaps_cli, tierset_cli
from physgate.evaluation import requirements as evaluation_requirements
from physgate.evaluation.baseline import cli as baseline_cli
from physgate.evaluation.gaps import published
from physgate.evaluation.inject import cli as inject_cli
from physgate.evaluation.observe import cli as observe_cli
from physgate.evaluation.observe import compare
from physgate.evaluation.per_role import cli as per_role_cli
from physgate.hooks import cli as hooks_cli
from physgate.knowledge import cli as knowledge_cli
from physgate.orchestrator import catches, requirements
from physgate.orchestrator import cli as orchestrator_cli
from physgate.ui import cli as ui_cli
from physgate.ui import table

#: What the comparison classes and how it compares, the gate's catch count, and the published
#: gap trend's names and parser, handed to the Evidence screen's routes.
CENSUS = evidence.Census(
    drift=compare.DRIFT,
    reported=compare.REPORTED,
    compare=compare.compare,
    catches=catches.catches,
    trend=evidence.TrendCensus(
        roles=published.ROLES,
        name=published.published_name,
        most=published.MOST_PUBLISHED_BYTES,
        parse=published.read_published,
        refused=published.GapsError,
    ),
)


def compose() -> None:
    """Wire the evaluation into the core, here and nowhere else.

    The evaluation's conditions on a run: the core states none of its own, and runs without
    them where there is no evaluation. And the Evidence screen's reads over the evaluation's
    records, served beside the UI's own routes: no module of the UI imports the evaluation, and
    the routes are handed the comparison's own census and function here, since the server's
    import fence does not admit the comparison's module.
    """
    requirements.register(evaluation_requirements.REQUIREMENTS)
    table.register(evidence.routes(CENSUS))


def main(
    argv: Sequence[str] | None = None,
    registrations: orchestrator_cli.Registrations | None = None,
) -> int:
    """Entry point for the ``physgate`` command.

    ``registrations`` is for tests; the command itself runs with the orchestrator's
    default registrations.
    """
    compose()
    parser = argparse.ArgumentParser(prog="physgate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    hooks_cli.add_parser(subparsers)
    knowledge_cli.add_parser(subparsers)
    orchestrator_cli.add_parsers(subparsers, registrations)
    observe_cli.add_parsers(subparsers, registrations)
    inject_cli.add_parser(subparsers, registrations)
    per_role_cli.add_parser(subparsers)
    tierset_cli.add_parser(subparsers)
    gaps_cli.add_parser(subparsers)
    baseline_cli.add_parser(subparsers)
    ui_cli.add_parser(subparsers)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result
