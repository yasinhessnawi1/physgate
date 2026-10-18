"""``physgate per-role``: the per-role evaluation's commands.

``physgate per-role controleval --cache C --out O [--category …] [--seed N]`` fetches the
public ControlEval categories at their pinned commit into ``C`` (outside the repository),
writes each task to ``O/<task id>/`` with a good reference and the bad ones that could be
built, holds the scorer to them, and writes one row per task to ``O/references.jsonl``
and a digest of every file to ``O/SHA256SUMS``. It exits 1 if any task lacks a good
reference or its references do not hold.

``physgate per-role validate --tier D [--tasks N] [--show-ids]`` holds every task in the
tier ``D`` to its references and its brief to the answer-leak check, and prints only
counts, the digest of each task's id and the tier's digest, so a tier can be approved
without being read. ``--show-ids`` prints the ids themselves, only where every task in the
tier is a visible one. It exits 1 if a task is refused, a brief gives its answer away, or
the tier does not hold ``N`` tasks.

``physgate per-role report --design D --trials T [--out O]`` writes the per-role table of
the trial records in ``T`` (one JSON object per line) under the registered design ``D``,
to ``O`` or the standard output. It exits 1, writing nothing, if the records are not every
trial the design registered, once each, or a published number lacks its record.

The scorer's numerical libraries are the evaluation group's, which the hooks' own
installation does not carry; so this module imports them only when a command runs, and
the ``physgate`` command loads without them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

CATEGORY_CHOICES = ("second_order_unstable", "higher_order", "first_order_w_delay")


def add_parser(subparsers: Any) -> None:
    """Register ``physgate per-role`` and its subcommands."""
    parser = subparsers.add_parser("per-role", help="per-role evaluation tasks and references")
    commands = parser.add_subparsers(dest="per_role_command", required=True)
    ce = commands.add_parser("controleval", help="fetch ControlEval and build its references")
    ce.add_argument("--cache", type=Path, required=True)
    ce.add_argument("--out", type=Path, required=True)
    ce.add_argument("--category", action="append", choices=CATEGORY_CHOICES)
    ce.add_argument("--seed", type=int, default=0)
    ce.set_defaults(func=_controleval)
    val = commands.add_parser("validate", help="check a tier without reading it out")
    val.add_argument("--tier", type=Path, required=True)
    val.add_argument("--tasks", type=int, default=8)
    val.add_argument("--show-ids", action="store_true")
    val.set_defaults(func=_validate)
    rep = commands.add_parser("report", help="the per-role table of a run's trial records")
    rep.add_argument("--design", type=Path, required=True)
    rep.add_argument("--trials", type=Path, required=True)
    rep.add_argument("--out", type=Path)
    rep.set_defaults(func=_report)


def sha256sums(root: Path) -> str:
    """One ``<digest>  <path>`` line per file under ``root``, sorted by path."""
    lines = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS"):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    return "\n".join(lines) + "\n"


def _controleval(args: argparse.Namespace) -> int:
    from physgate.evaluation.per_role import controleval
    from physgate.evaluation.per_role.synthesise import prepare

    categories = args.category or list(CATEGORY_CHOICES)
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for category in categories:
        tasks = controleval.category_tasks(category, controleval.fetch(category, args.cache))
        rows.extend(prepare(tasks, args.out, seed=args.seed))
    with (args.out / "references.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (args.out / "SHA256SUMS").write_text(sha256sums(args.out), encoding="utf-8")
    missing = [row["task"] for row in rows if not row["checked"]]
    print(
        json.dumps(
            {"tasks": len(rows), "checked": len(rows) - len(missing), "not_checked": missing}
        )
    )
    if missing:
        print(f"{len(missing)} task(s) without a held reference set", file=sys.stderr)
        return 1
    return 0


def _report(args: argparse.Namespace) -> int:
    from physgate.evaluation.per_role.report import (
        ReportError,
        parse_design,
        parse_trials,
        render,
    )

    try:
        design = parse_design(args.design.read_bytes())
        records = parse_trials(args.trials.read_text(encoding="utf-8").splitlines())
        text = render(design, records)
    except ReportError as exc:
        print(f"no report: {exc}", file=sys.stderr)
        return 1
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8")
    return 0


def _validate(args: argparse.Namespace) -> int:
    from physgate.evaluation.per_role.validate import validate

    found = validate(args.tier, show_ids=args.show_ids)
    print(json.dumps(found, sort_keys=True))
    whole = found["tasks"] == args.tasks == found["references_held"]
    return 0 if whole and not found["refused"] and not found["brief_gives_the_answer"] else 1
