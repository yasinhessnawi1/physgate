# R-TM-01c — Tsetlin escalation backend, third run

**Status:** pre-registered, frozen before the first TM run
**Owner:** Yasin Hessnawi
**Supersedes:** R-TM-01b (run03b, FAIL — killed on A3)
**Gates:** ARCH-132's `tsetlin` row, amended: entry requires **A1, A2, A3 and A4**.
A5 is no longer an entry condition and is reported without gating.
**Budget:** one working day.

## Why this run exists, and what changes

R-TM-01b passed A1, A2 and A4 and failed A3 at 0.117 / 0.109 against 0.15. The post-hoc
frontier showed the failure tracking a single hyperparameter: the sweep selected T on
validation accuracy alone, accuracy peaks at small T, and out-of-domain humility needs a
larger one. That diagnosis was made with the OOD sets in hand and therefore proves
nothing on its own.

**R-TM-01c is a single-variable test of it.** Exactly one thing changes:

| | R-TM-01b | R-TM-01c |
|---|---|---|
| Generator | `generator_b.py` | **identical file, identical seeds** |
| Splits, arms, confidence formula, metrics | as in R-TM-01b | unchanged |
| A1, A2, A3, A4 | as in R-TM-01b | **unchanged, same thresholds** |
| A5 | gating | reported, not gating (ARCH-132 amendment) |
| Sweep objective | validation accuracy, tie-break ECE | **accuracy subject to a humility floor measured on train-internal pseudo-OOD slices** |

If A3 now passes, the R-TM-01b failure was hyperparameter selection and not the model. If
it still fails, the humility claim does not survive a selection rule that never sees the
test sets, and the argument for this backend is in real trouble — because A5 has already
been dropped and humility is what is left.

## S1–S3

Unchanged from `R-TM-01b.md` (frozen in `runs/run03b/`), which is reproduced in this run
directory for reference. One binary `escalate_to_human` decision from 21 bits of
structured state; train 8 000 (attempts 1–2), Test-ID 2 000, OOD-A 1 000 (`attempt == 3`),
OOD-B 1 000 (`domain == fw`, with the no-fw model retrained on train and Test-ID minus fw
rows); mixed stream 70/15/15; arms TM, LR, GBT, RULE; five seeds 0–4; TM confidence from
the class-sum formula, temperature-scaled variant fitted on 500 train rows.

## S3b. The sweep objective (the one change)

Grid unchanged: clauses ∈ {200, 300, 500}, T ∈ {20, 40, 80, 160}, s ∈ {2, 3, 5, 10},
60 epochs. Selection now uses three fits per configuration, all inside the training split:

- **Accuracy fit.** Fit on 6 500 rows of train, score accuracy and ECE on the held-out
  1 500 rows. As before.
- **Pseudo-OOD-B fit.** Fit on the 6 500 rows with `domain == mech` removed. Humility =
  mean confidence on the non-mech validation rows minus mean confidence on the mech
  validation rows. This mimics OOD-B — an unseen category — using only training data.
- **Pseudo-OOD-A fit.** Fit on the 6 500 rows with `attempt == 2` removed, i.e. on
  attempt 1 alone. Humility = mean confidence on attempt-1 validation rows minus mean
  confidence on attempt-2 validation rows. This mimics OOD-A — an unseen value of an
  ordinal feature — using only training data.

**Selection rule:** among configurations whose pseudo-OOD humility is ≥ 0.15 on **both**
slices, take the highest validation accuracy, tie-breaking on lower validation ECE. If no
configuration qualifies, take the configuration with the largest
`min(pseudo-A, pseudo-B)` and record in `RESULT.md` that the floor was not satisfiable —
that outcome is itself informative and is not grounds for relaxing the rule afterwards.

The floor is set to 0.15, the same number A3 grades, so the sweep is looking for the
property the criterion measures. No test split — Test-ID, OOD-A, OOD-B, mixed — is touched
at any point in selection.

## S4. Acceptance criteria (frozen)

| # | Criterion | Threshold | Status |
|---|---|---|---|
| A1 | Accuracy on Test-ID | within 3 pts of GBT and ≥ 5 pts above LR | gating |
| A2 | ECE on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 after temperature scaling | gating |
| A3 | OOD humility | mean confidence on OOD-A and on OOD-B each ≥ 0.15 below same-model Test-ID confidence | gating |
| A4 | Selective prediction, mixed stream | ≥ 40 % error reduction when abstaining on the lowest-confidence 20 % | gating |
| A5 | Term recovery | ≥ 3 of 4 learnable terms, same definition as R-TM-01b | **reported only** |

All four gating criteria must hold on the mean over five seeds for `tsetlin` to enter
ARCH-132.

**Reported without gating**, alongside A5: the routing rate at the 0.8 escalation
threshold on each split and the routing delta between Test-ID and each OOD set, for TM and
for both baselines. This is recorded because the operational justification offered for
A3's threshold — that below roughly a 0.15 gap too little mass crosses the routing
threshold to be distinguishable from seed noise — is contradicted by R-TM-01b, where a
0.117 gap produced a 31-point routing delta. Recording both numbers on this run lets the
threshold be restated on evidence in a later amendment. **It does not change A3 here.**

## S5. Kill criteria

- A2 fails even after temperature scaling
- A3 fails on both OOD sets
- A1 fails against LR
- the run cannot complete in one day

A5 cannot kill; it is no longer an entry condition.

## S6. Outputs

Run directory with this file frozen, the sweep record including every configuration's
pseudo-OOD humility, per-seed metrics, figures, and `RESULT.md` stating pass or fail per
criterion. On pass, `ARCH-13x — Tsetlin escalation backend` is written against ARCH-131
and ARCH-132's contingent row resolves. On fail, this file moves to `parked/` with
`RESULT.md` beside it and the row stays contingent.

## S7. What this does not test

Unchanged from R-TM-01b: text input, real pipeline state, the `choice` and `score` question
kinds, drift, latency and cost. Additionally: whether a humility floor that holds on
train-internal pseudo-OOD slices transfers to novelty of a *kind* neither slice imitates.
That is the standing risk of this selection rule and it should be stated wherever the rule
is reused — including in R-JEV-01, if Jev's confidence is tuned at all.
