"""``physgate gaps``: the two gaps, and the vector writer that feeds them.

Registered by the ``physgate`` command's composition root, beside the gap machinery rather than
in it: this module reaches the machinery only when a command runs.

- ``physgate gaps --design D --runs R --trials T --held-out H [--validation W] [--append TREND]``
  computes both gaps of the design's role and arm from the visible tier's run set ``R`` and
  trial records ``T`` and the protected tiers' vectors ``H`` and ``W``, and prints one JSON line:
  each tier's count, both gaps with their intervals, notes in words, the harness commits and
  the accounts. ``--append`` adds the line to the gap trend at ``TREND``; it writes nothing to
  the register.
- ``physgate gaps trend --store S --role R --trend T [--publish DIR]`` reads the role's trend
  with its one reader and prints it as the Evidence page shows it: every week through today, or
  the reader's refusal (exit 1). ``--publish`` also writes that, whole, into the folder ``DIR``,
  which the UI's server is then given as a root: the server cannot run the reader, whose head and
  register lie beneath the role's withheld root. ``DIR`` is refused in any place the harness
  knows a run's sessions, a reviewer or a commit reach; the command is given no run, so it
  cannot know every such place, and its help says which folder to name.
- ``physgate gaps vector --withheld W --version V --tier T --runs R --trials T`` is the harness
  side's step for a protected tier: it counts one measurement of ``V`` in the register and writes
  the tier's anonymous vector beneath ``W``, the role's withheld root, and prints its key. Its
  run set and records lie beneath ``W`` too. What holds a session off is that place, which every
  run on the role withholds; it also refuses inside a session's environment.

A refusal is one JSON line with ``refused_because`` and the reason in words, and exit 1.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def add_parser(subparsers: Any) -> None:
    """Register ``physgate gaps``, ``physgate gaps vector`` and ``physgate gaps trend``."""
    parser = subparsers.add_parser("gaps", help="the two gaps, their counts and their trend")
    parser.add_argument("--design", type=Path)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--trials", type=Path)
    parser.add_argument("--held-out", dest="held_out", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--append", type=Path)
    parser.set_defaults(func=_gaps)
    commands = parser.add_subparsers(dest="gaps_command")
    vector = commands.add_parser("vector", help="write a protected tier's anonymous vector")
    vector.add_argument("--withheld", type=Path, required=True)
    vector.add_argument("--version", required=True)
    vector.add_argument("--tier", required=True)
    # Named apart from the parent's own flags, which argparse would otherwise share.
    vector.add_argument("--runs", dest="vector_runs", type=Path, required=True)
    vector.add_argument("--trials", dest="vector_trials", type=Path, required=True)
    vector.set_defaults(func=_vector)
    trend = commands.add_parser("trend", help="read the gap trend, and publish it for the page")
    trend.add_argument("--store", type=Path, required=True)
    trend.add_argument("--role", required=True, choices=("control", "firmware"))
    trend.add_argument("--trend", dest="trend_path", type=Path, required=True)
    trend.add_argument("--publish", type=Path, help=_PUBLISH_HELP)
    trend.set_defaults(func=_trend)


#: What ``--publish`` takes, said where the flag is listed. Kept here, beside the parser, so the
#: command's help imports nothing of the gap machinery.
_PUBLISH_HELP = (
    "the folder to publish the trend into, for the operator UI's Evidence page. Refused inside "
    "the store, the harness checkout or any git checkout or worktree, a run's directory or a "
    "folder of runs, an installation, a review root, or the machine's shared temporary "
    "directories. This command is given no run, so it cannot know every place a run's sessions "
    "may read: publish into a folder of its own that no run names and nothing else writes, and "
    "give that folder to the operator UI as a root (physgate ui --root)."
)


def _refused(exc: Exception) -> int:
    context = getattr(exc, "context", {})
    said = {"refused_because": context.get("refused_because", "refused"), "error": str(exc)}
    print(json.dumps(said, sort_keys=True))
    return 1


def _gaps(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from physgate.evaluation.gaps.measure import GapsDesign, append_gap_line, measure
    from physgate.evaluation.per_role.exceptions import PerRoleError

    missing = [
        flag
        for flag, value in (
            ("--design", args.design),
            ("--runs", args.runs),
            ("--trials", args.trials),
            ("--held-out", args.held_out),
        )
        if value is None
    ]
    if missing:
        usage = {"refused_because": "usage", "error": f"gaps needs {', '.join(missing)}"}
        print(json.dumps(usage, sort_keys=True))
        return 1
    try:
        design = GapsDesign.model_validate_json(Path(args.design).read_bytes())
    except (OSError, ValidationError) as exc:
        unread = {"refused_because": "design_unreadable", "error": type(exc).__name__}
        print(json.dumps(unread, sort_keys=True))
        return 1
    try:
        found = measure(
            design,
            runs=args.runs,
            trials=args.trials,
            held_out=args.held_out,
            validation=args.validation,
        )
        if args.append is not None:
            append_gap_line(args.append, found)
    except PerRoleError as exc:
        return _refused(exc)
    numbers = found.numbers.model_dump(mode="json")
    said: dict[str, Any] = {
        "role": found.role,
        "arm": "harness",
        "version": found.version,
        **numbers,
        "notes": list(found.notes),
        "harness_commits": list(found.harness_commits),
        "accounts": list(found.accounts),
        "measurements": found.measurements,
        "keys": found.keys,
        "manifest_ids": list(found.manifest_ids),
        "appended": args.append is not None,
    }
    print(json.dumps(said, sort_keys=True))
    return 0


def _vector(args: argparse.Namespace) -> int:
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers.measure import write_vector

    try:
        key = write_vector(
            args.withheld,
            version=args.version,
            tier=args.tier,
            runs=args.vector_runs,
            trials=args.vector_trials,
        )
    except PerRoleError as exc:
        return _refused(exc)
    print(json.dumps({"key": key}, sort_keys=True))
    return 0


def _trend(args: argparse.Namespace) -> int:
    from physgate.evaluation.gaps.published import publish_trend, read_for_publication
    from physgate.evaluation.per_role.exceptions import PerRoleError

    try:
        if args.publish is not None:
            path = publish_trend(
                args.trend_path, store=args.store, role=args.role, out=args.publish
            )
            record = path.read_bytes().decode().strip()
        else:
            found = read_for_publication(args.trend_path, store=args.store, role=args.role)
            record = found.model_dump_json()
    except PerRoleError as exc:
        return _refused(exc)
    print(record)
    return 0 if json.loads(record)["refused"] is None else 1
