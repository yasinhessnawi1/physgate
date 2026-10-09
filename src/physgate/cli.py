"""The ``physgate`` command: hooks, orchestrator, observability, the instrument and the UI."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from physgate.evaluation.inject import cli as inject_cli
from physgate.evaluation.observe import cli as observe_cli
from physgate.hooks import cli as hooks_cli
from physgate.knowledge import cli as knowledge_cli
from physgate.orchestrator import cli as orchestrator_cli
from physgate.ui import cli as ui_cli


def main(
    argv: Sequence[str] | None = None,
    registrations: orchestrator_cli.Registrations | None = None,
) -> int:
    """Entry point for the ``physgate`` command.

    ``registrations`` is for tests; the command itself runs with the orchestrator's
    default registrations.
    """
    parser = argparse.ArgumentParser(prog="physgate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    hooks_cli.add_parser(subparsers)
    knowledge_cli.add_parser(subparsers)
    orchestrator_cli.add_parsers(subparsers, registrations)
    observe_cli.add_parsers(subparsers, registrations)
    inject_cli.add_parser(subparsers, registrations)
    ui_cli.add_parser(subparsers)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result
