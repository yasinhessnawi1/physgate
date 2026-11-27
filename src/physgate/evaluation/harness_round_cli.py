"""``physgate harness-round``: the harness arm on every task and trial of a tier version.

``physgate harness-round --store S --role control --version V --tier visible [--tier
validation --tier held_out] --trials K --seed-base B --params P --run-root R --target-from T
--install I --prices DATE --out O [--tasks N] [--resume] [--limit-reset] [--set-aside I]
[--credential-replaced]`` runs
one harness trial per task and trial of the named tiers, in a fixed order, each a run decomposed
and driven by this process on a fresh clone of ``T`` inside its own run directory beneath the
registered run root ``R`` (:mod:`physgate.evaluation.harness_round`). It writes the visible
tier's run set and records into the new directory ``O``, and everything of a protected tier,
the combined run set, the ledger and the round's record beneath the role's withheld root. The
parameters ``P`` of a round of any tier name in ``withheld_whole`` every registered run root of
the store and nothing else, as the core's rule holds every measured run, or the round is refused
before anything is made; ``R`` is given as its real path, spelt as the disk spells it, and holds
no word in its path that would tell a reviewer what it reads, since each trial reviews beneath it.

``--resume`` goes on with the round ``O`` names, given the same inputs, on the same code, client
and tools: a killed round resumes its killed run and repeats no trial. ``--limit-reset`` is the
person's word that the account's usage limit has reset, for the run or the decomposition the
round stands waiting at, held to the core's rule: a reset the client's message gave is waited for
whatever the word says; one it did not give is waited for until the core's stated wait after the
halt, or the word, used once and named on the line of the directory it makes. ``--set-aside I``
is the person's word on trial ``I``'s directory, where the round stands stopped for a person: a
decomposition that spent its call and left no run after the trial's one more go, or a second
directory with nothing but its parameters. It is set aside, recorded as the person's act, and the
trial decomposed again; a run halted on a refused credential, set aside so, is decomposed afresh
and spends nothing. ``--credential-replaced`` is the person's word that the refused credential
the round stands stopped at was replaced with another secret: the trial's halted run is resumed
with it (``physgate resume --credential-replaced``), which records both fingerprints on the run's
resume line and prints them; the round's record names them per trial. Without it a run halted on
a refused credential resumes only on the secret it began on. ``--tasks N`` runs the first ``N``
tasks of each named tier in the round's order: a shakedown, whose run sets the counting rule
refuses as not covering their tier.

It prints one JSON line of counts and digests, never a task, and writes the same into ``O``. Exit
0 once every trial is assembled, a trial that gives no figure stated as ``no_figure`` (the cap
rule gives its pair the largest figure among the task's other trials, else the cell's middle one);
3 once every trial is assembled but a tier with such a trial has no figure at all; 75 while the
round waits for the account's usage limit; 77 while it waits for a person (a refused credential to
replace, or a trial's directory to set aside); 1 with ``refused_because`` and the reason in words
when it is refused or stopped. 75 and 77 are states, not waits: the command returns at once, and
its line's ``waiting`` names the trial and why, and for the limit ``resume_after`` (the instant
after which it goes on with no word: never an instant already past, where the reset passed before
it was read the floor from now, marked ``floor``) and ``word_helps``. A wrapper sleeps until
``resume_after`` between turns, and never puts ``--limit-reset`` in a loop: each word given
before the reset makes one more call, clone and directory. A person's word given to a round that
waits for none is refused.

The round's machinery and the scorer's numerical libraries are imported only when it runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TIERS = ("visible", "validation", "held_out")


def add_parser(subparsers: Any) -> None:  # noqa: ANN401 - argparse's private subparsers type
    """Register ``physgate harness-round``."""
    run = subparsers.add_parser(
        "harness-round", help="the harness arm on every task and trial of a tier version"
    )
    run.add_argument("--store", type=Path, required=True)
    run.add_argument("--role", choices=("control",), required=True)
    run.add_argument("--version", required=True)
    run.add_argument("--tier", dest="tiers", action="append", choices=TIERS, required=True)
    run.add_argument("--trials", type=int, required=True)
    run.add_argument("--seed-base", dest="seed_base", type=int, required=True)
    run.add_argument("--params", type=Path, required=True)
    run.add_argument("--run-root", dest="run_root", type=Path, required=True)
    run.add_argument("--target-from", dest="target_from", type=Path, required=True)
    run.add_argument("--install", type=Path, required=True)
    run.add_argument("--prices", required=True, help="the dated price sheet the runs are priced at")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--tasks", type=int, help="the first N tasks of each tier: a shakedown")
    run.add_argument("--resume", action="store_true", help="go on with the round OUT names")
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
    run.add_argument(
        "--credential-replaced",
        dest="credential_replaced",
        action="store_true",
        help=(
            "say that the refused credential the round stands stopped at was replaced with "
            "another secret: the trial's halted run is resumed on it, both fingerprints recorded"
        ),
    )
    run.add_argument(
        "--set-aside",
        dest="set_aside",
        type=int,
        metavar="TRIAL",
        help="set aside the directory of the trial the round stands stopped at for a person",
    )
    run.set_defaults(func=_run)


def _score(task: Any, answer: Path) -> Any:  # noqa: ANN401 - the scorer's own types
    """The control scorer, imported only once there is an answer to score.

    Its numerical libraries are the evaluation group's, which a refusal never needs.
    """
    from physgate.evaluation.per_role.scorers.control import score

    return score(task, answer)


def _refused(reason: str, words: str) -> int:
    print(json.dumps({"refused_because": reason, "error": words}, sort_keys=True))
    return 1


def _run(args: argparse.Namespace) -> int:
    from physgate.evaluation.harness_round import (
        EXIT_DONE_WITHOUT_CAPS,
        EXIT_WAITING_FOR_A_PERSON,
        CommandDriver,
        Inputs,
        RoundError,
        run_round,
    )
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.observe.exceptions import ObserveError
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT

    if args.trials < 1 or (args.tasks is not None and args.tasks < 1):
        return _refused("counts", "a round runs at least one trial of at least one task")
    if len(set(args.tiers)) != len(args.tiers):
        return _refused("tiers", "each tier is named once")
    try:
        inputs = Inputs(
            store=args.store.resolve(),
            role=args.role,
            version=args.version,
            tiers=tuple(args.tiers),
            trials=args.trials,
            seed_base=args.seed_base,
            params=args.params.resolve(),
            # As typed, made absolute: the round holds it to its spelling on disk, links included.
            run_root=args.run_root.absolute(),
            target_from=args.target_from.resolve(),
            install=args.install.resolve(),
            prices=load_price_sheet(args.prices),
            out=args.out.resolve(),
            tasks=args.tasks,
        )
        status, summary = run_round(
            inputs,
            driver=CommandDriver(),
            scorer=_score,
            resume=args.resume,
            limit_reset=args.limit_reset,
            set_aside=args.set_aside,
            credential_replaced=args.credential_replaced,
        )
    except RoundError as exc:
        return _refused(exc.context.get("refused_because", "refused"), str(exc))
    except (PerRoleError, ObserveError) as exc:
        context = getattr(exc, "context", {})
        return _refused(str(context.get("refused_because", "refused")), str(exc))
    print(json.dumps({"status": status, **summary}, sort_keys=True))
    if status == "waiting_for_a_person":
        return EXIT_WAITING_FOR_A_PERSON
    if status == "done_without_caps":
        return EXIT_DONE_WITHOUT_CAPS
    return EXIT_WAITING_FOR_LIMIT if status == "waiting_for_limit" else 0
