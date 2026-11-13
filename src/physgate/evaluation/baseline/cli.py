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
    run.add_argument("--version", required=True)
    run.add_argument("--runs", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--prices", required=True, help="the dated price sheet the harness used")
    run.add_argument("--development", action="store_true")
    run.set_defaults(func=_run)


def _run(args: argparse.Namespace) -> int:
    import os
    import shutil

    from physgate.evaluation.baseline.runner import BaselineError, RunSet, run_baseline
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
            runs=runs,
            out=out,
            setup_for=_setup_for(install_bin, base_url),
            base_url=base_url,
            score=score,
            prices=load_price_sheet(args.prices),
            development=args.development,
        )
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
