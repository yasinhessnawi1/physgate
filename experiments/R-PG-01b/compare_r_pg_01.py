"""R-PG-01b, CRITERIA.md §8, the last step: the comparison with R-PG-01, by fixed rules.

Usage, in a checkout that can fetch the pushed "numbers final" branch, and only then::

    compare_r_pg_01.py --numbers-ref <remote>/exp/r-pg-01b-numbers --output <path in that commit>
        --r-pg-01-run <R-PG-01's run directory>
        --run I1=<run dir> --run F1=<run dir> [--run I2=... --run F2=...] --out <file>

**It refuses to run** unless the "numbers final" commit is pushed: the ref is fetched from its
remote and the remote holds the same commit; the tally's output ``--output`` is in that commit;
and that file's sha256 appears in the same commit's ``experiments/R-PG-01b/RESULT.md``. Every
R-PG-01b number it uses is read from that committed output, never recomputed.

**What it computes** (§8, steps 1 to 4), changing no number of R-PG-01b's:

1. Replication against the same-day noise floor, for the injected artefacts and for the twins:
   D_cross, for each arm-I round the artefacts whose approval differs from R-PG-01's, averaged
   over the rounds; D_same, the artefacts on which arm I's two rounds differ; *replicated* if the
   bootstrap 95 % interval of D_cross − D_same (over artefacts, ``random.Random(13)``, 10,000
   draws) includes 0 or lies below it, and the exact McNemar test between R-PG-01 and arm I,
   pooled over rounds, gives p ≥ 0.05; else *not replicated*, named "drift or protocol
   differences". With one valid round there is no noise floor: D_cross with its bootstrap
   interval, and *replicated* means p ≥ 0.05, labelled "without a noise floor".
2. The sheet's share of R-PG-01's advantage: −ΔC divided by R-PG-01's C, when that is at least 1
   and the floor (§7) does not hold.
3. The gate across time: R-PG-01's gate records against R-PG-01b's, expected byte-identical.
4. D1's sentence, from §7's table, read from the top, the first row that holds; only where R6
   held in the committed output (§7, §12), and not taken otherwise, as is step 2.

It uses whichever rounds the committed output holds: with one valid round, round 1 or round 2,
that round's figures and its Newcombe interval.

R-PG-01's figures are read from its run directory by R-PG-01's own ``tally_rows.py``. It writes
the output to ``--out`` (never over a file) and prints its sha256.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import contrast as K  # noqa: E402

RESULT = "experiments/R-PG-01b/RESULT.md"


class Refused(Exception):
    """The comparison may not run yet."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def numbers_final(repo: Path, ref: str, output: str) -> dict[str, Any]:
    """The pushed "numbers final" commit's tally output, held to the digest RESULT.md gives."""
    remote, _, branch = ref.partition("/")
    if not branch:
        raise Refused("the numbers ref is <remote>/<branch>")
    if _git(repo, "fetch", "-q", remote, branch).returncode != 0:
        raise Refused(f'{ref} cannot be fetched: "numbers final" is not pushed')
    listed = _git(repo, "ls-remote", remote, f"refs/heads/{branch}").stdout.split()
    local = _git(repo, "rev-parse", ref).stdout.strip()
    if not listed or listed[0] != local:
        raise Refused(f"{ref} is not the commit its remote holds")
    data = _git(repo, "show", f"{local}:{output}")
    result = _git(repo, "show", f"{local}:{RESULT}")
    if data.returncode != 0 or result.returncode != 0:
        raise Refused("the numbers-final commit lacks the tally's output or RESULT.md")
    digest = C.sha256_bytes(data.stdout.encode())
    if digest not in result.stdout:
        raise Refused("the committed tally output does not match the digest RESULT.md gives")
    return {"commit": local, "sha256": digest, "output": json.loads(data.stdout)}


def kill(a: float, c: float) -> bool:
    """R-PG-01 §5's rule."""
    return c < 10 or a < 4


def replication(
    prior: dict[str, int], rounds: list[dict[str, int]], resamples: list[list[int]]
) -> dict[str, Any]:
    """§8 step 1 on one side: D_cross, D_same, the interval and the exact test."""
    arts = sorted(prior)
    n, r = len(arts), len(rounds)

    def d_cross(idx: list[int]) -> float:
        return sum(rounds[k][arts[i]] != prior[arts[i]] for k in range(r) for i in idx) / r

    def d_same(idx: list[int]) -> float:
        return float(sum(rounds[0][arts[i]] != rounds[1][arts[i]] for i in idx)) if r == 2 else 0.0

    every = list(range(n))
    pairs = [(rounds[k][a], prior[a]) for k in range(r) for a in arts]
    b = sum(1 for x, y in pairs if x and not y)
    c = sum(1 for x, y in pairs if not x and y)
    p = K.mcnemar_exact(b, c)
    found: dict[str, Any] = {"D_cross": d_cross(every), "exact_p": p, "discordant": [b, c]}
    if r == 2:
        found["D_same"] = d_same(every)
        diff = K.boot(lambda idx: d_cross(idx) - d_same(idx), resamples)
        found["D_cross_minus_D_same"] = {"value": found["D_cross"] - found["D_same"], **diff}
        low = diff["low"]
        found["replicated"] = low is not None and low <= 0 and p >= 0.05
    else:
        found["D_cross_interval"] = K.boot(d_cross, resamples)
        found["replicated"] = p >= 0.05
        found["label"] = "without a noise floor"
    if not found["replicated"]:
        found["named"] = "drift or protocol differences"
    return found


def d1_sentence(
    prior_kill: bool,
    i_kill: bool,
    f_kill: bool,
    i_rounds_agree: bool,
    deltas: dict[str, Any],
    legs: str,
) -> tuple[int, str]:
    """§7's table, read from the top: the first row that holds, and its sentence."""
    a, c = deltas["A"], deltas["C"]
    filled = f"ΔA = {a} , ΔC = {c}"
    if not i_rounds_agree:
        return (
            1,
            "The kill reading is not stable at this size; the sheet's part in it is not separable.",
        )
    if prior_kill == i_kill == f_kill:
        return 2, "The complete sheet did not change the kill reading."
    if prior_kill == f_kill and i_kill != f_kill:
        return 3, (
            f"Under today's protocol the complete sheet changed the kill reading, through {legs}: "
            f"{filled}. Today's reading with the incomplete sheet differs from R-PG-01's (drift or "
            "protocol differences), so R-PG-01's published reading matches the corrected one."
        )
    if prior_kill != f_kill and i_kill == prior_kill:
        return 4, f"The complete sheet changed the kill reading, through {legs}: {filled}."
    return 5, (
        "The kill reading changed between R-PG-01 and today's same protocol (drift or protocol "
        "differences), not through the sheet."
    )


def legs(a_i: float, a_f: float, c_i: float, c_f: float) -> str:
    """Which legs of the kill reading the two arms' means lie on different sides of."""
    a_leg = (a_i < 4) != (a_f < 4)
    c_leg = (c_i < 10) != (c_f < 10)
    if a_leg and c_leg:
        return "both"
    return "the A leg" if a_leg else ("the C leg" if c_leg else "neither leg")


def compare(
    numbers: dict[str, Any], prior_run: Path, runs: dict[str, Path], any_count: bool = False
) -> dict[str, Any]:
    """§8's four steps (``any_count`` for invented fixtures only)."""
    out = numbers["output"]
    tally = K.tally_module()
    prior = tally.tally(prior_run, None, any_count)
    rounds = out["rounds"]
    resamples = K.draws(out["artefacts"])
    per_run = out["per_run"]

    def approvals(key: str, field: str) -> dict[str, int]:
        return {
            p["artefact"]: int(p["approved"] if field == "A" else p["twin_review"] == "pass")
            for p in per_run[key]["per_artefact"]
        }

    prior_a = {p["artefact"]: int(p["approved"]) for p in prior["per_artefact"]}
    prior_t = {p["artefact"]: int(p["twin_review"] == "pass") for p in prior["per_artefact"]}
    step1 = {
        "injected": replication(prior_a, [approvals(f"I{r}", "A") for r in rounds], resamples),
        "twins": replication(prior_t, [approvals(f"I{r}", "T") for r in rounds], resamples),
    }
    prior_c = prior["C_caught_among_approved"]
    prior_gate = K.gate_records(prior_run)
    step3 = {key: K.gate_records(run) == prior_gate for key, run in sorted(runs.items())}
    step2: dict[str, Any] | None = None
    step4: dict[str, Any]
    if out["R6"]["holds"] is not True:
        # §7 and §12: under R6's deviation the primary contrast is void, and D1 is not taken.
        step4 = {"row": None, "sentence": K.NOT_TAKEN}
    else:
        primary = out["primary_delta_C"]
        if prior_c >= 1 and not out["floor"]:
            step2 = {"share": -primary["value"] / prior_c, "r_pg_01_C": prior_c}
        arms = out["arms"]
        a_i, c_i = arms["I"]["A_mean"]["value"], arms["I"]["C_mean"]["value"]
        a_f, c_f = arms["F"]["A_mean"]["value"], arms["F"]["C_mean"]["value"]
        deltas = {
            "A": json.dumps(_with_interval(out["secondary"]["delta_A"], rounds)),
            "C": json.dumps(_with_interval(primary, rounds)),
        }
        row, sentence = d1_sentence(
            prior["kill_criterion_fires"],
            kill(a_i, c_i),
            kill(a_f, c_f),
            arms["I"]["rounds_agree_on_kill"],
            deltas,
            legs(a_i, a_f, c_i, c_f),
        )
        step4 = {"row": row, "sentence": sentence}
    return {
        "numbers_final": {"commit": numbers["commit"], "sha256": numbers["sha256"]},
        "r_pg_01": {
            "A": prior["A_approved"],
            "C": prior_c,
            "kill": prior["kill_criterion_fires"],
        },
        "step_1_replication": step1,
        "step_2_share_of_r_pg_01_advantage": step2,
        "step_3_gate_records_identical_to_r_pg_01": step3,
        "step_4_D1": step4,
    }


def _with_interval(contrast: dict[str, Any], rounds: list[int]) -> dict[str, Any]:
    """A contrast's value and interval.

    The bootstrap's, or with one valid round that round's Newcombe interval, whichever round it
    is.
    """
    one = contrast.get("newcombe_per_round", {}).get(str(rounds[0])) if len(rounds) == 1 else None
    interval = contrast.get("bootstrap") or one or {}
    return {
        "value": contrast.get("value"),
        "low": interval.get("low"),
        "high": interval.get("high"),
    }


def main(argv: list[str] | None = None) -> int:
    """Refuse before the pushed numbers; else write the comparison and print its sha256."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--numbers-ref", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--r-pg-01-run", type=Path, required=True)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit(f"{args.out} exists; an output is never written over")
    try:
        numbers = numbers_final(C.REPO, args.numbers_ref, args.output)
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    runs = {
        s.partition("=")[0]: Path(s.partition("=")[2].split(",")[0]).resolve() for s in args.run
    }
    found = compare(numbers, args.r_pg_01_run.resolve(), runs)
    text = json.dumps(found, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    args.out.write_text(text)
    print(json.dumps({"out": str(args.out), "sha256": C.sha256_bytes(text.encode())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
