# R-TM-01 — Can a Tsetlin machine serve as the escalation decision layer?

**Status:** pre-registered, not yet run
**Owner:** Yasin Hessnawi
**Budget:** one working day
**Decides:** whether a `tsetlin` implementation of the escalation interface (ARCH-130 sources, ARCH-040 arbitration fallthrough) is specified as an ablation arm in ARCH-140, or parked.
**Premise this can overturn:** that a TM gives usable calibration and out-of-domain humility on structured pipeline state. If it does not, rules stay as the first slice and Jev stays the only learned candidate.

The criteria below are fixed before the first run. Nothing in S4 changes after data is seen.

---

## S1. The decision being learned

One binary decision, `escalate_to_human`, from the structured state of a subtask at the moment the control loop reaches the end of an attempt. This is the decision ARCH-030 makes at attempt three and ARCH-040 makes on unresolved arbitration. Today it is a rule. The question is whether a TM can learn it from examples, say how sure it is, and be less sure on states it has not seen.

No text input. Structured state only. That is the case the architecture needs and the case where a TM needs no embedding bridge.

---

## S2. Data

No pipeline exists yet, so the state is synthetic, generated from a hidden rule that the learner never sees. The generator must produce interactions and negations so that a linear baseline cannot recover the rule and the test is not trivial.

### Features (booleanised, mirroring ARCH-010, ARCH-012, ARCH-080, ARCH-083)

| Feature | Values | Bits |
|---|---|---|
| `gate_unit_pass` | 0/1 | 1 |
| `gate_magnitude_pass` | 0/1 | 1 |
| `gate_power_pass` | 0/1 | 1 |
| `gate_propagation_pass` | 0/1 | 1 |
| `attempt` | 1, 2, 3 | 2 (thermometer) |
| `reviewer_verdict` | accept, reject, uncertain | 3 (one-hot) |
| `reviewer_confidence` | low, mid, high | 2 (thermometer) |
| `domain` | mech, elec, ctrl, fw | 4 (one-hot) |
| `cross_domain_quantity_changed` | 0/1 | 1 |
| `interface_node_touched` | 0/1 | 1 |
| `prior_failures_module` | 0, 1, 2+ | 2 (thermometer) |
| `spec_coverage` | low, mid, high | 2 (thermometer) |

Twenty-one bits. Sample each feature from a plausible marginal (gates pass ~85 per cent, attempt 1 most common, reviewer accept ~70 per cent, and so on).

### Hidden rule (the generator's, not the learner's)

`escalate = 1` if any of:

1. `attempt == 3`
2. any gate fails **and** `reviewer_verdict == accept` (the reviewer-missed-it case, ARCH-083)
3. `cross_domain_quantity_changed and interface_node_touched and reviewer_verdict == uncertain`
4. `reviewer_verdict == reject and reviewer_confidence == high and prior_failures_module >= 2`
5. `not gate_propagation_pass and domain in {elec, ctrl}`

Apply 5 per cent label noise (flip) after the rule, so perfect accuracy is impossible and calibration has something to measure.

### Splits

| Split | Content | Size |
|---|---|---|
| Train | all domains, attempts 1 and 2 only, all other features free | 8,000 |
| Test-ID | same distribution as train, disjoint samples | 2,000 |
| Test-OOD-A | `attempt == 3` only (never seen in train) | 1,000 |
| Test-OOD-B | `domain == fw` only, with fw removed from train (retrain for this arm) | 1,000 |

OOD-A tests humility on an unseen feature value. OOD-B tests humility on an unseen category. Both are the situations the escalation layer will face when a new module type or a new failure pattern first appears in the real pipeline.

---

## S3. Models

| Arm | Implementation | Role |
|---|---|---|
| TM | `tmu` (Granmo's library) or `pyTsetlinMachine`; standard TM, clauses 200–500, T and s from a short sweep on train only | the candidate |
| LR | scikit-learn logistic regression on the same 21 bits | linear baseline |
| GBT | scikit-learn `HistGradientBoostingClassifier` | strong non-linear baseline |
| RULE | the current rule from ARCH-030/040, hand-coded, no learning | what the first slice ships |

Confidence for TM: `P(y=1|x) = 0.5 * (1 + v(x)/T)`, the Helin et al. 2025 formula, clipped to [0, 1]. Report also a temperature-scaled variant fitted on a 500-sample slice of train, since the formula's calibration is known to weaken with negative-polarity clauses. Confidence for LR and GBT: `predict_proba`.

Seeds: five per arm. Report mean and standard deviation. Pin library versions in the run directory.

---

## S4. Acceptance criteria (pre-registered)

All five must hold for the TM arm, on the mean over five seeds, for the component to enter the architecture as an ablation arm.

| # | Criterion | Threshold | Why this number |
|---|---|---|---|
| A1 | Accuracy on Test-ID | within 3 points of GBT, and at least 5 points above LR | it must recover the interactions LR cannot, and it need not beat the strongest baseline, only stay close |
| A2 | Expected calibration error on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 after temperature scaling | 0.05 is textbook well-calibrated; 0.10 leaves room for the known weakness of the class-sum formula; if temperature scaling cannot reach 0.06 the confidence is not usable for thresholding |
| A3 | Out-of-domain humility | mean confidence on Test-OOD-A and Test-OOD-B each at least 0.15 lower than mean confidence on Test-ID, on the same model | this is the property Helin et al. report and the reason to prefer a TM over a neural gate; a smaller drop is indistinguishable from noise across seeds |
| A4 | Selective prediction | abstaining on the 20 per cent lowest-confidence Test-ID samples raises accuracy on the remainder by at least 4 points | confidence must be informative, not only calibrated on average |
| A5 | Interpretability | at least three of the five hidden-rule terms appear, recognisably, among the ten highest-weight clauses | the clauses must explain the decision to the human reading the approval queue, or the interpretability argument for the TM is empty |

Report LR and GBT on A1, A2 and A4 for comparison. Report RULE on A1 only. If GBT also passes A3, note it, because then humility is not a TM-specific advantage and the argument narrows to interpretability.

---

## S5. Kill criteria

Any one of these eliminates the component from the semester and parks it:

- A2 fails even after temperature scaling
- A3 fails on both OOD sets
- A1 fails against LR (the TM cannot learn the interactions)
- The run cannot complete in one day with the libraries as installed

Failing A4 or A5 alone does not kill it; it narrows the claim and is recorded.

---

## S6. Outputs

A run directory containing: generator code with seed, the five hidden rules, resolved config, per-seed metrics as JSON, calibration reliability diagrams for each arm, the ten top clauses per seed printed in readable form, and a one-page `RESULT.md` stating pass or fail per criterion with the numbers.

If pass: I write `ARCH-13x — Tsetlin escalation layer` as an ablation arm behind the existing escalation interface, with this run as its baseline evidence.

If fail: this file is moved to `parked/` with `RESULT.md` beside it, and nothing else in the architecture changes.

---

## S7. What this does not test

Text input. Real pipeline state. Concept drift over a semester. Whether calibration survives the move from synthetic to real decisions. Each of those is a later experiment, contingent on this one passing.
