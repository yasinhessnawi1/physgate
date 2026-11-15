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

An exposure, read from the role's register as freshly scanned, marks a version's held-out tier
stale as well (``because``: ``exposed``); a register that cannot be read prints one refusal line
(``register_unreadable``) and exits 1.

Three commands write the register and the run roots, each only appending, and none takes a
line away: nothing unmarks a version. Each is given the role's withheld root itself
(``--withheld <store>/<role>/withheld``), where both logs lie. That is what holds a session
off: every run on the role withholds that root, so its hooks refuse a command naming it and
its OS layer denies a write beneath it, whatever started the write. Each writer also refuses
inside a harness session's environment, as defence in depth only.

- ``physgate tiers scan-exposures --withheld W`` records every exposure the role's run roots
  hold that the register does not, and prints the counts added and already recorded.
- ``physgate tiers mark-exposed --withheld W --version V --by NAME --reason TEXT`` marks a
  version exposed by hand, for a read no hook sees: a person's. As a second measure for that
  person, it asks for a terminal (``not_at_a_terminal``) and a name; neither is what stops a
  session, which can make a terminal of its own.
- ``physgate tiers add-run-root --withheld W --path DIR`` adds a directory beneath which the
  role's runs are made; a measured run made anywhere else is refused. A directory the scan
  could not read whole, with the roots there already, is refused and nothing is appended.

Each prints one JSON line, and a refusal as ``refused_because`` with exit 1.
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
    writers = {
        "scan-exposures": "record the exposures the role's run roots hold",
        "mark-exposed": "mark a version exposed by hand, at a terminal",
        "add-run-root": "add a directory beneath which the role's runs are made",
    }
    for name, text in writers.items():
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--withheld", type=Path, required=True)
        if name == "mark-exposed":
            sub.add_argument("--version", required=True)
            sub.add_argument("--by", required=True)
            sub.add_argument("--reason", required=True)
        elif name == "add-run-root":
            sub.add_argument("--path", type=Path, required=True)
        sub.set_defaults(func=_write)


def status(store: Path) -> dict[str, Any]:
    """Every version in ``store`` with its state, counts and digests; the leftovers, counted.

    Raises:
        OSError: the store, or a role's root in it, cannot be read.
        ExposureError: a role's register, its run roots or what they hold cannot be read whole.
    """
    from physgate.evaluation.tiers.authoring import TIERS
    from physgate.evaluation.tiers.exposure import ExposureError, exposed_versions
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
        unread: str | None = None
        try:
            exposed = exposed_versions(store, role) if names else frozenset()
        except ExposureError as exc:
            # Whether any version of the role was seen cannot be told: none reads as fresh.
            exposed, unread = frozenset(), exc.context.get("refused_because", "register_unreadable")
        for name in names:
            why = unread
            try:
                manifest = read_version(root / name)
            except TierSetError as exc:
                why = exc.context.get("refused_because", "unreadable")
            if why is not None:
                versions.append(
                    {"role": role, "version": name, "state": "refused", "because": [why]}
                )
                continue
            found = stale(manifest)
            stale_tiers, because = list(found.tiers), list(found.because)
            if name in exposed:
                stale_tiers = sorted({*stale_tiers, "held_out"})
                because.append("exposed")
            versions.append(
                {
                    "role": role,
                    "version": name,
                    "state": "stale" if stale_tiers else "fresh",
                    "stale_tiers": stale_tiers,
                    "because": because,
                    "tiers": {t: manifest.tier(t).model_dump(mode="json") for t in TIERS},
                    "model": manifest.model,
                    "seed": manifest.seed,
                    "generated": manifest.generated,
                }
            )
    return {"versions": versions, "left": leftovers(store)}


def _status(args: argparse.Namespace) -> int:
    from physgate.evaluation.tiers.exposure import ExposureError

    store = args.store.resolve()
    try:
        found = status(store)
    except OSError as exc:
        refusal = {"refused_because": "store_unreadable", "store": str(store), "error": str(exc)}
        print(json.dumps(refusal, sort_keys=True))
        return 1
    except ExposureError as exc:
        reason = exc.context.get("refused_because", "register_unreadable")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(found, sort_keys=True))
    refused = any(v["state"] == "refused" for v in found["versions"])
    return 1 if refused or any(found["left"].values()) else 0


def _write(args: argparse.Namespace) -> int:
    """One of the three writers of the role's register and run roots; one JSON line."""
    import sys

    from physgate.evaluation.tiers import exposure
    from physgate.evaluation.tiers.store import WITHHELD
    from physgate.evaluation.tiers.task import Role

    withheld = args.withheld.resolve()
    store, role = withheld.parent.parent, withheld.parent.name
    said: dict[str, Any]
    if withheld.name != WITHHELD or role not in get_args(Role):
        print(json.dumps({"refused_because": "not_a_withheld_root"}, sort_keys=True))
        return 1
    args.role = role
    try:
        if args.tiers_command == "scan-exposures":
            added, already = exposure.record_scan(store, args.role)
            said = {"added": added, "already": already}
        elif args.tiers_command == "mark-exposed":
            # A second measure for a person, never what stops a session (which can make a
            # terminal of its own): the place does, beneath a root every run withholds.
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                said = {"refused_because": "not_at_a_terminal"}
                print(json.dumps(said, sort_keys=True))
                return 1
            exposure.mark_exposed(store, args.role, args.version, by=args.by, reason=args.reason)
            said = {"marked": args.version}
        else:
            said = {"added": exposure.add_run_root(store, args.role, args.path)}
    except exposure.ExposureError as exc:
        reason = exc.context.get("refused_because", "refused")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(said, sort_keys=True))
    return 0
