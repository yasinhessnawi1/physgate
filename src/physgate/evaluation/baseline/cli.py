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
entry has been checked. A round that has ended, started again with ``--resume``, prints its
record again and exits 0.

It exits 1, naming no task, if the round is refused or stopped, and prints one line on stdout:
``status`` (``refused``), ``refused_because``, ``entry`` (the entry by its place in the run set,
or ``null``) and ``session_started``: true where the entry was stopped for a cause after its
session started, at this start or an earlier one (a pair that differs, other pins, an error, a
move that failed, ``entry_stopped``): it is never run again in its round, only once more with
``--rerun-of``. False is a refusal before any session of this start: it spent nothing, and the
same round is started again once its cause is removed.
``--rerun-of OUT`` runs once more, as a new round of its one entry, an entry the earlier round
``OUT`` stopped on for a cause, recorded excluded for a reason its records give for not trusting
the answer, or ran under a harness run that was itself run once more (named by the sheet beside
the run set, ``<n>.trial.json``); it is refused otherwise, and for an earlier round that was
itself such a once-more. ``--cell RUNS`` names the run set of every harness trial of the cell
the entries' caps are taken from, where the round's own run set is not the whole cell;
``--shakedown`` lets the round run on a practice version. The round records the checkout it runs
from with every session and holds the harness runs' to it.

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
written beneath the role's withheld root. ``--out`` and ``--runs`` may be left out to audit the
harness arm's records alone. It exits 0 when nothing differs, 1 when anything does, and 3 with
``refused_because`` on one line when the audit cannot be made (2 is the command line refused).

The scorer's numerical libraries are the evaluation group's; they are imported only when the
command runs.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Iterator
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
        "--cell", type=Path, help="the run set of every harness trial of the cell, for the caps"
    )
    run.add_argument(
        "--shakedown", action="store_true", help="the round is a shakedown: a practice version"
    )
    run.add_argument(
        "--rerun-of",
        dest="rerun_of",
        type=Path,
        help="the earlier round whose entry this one-entry round runs once more",
    )
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
    audit.add_argument("--runs", type=Path)
    audit.add_argument("--out", type=Path)
    audit.add_argument("--cell", type=Path)
    audit.add_argument("--shakedown", action="store_true")
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
    import traceback

    from physgate.evaluation.baseline.runner import (
        BaselineError,
        RoundWaits,
        RunSet,
        Stopped,
        run_baseline,
    )
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.evaluation.per_role.scorers.control import score
    from physgate.orchestrator.install import prepare_install
    from physgate.orchestrator.run_config import harness_state

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
        cell = None if args.cell is None else RunSet.model_validate_json(args.cell.read_bytes())
        install_bin = prepare_install(install / "hooks", CHECKOUT)
        with stopping():
            record = run_baseline(
                store=args.store.resolve(),
                role=args.role,
                version=args.version,
                external=None if args.external is None else args.external.resolve(),
                runs=runs,
                out=out,
                setup_for=_setup_for(install_bin, base_url, harness_state(CHECKOUT)),
                base_url=base_url,
                score=score,
                prices=load_price_sheet(args.prices),
                development=args.development,
                resume=args.resume,
                limit_reset=args.limit_reset,
                cell=cell,
                shakedown=args.shakedown,
                rerun_of=None if args.rerun_of is None else args.rerun_of.resolve(),
                replaces=replaced_run(args.runs),
            )
    except Stopped as stop:
        return stopped_line(stop)
    except RoundWaits as waits:
        print(json.dumps(waits.printed(), sort_keys=True))
        return waits.exit_code
    except (BaselineError, PerRoleError) as exc:
        print(f"physgate baseline: {exc}", file=sys.stderr)
        print(refused_line(exc.context))
        return 1
    except Exception as exc:  # noqa: BLE001 - said as a refusal by its kind; its words to stderr
        traceback.print_exc(file=sys.stderr)
        print(refused_line({"refused_because": "error", "error": type(exc).__name__}))
        return 1
    finally:
        if install.exists():
            shutil.rmtree(install, onexc=writable_again)
    for tier, counts in sorted((record.no_figure or {}).items()):
        if 3 * counts["no_figure"] > counts["entries"]:
            # Loud, never hidden: a cell where many harness trials give no total of their own
            # may hide a fault in how the runs' records were read.
            print(
                f"physgate baseline: {counts['no_figure']} of the {counts['entries']} {tier} "
                "entries gave no token total of their own and ran under a cap the cell's rule "
                "took from other trials; look at why before the cell is reported",
                file=sys.stderr,
            )
    print(json.dumps(record.model_dump(mode="json"), sort_keys=True))
    return 0


@contextlib.contextmanager
def stopping() -> Iterator[None]:
    """Inside, a stop signal raises :class:`.runner.Stopped` in the main thread, once.

    So the round unwinds as on any error: the arm ends its session with its process group and
    removes its credential, and the round names the stop on its ledger. A further stop signal
    while it unwinds is ignored, so the cleanup is not cut short; a kill is not, and leaves what
    the next start clears. A signal the launcher set to be ignored stays ignored.
    """
    import signal
    import threading

    from physgate.evaluation.baseline.runner import Stopped
    from physgate.orchestrator.stop_signals import STOP_SIGNALS

    if threading.current_thread() is not threading.main_thread():
        yield
        return
    found: dict[int, Any] = {}

    def stop(signum: int, _frame: Any) -> None:  # noqa: ANN401 - a signal handler's frame
        for each in found:
            signal.signal(each, signal.SIG_IGN)
        raise Stopped(signum)

    for signum in STOP_SIGNALS:
        before = signal.getsignal(signum)
        if before == signal.SIG_IGN:
            continue
        found[signum] = before
        signal.signal(signum, stop)
    try:
        yield
    finally:
        for each, before in found.items():
            signal.signal(each, before)


def stopped_line(stop: Any) -> int:  # noqa: ANN401 - a runner.Stopped
    """Say a stop, after every session of this process is gone; the status the command ends with.

    The line: ``status`` ``stopped``, the signal, the entry the round was at and whether a session
    of it had started, and how many sessions of this process still live. It ends with ``128 + N``
    for the signal ``N``, as a process the signal ended would; with 76 where a session still
    lives after its stop, since it may write its credential again.
    """
    import signal

    from physgate.orchestrator.credentials import remove_held_secrets
    from physgate.orchestrator.stop_signals import EXIT_SESSIONS_ALIVE, end_live_sessions

    ended = end_live_sessions()
    remove_held_secrets()
    alive = len(ended.survivors)
    print(
        json.dumps(
            {
                "format": 1,
                "status": "stopped",
                "signal": signal.Signals(stop.signum).name,
                "entry": stop.entry,
                "session_started": stop.session_started,
                "sessions_alive": alive,
            },
            sort_keys=True,
        )
    )
    return EXIT_SESSIONS_ALIVE if alive else 128 + int(stop.signum)


def replaced_run(runs: Path) -> str | None:
    """The run a re-run harness trial superseded, as the sheet beside its run set names it.

    The harness round writes beside each trial's one-entry run set (``<n>.runs.json``) a sheet
    (``<n>.trial.json``) that names, for a trial run once more, the run it superseded
    (``rerun_of.run_dir``). ``None`` where there is no such sheet or it names none.

    Raises:
        BaselineError: the sheet is an ablation arm's trial's.
    """
    if not runs.name.endswith(".runs.json"):
        return None
    sheet = runs.with_name(runs.name.removesuffix(".runs.json") + ".trial.json")
    try:
        found = json.loads(sheet.read_bytes())
    except (OSError, ValueError):
        return None
    if isinstance(found, dict) and found.get("arm", "harness") != "harness":
        # The sheet of an ablation arm's trial: no raw trial is ever paired with one, whatever
        # run set it lies beside.
        from physgate.evaluation.baseline.runner import BaselineError

        msg = "the sheet beside the run set is an ablation trial's; no baseline is held to one"
        raise BaselineError(msg, refused_because="ablation_record")
    rerun = found.get("rerun_of") if isinstance(found, dict) else None
    run_dir = rerun.get("run_dir") if isinstance(rerun, dict) else None
    return run_dir if isinstance(run_dir, str) else None


def refused_line(context: dict[str, str]) -> str:
    """The one line a refused or stopped round prints: why, which entry, and whether it had run.

    ``entry`` is the entry by its place in the run set, ``null`` where the refusal names none;
    ``session_started`` whether a session of it had started in the round.
    """
    entry = context.get("entry")
    return json.dumps(
        {
            "format": 1,
            "status": "refused",
            "refused_because": context.get("refused_because", "refused"),
            "entry": int(entry) if entry is not None and entry.isdigit() else None,
            "session_started": context.get("session_started") == "true",
        },
        sort_keys=True,
    )


def _setup_for(install_bin: Path, base_url: str | None, harness: Any) -> Any:  # noqa: ANN401
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
            harness=harness,
        )

    return setup_for


def _audit(args: argparse.Namespace) -> int:
    import os
    import secrets

    from physgate.evaluation.baseline.audit import (
        AuditError,
        HarnessCell,
        audit_harness,
        audit_raw,
        printed,
        write_detail,
    )
    from physgate.evaluation.baseline.runner import BASELINE_DIR, RunSet
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.per_role.scorers.control import score
    from physgate.evaluation.tiers.store import withheld_root

    store = args.store.resolve()
    try:
        if (args.out is None) != (args.runs is None):
            msg = "a baseline round is audited from its directory and its run set, both"
            raise AuditError(msg, refused_because="round_half_named")  # noqa: TRY301
        if args.out is None and not args.harness:
            msg = "nothing to audit: name a baseline round, a tier of the harness arm, or both"
            raise AuditError(msg, refused_because="nothing_to_audit")  # noqa: TRY301
        prices = load_price_sheet(args.prices)
        found = []
        if args.out is not None:
            cell = None if args.cell is None else RunSet.model_validate_json(args.cell.read_bytes())
            found += audit_raw(
                store=store,
                role=args.role,
                version=args.version,
                runs=RunSet.model_validate_json(args.runs.read_bytes()),
                out=args.out.resolve(),
                prices=prices,
                score=score,
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
                development=args.development,
                cell=cell,
                shakedown=args.shakedown,
            )
        cells = []
        for tier, runs, trials in args.harness:
            if tier not in ("visible", "validation", "held_out"):
                raise AuditError(f"no tier {tier!r}", refused_because="tier")  # noqa: TRY301
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
    except Exception as exc:  # noqa: BLE001 - every way the audit cannot be made has one status
        context = getattr(exc, "context", {})
        reason = str(context.get("refused_because", "audit_refused"))
        print(json.dumps({"refused_because": reason, "error": type(exc).__name__}, sort_keys=True))
        return EXIT_CANNOT_AUDIT
    print(printed(found, digest))
    return 1 if found else 0


#: The audit's exit status where it cannot be made: its own, apart from "a record differs" (1)
#: and from the command line refused (2).
EXIT_CANNOT_AUDIT = 3
