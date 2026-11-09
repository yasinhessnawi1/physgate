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

``physgate per-role author --role control --store S --work W --seed N`` runs one authoring
session on ``--model`` (never the implementers' model), withholding the role's root
``S/<role>``, pools the tasks that hold there, and once twenty-four are pooled writes them as
a new version ``S/<role>/<version>/`` (visible, validation and held-out tiers, each of eight,
and the manifest); it prints counts, the version id, the visible ids and the protected tiers'
digests only. ``physgate per-role blind-check --role control --store S --version V --work W``
runs the blind yes/no check on that version's held-out tier and prints counts and the digests
of flagged tasks only. Both read the credential from the environment variable its auth mode
names, refuse where the OS layer is absent, and call a model unless ``--endpoint`` names a
scripted one.

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
    for name, func, text in (
        ("author", _author, "run one authoring session and split its tasks into tiers"),
        ("blind-check", _blind_check, "run the blind yes/no check on a held-out tier"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--role", choices=("control",), required=True)
        # The tier-set store: the session withholds the role's root in it.
        sub.add_argument("--store", type=Path, required=True)
        sub.add_argument("--withhold", type=Path, action="append", default=[])
        # Outside every protected root. The author works there; the blind check works under
        # the role's work root in the store, and only its hook installation is put here.
        sub.add_argument("--work", type=Path, required=True)
        sub.add_argument("--model", default="claude-sonnet-5")
        sub.add_argument("--implementer-model", default="claude-opus-5-5")
        sub.add_argument("--auth", choices=("subscription", "api_key"), default="subscription")
        sub.add_argument("--endpoint")
        sub.add_argument("--claude-version", default="2.1.301")
        sub.add_argument("--cap", type=int, required=True)
        # A role session's bounds; the session gets them times the harness's repair
        # budget, as the raw arm does. An author writing a tier's worth of tasks with
        # their references outlasts a role session's defaults.
        sub.add_argument("--session-wall-clock-s", type=float, default=1800.0)
        sub.add_argument("--session-max-turns", type=int, default=150)
        # How often the binary retries a failed request before the session ends with an
        # error. One long session is lost whole to a dropped connection unless the
        # binary retries; the token cap holds whatever the count.
        sub.add_argument("--binary-max-retries", type=int, default=0)
        if name == "author":
            # The interpreter the arms' sessions get, with the scorer's libraries: the
            # author computes with them, though the scorer itself is never given.
            sub.add_argument("--role-python", required=True)
            sub.add_argument("--seed", type=int, required=True)
            sub.add_argument("--count", type=int, default=24)
            # The session is stopped once this many tokens pass without a new task
            # holding (an eighth of the cap when not given), and when no task holds after
            # a quarter of the cap. Tasks that hold are pooled in the role's root across
            # sessions; a version is cut once twenty-four are pooled.
            sub.add_argument("--per-task-cap", type=int)
            # What every id this session writes begins with, so sessions pooled together
            # never write the same id. When not given: "b<n>." with n the number of
            # authoring sessions already recorded under the role's root, plus one.
            sub.add_argument("--id-prefix")
        else:
            sub.add_argument("--version", required=True)
        sub.set_defaults(func=func)
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


#: The checkout this command runs from: its hooks are copied for the session to run.
CHECKOUT = Path(__file__).resolve().parents[4]


def session_held_out(args: argparse.Namespace) -> tuple[str, ...]:
    """What the command's session withholds.

    An author withholds the role's whole root. A blind check works in a directory of its
    own under the role's work root (``args.check_work``), so it withholds all of the role's
    root but that directory (:func:`.tiers.store.check_roots`).
    """
    from physgate.evaluation.tiers.store import check_roots, role_root

    store = args.store.resolve()
    if getattr(args, "func", None) is _blind_check:
        return tuple(str(p) for p in check_roots(store, args.role, args.check_work))
    return (str(role_root(store, args.role)),)


def _session_setup(args: argparse.Namespace, install: Path) -> Any:
    """A session's pins, as a role session's: the pinned binary, the OS layer, offline."""
    import os

    from physgate.evaluation.per_role.arms.raw import RawSetup
    from physgate.orchestrator.credentials import credential_for
    from physgate.orchestrator.decompose import binary_version
    from physgate.orchestrator.install import prepare_install
    from physgate.orchestrator.invocation import claude_binary, session_search_path
    from physgate.orchestrator.run_config import RunBounds
    from physgate.oslayer.probe import Absent, judge_here

    binary = claude_binary()
    version = binary_version(binary)
    if version != args.claude_version:
        msg = f"the binary is {version}, not the pinned {args.claude_version}"
        raise SystemExit(msg)
    layer = judge_here(claude_version=version, search_path=session_search_path(binary))
    if isinstance(layer, Absent):
        msg = f"the OS layer is absent here ({layer.reason}); a held-out tier is never made so"
        raise SystemExit(msg)
    return RawSetup(
        binary=binary,
        claude_version=version,
        model=args.model,
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        bounds=RunBounds(
            binary_max_retries=args.binary_max_retries,
            session_wall_clock_s=args.session_wall_clock_s,
            session_max_turns=args.session_max_turns,
            infra_retry_delays_s=(),
        ),
        credential=credential_for(args.auth, os.environ),
        base_url=args.endpoint,
        install_bin=prepare_install(install / "hooks", CHECKOUT),
        role_python=_role_python(getattr(args, "role_python", None)),
        held_out=session_held_out(args),
        withheld_reads=tuple(str(p.resolve()) for p in args.withhold),
        # Each command gives the session every canary under its root (``root_canaries``).
        held_out_canaries=(),
        network="none",
        os_layer=layer,
    )


def _role_python(path: str | None) -> Any:
    """The named interpreter, measured as a run's role sessions' is; ``None`` if unnamed."""
    if path is None:
        return None
    from physgate.orchestrator.dispatch import probe_interpreter
    from physgate.orchestrator.role_python import measure

    return measure(path, probe=probe_interpreter, harness=CHECKOUT)


def _with_install(args: argparse.Namespace, run: Any) -> int:
    import os
    import shutil

    install = args.work.parent / f"{args.work.name}.install"

    def writable_again(function: Any, path: str, _exc: BaseException) -> None:
        # The installation is made read-only; its owner makes each place writable to remove it.
        os.chmod(os.path.dirname(path), 0o700)
        if os.path.lexists(path) and not os.path.islink(path):
            os.chmod(path, 0o700)
        function(path)

    try:
        result = run(_session_setup(args, install))
    finally:
        if install.exists():
            shutil.rmtree(install, onexc=writable_again)
    print(json.dumps(result, sort_keys=True))
    status = result.get("status", "split")
    if status == "split" and result.get("answered", True):
        return 0
    # Tasks were pooled and the tiers are not cut yet: a further session is wanted.
    return 2 if status == "pooled" else 1


def _author(args: argparse.Namespace) -> int:
    import dataclasses

    from physgate.evaluation.per_role.author_session import AuthoringPlan, author, root_canaries
    from physgate.evaluation.tiers.store import author_evidence, role_root

    # The paths given are resolved once, before anything runs, so a system link such as
    # macOS's /var is followed here and never met by the split's refusal of links.
    store = args.store.resolve()
    root = role_root(store, args.role)
    prefix = args.id_prefix
    if prefix is None:
        evidence = author_evidence(store, args.role)
        recorded = sum(1 for p in evidence.iterdir() if p.is_dir()) if evidence.is_dir() else 0
        prefix = f"b{recorded + 1}."
    plan = AuthoringPlan(
        role=args.role,
        implementer_model=args.implementer_model,
        work=args.work.resolve(),
        store=store,
        seed=args.seed,
        cap=args.cap,
        count=args.count,
        per_task_cap=args.per_task_cap,
        id_prefix=prefix,
    )
    # Every canary the tiers already cut under the root name: the session's record says
    # whether one showed in its stream, and the runner refuses a session not looking.
    canaries = root_canaries(root)
    return _with_install(
        args,
        lambda setup: author(plan, dataclasses.replace(setup, held_out_canaries=canaries)),
    )


def _blind_check(args: argparse.Namespace) -> int:
    import dataclasses
    import secrets

    from physgate.evaluation.per_role.author_session import blind_check, root_canaries
    from physgate.evaluation.tiers.store import role_root, work_root

    store = args.store.resolve()
    args.work = args.work.resolve()
    # Its copy of the held-out tasks lies in the store, where every run withholds it.
    work = work_root(store, args.role) / f"check-{secrets.token_hex(8)}"
    args.check_work = work
    # As the author's: the check looks for every canary the root's tiers name, and its
    # answer is not taken unless its record says none showed.
    canaries = root_canaries(role_root(store, args.role))
    return _with_install(
        args,
        lambda setup: blind_check(
            store,
            args.role,
            args.version,
            dataclasses.replace(setup, held_out_canaries=canaries),
            work,
            implementer_model=args.implementer_model,
            cap=args.cap,
        ),
    )
