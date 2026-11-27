"""``physgate harness-round``: the harness arm on every task and trial of a tier version.

``physgate harness-round --store S --role control --version V --tier visible [--tier
validation --tier held_out] --trials K --seed-base B --params P --run-root R --target-from T
--install I --prices DATE --out O [--tasks N] [--resume] [--limit-reset] [--set-aside I]
[--credential-replaced] [--order-seed S] [--only PLACE] [--ablation NAME --ablation-params A]
[--drop-ablation WHY --dropped-by WHO]`` runs
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
refuses as not covering their tier. ``--shakedown`` says the round is a shakedown: a practice
version (its manifest marked so) is refused without it (``practice_version``).

``--order-seed S`` runs one cell (one ``--tier``) in the registered order: the cell's (id digest,
trial) pairs sorted and shuffled once by ``random.Random("S:order:<role>_<tier>")``, trial ``n``
of a task seeded ``B + n``. ``--only PLACE`` takes on that one place of the round's order (the first
not yet assembled; one already assembled is only said again), stops once it is assembled, and
writes its one-entry run set ``trials/<PLACE>.runs.json`` and its sheet ``<PLACE>.trial.json``
(in ``O`` for the visible tier, beneath the withheld root for a protected one), as every trial's
are written once it is assembled. Its line's ``trial`` names the set and, for a visible trial,
``raw_pair``: ``now`` (exit 0) or ``at_cell_end`` (exit 3: the trial gives no figure, and its raw
pair runs once the cell's last harness trial is assembled). A protected trial's ``raw_pair`` is
never said outside the withheld root, and its call exits 0: its sheet beneath the root says it.
Status ``trial_assembled`` while later places remain; the call that assembles the last place ends
the round as a whole call does.

``--ablation NAME --ablation-params A`` runs an ablation arm beside the harness trials of the one
visible cell, in the registered order: ``A`` is an ablation run's parameters (``ablation: true``,
``reportable: false``) that differ from ``P`` in the parts they take away alone (a refusal names
the field), held by its digest as ``P`` is. Each (task, trial) of the cell is a unit: the harness
trial and the arm's trial of the same task and seed, each a place of its own. The units keep the
cell's order, and the same generator then orders each unit's two places by one shuffle of [the
harness trial, the arm's trial]. ``--only PLACE`` takes on a place of either arm; its line's
``trial`` names the place's ``arm`` (``harness`` or ``ablation``, with the arm's name), and an
ablation trial's ``raw_pair`` is ``never`` (exit 0): no raw trial is paired with it, and it caps
none. The arm's trials are held to every rule the harness's are; they are written only into the
arm's own files beside ``O``'s (``ablation.NAME.runs.json``, ``ablation.NAME.trials.jsonl``, and
each trial's set and sheet in ``ablation.NAME/trials/``), never into a tier's set or the combined
one, and the round's record and line count the arm apart. ``--drop-ablation WHY --dropped-by WHO``
drops the arm's places not yet assembled, at once and for good, recorded on the ledger with who
and why; the harness trials go on alone, and every later start says the same words, or is refused.

It prints one JSON line of counts and digests, never a task, and writes the same into ``O``.
Its outcome counts, ``tiers.visible.pass``, ``.fail`` and ``.flaky`` and the same three under
``arms.NAME``, are a look at a cell's outcomes: a launch script never prints or logs them before
the cell's report is written (its ``unscored`` and ``excluded`` counts it may say). Exit
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
    run.add_argument(
        "--shakedown",
        action="store_true",
        help="the round is a shakedown: the only round that runs on a practice version",
    )
    run.add_argument(
        "--order-seed",
        dest="order_seed",
        type=int,
        help=(
            "run one cell (one tier) in the registered order: its (id digest, trial) pairs "
            "shuffled once by this seed, trial n of a task seeded SEED_BASE + n"
        ),
    )
    run.add_argument(
        "--only",
        type=int,
        metavar="PLACE",
        help=(
            "take on only this place of the round's order (the first not yet assembled), stop "
            "once it is assembled, and write its one-entry run set"
        ),
    )
    run.add_argument(
        "--ablation",
        metavar="NAME",
        help="run an ablation arm of this name beside the visible cell's harness trials",
    )
    run.add_argument(
        "--ablation-params",
        dest="ablation_params",
        type=Path,
        help="the ablation arm's parameters: an ablation run's, differing only in what they ablate",
    )
    run.add_argument(
        "--drop-ablation",
        dest="drop_ablation",
        metavar="WHY",
        help="drop the ablation arm's places not yet assembled, at once and for good, for WHY",
    )
    run.add_argument(
        "--dropped-by",
        dest="dropped_by",
        metavar="WHO",
        help="who drops the ablation arm (a plain word), with --drop-ablation",
    )
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
        Ablation,
        CommandDriver,
        Drop,
        Inputs,
        RoundError,
        run_round,
    )
    from physgate.evaluation.observe.cost import load_price_sheet
    from physgate.evaluation.observe.exceptions import ObserveError
    from physgate.evaluation.per_role.exceptions import PerRoleError
    from physgate.orchestrator.waiting import EXIT_WAITING_FOR_LIMIT

    if args.only is not None and args.only < 0:
        return _refused("counts", "a place of the order is counted from 0")
    if args.trials < 1 or (args.tasks is not None and args.tasks < 1):
        return _refused("counts", "a round runs at least one trial of at least one task")
    if len(set(args.tiers)) != len(args.tiers):
        return _refused("tiers", "each tier is named once")
    if (args.ablation is None) != (args.ablation_params is None):
        return _refused(
            "ablation_needs_both", "an ablation arm is given by its name and parameters"
        )
    if (args.drop_ablation is None) != (args.dropped_by is None):
        return _refused("ablation_drop_words", "a drop says who makes it and why")
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
            order_seed=args.order_seed,
            shakedown=args.shakedown,
            ablation=(
                None
                if args.ablation is None
                else Ablation(name=args.ablation, params=args.ablation_params.resolve())
            ),
        )
        status, summary = run_round(
            inputs,
            driver=CommandDriver(),
            scorer=_score,
            resume=args.resume,
            limit_reset=args.limit_reset,
            set_aside=args.set_aside,
            credential_replaced=args.credential_replaced,
            only=args.only,
            drop=(
                None
                if args.drop_ablation is None
                else Drop(by=args.dropped_by, why=args.drop_ablation)
            ),
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
    if status == "trial_assembled":
        # The named trial gives its raw pair no figure: the pair runs at the cell's end.
        no_figure = summary.get("trial", {}).get("raw_pair") == "at_cell_end"
        return EXIT_DONE_WITHOUT_CAPS if no_figure else 0
    return EXIT_WAITING_FOR_LIMIT if status == "waiting_for_limit" else 0
