"""``physgate baseline run``: the raw arm on every trial of a harness run set, over a tier version.

``physgate baseline run --store S --role control --version V --runs R --out O --prices DATE``
reads the harness run set ``R`` (``{"format": 1, "trials": [{"run_dir": …, "trial": n}]}``),
finds each run's task in the version ``V`` of the store ``S`` by the brief the run was given,
and runs the raw arm on it under the run's own recorded pins, capped at the run's total. It
writes the round's records under the new directory ``O`` and prints the round's record: counts
and digests only. ``--development`` holds the round to harness runs that need not be
reportable; the record says so. The endpoint is ``ANTHROPIC_BASE_URL``, or the binary's
default, as for every other command, and every harness run must have recorded it; the
credential is read from the environment variable the run's auth mode names, after every
entry has been checked. It exits 1, naming no task, if the round is refused or stopped.

A round waits, as the harness round driver's does, and the command returns at once: 75 while
it waits for the account's usage limit to reset, 77 while it waits for a person (a refused
credential to replace). It prints one line, ``status`` and ``waiting`` (the entry by its place
in the run set, why, and for the limit ``resume_after``, the instant after which it goes on, and
``word_helps``), and writes the same into ``O/round.json``. ``--resume`` goes on with the round
``O`` holds, given the same inputs: before ``resume_after`` it makes nothing, writes nothing and
exits 75 again. ``--limit-reset`` is a person's word that the limit has reset, used once and only
where the client's stream gave no reset; a round that waits for no limit refuses it. A wrapper
sleeps until ``resume_after`` between starts and never puts the word in a loop.
``--external DIR`` in place of ``--version`` runs the round on an external task set (one
benchmark's published tasks, each ``DIR/<id>/task.json``), kept apart from the store's tiers.

``physgate baseline audit --store S --role control --version V --runs R --out O --prices DATE
[--harness TIER RUNS TRIALS ...]`` is the record audit of a cell
(:mod:`physgate.evaluation.baseline.audit`): every record the baseline round in ``O`` wrote, and
every harness trial record named by ``--harness`` (a tier, its run set and its trial records, as
the harness round writes them), is derived again from its trial's own files and compared. It
prints one JSON line: of a visible tier each difference by kind and the trial's place in its run
set, of a protected tier only how many of each kind, and the digest of the whole detail, which is
written beneath the role's withheld root. It exits 0 when nothing differs, 1 when anything does,
and 2 with ``refused_because`` when the audit cannot be made.

The scorer's numerical libraries are the evaluation group's; they are imported only when the
command runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: The checkout this command runs from: its hooks are copied for each session to run.
CHECKOUT = Path(__file__).resolve().parents[4]


def add_parser(subparsers: Any) -> None:  # noqa: ANN401 - argparse's private subparsers type
    """Register ``physgate baseline`` and its one command."""
    parser = subparsers.add_parser("baseline", help="the raw coding agent the harness is held to")
    commands = parser.add_subparsers(dest="baseline_command", required=True)
    run = commands.add_parser("run", help="run the raw arm on a harness run set's trials")
    run.add_argument("--store", type=Path, required=True)
    run.add_argument("--role", choices=("control",), required=True)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--version", help="the store's tier version the harness runs ran on")
    source.add_argument(
        "--external", type=Path, help="an external task set's directory, kept apart from the tiers"
    )
    run.add_argument("--runs", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--prices", required=True, help="the dated price sheet the harness used")
    run.add_argument("--development", action="store_true")
    run.add_argument("--resume", action="store_true", help="go on with the round OUT holds")
    run.add_argument(
        "--limit-reset",
        dest="limit_reset",
        action="store_true",
        help=(
            "say that the account's usage limit has reset, for the wait the round stands at; "
            "exit 75 is not a wait: sleep until the printed resume_after between starts, and "
            "never loop this word"
        ),
    )
    run.set_defaults(func=_run)
    audit = commands.add_parser("audit", help="re-derive every record of a cell and compare")
    audit.add_argument("--store", type=Path, required=True)
    audit.add_argument("--role", choices=("control",), required=True)
    audit.add_argument("--version", required=True)
    audit.add_argument("--runs", type=Path, required=True)
    audit.add_argument("--out", type=Path, required=True)
    audit.add_argument("--prices", required=True)
    audit.add_argument("--development", action="store_true")
    audit.add_argument(
        "--harness",
        nargs=3,
        action="append",
        default=[],
        metavar=("TIER", "RUNS", "TRIALS"),
        help="a tier of the harness arm's cell: its run set and its trial records",
    )
    audit.set_defaults(func=_audit)


def _run(args: argparse.Namespace) -> int:
    import os
    import shutil

    from physgate.evaluation.baseline.runner import (
        BaselineError,
        RoundWaits,
        RunSet,
        run_baseline,
    )
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.per_role.scorers.control import score
    from physgate.orchestrator.install import prepare_install

    out = args.out.resolve()
    install = out.with_name(f"{out.name}.install")

    def writable_again(function: Any, path: str, _exc: BaseException) -> None:  # noqa: ANN401
        # The installation is made read-only; its owner makes each place writable to remove it.
        os.chmod(os.path.dirname(path), 0o700)
        if os.path.lexists(path) and not os.path.islink(path):
            os.chmod(path, 0o700)
        function(path)

    # The endpoint is the operator's, as every other command's: a run's record names one only
    # to be compared with it, and a credential is never sent where a record says.
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    try:
        runs = RunSet.model_validate_json(args.runs.read_bytes())
        install_bin = prepare_install(install / "hooks", CHECKOUT)
        record = run_baseline(
            store=args.store.resolve(),
            role=args.role,
            version=args.version,
            external=None if args.external is None else args.external.resolve(),
            runs=runs,
            out=out,
            setup_for=_setup_for(install_bin, base_url),
            base_url=base_url,
            score=score,
            prices=load_price_sheet(args.prices),
            development=args.development,
            resume=args.resume,
            limit_reset=args.limit_reset,
        )
    except RoundWaits as waits:
        print(json.dumps(waits.printed(), sort_keys=True))
        return waits.exit_code
    except (BaselineError, PerRoleError) as exc:
        print(f"physgate baseline: {exc}", file=sys.stderr)
        return 1
    finally:
        if install.exists():
            shutil.rmtree(install, onexc=writable_again)
    print(json.dumps(record.model_dump(mode="json"), sort_keys=True))
    return 0


def _setup_for(install_bin: Path, base_url: str | None) -> Any:  # noqa: ANN401 - a SetupFor
    """The raw arm's setup for a harness run, from what this machine has and the run recorded."""
    import os

    from physgate.evaluation.baseline.runner import BaselineError, setup_from_run
    from physgate.orchestrator.credentials import credential_for
    from physgate.orchestrator.decompose import binary_version
    from physgate.orchestrator.dispatch import probe_interpreter
    from physgate.orchestrator.invocation import claude_binary, session_search_path
    from physgate.orchestrator.role_python import measure
    from physgate.orchestrator.run_config import RunConfig
    from physgate.oslayer.probe import judge_here

    def setup_for(config: RunConfig, role: Any) -> Any:  # noqa: ANN401
        binary = claude_binary()
        version = binary_version(binary)
        if version != config.claude_version:
            msg = "the binary here is not the version the harness run recorded"
            raise BaselineError(msg, binary=version, recorded=config.claude_version)
        python = config.role_python
        return setup_from_run(
            config,
            role,
            binary=binary,
            credential=credential_for(config.auth, os.environ),
            install_bin=install_bin,
            os_layer=judge_here(claude_version=version, search_path=session_search_path(binary)),
            role_python=(
                None
                if python is None
                else measure(python.path, probe=probe_interpreter, harness=CHECKOUT)
            ),
            base_url=base_url,
        )

    return setup_for


def _audit(args: argparse.Namespace) -> int:
    import os
    import secrets

    from physgate.evaluation.baseline.audit import (
        HarnessCell,
        audit_harness,
        audit_raw,
        printed,
        write_detail,
    )
    from physgate.evaluation.baseline.runner import BASELINE_DIR, BaselineError, RunSet
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.per_role.scorers.control import score
    from physgate.evaluation.tiers.store import withheld_root

    store = args.store.resolve()
    try:
        prices = load_price_sheet(args.prices)
        found = audit_raw(
            store=store,
            role=args.role,
            version=args.version,
            runs=RunSet.model_validate_json(args.runs.read_bytes()),
            out=args.out.resolve(),
            prices=prices,
            score=score,
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            development=args.development,
        )
        cells = []
        for tier, runs, trials in args.harness:
            if tier not in ("visible", "validation", "held_out"):
                raise BaselineError(f"no tier {tier!r}", refused_because="tier")  # noqa: TRY301
            cells.append(
                HarnessCell(tier, RunSet.model_validate_json(Path(runs).read_bytes()), Path(trials))
            )
        if cells:
            scratch = (
                withheld_root(store, args.role) / BASELINE_DIR / f"audit-{secrets.token_hex(8)}"
            )
            found += audit_harness(
                store=store,
                role=args.role,
                version=args.version,
                cells=cells,
                prices=prices,
                score=score,
                scratch=scratch,
            )
        digest = write_detail(store, args.role, found)
    except (PerRoleError, OSError, ValueError) as exc:
        context = getattr(exc, "context", {})
        reason = str(context.get("refused_because", "audit_refused"))
        print(json.dumps({"refused_because": reason, "error": type(exc).__name__}, sort_keys=True))
        return 2
    print(printed(found, digest))
    return 1 if found else 0
