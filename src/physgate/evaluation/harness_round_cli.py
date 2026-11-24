"""``physgate harness-round``: the harness arm on every task and trial of a tier version.

``physgate harness-round --store S --role control --version V --tier visible [--tier
validation --tier held_out] --trials K --seed-base B --params P --run-root R --target-from T
--install I --prices DATE --out O [--tasks N] [--resume] [--limit-reset]`` runs one harness
trial per task and trial of the named tiers, in a fixed order, each a run decomposed and
driven by this process on a fresh clone of ``T`` inside its own run directory beneath the
registered run root ``R`` (:mod:`physgate.evaluation.harness_round`). It writes the visible
tier's run set and records into the new directory ``O``, and everything of a protected tier,
the combined run set, the ledger and the round's record beneath the role's withheld root.

``--resume`` goes on with the round ``O`` names, given the same inputs: a killed round resumes
its killed run and repeats no trial. ``--limit-reset`` is the person's word that the account's
usage limit has reset, for a run or a decomposition the limit stopped. ``--tasks N`` runs the
first ``N`` tasks of each named tier in the round's order: a shakedown, whose run sets the
counting rule refuses as not covering their tier.

It prints one JSON line of counts and digests, never a task. Exit 0 once every trial is
assembled; 75 while the round waits for the account's usage limit (start it again after the
reset); 77 while it waits for a person to replace a refused credential (start it again after);
1 with ``refused_because`` and the reason in words when it is refused or stopped.

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
        help="say that the account's usage limit has reset; recorded on the resume it lets on",
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
            run_root=args.run_root.resolve(),
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
        )
    except RoundError as exc:
        return _refused(exc.context.get("refused_because", "refused"), str(exc))
    except (PerRoleError, ObserveError) as exc:
        context = getattr(exc, "context", {})
        return _refused(str(context.get("refused_because", "refused")), str(exc))
    print(json.dumps({"status": status, **summary}, sort_keys=True))
    if status == "waiting_for_a_person":
        return EXIT_WAITING_FOR_A_PERSON
    return EXIT_WAITING_FOR_LIMIT if status == "waiting_for_limit" else 0
