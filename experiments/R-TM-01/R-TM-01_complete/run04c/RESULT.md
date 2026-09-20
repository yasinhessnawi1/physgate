# R-TM-01c — RESULT

**Verdict: all four gating criteria pass.** A1, A2, A3 and A4 hold on the mean over five
seeds, and A3 holds on every individual seed. Under ARCH-132 as amended, this resolves the
`tsetlin` row.

**My recommendation is to not resolve it on this run alone.** The pass is real arithmetic
on leak-free code, and the A3 effect is robust — but the *joint* pass depends on which
configuration the sweep lands on, and a replicated re-run of the same selection rule lands
on one that fails A1. One confirmatory run fixes this. Details in "How much to trust this".

Run `run04c`, 5 seeds, TM = tmu 0.8.3, 500 clauses / T=40 / s=3.0 / 60 epochs, selected by
the humility-constrained sweep. Generator, splits, metric code and seeds byte-identical to
R-TM-01b; the sweep objective is the only change.

---

## S4 criteria

| # | Criterion | Threshold | R-TM-01b | R-TM-01c | |
|---|---|---|---|---|---|
| A1 | Test-ID accuracy | within 3 pts of GBT, ≥ 5 pts above LR | 0.9726 ✓ | **0.9677** (GBT 0.9890, gap 2.13 pts; LR 0.8263, +14.1 pts) | **PASS** |
| A2 | ECE on Test-ID | ≤ 0.10 raw or ≤ 0.06 scaled | 0.070 ✓ | **0.086 raw**, 0.015 temperature-scaled | **PASS** |
| A3 | OOD humility | each ≥ 0.15 below same-model Test-ID | 0.117 / 0.109 ✗ | **0.225 ± 0.007 / 0.206 ± 0.024** | **PASS** |
| A4 | Mixed-stream selective prediction | ≥ 40 % error reduction | 0.425 ✓ | **0.641 ± 0.035** (LR 0.170, GBT 0.001) | **PASS** |
| A5 | Term recovery | — | 0 / 4 | **0.2 / 4** | reported, not gating |

A3 per seed: OOD-A 0.226, 0.230, 0.217, 0.217, 0.235 — OOD-B 0.211, 0.250, 0.189, 0.190,
0.189. Every seed clears 0.15 on both sets, which was not true in R-TM-01b (OOD-A ranged
0.052–0.167 there). No kill criterion fires.

**The single-variable claim holds.** Changing only the sweep objective moved A3 from
0.117/0.109 to 0.225/0.206. The generator, splits, seeds, confidence formula and metric
code are byte-identical to R-TM-01b; the selected configuration went from T=20, s=5 to
T=40, s=3. The humility floor was measured entirely inside the training split — 12 of 48
configurations met it (`fig3_sweep_landscape.png`).

## Routing, and what the gate decides by itself

Routing rate at the 0.8 threshold (ARCH-131), and accuracy on the decisions it does *not*
route:

| | Test-ID | OOD-A | Test-ID (no-fw) | OOD-B | Mixed |
|---|---|---|---|---|---|
| TM routed to human | 0.230 | **0.778** | 0.223 | **0.807** | 0.398 |
| TM accuracy where it did not ask | 0.989 | **0.988** | — | **0.977** | — |
| R-TM-01b routed | 0.170 | 0.483 | 0.223 | 0.453 | 0.276 |
| R-TM-01b accuracy where it did not ask | 0.987 | **0.547** | — | 0.975 | — |
| GBT routed | 0.003 | 0.003 | 0.004 | 0.002 | 0.003 |

This is the number that matters operationally, and it is the strongest result in the run.
R-TM-01b answered half of the unseen-attempt decisions by itself and was right on 55 % of
them. R-TM-01c answers 22 % of them and is right on 99 %. The GBT answers all of them,
always, at 0.3 % routing, and is right on 47 %.

It also settles the question raised against R-TM-01b's threshold: at a 0.117 confidence
gap the routing delta was 31 points; at 0.225 it is 55 points. Both are far outside seed
noise (sd ≤ 0.024), so **0.15 is a defensible conservative bar but not because smaller gaps
are indistinguishable** — they are clearly distinguishable. If the threshold is meant to
protect routing separation, it should grade routing separation.

## How much to trust this

An adversarial audit of the run found no leakage and no metric error: the sweep touches
only the 8 000-row train split, the pseudo-OOD fits genuinely exclude every mech row and
every attempt-2 row, fit and validation rows are disjoint, A3 uses the same model on both
sides, A4's stream is exactly 70/15/15 without replacement, and every artefact reproduces
bit-exactly from the frozen code. Four things it found that belong in the record:

**1. The pass depends on where the sweep lands, and that is noisier than the margin.** Each
configuration is fitted once. Four configurations are decision-relevant:

| Configuration | How it was selected | A1 | A2 | A3 | A4 | Gating |
|---|---|---|---|---|---|---|
| 500 / T=40 / s=3.0 | **the pre-registered sweep** | 0.9677 (gap 0.021) ✓ | 0.086 ✓ | 0.225 / 0.206 ✓ | 0.641 ✓ | **PASS** |
| 500 / T=40 / s=2.0 | nearest qualifying neighbour | 0.9714 (gap 0.018) ✓ | 0.082 ✓ | 0.216 / 0.181 ✓ | 0.569 ✓ | PASS |
| 200 / T=20 / s=2.0 | **the same rule, sweep replicated over 3 seeds** | 0.9534 (gap **0.036**) ✗ | 0.087 ✓ | 0.195 / 0.191 ✓ | 0.626 ✓ | **FAIL (A1)** |
| 500 / T=20 / s=3.0 | identical validation accuracy, 0.006 under the floor | 0.9688 ✓ | 0.065 ✓ | **0.135** / 0.175 ✗ | **0.376** ✗ | FAIL (A3, A4) |

Read it this way: **A3 is robust.** Every configuration the humility rule admits clears the
floor on the real test sets — 0.195 to 0.225 on OOD-A, 0.181 to 0.206 on OOD-B, against a
0.15 bar. The *joint* pass is not robust: a three-seed-replicated run of the identical rule
selects a 200-clause model that satisfies A3 comfortably and misses A1 by 0.6 points. The
sweep optimises accuracy subject to humility but has no knowledge of A1's "within 3 points
of GBT" bar, so nothing in the procedure protects the criterion that then fails.

**2. This run confirms a value it did not discover.** The T ≈ 40 region was identified in
R-TM-01b's post-hoc frontier, which was computed with the OOD sets in hand. The selection
rule's free parameters — the 0.15 floor, the two slices, requiring both rather than either
— were authored by someone who knew that. The code is clean and the rule uses no test data,
but this is a transferability check of a known answer, not an independent discovery. The
floor's pass window on this grid is roughly [0.145, 0.205]; 0.15 sits just above the point
where the rule would have selected a failing configuration.

**3. Out-of-domain accuracy fell, and the routing table is why that is acceptable.** On the
full OOD-B split, accuracy dropped from 0.890 to 0.740 (argmax rule) or 0.874 to 0.840
(probability rule — the two TM decision rules disagree here, see 4). Taken alone that reads
as a worse model. But the drop is concentrated in decisions the gate now hands to a human:
on what it still answers by itself, accuracy is 0.977 on OOD-B and 0.988 on OOD-A, against
R-TM-01b's 0.975 and 0.547. Off-domain calibration also improved on both sets. An
escalation gate that loses accuracy only on cases it escalates is behaving as specified —
but the raw split accuracy should be quoted with the routing table, never alone.

**4. A1 grades a different decision rule than A2–A4.** TM accuracy for A1 comes from the
argmax over both class sums (0.9677); every other criterion is computed from the class-sum-1
probability, whose accuracy is 0.9599. On that rule A1's gap to GBT is 0.0291 — still
inside the 3-point band, by 0.0009. This is inherited unchanged from R-TM-01 and R-TM-01b,
so it does not affect comparability, but A1 is certifying a classifier the other criteria
do not measure. It should be made one rule in any further run.

## What I would do

The component now has a real result behind it: **calibrated, distribution-aware confidence
that no baseline reproduces, and that routes three and a half times as many novel-state
decisions to a human while answering the rest at 99 % accuracy.** That is the property
ARCH-131 was built to consume, and it has now survived a selection rule that never saw the
test sets.

Before resolving ARCH-132's row I would want one confirmatory run, R-TM-01d, changing three
things, all pre-registrable and all cheap:

1. **Replicate the sweep.** Three tmu seeds per configuration, median of accuracy and of
   both pseudo-OOD drops. Roughly seven minutes of compute, and it removes the 0.005-margin
   fragility entirely.
2. **Put A1's bar inside the selection rule.** The sweep should require both the humility
   floor and a validation accuracy within the A1 band, rather than discovering the accuracy
   constraint only at scoring time.
3. **Make the TM decision rule one thing** — the class-sum probability, since that is what
   the routing threshold consumes — and grade A1 on it.

Optionally, restate A3 as routing separation, which is scale-free, is what the architecture
actually uses, and does not depend on the model's own tuning scale. That is an amendment to
make deliberately, with both numbers already on the table, not a post-hoc swap.

## Deviations, assumptions, provenance

- Generator, splits, arms, confidence formula and metric code identical to R-TM-01b; only
  `sweep_c.py` and the A5 de-gating in `score_c.py` differ.
- Pilot record (`pilot.json`) carried over from R-TM-01b unchanged; the generator was never
  re-calibrated for this run.
- RULE arm is still the assumed rule (`attempt == 3` or any gate fails).
- Temperature fitted on 500 train rows, as pre-registered; A2 passes on raw ECE regardless.
- The replicated sweep, the four-configuration comparison and the autonomy table are
  **post-hoc diagnostics**. They do not change the verdict, and none of them was used to
  select anything.
- **No S4 threshold was changed after any TM result.**

## Contents

`R-TM-01c.md` (frozen pre-registration) · `R-TM-01b.md` (the superseded one, for reference)
· `sweep_c.py` `run_b.py` `score_c.py` `generator_b.py` `generator.py` `experiment.py`
`plots_c.py` `plots_b.py` `sweep_c_replicated.py` (frozen copies) · `config.json` ·
`sweep.json` (48 configurations with pseudo-OOD humility) ·
`sweep_replicated_diagnostic.json` · `metrics_seed{0..4}.json`, `metrics_all.json`,
`summary.json` · `preds_seed*.npz` · `fig1_reliability.png` · `fig2_routing.png` ·
`fig3_sweep_landscape.png` · `fig4_autonomy.png` · `alt_configs/` (the three comparison
configurations, each with its own metrics and summary).
