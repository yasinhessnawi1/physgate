# R-TM-01 — RESULT

**Verdict: FAIL.** The run trips a kill criterion (S5: "A1 fails against LR"), so under
the pre-registration the `tsetlin` escalation layer is parked and nothing in the
architecture changes.

**But the kill fires on a threshold that cannot be met by any model.** A1 asks the TM to
beat LR by 5 accuracy points; LR scores 0.9078 and the label-noise ceiling is 0.9502, so
A1 requires 0.9578 from a task whose maximum is 0.9502. A4 is unreachable for the same
reason. The pre-registered verdict stands as written; whether it is *informative* is the
decision in front of you. See "What the run actually decided" below.

Run `run02`, 5 seeds, TM = tmu 0.8.3, 500 clauses / T=40 / s=5.0 / 60 epochs, chosen by a
48-point sweep on train only. Total compute: ~4 minutes. Budget was one working day.

---

## S4 criteria

| # | Criterion | Threshold | Measured (mean ± sd over 5 seeds) | |
|---|---|---|---|---|
| A1 | Accuracy on Test-ID | within 3 pts of GBT **and** ≥ 5 pts above LR | TM 0.9351 ± 0.0028; GBT 0.9479 ± 0.0032 (−1.3 pts, **ok**); LR 0.9078 ± 0.0031 (+2.7 pts, **short**) | **FAIL** |
| A2 | ECE on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 scaled | raw **0.0814**; temperature-scaled 0.0375; Platt (2-param) 0.0368 | **PASS** |
| A3 | OOD humility | each OOD set ≥ 0.15 below Test-ID confidence | OOD-A **0.153 ± 0.013** (pass); OOD-B **0.131 ± 0.031** (short) | **FAIL** |
| A4 | Selective prediction | ≥ +4 pts after abstaining on lowest-confidence 20 % | **+1.3 pts** (0.9341 → 0.9468); max attainable at the noise ceiling is +1.6 pts | **FAIL** |
| A5 | Interpretability | ≥ 3 of 5 hidden-rule terms among the top 10 clauses | **1 of 5** (R2 only), all five seeds; 2 of 5 under lenient matching; 0–2 of 5 (mean 1.0) for a weighted-clause TM ranked by real weights | **FAIL** |

Kill criteria (S5): A1-vs-LR fires. A2 does not. A3 does not (it passes on OOD-A). Runtime
does not.

## Arms

| Arm | Test-ID acc | ECE | mean conf ID | conf change → OOD-A | conf change → OOD-B | selective gain |
|---|---|---|---|---|---|---|
| TM | 0.9351 | 0.081 | 0.892 | **−0.153** | **−0.131** | +0.013 |
| TM, temp-scaled | 0.9341 | 0.037 | 0.906 | −0.143 | −0.115 | +0.013 |
| LR | 0.9078 | 0.090 | 0.860 | +0.003 | +0.005 | +0.019 |
| GBT | 0.9479 | 0.029 | 0.943 | +0.002 | +0.000 | +0.001 |
| RULE (assumed) | 0.8451 | — | — | — | — | — |

Negative = less confident off-distribution, which is the direction A3 wants.

Rule recovery against the **noiseless** hidden label on Test-ID — the cleanest read of
"did it learn the interactions": **GBT 0.9973, TM 0.9833, LR 0.9524, RULE 0.8817.**

## What the run actually decided

1. **The TM learns the interactions.** It agrees with the hidden rule on 98.3 % of
   Test-ID against LR's 95.2 %, closing 62 % of the LR→ceiling gap. A1's "5 points" was
   written against noisy labels where 4.2 points is all that exists; on clean labels the
   TM–LR gap is 3.1 points. The premise A1 was meant to test — "the TM cannot learn the
   interactions" — is contradicted by the data even though the criterion fails.
2. **Out-of-domain humility is real and TM-specific.** Confidence falls 0.892 → 0.739 on
   an unseen `attempt` value and 0.884 → 0.753 on an unseen domain, while GBT does not
   move at all (0.943 → 0.944 / 0.943) and LR does not either. This is the property the
   architecture wanted from a TM, and no baseline reproduces it. It misses the
   pre-registered 0.15 on OOD-B by 0.019, within one seed's spread (sd 0.031).
3. **Calibration is usable.** 0.081 raw passes as written; one-parameter temperature
   scaling on 500 training rows halves it to 0.037 (0.033 when the temperature is fitted
   on fresh samples instead). The fitted temperature is ≈ 0.32 — the class-sum formula is
   systematically *under*-confident here, not over-confident.
4. **Interpretability is the genuine weakness.** Only R2 ("a gate fails but the reviewer
   accepted") is legible in the top ten. R5 appears as the weakened `NOT
   gate_propagation_pass` without its domain conjunct; R3 and R4 (0.3 % and 1.0 % of
   samples) are learned by no clause at all; R1 cannot be learned because `attempt == 3`
   never occurs in training — so A5's ceiling is 4 of 5, not 5 of 5. A clause bank is also
   highly redundant: 250 positive clauses collapse to ~176 distinct bodies.
5. **A4 is structurally unreachable.** With uniform 5 % label flips the error left at
   0.934 is almost all irreducible noise, spread evenly across confidence. No abstention
   policy can gain 4 points when only 1.6 exist. LR "wins" A4 (+1.9) only because it is
   further from the ceiling.

## Options

- **Accept the kill as written.** Park the component. Defensible and pre-registered; the
  cost is parking on a criterion that measured nothing.
- **Re-run as R-TM-01b with a repaired generator**, recorded as a new pre-registration:
  drop label noise to ~1 % and make the rule harder for a linear model (more XOR-like
  terms, rarer marginals) so LR lands nearer 0.80 and the A1/A4 margins exist. Re-use
  everything here unchanged; cost is a few hours, most of it waiting for a sweep.
- **Narrow the claim and keep it.** A2 passes, A3 passes on one of two sets and is the
  only arm to show the effect at all. That is enough to specify the TM as an ablation arm
  on humility and calibration grounds alone — but it needs A5 rewritten, since the
  interpretability argument did not survive contact with the clauses.

My reading: the second option, and A5 re-specified against a per-clause precision
threshold rather than a top-ten ranking, because "highest-weight clause" has no meaning
for a standard unweighted TM.

## Deviations and assumptions

- **RULE arm is assumed.** The spec does not print ARCH-030/040's rule; implemented as
  "escalate if attempt == 3 or any gate fails". Reported on A1 only, as specified.
- **"Highest-weight clauses" (A5)** does not apply to a standard TM — every clause weight
  is ±1. Ranked instead by coverage × precision on **train**, over distinct clause bodies,
  positive-polarity bank only. A weighted-clause TM ranked by real weights is reported in
  `diagnostics.json` and gives the same verdict (0–2 terms by seed, mean 1.0).
- **Temperature scaling** is the one-parameter form fitted by NLL on a 500-row slice of
  train, per S3. A two-parameter Platt fit is reported beside it.
- **OOD-B retrain** is the train and Test-ID draws with `fw` rows removed (6 837 and
  ~1 700 rows), the literal reading of S2.
- **Library**: tmu 0.8.3 needs a one-line patch for numpy ≥ 2 (`np.uint32(~0)`), and hangs
  if its internal seed is 0; TM seeds are therefore 1000 + seed. Both recorded in
  `config.json`.
- Six defects found by an independent code audit were fixed before this run; the list is
  in `config.json`. **No S4 threshold was changed at any point.**

## Contents

`generator.py` `experiment.py` `sweep.py` `run.py` `score.py` `diagnostics.py` `plots.py`
· `config.json` (resolved config, hidden rule, library versions) · `sweep.json` (48-point
grid) · `metrics_seed{0..4}.json`, `metrics_all.json`, `summary.json` ·
`clauses.txt` (top ten clauses per seed, readable) · `diagnostics.json` (ceiling,
feasibility, capacity check, A5 re-reads) · `preds_seed*.npz` ·
`fig1_reliability.png` (four arms, pooled Test-ID) · `fig2_confidence_ood.png`
(TM vs GBT, ID vs both OOD sets) · `fig3_risk_coverage.png`.
