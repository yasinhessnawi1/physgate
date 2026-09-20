# R-TM-01b — Can a Tsetlin machine serve as the escalation decision layer?

**Status:** pre-registered, frozen before the first TM run
**Owner:** Yasin Hessnawi
**Supersedes:** R-TM-01 (run02, FAIL — killed on an infeasible A1 threshold)
**Budget:** one working day
**Decides:** whether `tsetlin` enters ARCH-132 as a backend behind the ARCH-131
`decide()` interface, or is parked.

**Why there is a second pre-registration.** R-TM-01's A1 required the TM to beat
logistic regression by 5 accuracy points on data whose noise ceiling left only 4.2
points in existence, and its A4 required a 4-point selective-prediction gain where at
most 1.6 points existed. Both criteria were unsatisfiable before the first run, and the
kill they triggered measured nothing. A5 asked for the "ten highest-weight clauses" of a
model whose clause weights are all ±1. This file repairs the generator so accuracy
margins exist, re-specifies A4 and A5 so they measure the property the architecture
needs, and leaves A2 and A3 exactly as they were so the two runs remain comparable.

**Premise this can overturn:** that a TM gives usable calibration, out-of-domain
humility, and legible clauses on structured pipeline state. If it does not, `rules` and
`llm` stay the only first-slice backends and `tsetlin` is parked.

Nothing in S4 changes after the first TM result is seen.

---

## S1. The decision being learned

Unchanged from R-TM-01. One binary decision, `escalate_to_human`, from the structured
state of a subtask at the end of an attempt — the decision ARCH-030 makes at attempt
three and ARCH-040 makes on unresolved arbitration, expressed through the ARCH-131
`decide()` interface with `kind = yes_no`. Structured state only, no text.

## S2. Data

Same 21 bits, same feature table, same split design as R-TM-01. Two changes, both
recorded before any TM run:

1. **Label noise 5 % → 1 %.** The ceiling rises from 0.950 to 0.9907, so a 5-point gap
   between arms can exist.
2. **The near-linear term becomes a parity term.** R2 is now
   `(any gate fails) XOR (reviewer_verdict == reject)` — the automated checks and the
   reviewer disagree, in either direction. R5 gains a third conjunct. Gate-failure and
   verdict marginals were re-set so the parity carries real mass.

### Hidden rule

```
escalate = 1 if any of:
  R1  attempt == 3
  R2  (any gate fails) XOR (reviewer_verdict == reject)
  R3  cross_domain_quantity_changed AND interface_node_touched
          AND reviewer_verdict == uncertain
  R4  reviewer_verdict == reject AND reviewer_confidence == high
          AND prior_failures_module >= 2
  R5  NOT gate_propagation_pass AND domain in {elec, ctrl}
          AND spec_coverage == low
then flip 1 % of labels
```

Marginals: gates pass 0.90 each (propagation 0.83); attempt 1/2/3 = 0.60/0.25/0.15;
verdict accept/reject/uncertain = 0.60/0.25/0.15; reviewer confidence low/mid/high =
0.25/0.40/0.35; domain mech/elec/ctrl/fw = 0.30/0.30/0.25/0.15; cross-domain 0.25;
interface 0.30; prior failures 0/1/2+ = 0.55/0.25/0.20; spec coverage low/mid/high =
0.30/0.40/0.30.

### Splits

| Split | Content | Size |
|---|---|---|
| Train | all domains, attempts 1 and 2 | 8 000 |
| Test-ID | same distribution, independent draw | 2 000 |
| Test-OOD-A | `attempt == 3` only | 1 000 |
| Test-OOD-B | `domain == fw` only; the no-fw arm retrains on Train and Test-ID with fw rows removed | 1 000 |
| Mixed stream | 70 % Test-ID, 15 % OOD-A, 15 % OOD-B, sampled without replacement | 2 000 |

The mixed stream is the traffic the escalation layer actually faces: mostly states like
the ones it was trained on, with a minority of genuinely new ones. A4 is measured there.

### Generator calibration (pilot, seeds 900–902, LR and GBT only)

The marginals above were chosen on pilot seeds using **only** logistic regression and
gradient-boosted trees. **The TM was never run on pilot data**, and the run proper uses
seeds 0–4, which the pilot never touches. Pilot numbers, frozen here:

| Quantity | Pilot value |
|---|---|
| Accuracy ceiling on Test-ID (1 % noise) | 0.9907 ± 0.0006 |
| LR accuracy | 0.8175 ± 0.0098 |
| GBT accuracy | 0.9902 ± 0.0006 |
| Headroom above LR | **0.173** |
| Escalation base rate | 0.463 |
| Mixed-stream error reduction at 80 % coverage — LR | 0.184 ± 0.014 |
| Mixed-stream error reduction at 80 % coverage — GBT | 0.028 ± 0.054 |
| Train support: R1 / R2 / R3 / R4 / R5 | 0 / 3 587 / 95 / 135 / 226 |

R1 has zero support in train by construction (`attempt == 3` never occurs there), so it
is not learnable and A5 counts only R2–R5.

## S3. Models

| Arm | Implementation | Role |
|---|---|---|
| TM | `tmu` TMClassifier, standard (unweighted) clauses, clauses 200–500, T and s from a short sweep on train only | the candidate |
| LR | scikit-learn logistic regression on the same 21 bits | linear baseline |
| GBT | scikit-learn `HistGradientBoostingClassifier` | strong non-linear baseline |
| RULE | hand-coded current rule: escalate if `attempt == 3` or any gate fails | what the first slice ships |

Confidence for TM: `P(y=1|x) = clip(0.5 · (1 + clip(v, −T, T)/T), 0, 1)` with `v` the
class-1 clause sum. Temperature-scaled variant: one parameter, `p = sigmoid(v / (T·τ))`,
τ fitted by NLL on a 500-row slice of train. LR and GBT use `predict_proba`.

Five seeds (0–4) per arm; mean and standard deviation reported. Library versions pinned
in `config.json`.

## S4. Acceptance criteria (pre-registered, frozen)

All five must hold for the TM arm, on the mean over five seeds.

| # | Criterion | Threshold | Why this number |
|---|---|---|---|
| A1 | Accuracy on Test-ID | within 3 pts of GBT **and** ≥ 5 pts above LR | unchanged from R-TM-01; now feasible — the pilot leaves 17.3 points between LR and the ceiling, so both halves can be met simultaneously |
| A2 | ECE on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 after temperature scaling | unchanged from R-TM-01, which passed it (0.081 raw, 0.037 scaled); kept so the two runs compare directly |
| A3 | Out-of-domain humility | mean confidence on OOD-A and on OOD-B each ≥ 0.15 below same-model Test-ID confidence | unchanged from R-TM-01, which reached 0.153 and 0.131; kept so the near-miss on OOD-B is retested rather than redefined |
| A4 | Selective prediction **on the mixed stream** | abstaining on the lowest-confidence 20 % reduces the error rate by ≥ 40 % relative to full coverage | re-specified. R-TM-01's version was unreachable: on a pure in-distribution stream at the noise ceiling there is no recoverable error. On the mixed stream the abstention budget (20 %) is roughly twice the error mass, so a perfectly ordered confidence signal reaches 100 %; the pilot baselines reach 18 % (LR) and 3 % (GBT), so 40 % separates a useful signal from an ordinary one |
| A5 | Interpretability, per term | ≥ 3 of the 4 learnable terms (R2–R5) **recovered** | re-specified. A standard TM has no clause weights, so "ten highest-weight clauses" is undefined; and a top-ten ranking is dominated by duplicate clause bodies. Term-level recovery is what the human in the approval queue actually needs: an explanation naming the condition that fired |

**Recovered**, for A5, means: some positive-polarity clause contains every literal of the
term, with at most one extra literal, and on train has precision ≥ 0.85 and fires on
≥ 25 % of that term's positive examples. For the parity term R2, recovery requires clauses
for **both** directions — at least one `NOT gate_i AND NOT verdict=reject` shape and at
least one `all gates pass AND verdict=reject` shape.

Report LR and GBT on A1, A2 and A4, and on A3 for the cross-check: if GBT also passes A3,
humility is not TM-specific and the argument narrows. Report RULE on A1 only. Also report,
without gating on them: the routing rate at an escalation threshold of 0.8 (ARCH-131's
"below threshold routes to ARCH-130") on each split, and the number of distinct clause
bodies needed to cover 80 % of escalate decisions.

## S5. Kill criteria

Any one of these parks the component:

- A2 fails even after temperature scaling
- A3 fails on both OOD sets
- A1 fails against LR
- the run cannot complete in one day

Failing A4 or A5 alone does not kill it; it narrows the claim and is recorded. ARCH-132's
entry condition for `tsetlin` is all five, so a narrowed claim means the backend does not
enter without an explicit amendment to ARCH-132.

## S6. Outputs

A run directory containing: this file frozen, generator code with seeds, the pilot record,
resolved config with library versions, per-seed metrics as JSON, reliability diagrams per
arm, the term-recovery table and readable clauses per seed, and `RESULT.md` stating pass
or fail per criterion with the numbers.

If pass: `ARCH-13x — Tsetlin escalation backend` is written against the ARCH-131
interface, with this run as its baseline evidence, and ARCH-132's contingent row resolves.

If fail: this file moves to `parked/` with `RESULT.md` beside it, ARCH-132's `tsetlin` row
stays contingent, and nothing else in the architecture changes.

## S7. What this does not test

Text input. Real pipeline state. The `choice` and `score` question kinds in ARCH-131 —
this tests `yes_no` only. Concept drift over a semester. Latency and cost, which R-JEV-01
does measure. Whether calibration survives the move from synthetic to real decisions.
