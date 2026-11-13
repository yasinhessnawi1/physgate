"""``physgate tiers``: the tier-set store's commands.

The command is registered by the ``physgate`` command's composition root, so it lives beside
the tier machinery rather than in it: nothing outside the evaluation imports the machinery,
and this module reaches it only when a command runs.

``physgate tiers status --store S`` reads every version of every role in the store as every
reader reads it (its manifest held to the bytes on disk) and prints, for each, its state:
``fresh``, ``stale`` (which tiers, and why: a changed author brief or requirements source),
or ``refused`` (the version is not what its manifest says, and why). Beside each, the tiers'
counts and digests, the model, the seed and the date; and for the store, what only a split in
progress holds (pools, versions being written) and records of a session's work out of a role's
root, counted. Never a task id, a brief or a canary. It exits 1 if a version is refused or the
store holds a split's leftovers or work left; and if the store cannot be read, it prints one
refusal line (``store_unreadable``) instead and exits 1.

An exposure, read from the store's register, marks a version stale as well; the register is
read here once it exists.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, get_args


def add_parser(subparsers: Any) -> None:
    """Register ``physgate tiers`` and its subcommands."""
    parser = subparsers.add_parser("tiers", help="the tier-set store's versions and their state")
    commands = parser.add_subparsers(dest="tiers_command", required=True)
    status_parser = commands.add_parser("status", help="each version's state, counts and digests")
    status_parser.add_argument("--store", type=Path, required=True)
    status_parser.set_defaults(func=_status)


def status(store: Path) -> dict[str, Any]:
    """Every version in ``store`` with its state, counts and digests; the leftovers, counted.

    Raises:
        OSError: the store, or a role's root in it, cannot be read.
    """
    from physgate.evaluation.tiers.authoring import TIERS
    from physgate.evaluation.tiers.manifest import VERSION_NAME, TierSetError, read_version
    from physgate.evaluation.tiers.manifest import staleness as stale
    from physgate.evaluation.tiers.store import leftovers, role_root
    from physgate.evaluation.tiers.task import Role

    versions: list[dict[str, Any]] = []
    for role in get_args(Role):
        root = role_root(store, role)
        names = (
            sorted(p.name for p in root.iterdir() if VERSION_NAME.fullmatch(p.name))
            if (root.is_dir())
            else []
        )
        for name in names:
            try:
                manifest = read_version(root / name)
            except TierSetError as exc:
                versions.append(
                    {
                        "role": role,
                        "version": name,
                        "state": "refused",
                        "because": [exc.context.get("refused_because", "unreadable")],
                    }
                )
                continue
            found = stale(manifest)
            versions.append(
                {
                    "role": role,
                    "version": name,
                    "state": "stale" if found.tiers else "fresh",
                    "stale_tiers": list(found.tiers),
                    "because": list(found.because),
                    "tiers": {t: manifest.tier(t).model_dump(mode="json") for t in TIERS},
                    "model": manifest.model,
                    "seed": manifest.seed,
                    "generated": manifest.generated,
                }
            )
    return {"versions": versions, "left": leftovers(store)}


def _status(args: argparse.Namespace) -> int:
    store = args.store.resolve()
    try:
        found = status(store)
    except OSError as exc:
        refusal = {"refused_because": "store_unreadable", "store": str(store), "error": str(exc)}
        print(json.dumps(refusal, sort_keys=True))
        return 1
    print(json.dumps(found, sort_keys=True))
    refused = any(v["state"] == "refused" for v in found["versions"])
    return 1 if refused or any(found["left"].values()) else 0
