# R-TM-01d — RESULT

**Verdict: FAIL.** Of three independent runs of the selection rule, two selected the same
configuration and that configuration passes all four gating criteria. **The third found no
qualifying configuration at all.** Under S5 that is a kill criterion, and under the
run-level criterion — every replicate must select a configuration that passes A1–A4 — the
run fails.

`tsetlin` does not enter ARCH-132. The row stays contingent and the component parks with
four runs behind it.

The failure is informative and it is not about humility.

---

## What happened

| Replicate | Qualifying configurations | Selected | Passes A1–A4 |
|---|---|---|---|
| sweep seed 1000 | 1 of 48 | 500 clauses, T=40, s=2.0 | **yes** |
| sweep seed 1001 | 1 of 48 | 500 clauses, T=40, s=2.0 | **yes** |
| sweep seed 1002 | **0 of 48** | — | — |

The selected configuration, evaluated over five data seeds under the single decision rule:

| # | Criterion | Threshold | Measured | |
|---|---|---|---|---|
| A1 | Test-ID accuracy (probability rule) | within 3 pts of GBT, ≥ 5 pts above LR | 0.9706; GBT 0.9890 (gap 1.84 pts); LR 0.8263 (+14.4 pts) | PASS |
| A2 | ECE on Test-ID | ≤ 0.10 raw or ≤ 0.06 scaled | 0.0815 raw, 0.0131 scaled | PASS |
| A3 | OOD humility | ≥ 0.15 below same-model Test-ID on each | 0.216 ± 0.052 / 0.181 ± 0.054 | PASS |
| A4 | Mixed-stream selective prediction | ≥ 40 % error reduction | 0.569 ± 0.070 | PASS |
| A5 | Term recovery | — | 1.0 of 4 | reported |

A3 per seed: OOD-A 0.200, 0.254, 0.282, **0.130**, 0.213; OOD-B 0.238, **0.146**, 0.178,
**0.102**, 0.242. S4 grades the mean over five seeds, which this clears — but unlike
R-TM-01c, three of ten seed-level values fall below 0.15. The mean is doing real work here
and should not be read as five independent successes.

## Why the third replicate failed — the binding constraint is A1, not A3

Per replicate, how many of the 48 configurations met each constraint separately:

| | sweep seed 1000 | 1001 | 1002 |
|---|---|---|---|
| Humility floor (both pseudo-OOD slices ≥ 0.15) | 12 | 11 | 9 |
| Accuracy band (≥ GBT − 3 pts, on the fold) | **6** | **3** | **1** |
| Both | 1 | 1 | **0** |

Fold baselines: LR 0.8373, GBT 0.9887, so the accuracy floor is 0.9587.

The humility floor is met by roughly a fifth of the grid on every draw. The accuracy band
is met by six, then three, then one. In the failing replicate the most accurate humble
configuration missed the band by **0.0007**.

The same configuration, across the three draws:

| | seed 1000 | 1001 | 1002 |
|---|---|---|---|
| validation accuracy (500/T=40/s=2.0) | 0.9667 | 0.9647 | **0.9507** |
| pseudo-OOD-A drop | 0.224 | 0.162 | 0.185 |
| pseudo-OOD-B drop | 0.179 | 0.154 | 0.216 |

Its humility clears the floor on all three draws. Its accuracy swings 1.6 points on fitting
noise alone, and the 0.9587 band sits inside that swing. **The TM's accuracy parity with a
gradient-boosted tree is what this component cannot deliver reliably — not its confidence
behaviour.** Putting A1's band into the selection rule, which R-TM-01c's failure asked for,
is exactly what exposed this: the rule now fails on the constraint it was extended to
protect.

Two consequences worth stating plainly:

- **A rule with a feasible set of one is brittle by construction.** Requiring both floors
  at once leaves 1, 1 and 0 admissible configurations out of 48. Even where it succeeds it
  is selecting from a set of size one, which is not selection.
- **The run-level criterion did its job.** R-TM-01c looked like a clean pass on a single
  draw. Three draws show the rule works twice and collapses once. That is the thing Yasin's
  addition was written to catch, and it caught it.

## The finding to carry forward

For the selected configuration, at the 0.8 routing threshold, over five seeds:

| Split | Accuracy on the whole split | Routed to a human | Accuracy where it did not ask |
|---|---|---|---|
| Test-ID | 0.971 | 0.184 | **0.988** |
| OOD-A (`attempt == 3`) | 0.665 | 0.813 | **0.989** |
| OOD-B (`domain == fw`) | 0.647 | 0.756 | **0.962** |

Split accuracy falls by thirty points off-distribution. Accuracy on the decisions it still
answers by itself does not move. **The component gets worse at answering and much better at
knowing when not to.** That is the sentence for Hagen, and the two numbers travel together —
the split figure alone says the model broke, the retained figure alone hides that it is
handing over four decisions in five.

For comparison, the gradient-boosted tree routes 0.3 % of decisions at the same threshold
on every split, in-distribution or not, and is right on 47 % of the OOD-A cases it keeps.
No baseline in four runs has reproduced this behaviour.

## Provenance — keep this in any summary

The T ≈ 40 region these runs select was first identified in **R-TM-01b's post-hoc frontier,
which was computed with the OOD test sets in hand.** The humility rule's free parameters —
the 0.15 floor, the two pseudo-OOD slices, requiring both, the 6 500/1 500 fold — were
authored knowing that region worked. The selection code reads no test data and every
criterion was frozen before it ran, so the result is not contaminated in the statistical
sense, but the hypothesis space was narrowed by earlier looks at the test sets.

**R-TM-01d is a stability check of a known answer, not an independent discovery.** An
examiner who notices this unflagged will discount everything around it; flagged, it is
simply the honest scope of the claim. An independent demonstration needs a generator and a
novelty type none of R-TM-01, -01b, -01c or -01d has seen.

## Where this leaves the component

Four runs, one consistent positive and two consistent negatives:

- **Positive, every time:** calibrated confidence that falls off-distribution and routes
  novel states to a human, which no baseline reproduces at any setting tested.
- **Negative, every time:** clause legibility. Best observed, one hidden-rule term of four.
  Already removed from the entry condition.
- **Negative, newly established:** accuracy parity with a strong baseline is not reliably
  achievable. The gap is small — 1.8 points on the configuration that passed — but it sits
  inside the noise of the selection procedure, which is what matters for a rule that has to
  work every time.

Three honest options, in the order I would consider them:

1. **Park it, as agreed.** The evidence is a coherent story: a confidence layer that works
   and an accuracy bar it cannot clear reliably. `rules` and `llm` ship in the first slice;
   revisit if the pipeline later produces real state where the accuracy gap looks different.
2. **Re-specify A1 on architecture grounds, not to rescue the run.** The question ARCH-131
   actually poses is not "is the TM within 3 points of the best classifier" but "is the gate
   accurate enough on what it does not escalate". On that question this component reads
   0.988 / 0.989 / 0.962 while escalating 18–81 %. If that is the requirement, write it as
   the requirement — before another run, with the reasoning recorded, and knowing it lowers
   a bar the component has failed twice.
3. **Widen the feasible set, not the criteria.** A grid of 48 with two hard floors is too
   coarse; a finer T and s grid around the admissible region, with per-configuration
   medians over replicates, would let the rule select rather than accept its only option.
   This is more engineering of a rule that has now been tuned across four runs, and each
   iteration spends more of the credibility the pre-registrations were meant to build.

My reading: option 1 now, and option 2 written up as a proposal for the spring — because the
case for this backend has always been the confidence behaviour, and A1 is a parity test
borrowed from a different question.

## Deviations, assumptions, provenance

- All four pre-registered changes were implemented as written: replicated selection with an
  every-replicate requirement, A1's band inside the selection rule, one decision rule
  (class-sum probability ≥ 0.5) everywhere including the sweep, paired accuracy reporting.
- Generator, splits, data seeds, metric code identical to R-TM-01b and R-TM-01c. Pilot
  record carried over; the generator was not re-calibrated.
- The fold baselines that define the accuracy band are fitted inside the training split on
  the same 6 500 rows, scored on the same 1 500-row validation slice. No test split is read
  during selection.
- RULE arm remains the assumed rule (`attempt == 3` or any gate fails).
- Library patches as before (tmu for numpy ≥ 2; TM seeds 1000 + data seed).
- **No S4 threshold was changed after any TM result, in any of the four runs.**

## Contents

`R-TM-01d.md` (frozen pre-registration) · `sweep_d.py` `run_b.py` `score_d.py`
`stability_d.py` `generator_b.py` `experiment.py` `plots_d.py` (frozen copies) ·
`sweep.json` (three replicates × 48 configurations, with both floors per configuration) ·
`stability.json` (per-replicate verdict and the paired-accuracy table) ·
`eval_c500_T40_s2.0/` (five-seed evaluation of the selected configuration) ·
`fig1_feasible_set.png` · `fig2_paired_accuracy.png` · `parked/` (this file and the
pre-registration, per S6).
