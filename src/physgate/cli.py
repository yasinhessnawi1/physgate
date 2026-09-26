"""The ``physgate`` command: the hook layer's and the orchestrator's subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from physgate.hooks import cli as hooks_cli
from physgate.orchestrator import cli as orchestrator_cli


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
    orchestrator_cli.add_parsers(subparsers, registrations)
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result
