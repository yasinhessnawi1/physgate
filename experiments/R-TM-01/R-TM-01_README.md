# R-TM-01 — Tsetlin machine as the escalation decision layer

Four pre-registered runs testing whether a Tsetlin machine can serve as the `tsetlin`
backend behind the ARCH-131 `decide()` interface. **Outcome: parked.** ARCH-132's
`tsetlin` row stays contingent.

Everything here was produced in one session on 19–20 September 2026. Every run has a
pre-registration frozen before its first TM fit, per-seed metrics, figures, and a
`RESULT.md` giving pass or fail per criterion with the numbers.

## The four runs

| Run | Directory | Pre-registration | Verdict | Killed on |
|---|---|---|---|---|
| R-TM-01 | `run02/` | the original spec (in `parked/`) | FAIL | A1 vs LR — a threshold no model could meet |
| R-TM-01b | `run03b/` | `R-TM-01b.md` | FAIL | A3 on both OOD sets |
| R-TM-01c | `run04c/` | `R-TM-01c.md` | all four gating criteria pass | — (single-draw sweep; not acted on) |
| R-TM-01d | `run05d/` | `R-TM-01d.md` | FAIL | one replicate of the selection rule found no qualifying configuration |

`run01/` is the first execution of R-TM-01, superseded by `run02/` after a code audit found
six defects. It is kept for completeness; use `run02/`.

## What the four runs established

**Positive, in every run:** calibrated confidence that falls off-distribution. At the 0.8
routing threshold the final configuration routes 18 % of in-distribution decisions to a
human and 76–81 % of novel-state ones, and is right on 96–99 % of what it still answers by
itself. No baseline reproduces this at any setting tested — the gradient-boosted tree
routes 0.3 % of decisions everywhere, in-distribution or not, and is right on 47 % of the
unseen-attempt cases it keeps.

**The sentence that travels with it, and the two numbers that must never be separated:**
the component gets worse at answering and much better at knowing when not to. Whole-split
accuracy off-distribution 0.647–0.665; accuracy on the decisions it does not escalate
0.962–0.989. The first number alone says the model broke; the second alone hides that it is
handing over four decisions in five.

**Negative, in every run:** clause legibility. Best observed, one hidden-rule term of four
recovered. Removed from ARCH-132's entry condition after two runs failed it.

**Negative, established in the last run:** accuracy parity with a strong baseline is not
reliably achievable. The gap is 1.8 points on the configuration that passed, but validation
accuracy swings 1.6 points on fitting noise alone, and the "within 3 points of GBT" band
sits inside that swing. Of 48 configurations the humility floor admits 9–12 on every draw;
the accuracy band admits 6, then 3, then 1.

**Two methodological findings worth keeping:**

- Two of R-TM-01's five criteria were unsatisfiable before the first run — A1 required
  0.9578 accuracy on a task whose noise ceiling was 0.9502. Check feasibility against the
  ceiling when writing thresholds.
- Hyperparameter selection by accuracy alone selects away out-of-domain humility. Moving
  the property into the selection rule moved A3 from 0.117/0.109 to 0.225/0.206 at a cost
  of 0.5 accuracy points.

## Provenance — keep this attached to any summary

The T ≈ 40 region that runs -01c and -01d select was first identified in **R-TM-01b's
post-hoc frontier, which was computed with the OOD test sets in hand.** The humility rule's
free parameters — the 0.15 floor, the two pseudo-OOD slices, requiring both, the 6 500/1 500
fold — were authored knowing that region worked. No selection code reads test data and every
criterion was frozen before it ran, so nothing is contaminated in the statistical sense; but
the hypothesis space was narrowed by earlier looks at the test sets. These are stability and
transferability checks of a known answer, not independent discoveries. An independent
demonstration needs a generator and a novelty type none of these four runs has seen.

## Reading order

1. `run05d/RESULT.md` — the final verdict and the finding to carry forward.
2. `run04c/RESULT.md` — the run that passed, and the audit findings against it.
3. `run03b/RESULT.md` — where the humility failure was diagnosed.
4. `run02/RESULT.md` — the infeasible-threshold finding.

Each directory also holds the frozen pre-registration it was judged against.

## Reproducing

Python 3.11. `pip install tmu numpy scikit-learn scipy matplotlib` in a virtualenv (the
Debian system setuptools cannot build `pyTsetlinMachine`; `tmu` installs cleanly). Two
patches are needed and are recorded in each `config.json`:

- `tmu` 0.8.3 with numpy ≥ 2: replace `np.uint32(~0)` with `np.uint32(0xFFFFFFFF)` in
  `clause_bank/clause_bank.py` lines 136 and 145 and `clause_bank/clause_bank_cuda.py`
  line 169.
- `tmu` hangs when its internal seed is 0; all TM seeds here are 1000 + data seed.

Then, from a run directory's code copies:

```
python sweep_d.py   runs/run05d/sweep.json      # selection, train data only
python run_b.py     runs/run05d <sweep.json>    # 5 seeds, all arms
python score_d.py   runs/run05d                 # criteria
python stability_d.py                           # run-level verdict (R-TM-01d)
python plots_d.py   runs/run05d                 # figures
```

Each run directory carries the exact code it was produced with. `generator_b.py` is
byte-identical across `run03b`, `run04c` and `run05d`, which is what makes those three
comparable.

## Where the decision stands

`rules` and `llm` ship in the first slice. `tsetlin` is parked with four runs behind it.
The open proposal, for the spring and not as a rescue of these runs: **A1 is a parity test
borrowed from a different question.** ARCH-131 asks whether the gate is accurate enough on
what it does *not* escalate, and on that question this component reads 0.962–0.989 while
escalating 18–81 %. If that is the requirement, it should be written as the requirement —
deliberately, with the reasoning recorded, and knowing it lowers a bar the component has
now failed twice.
