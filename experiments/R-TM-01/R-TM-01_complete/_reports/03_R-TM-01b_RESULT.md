# R-TM-01b — RESULT

**Verdict: FAIL.** A3 fails on both out-of-domain sets, which is a kill criterion (S5).
Under ARCH-132's entry condition — all five criteria — the `tsetlin` backend does **not**
enter. That row stays contingent and nothing else in the architecture changes.

**A1, A2 and A4 all pass.** The repaired generator did its job: the criteria that were
unsatisfiable in R-TM-01 are now satisfied with room to spare. The failure moved to a
different place, and it is a more useful failure than the first one.

Run `run03b`, 5 seeds, TM = tmu 0.8.3, 500 clauses / T=20 / s=5.0 / 60 epochs, selected by
a 48-point sweep on train only. Pre-registration frozen in `R-TM-01b.md` before the first
TM run; generator calibrated on pilot seeds 900–902 with LR and GBT only. Compute: ~5
minutes.

---

## S4 criteria

| # | Criterion | Threshold | Measured (mean ± sd, 5 seeds) | |
|---|---|---|---|---|
| A1 | Accuracy on Test-ID | within 3 pts of GBT and ≥ 5 pts above LR | TM **0.9726 ± 0.0050**; GBT 0.9890 (−1.6 pts); LR 0.8263 (+14.6 pts) | **PASS** |
| A2 | ECE on Test-ID | ≤ 0.10 raw or ≤ 0.06 scaled | raw **0.070**; temperature-scaled **0.017** | **PASS** |
| A3 | OOD humility | each OOD set ≥ 0.15 below same-model Test-ID confidence | OOD-A **0.117 ± 0.052**; OOD-B **0.109 ± 0.046** | **FAIL** |
| A4 | Selective prediction, mixed stream | ≥ 40 % error reduction at 80 % coverage | **42.5 % ± 23.0** (LR 17.0 %, GBT 0.1 %) | **PASS** |
| A5 | Term recovery | ≥ 3 of the 4 learnable terms recovered | **0 of 4** on every seed (R2 recovered in one direction only) | **FAIL** |

Kill criteria: **A3 fails on both OOD sets — fires.** A1-vs-LR does not. A2 does not.
Runtime does not.

## Arms

| Arm | Test-ID acc | ECE | mixed-stream acc | mixed error reduction | conf: ID → OOD-A | ID → OOD-B |
|---|---|---|---|---|---|---|
| TM | 0.9726 | 0.070 | 0.873 | **0.425** | 0.910 → 0.793 | 0.889 → 0.780 |
| TM, temp-scaled | 0.9663 | 0.017 | — | — | 0.964 → 0.884 | 0.945 → 0.874 |
| LR | 0.8263 | 0.221 | 0.770 | 0.170 | 0.732 → 0.732 | 0.734 → 0.734 |
| GBT | 0.9890 | 0.007 | 0.909 | 0.001 | 0.987 → 0.986 | 0.987 → 0.988 |
| RULE | 0.7558 | — | — | — | — | — |

Rule recovery against the noiseless label: **GBT 0.9999, TM 0.9833, LR 0.8334, RULE
0.7603.** The parity term did what it was meant to: LR now recovers only 83 % of the rule
where the TM recovers 98 %.

**Routing at the 0.8 escalation threshold** — the statistic ARCH-131 actually consumes:

| | Test-ID | OOD-A | Test-ID (no-fw) | OOD-B | Mixed |
|---|---|---|---|---|---|
| TM | 0.170 | **0.483** | 0.225 | **0.547** | 0.276 |
| GBT | 0.003 | 0.003 | 0.004 | 0.002 | 0.003 |

The TM sends about three times as many novel-state decisions to a human as familiar ones.
The GBT sends the same 0.3 % everywhere, whatever it is looking at. This is not a
pre-registered criterion and does not change the verdict — it is reported because it is
the form in which the architecture consumes confidence, and because it says the humility
effect is present even at the T this run used.

## Why A3 failed — and why it is a hyperparameter result, not a model result

The sweep selects clauses, T and s on validation accuracy. T controls the class-sum
saturation, and therefore the confidence scale. The post-hoc frontier (3 seeds, 500
clauses, s = 5, `fig3_t_frontier.png`):

| T | Test-ID acc | ECE raw | drop OOD-A | drop OOD-B | mixed reduction |
|---|---|---|---|---|---|
| 10 | 0.9745 | 0.036 | 0.047 | 0.058 | 0.378 |
| **20** (chosen) | 0.9720 | 0.069 | 0.122 | 0.107 | 0.431 |
| 40 | 0.9595 | 0.103 | **0.170** | **0.158** | 0.454 |
| 80 | 0.9057 | 0.173 | 0.184 | 0.166 | 0.536 |
| 160 | 0.9018 | 0.278 | 0.122 | 0.122 | 0.414 |

Accuracy peaks at small T; humility needs a larger one. At T = 40 both A3 thresholds are
cleared while A1 still holds (0.9595 is 2.95 points below GBT, inside the 3-point band)
and A2 still passes after scaling. The sweep, optimising accuracy alone, selected the
value that fails A3.

**This is not a pass.** The frontier was measured with the OOD sets in hand, and choosing
T that way is exactly the leak a pre-registration exists to prevent. It licenses one
thing: a *pre-registered* selection rule that accounts for humility using train-only
signals. R-TM-01 used T = 40 and reached 0.153 / 0.131 on the same criterion — the two
runs agree that this property lives around T = 40–80, and that nothing in the sweep as
specified looks for it.

## Why A5 failed — the generator repair broke it

Zero terms recovered on every seed. Diagnosed, not guessed:

- **The shapes are genuinely absent from the clause bank.** Relaxing the matcher's
  one-extra-literal budget to six changes nothing: R2a present on 3/3 seeds, R2b on 3/3 at
  ≤ 2 extras, R3 on 1/3, **R4 and R5 on 0/3 at any budget**. Not a matcher artefact.
- **The rare terms stopped being worth learning.** Marginal support — rows where a term is
  the *only* reason to escalate — is R2 3 277, R3 61, R4 53, R5 54, out of 8 000. The
  parity term subsumes almost everything the other three flag, so recovering them buys
  about 0.7 % accuracy each, below what a clause bank will spend capacity on.
- R2 itself came within one step: on seed 1 the `all gates pass AND verdict = reject`
  clause has precision 1.00 but fires on 16 % of that direction's positives, under the
  25 % the criterion asks for.

R-TM-01 failed A1 because its rule was too easy for a linear model; R-TM-01b fails A5
because the fix made one term dominate the others. **Both failures are generator design,
not TM behaviour.** The lesson for R-TM-01c is explicit: every term the interpretability
criterion counts must carry its own *exclusive* support, and the pilot must check marginal
support, not just total support.

On legibility, which A5 reports without gating: 1.8 distinct clauses cover 80 % of the
escalate decisions (161 distinct bodies in the positive bank). The approval-queue
explanation is short — but it names only the dominant condition, "the gates and the
reviewer disagree".

## What this means for ARCH-132

- The `tsetlin` row does not resolve. It stays contingent.
- ARCH-132's logging promise — clauses as the `tsetlin` rationale — is supported only in a
  thin sense. The clauses are short and readable, but across two runs they have reliably
  recovered exactly one hidden-rule term. If the rationale field is meant to justify an
  escalation to a human reviewer, that is currently a one-line explanation of the most
  common case, not an account of the decision.
- The humility argument for preferring a TM over a neural or boosted gate now has
  consistent support across two independent generators: the TM's confidence moves
  off-distribution and the GBT's does not, at every T tested. The pre-registered *form* of
  that claim has failed twice, at 0.131 and at 0.109 against a 0.15 bar.

## R-TM-01c, if you want a third run

Three changes, all pre-registrable before any data is seen:

1. **Pre-register the sweep objective.** Select on validation accuracy subject to a
   humility floor measured on a *train-internal* pseudo-OOD slice — hold `mech` out of the
   sweep's training fold and measure the confidence drop on it. No test data, and it looks
   for the property A3 grades.
2. **Give every term exclusive support.** Restrict the parity term to the region the other
   terms do not claim (for example, R2 applies only when `verdict != uncertain` and
   `prior_failures == 0`), so R3–R5 each carry several hundred exclusive rows. Check
   marginal support in the pilot, not just total support.
3. **Decide what A3 grades.** Mean-confidence drop and routing-rate delta measure the same
   property; the architecture consumes the second. If routing rate is what matters, grade
   it — but pre-register the threshold rather than adopting it after seeing this table.

My reading: the component is not dead, and it is also not passing. Two runs have produced
one consistent positive finding (calibrated, distribution-aware confidence that no
baseline reproduces) and one consistent negative (the interpretability claim does not
survive contact with the clause bank). A third run should be aimed at the first, and A5
should either be repaired properly or dropped from the entry condition — because the
argument for this backend is now humility, not legibility.

## Deviations and assumptions

- RULE arm remains the assumed rule from R-TM-01 (`attempt == 3` or any gate fails).
- Generator marginals were set on pilot seeds 900–902 using LR and GBT only; the TM never
  ran on pilot data and the run used seeds 0–4. Tuning grid in `generator_tuning.json`.
- The sweep's selection objective (validation accuracy, tie-break ECE) was inherited
  unchanged from R-TM-01 and ran after the pre-registration was frozen.
- A4's mixed stream is 70 % Test-ID / 15 % OOD-A / 15 % OOD-B, sampled without replacement
  at a fixed seed per run seed.
- Library patches as in R-TM-01 (tmu for numpy ≥ 2; TM seeds 1000 + seed).
- **No S4 threshold was changed after the first TM result.**

## Contents

`R-TM-01b.md` (frozen pre-registration) · `generator_b.py` `run_b.py` `score_b.py`
`sweep_b.py` `pilot_b.py` `diagnostics_b.py` `plots_b.py` · `pilot.json`,
`generator_tuning.json` · `sweep.json` · `metrics_seed{0..4}.json`, `metrics_all.json`,
`summary.json` · `diagnostics.json` (T frontier, marginal support, matcher sanity) ·
`preds_seed*.npz` · `fig1_reliability.png` · `fig2_routing.png` · `fig3_t_frontier.png` ·
`parked/` (this file and the pre-registration, per S6).
