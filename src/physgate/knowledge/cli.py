"""``physgate knowledge promote``: a human, at a terminal, moves one candidate into the library.

The one place the OS username is read for a default: a person running this
at their own terminal is exactly who `getpass.getuser()` names, and the flag
exists only so they can name someone else instead, never to skip naming
anyone.
"""

from __future__ import annotations

import argparse
import getpass

from physgate.knowledge.promote import PromotionError, promote
from physgate.knowledge.standards_lint import main as _lint_main


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``knowledge promote``/``knowledge list-unmarked-rules`` on the top-level command."""
    knowledge = subparsers.add_parser("knowledge", help="the knowledge layer")
    actions = knowledge.add_subparsers(dest="action", required=True)
    p = actions.add_parser("promote", help="move one staged candidate into the library")
    p.add_argument("candidate_id", help="the candidate's id, as staged under knowledge/staging/")
    p.add_argument("--by", help="who is approving this; defaults to the current OS user")
    p.set_defaults(func=_promote)
    lint = actions.add_parser(
        "list-unmarked-rules",
        help="list every numbered rule in a promoted standards.md naming no enforcement",
    )
    lint.set_defaults(func=_list_unmarked_rules)


def _list_unmarked_rules(args: argparse.Namespace) -> int:  # noqa: ARG001
    return _lint_main([])


def _promote(args: argparse.Namespace) -> int:
    by = args.by or getpass.getuser()
    try:
        destination = promote(args.candidate_id, by=by)
    except PromotionError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"promoted {args.candidate_id} to {destination}, approved by {by}")
    return 0
