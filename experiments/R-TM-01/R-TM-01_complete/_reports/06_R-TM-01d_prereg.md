# R-TM-01d — Tsetlin escalation backend, confirmatory run

**Status:** pre-registered, frozen before the first TM run
**Owner:** Yasin Hessnawi
**Supersedes:** R-TM-01c (run04c — passed all four gating criteria on a single-draw sweep)
**Gates:** ARCH-132's `tsetlin` row. On a pass the row resolves and the backend enters as
an ablation arm behind ARCH-131. On a fail it parks, with three runs behind it.
**Budget:** one working day. Expected compute: ~15 minutes.

## Why this run exists

R-TM-01c passed A1–A4, but each configuration in its sweep was fitted once, and the
selected configuration cleared the humility floor by 0.0055. A three-seed-replicated run of
the identical rule selected a different configuration (200 clauses, T=20, s=2.0) which
satisfies A3 comfortably and misses A1 by 0.6 points. A selection rule that succeeds on one
draw and fails on another has not been shown to work.

This run tests the rule, not a model. Four changes, pre-registered together.

### Change 1 — replicated selection, every replicate must succeed

The selection rule is executed **independently three times**, at sweep seeds 1000, 1001 and
1002. Each replicate selects one configuration. Each distinct selected configuration is
then evaluated on the test splits over five data seeds, exactly as in R-TM-01c.

**The run passes only if every replicate's selected configuration passes all four gating
criteria.** If any replicate selects a configuration that fails any of A1–A4, or if any
replicate finds no qualifying configuration, the run fails. There is no median, no
best-of-three and no majority: a rule that only works on one draw is not a rule.

### Change 2 — A1's band moves inside the selection rule

R-TM-01c's sweep maximised accuracy subject to humility, and had no knowledge of A1's
"within 3 points of GBT" bar — which is precisely the criterion its replicated selection
then failed. The rule now requires all three of:

- pseudo-OOD humility ≥ 0.15 on **both** train-internal slices (as in R-TM-01c);
- validation accuracy ≥ (GBT validation accuracy on the same fold) − 0.03;
- validation accuracy ≥ (LR validation accuracy on the same fold) + 0.05.

The two baselines are fitted on the same 6 500-row fold and scored on the same 1 500-row
validation slice, both inside the training split. Among qualifying configurations, the rule
takes the highest validation accuracy, tie-breaking on lower validation ECE. **No test
split is read at any point in selection.**

### Change 3 — one decision rule

R-TM-01c graded A1 on the argmax over both class sums while A2, A3, A4 and the routing rate
all used the class-sum-1 probability. From this run the TM has one decision rule
everywhere: **`escalate` iff `p = clip(0.5·(1 + clip(v, −T, T)/T), 0, 1) ≥ 0.5`**, the same
quantity the 0.8 routing threshold consumes. A1 is graded on it, in the sweep and in
scoring. On R-TM-01c's numbers this is the stricter reading: it puts the TM 0.0291 from GBT
rather than 0.0213.

### Change 4 — paired reporting of accuracy and retained accuracy

Wherever this run reports accuracy on a split, it reports beside it the fraction of
decisions routed to a human at 0.8 and the accuracy on the decisions **not** routed. Split
accuracy is never quoted alone. This is a reporting rule, not a criterion, and it exists
because R-TM-01c's headline OOD-B accuracy fell 15 points while accuracy on retained
decisions rose — the two numbers mean the opposite things apart and the right thing
together.

## Provenance — read this before quoting the result

The T ≈ 40 region that R-TM-01c selected was first identified in R-TM-01b's **post-hoc**
frontier, which was computed with the OOD test sets in hand. The humility rule's free
parameters — the 0.15 floor, the choice of two pseudo-OOD slices, requiring both rather
than either, the 6 500/1 500 fold — were authored by someone who already knew that region
worked.

**R-TM-01d is therefore a transferability and stability check of a known answer, not an
independent discovery.** The selection code reads no test data and the criteria were frozen
before it ran, so the result is not contaminated in the statistical sense; but the
hypothesis space was narrowed by earlier looks at the test sets, and any claim drawn from
this run carries that qualification. It is stated here, in `RESULT.md`, and in any summary
written for a third party. An independent demonstration requires a generator and a novelty
type that none of R-TM-01, -01b or -01c has seen.

## S1–S3

Unchanged from R-TM-01c, which is unchanged from R-TM-01b: one binary `escalate_to_human`
decision from 21 bits of structured state; `generator_b.py` byte-identical, same marginals,
1 % label noise; train 8 000 (attempts 1–2), Test-ID 2 000, OOD-A 1 000 (`attempt == 3`),
OOD-B 1 000 (`domain == fw`, no-fw model retrained on train and Test-ID minus fw rows);
mixed stream 70/15/15 of 2 000, without replacement; arms TM, LR, GBT, RULE; five data
seeds 0–4; TM seeds 1000 + seed; temperature scaled on 500 train rows. Sweep grid unchanged:
clauses ∈ {200, 300, 500}, T ∈ {20, 40, 80, 160}, s ∈ {2, 3, 5, 10}, 60 epochs.

## S4. Acceptance criteria (frozen)

Per configuration, on the mean over five data seeds:

| # | Criterion | Threshold |
|---|---|---|
| A1 | Test-ID accuracy, **probability rule** | within 3 pts of GBT and ≥ 5 pts above LR |
| A2 | ECE on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 after temperature scaling |
| A3 | OOD humility | mean confidence on OOD-A and on OOD-B each ≥ 0.15 below same-model Test-ID |
| A4 | Mixed-stream selective prediction | ≥ 40 % error reduction when abstaining on the lowest-confidence 20 % |

**Run-level criterion (the point of this run):** every one of the three replicate-selected
configurations passes A1, A2, A3 and A4.

Reported without gating: A5 term recovery; routing rate and routing delta at 0.8; retained
accuracy per split; per-seed values for every gating criterion.

## S5. Kill criteria

- any replicate finds no qualifying configuration
- any replicate-selected configuration fails any of A1–A4
- A2 fails even after temperature scaling on any selected configuration
- the run cannot complete in one day

## S6. Outputs

Run directory with this file frozen, the three replicate sweeps in full, the evaluation of
each distinct selected configuration, figures, and `RESULT.md` giving pass or fail per
criterion per replicate, with the provenance paragraph above reproduced in it.

On pass: ARCH-132's `tsetlin` row resolves; the backend enters as an ablation arm; the
sentence carried forward is that the component **gets worse at answering and much better at
knowing when not to** — reported as both numbers, split accuracy and retained accuracy,
never the first alone.

On fail: this file moves to `parked/` with `RESULT.md` beside it, the row stays contingent,
and the component parks with three honest runs behind it.

## S7. What this does not test

Text input; real pipeline state; the `choice` and `score` question kinds of ARCH-131; drift;
latency and cost; and — stated again because it is the main limitation — novelty of a kind
the two pseudo-OOD slices do not imitate, on a generator the rule's authors had not already
studied.
