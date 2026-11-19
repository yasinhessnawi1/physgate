"""``physgate tiers``: the tier-set store's commands.

The command is registered by the ``physgate`` command's composition root, so it lives beside
the tier machinery rather than in it: nothing outside the evaluation imports the machinery,
and this module reaches it only when a command runs.

``physgate tiers status --store S`` reads every version of every role in the store as every
reader reads it (its manifest held to the bytes on disk) and prints, for each, its state:
``fresh``, ``stale`` (which tiers, and why: a changed author brief or requirements source),
or ``refused`` (the version is not what its manifest says, and why). Beside each, the tiers'
counts and digests, the model, the seed and the date, and its blind check (``check``): the
record's counts (tasks, all three answers yes, flagged) and whether the check wrote it or it
was imported; ``null`` where the version has none, and so is not scored on its held-out tier;
or why the record is refused. Never a flagged task's digest. And for the store, what only a split in
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

- ``physgate tiers scan-exposures --withheld W [--roots DIR ...]`` records every exposure the
  role's run roots (or the ``--roots`` given, read in place of a run-roots log that may be
  broken) hold that the register does not, and prints the counts added and already recorded. A
  root that is gone, or that holds a link to a directory (not followed), is named and said in
  words, and the command exits 1.
- ``physgate tiers mark-exposed --withheld W --version V --by NAME --reason TEXT`` marks a
  version exposed by hand, for a read no hook sees: a person's. As a second measure for that
  person, it asks for a terminal (``not_at_a_terminal``) and a name; neither is what stops a
  session, which can make a terminal of its own.
- ``physgate tiers add-run-root --withheld W --path DIR`` adds a directory beneath which the
  role's runs are made; a measured run made anywhere else is refused. A directory the scan
  could not read whole, with the roots there already, is refused and nothing is appended.

Each prints one JSON line, and a refusal as ``refused_because`` with exit 1.

``physgate tiers probe --withheld W --version V --seed N`` is the isolation probe
(:mod:`physgate.evaluation.tiers.probe`): for each task of ``V``'s held-out tier and each
requirement it composes, an answer is built for that requirement alone by the seeded search and
scored on the task, and the counts are printed on one JSON line. It is one measurement of ``V``,
a line in the register, and like the writers it is given the role's withheld root and refuses
inside a session. It runs in the evaluation environment; elsewhere it refuses
(``evaluation_environment_missing``) and counts nothing. Whatever else goes wrong, it prints one
line naming why, never a traceback or an error's own words (``probe_failed``), since either may
name a held-out task.
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
        else:
            sub.add_argument("--roots", type=Path, nargs="+")
        sub.set_defaults(func=_write)
    probe = commands.add_parser(
        "probe", help="count what answers built for one requirement alone score on the held out"
    )
    probe.add_argument("--withheld", type=Path, required=True)
    probe.add_argument("--version", required=True)
    probe.add_argument("--seed", type=int, required=True)
    probe.set_defaults(func=_probe)


def status(store: Path) -> dict[str, Any]:
    """Every version in ``store`` with its state, counts and digests; the leftovers, counted.

    Raises:
        OSError: the store, or a role's root in it, cannot be read.
        ExposureError: a role's register, its run roots or what they hold cannot be read whole.
    """
    from physgate.evaluation.tiers.authoring import TIERS
    from physgate.evaluation.tiers.checks import CheckError, counts, read_check
    from physgate.evaluation.tiers.exposure import ExposureError, exposure_sources
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
        exposed: dict[str, frozenset[str]] = {}
        try:
            exposed = exposure_sources(store, role) if names else {}
        except ExposureError as exc:
            # Whether any version of the role was seen cannot be told: none reads as fresh.
            unread = exc.context.get("refused_because", "register_unreadable")
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
            check: dict[str, Any] | None
            try:
                record = read_check(store, role, name, manifest=manifest)
                check = None if record is None else counts(record)
            except CheckError as exc:
                check = {"refused_because": exc.context.get("refused_because", "unreadable")}
            if name in exposed:
                stale_tiers = sorted({*stale_tiers, "held_out"})
                # Nobody looked, apart from a confirmed read: both keep the version unmeasured.
                unchecked = exposed[name] == {"raw_record_unchecked"}
                because.append("exposed_unchecked" if unchecked else "exposed")
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
                    "check": check,
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
            roots = None if args.roots is None else [p.resolve() for p in args.roots]
            report = exposure.scan_exposures(store, args.role, roots)
            said = {
                "added": report.added,
                "already": report.already,
                "missing_roots": [str(p) for p in report.missing],
                "not_fully_read": [str(p) for p in report.unread],
                "unread_places": list(report.places),
            }
            if report.missing or report.unread:
                said["warning"] = (
                    "a run root is gone, holds a link to a directory the scan does not follow, "
                    "or holds a directory inside a run that looks like a run, which the scan "
                    "does not read: the runs there were not read, and their exposures are not "
                    "recorded"
                )
                print(json.dumps(said, sort_keys=True))
                return 1
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


def _probe(args: argparse.Namespace) -> int:
    """The isolation probe of one version's held-out tier; one JSON line."""
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers import probe

    said: dict[str, Any]
    try:
        method = probe.default_method()
    except ImportError:
        said = {
            "refused_because": "evaluation_environment_missing",
            "error": (
                "the probe runs the search and the scorer, in the evaluation environment: "
                "UV_PROJECT_ENVIRONMENT=.venv-evaluation uv run --group evaluation physgate ..."
            ),
        }
        print(json.dumps(said, sort_keys=True))
        return 1
    try:
        result = probe.probe_version(args.withheld, args.version, seed=args.seed, method=method)
        line = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    except PerRoleError as exc:
        # Every refusal's words are the probe's own, fixed, and name no task.
        reason = exc.context.get("refused_because", "refused")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    except Exception:
        # Neither a traceback nor the error's words: either may name a held-out task.
        print(
            json.dumps({"refused_because": "probe_failed", "error": probe.FAILED}, sort_keys=True)
        )
        return 1
    print(line)
    return 0
