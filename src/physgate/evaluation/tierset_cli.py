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
or why the record is refused. Never a flagged task's digest. Under ``settles``, each directory a
person settled (below), for a role that holds a version: its key, who, why and when, and its path
as given and as resolved then (``null`` on a line written before the paths were recorded), for a
person to find it by. And for the store, what only a split in
progress holds (pools, versions being written) and records of a session's work out of a role's
root, counted. Never a task id, a brief or a canary. It exits 1 if a version is refused or the
store holds a split's leftovers or work left; and if the store cannot be read, it prints one
refusal line (``store_unreadable``) instead and exits 1.

``--publish DIR`` also writes, for the operator UI's Evidence page, each role's current version
(its one ``fresh`` version) as that read found it, into the folder ``DIR``, one closed record per
role (:mod:`physgate.evaluation.tiers.published`): the version id, the three tiers' task counts,
the blind check's counts and source, an exposure word, whether it was measured, its state and
when it was read; or, where none or more than one version is fresh, a refusal word. It then
prints what it published, one JSON line, in place of the status. It exits 0 when every role is
published as read, or as having no fresh version (a role with no version yet is the normal state
of a new store); and 1 when a role is published as any other refusal (the store or a register
could not be read, a version is not what its manifest says, several versions are fresh, the read
failed), or when nothing is published (the folder is refused, or the files could not be written).
``DIR`` is a folder of its own, judged as the gap trend's publication judges one, not the gap
trend's folder and not beneath a withheld root; the UI's server is given it as a root and never
the store.

An exposure, read from the role's register as freshly scanned, marks a version's held-out tier
stale as well (``because``: ``exposed``); a register that cannot be read prints one refusal line
(``register_unreadable``) and exits 1.

Four commands write the register and the run roots, each only appending, and none takes a
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
  session, which can make a terminal of its own. It settles no directory: ``--settles`` is
  refused (``settles_is_its_own_command``), naming the command below.
- ``physgate tiers settle --withheld W --directory DIR --by NAME --reason TEXT`` settles a
  directory beneath the run roots that the register refuses because a record or a stream of it
  cannot be read: the person has looked at it, and what of it cannot be read is passed over
  from then on, for as long as it is the directory that was looked at. It marks no version (a
  version the person judges it may have shown is marked with ``mark-exposed``) and writes one
  line of its own: the directory's identity (a digest of its device and inode and of its
  parameters record, never its path; another directory made at the same path is not settled),
  who, why and when, and beside them, for a person, the directory's path as typed and as it
  resolved then (``tiers status`` lists them; nothing is matched by a path). It asks for a
  terminal as ``mark-exposed`` does, and is refused for a directory that lies outside every run
  root of the role (``settle_outside_the_run_roots``) and for one the register refuses nothing
  in, or nothing a settle passes over (``settle_refuses_nothing``).
- ``physgate tiers add-run-root --withheld W --path DIR`` adds a directory beneath which the
  role's runs are made; a measured run made anywhere else is refused. A directory the scan
  could not read whole, with the roots there already, is refused and nothing is appended.

Each prints one JSON line, and a refusal as ``refused_because`` with exit 1.

``physgate tiers check-target --path DIR`` is the check a launch calls on a round's prepared
target before the round starts: a trial prepared with the target's clone and not yet opened by
its decomposition's first record is walked whole by the register, so the target holds no
directory nested deeper than five beneath it (``target_too_deep``: the register would refuse
every reader, the trial's own ``decompose`` among them) and no file named ``run.json``,
``raw.json`` or ``params_source.json`` (``target_holds_a_record``: it would be read as a
record); and it holds nothing named ``knowledge``, in any case, at its top, where a
decomposition copies the planned roles' knowledge (``target_holds_role_knowledge``: a library
folder the target brought would be read in every run's worktree as another role's). It reads
nothing else and writes nothing; exit 0 when the target passes. The round driver does not call
it: the launch does, on the target the round clones from, before the round starts.

``physgate tiers practice --store S --implementer-model M [--seed N]`` builds, at the new
directory ``S``, a store holding one version of practice tasks written for a shakedown
(:mod:`physgate.evaluation.tiers.practice`): two control tasks to a tier, each labelled practice
in its brief and held to the split's entry checks, and a stand-in check record in the imported
form that flags none and names no session. It never reads another store. It prints the version
and its tiers' counts and digests on one JSON line, or ``refused_because`` with exit 1. It runs
in the evaluation environment, since each task's scorer is run on its references; elsewhere
it refuses (``evaluation_environment_missing``) and writes nothing. A shakedown on it then
registers a run root for the store (``physgate tiers add-run-root --withheld
S/control/withheld --path DIR``) before its harness runs, as every measured run's store needs.

``physgate tiers values-check --store S --role R --version V`` counts, for each tier of the
version, its tasks by what a session reading them is left without, from the brief alone and from
what a session is given now (:mod:`physgate.evaluation.tiers.issued_check`): a name of the
scorer's the brief writes with no value, a value it calls given with none, a value the scorer
takes by default. It prints one JSON line of counts, never a task id, a brief or a value, and
writes nothing; a version it cannot read is one ``refused_because`` line with exit 1.

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
    status_parser.add_argument("--publish", type=Path, help=_PUBLISH_HELP)
    status_parser.set_defaults(func=_status)
    writers = {
        "scan-exposures": "record the exposures the role's run roots hold",
        "mark-exposed": "mark a version exposed by hand, at a terminal",
        "settle": "settle by hand, at a terminal, a directory the register refuses",
        "add-run-root": "add a directory beneath which the role's runs are made",
    }
    for name, text in writers.items():
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--withheld", type=Path, required=True)
        if name == "mark-exposed":
            sub.add_argument("--version", required=True)
            sub.add_argument("--by", required=True)
            sub.add_argument("--reason", required=True)
            # No longer this command's: refused, naming the command that settles a directory.
            sub.add_argument("--settles", type=Path, help=argparse.SUPPRESS)
        elif name == "settle":
            # A directory beneath the run roots the register refuses, looked at by the person:
            # kept as typed, since the settle line says it so for a person.
            sub.add_argument("--directory", required=True)
            sub.add_argument("--by", required=True)
            sub.add_argument("--reason", required=True)
        elif name == "add-run-root":
            sub.add_argument("--path", type=Path, required=True)
        else:
            sub.add_argument("--roots", type=Path, nargs="+")
        sub.set_defaults(func=_write)
    target = commands.add_parser(
        "check-target", help="whether a round's prepared target lets the register read it whole"
    )
    target.add_argument("--path", type=Path, required=True)
    target.set_defaults(func=_check_target)
    probe = commands.add_parser(
        "probe", help="count what answers built for one requirement alone score on the held out"
    )
    probe.add_argument("--withheld", type=Path, required=True)
    probe.add_argument("--version", required=True)
    probe.add_argument("--seed", type=int, required=True)
    probe.set_defaults(func=_probe)
    practice = commands.add_parser(
        "practice", help="build a store holding one version of practice tasks, for a shakedown"
    )
    practice.add_argument("--store", type=Path, required=True)
    practice.add_argument("--implementer-model", dest="implementer_model", required=True)
    practice.add_argument("--seed", type=int)
    practice.set_defaults(func=_practice)
    launch = commands.add_parser(
        "launch-check",
        help="the machine's state a measured round may be launched on: each finding by name",
    )
    launch.add_argument("--store", type=Path, required=True)
    launch.add_argument(
        "--source", type=Path, required=True, help="the repository the trials are cloned from"
    )
    launch.add_argument(
        "--home", type=Path, help="the operator's home (the user's own if not given)"
    )
    launch.add_argument(
        "--also", type=Path, action="append", default=[], help="a further place a session reads"
    )
    launch.set_defaults(func=_launch_check)
    values = commands.add_parser(
        "values-check",
        help="count, for each tier of a version, the tasks that leave a session without a value",
    )
    values.add_argument("--store", type=Path, required=True)
    values.add_argument("--role", required=True, choices=_ROLES)
    values.add_argument("--version", required=True)
    values.set_defaults(func=_values_check)


#: The roles a version is counted for, said where the flag is listed.
_ROLES = ("control", "firmware", "whole_run")


#: What ``--publish`` takes, said where the flag is listed. Kept here, beside the parser, so the
#: command's help imports nothing of the tier machinery.
_PUBLISH_HELP = (
    "the folder to publish each role's current tier version into, for the operator UI's Evidence "
    "page: a folder of its own, not the gap trend's. Refused inside the store, beneath a role's "
    "withheld root, the harness checkout or any git checkout or worktree, a run's directory or a "
    "folder of runs, an installation, a review root, or the machine's shared temporary "
    "directories. This command is given no run, so it cannot know every place a run's sessions "
    "may read: publish into a folder of its own that no run names and nothing else writes, and "
    "give that folder to the operator UI as a root (physgate ui --root). Exits 0 when every role "
    "is published as read or as having no fresh version; 1 when a role is published as any other "
    "refusal, or when nothing is published."
)


def status(store: Path) -> dict[str, Any]:
    """Every version in ``store`` with its state, counts and digests; the leftovers, counted.

    Raises:
        OSError: the store, or a role's root in it, cannot be read.
        ExposureError: a role's register, its run roots or what they hold cannot be read whole.
    """
    from physgate.evaluation.tiers.authoring import TIERS
    from physgate.evaluation.tiers.checks import CheckError, counts, read_check
    from physgate.evaluation.tiers.exposure import ExposureError, exposure_sources, register_lines
    from physgate.evaluation.tiers.manifest import VERSION_NAME, TierSetError, read_version
    from physgate.evaluation.tiers.manifest import staleness as stale
    from physgate.evaluation.tiers.store import leftovers, role_root
    from physgate.evaluation.tiers.task import Role

    versions: list[dict[str, Any]] = []
    settles: list[dict[str, Any]] = []
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
            if names:
                # Each directory a person settled, with its path as they gave it and as it
                # resolved then: words for a person, never what settles (the key does).
                settles += [
                    {"role": role, **line.model_dump(mode="json", exclude={"n", "prev"})}
                    for line in register_lines(store, role)
                    if line.kind == "settle"
                ]
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
    return {"versions": versions, "settles": settles, "left": leftovers(store)}


#: The one refusal ``--publish`` exits 0 on: the role holds no fresh version, which is a state of
#: the store (a new store, or every version stale) and not a failure to read it.
_NO_FRESH_VERSION = "no_fresh_version"


def _publish(args: argparse.Namespace) -> int:
    """Publish each role's current version into ``--publish``; print what was published."""
    from physgate.evaluation.tiers.published import TierStatusError, publish_status

    try:
        records = publish_status(args.store.resolve(), out=args.publish)
    except TierStatusError as exc:
        reason = exc.context.get("refused_because", "publish_refused")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    said = [record.model_dump(mode="json") for record in records]
    print(json.dumps({"published": said}, sort_keys=True))
    # A role with no fresh version is a state of the store, not a failure to read it.
    failed = [r for r in said if r.get("refused", _NO_FRESH_VERSION) != _NO_FRESH_VERSION]
    return 1 if failed else 0


def _status(args: argparse.Namespace) -> int:
    from physgate.evaluation.tiers.exposure import ExposureError

    if args.publish is not None:
        return _publish(args)
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
    """One of the four writers of the role's register and run roots; one JSON line."""
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
        elif args.tiers_command in ("mark-exposed", "settle"):
            if args.tiers_command == "mark-exposed" and args.settles is not None:
                said = {
                    "refused_because": "settles_is_its_own_command",
                    "error": (
                        "a hand mark settles no directory, and a settle marks no version: "
                        f"{exposure.SETTLE_COMMAND}; then mark-exposed, without --settles, for "
                        "each version the directory may have shown"
                    ),
                }
                print(json.dumps(said, sort_keys=True))
                return 1
            # A second measure for a person, never what stops a session (which can make a
            # terminal of its own): the place does, beneath a root every run withholds.
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                said = {"refused_because": "not_at_a_terminal"}
                print(json.dumps(said, sort_keys=True))
                return 1
            if args.tiers_command == "settle":
                directory = Path(args.directory).absolute()
                exposure.settle_directory(
                    store,
                    args.role,
                    directory,
                    by=args.by,
                    reason=args.reason,
                    given=args.directory,
                )
                said = {"settled": str(directory)}
            else:
                exposure.mark_exposed(
                    store, args.role, args.version, by=args.by, reason=args.reason
                )
                said = {"marked": args.version}
        else:
            said = {"added": exposure.add_run_root(store, args.role, args.path)}
    except exposure.ExposureError as exc:
        reason = exc.context.get("refused_because", "refused")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(said, sort_keys=True))
    return 0


def _check_target(args: argparse.Namespace) -> int:
    """Whether a round's prepared target lets the register read the trial whole; one JSON line."""
    from physgate.evaluation.tiers.exposure import PREPARED_TARGET_DEPTH, prepared_target_refusal

    path = args.path.absolute()
    if path.is_symlink() or not path.is_dir():
        said = {"refused_because": "target_not_a_directory", "error": f"{path} is no directory"}
        print(json.dumps(said, sort_keys=True))
        return 1
    refused = prepared_target_refusal(path)
    if refused is not None:
        reason, words = refused
        print(json.dumps({"refused_because": reason, "error": words}, sort_keys=True))
        return 1
    checked: dict[str, Any] = {"checked": str(path), "deepest_allowed": PREPARED_TARGET_DEPTH}
    said = checked
    print(json.dumps(said, sort_keys=True))
    return 0


def _launch_check(args: argparse.Namespace) -> int:
    """Each finding of the launch check on its own line; non-zero where there is any."""
    from physgate.evaluation.launch_check import launch_findings

    found = launch_findings(
        store=args.store, source=args.source, home=args.home or Path.home(), also=args.also
    )
    for finding in found:
        print(finding.line())
    print(f"launch check: {len(found)} finding(s)" if found else "launch check: nothing found")
    return 1 if found else 0


def _values_check(args: argparse.Namespace) -> int:
    """The counts of one version's tasks by what they leave a session without; one JSON line."""
    from physgate.evaluation.tiers.issued_check import ValuesCheckError, value_counts

    try:
        said = value_counts(args.store.resolve(), args.role, args.version)
    except ValuesCheckError as exc:
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


def _practice(args: argparse.Namespace) -> int:
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.tiers.practice import SEED, build_practice_store, describe

    try:
        from physgate.evaluation.per_role.validate import sound
    except ImportError:
        said = {
            "refused_because": "evaluation_environment_missing",
            "error": (
                "the practice store's tasks are held to their scorer, in the evaluation "
                "environment: UV_PROJECT_ENVIRONMENT=.venv-evaluation uv run --group evaluation "
                "physgate ..."
            ),
        }
        print(json.dumps(said, sort_keys=True))
        return 1
    del sound
    try:
        manifest = build_practice_store(
            args.store.absolute(),
            implementer_model=args.implementer_model,
            seed=SEED if args.seed is None else args.seed,
        )
    except PerRoleError as exc:
        reason = exc.context.get("refused_because", "practice_refused")
        print(json.dumps({"refused_because": reason, "error": str(exc)}, sort_keys=True))
        return 1
    print(describe(manifest))
    return 0
