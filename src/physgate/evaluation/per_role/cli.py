"""``physgate per-role``: the per-role evaluation's commands.

``physgate per-role controleval --cache C --out O [--category …] [--seed N]`` fetches the
public ControlEval categories at their pinned commit into ``C`` (outside the repository),
writes each task to ``O/<task id>/`` with a good reference and the bad ones that could be
built, holds the scorer to them, and writes one row per task to ``O/references.jsonl``
and a digest of every file to ``O/SHA256SUMS``. It exits 1 if any task lacks a good
reference or its references do not hold.

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
