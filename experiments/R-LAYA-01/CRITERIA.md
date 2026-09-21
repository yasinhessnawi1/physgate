# R-LAYA-01 pre-registration

**Status:** frozen before any model was run, any checkpoint downloaded or any
metric produced.
**Written:** 2026-09-21
**Rule:** nothing in this file may change after the first metric is produced. If
a measurement turns out to be impossible as specified, that fact is recorded in
`RESULT.md` as a deviation, with its reason, and the criterion is scored as
failed rather than rewritten. An amendment is a new experiment that cites this
one; this file stays as it is.

---

## 1. Question

Can Laya serve as the `laya` backend of the escalation decision interface
(ARCH-131), and so enter the backend register (ARCH-132)? Concretely: is it
calibrated on distribution, does it become measurably less confident and
escalate measurably more off distribution, and is it safe on the decisions it
keeps?

ARCH-131 asks whether the decisions a backend does **not** escalate are safe. It
does not ask whether the backend is the strongest available classifier. There is
therefore **no accuracy-parity criterion** here. That criterion was retired after
R-TM-01d, where it was shown to be borrowed from a different question and to sit
inside the run-to-run noise of the thing it was meant to discriminate.

## 2. What is under test

**Laya**, github.com/NandhaKishorM/laya, Apache-2.0. A multilingual,
non-autoregressive decision engine: it evaluates typed questions over a state in
a single forward pass, with no text generation, and is trained with
reinforcement learning against strictly proper scoring rules. Calibration is
what it is optimised for, which is what makes C1 a test of its central claim
rather than of an incidental property.

**Everything is pinned, because the repository is three days old and was pushed
the day before this file was written.** An unpinned run here is unreproducible
within a week.

| Thing | Pin |
|---|---|
| Repository commit | `42626c348753fbb17572a813127df2278a1ec527` (2026-09-20) |
| Package | `laya==0.3.4` from PyPI |
| Checkpoint | `convaiinnovations/laya-typed-decisions`, revision `f9ab0b228f0fc0f14d873dbc99038f135c2da1b2` (2026-09-19) |

The question put to every arm, in Laya's own schema:

```json
{"escalate": {"type": "noul",
              "instructions": "Should this subtask be escalated to a human reviewer?"}}
```

## 3. The arms

Five seeds each wherever training is involved. `R` is deterministic and is run once.

| Arm | What |
|---|---|
| **L0** | Laya zero-shot on the pinned checkpoint. **Expected to fail. Reported for completeness; the entry decision does not rest on it** |
| **L1** | Laya fine-tuned on Train only, using the repository's own reinforcement-learning fine-tuning notebook adapted to the available accelerator (fp16; the card has no bfloat16). **The entry decision rests on this arm** |
| **T** | Tsetlin machine, the configuration R-TM-01d selected, rerun here |
| **G** | HistGradientBoosting |
| **R** | The hand rule, i.e. the deterministic conditions of ARCH-030 and ARCH-040 |

Temperature for **L0, L1 and T** is fitted on a 500-sample slice of **Train
only**, drawn once with a fixed seed and **identical for every arm**, so that
temperature fitting is not itself a source of difference between arms. `G` and
`R` are not temperature-scaled; `G` reports its native probabilities and `R`
emits confidence 1.0 by construction.

## 4. Rules of fair play

- **R1 Same draw.** Every arm sees the same samples, labels, seeds and splits,
  from R-TM-01's generator, reused unmodified.
- **R2 Native representation, one source.** The generator already returns the
  raw field dictionary alongside the bit vector from the same sample. Arms that
  consume bits get the bit vector; Laya gets the same sample serialised as JSON.
  Neither is re-derived and neither arm sees a sample the others did not.
- **R3 The serialisation is a fixture, not a variable.** One function produces
  the JSON for every Laya call. It emits **exactly the raw generator fields,
  under the ARCH-010/ARCH-012 field names, with readable values**
  (`"attempt": 2`, `"reviewer_verdict": "accept"`). It contains **no derived
  feature, no engineered summary and never the label or anything computed from
  it**. Its source and one example per split are committed with the run. Without
  this rule every other criterion measures an unknown.
- **R4 Train only.** No arm is fitted, tuned, temperature-scaled or
  early-stopped on any test split. The out-of-distribution sets are read once,
  at measurement.
- **R5 First honest version.** No arm is tuned after its numbers are seen. Any
  edit after a measured run means every seed is rerun for every arm, and the
  reason is recorded in `RESULT.md`.
- **R6 Frozen weights, zero tokens.** ARCH-131 admits a backend only if it
  spends no tokens on the decision and its weights are frozen at a recorded
  version. Both hold here and both are stated in `RESULT.md`.

## 5. Workload

R-TM-01's generator, seeds and splits, **reused exactly**: Train, Test-ID,
Test-OOD-A (`attempt == 3`), Test-OOD-B (unseen domain, with the retrained arm
for OOD-B as R-TM-01 defined it). The label is the same hidden-rule output with
the same **5 % noise**, which puts the achievable accuracy ceiling at about
0.95. That ceiling is stated here, before the run, because R-TM-01's first
pre-registration was killed by a threshold that sat above its own ceiling.

`generator_b.py` is byte-identical across R-TM-01's runs 03b, 04c and 05d,
verified by checksum before this file was written. Its checksum is recorded in
the run's resolved config.

## 6. Measurements

All on the mean over seeds, at the ARCH-131 routing threshold of **0.8**.

### C1 Calibration
Expected calibration error, 10 bins, on Test-ID.
**Passes at ECE ≤ 0.10 raw, or ≤ 0.06 after temperature scaling.**

### C2 Humility
On **each** out-of-distribution set, both of:
- mean confidence at least **0.15 below** the Test-ID mean, and
- escalation rate at least **20 points above** the Test-ID escalation rate.

### C3 Selective accuracy
Accuracy on the decisions the backend does **not** escalate, on Test-ID, OOD-A
and OOD-B separately. **Passes at ≥ 0.95 on all three.**

### C4 Latency
p50 per decision. **Gated on the laptop**, which is where the orchestrator and
its sessions actually run, and where the interface would be called: **p50 ≤ 500 ms**.
Also measured and reported, not gated, on the server, whose two CPU cores make it
the slower of the two for a single forward pass. Both machines' specifications are
recorded in the resolved config. p90 and p99 are reported for both.

### C5 Assumption mismatches
A written list, one entry per place Laya's model had to be worked around: what
ARCH-131 needs, what Laya offers, what was done, and whether resolving it would
require changing ARCH-131 or ARCH-010. Written during implementation, not after
seeing the numbers.

## 7. Acceptance

`laya` enters ARCH-132 as a contingent backend only if **L1** satisfies **C1,
C2, C3 and C4**.

**Kill criteria. Any one parks the backend:**
- C1 fails after temperature scaling;
- C2 fails on **both** out-of-distribution sets;
- C3 fails on Test-ID;
- L1 cannot be trained on the available accelerator within 12 hours.

**The feasibility of L1 is checked before the 12-hour budget is spent, not by
spending it.** The checkpoint is a ModernBERT-large encoder and the card is
compute capability 7.0, with no bfloat16 and no second-generation fused
attention. Whether that combination trains at all is the first question the run
answers, and a negative answer is a result recorded against the fourth kill
criterion rather than a day lost.

## 8. Out of scope, declared here so it cannot be claimed later

- **Accuracy parity against any arm.** Deliberately absent, see §1.
- The `choice` and `score` question kinds of ARCH-131. Only `yes_no` is tested.
- Free-text state. The first slice passes structured state only.
- Multilingual behaviour, which Laya is built for and this question does not use.
- Drift over time, adversarial states, and behaviour on a real pipeline rather
  than a generated one.
- Whether `laya` is better than `tsetlin`. Both are measured against the same
  criteria; neither is measured against the other.

## 9. Provenance to attach to any summary

**C3's framing and its threshold were informed by R-TM-01d's post-hoc
observation** that the Tsetlin arm was accurate on what it kept while escalating
heavily. This file is therefore the **first prospective test of the
selective-accuracy criterion**, and it is applied identically to every arm,
including the two baselines that were never proposed as backends. The criterion
has not been prospectively validated on any data before this run.

The Tsetlin arm carries R-TM-01's own provenance caveat: the configuration being
rerun here was selected in a region first identified with the
out-of-distribution sets in hand. Its numbers in this run are a transferability
check of a known answer, not an independent result, and any summary that cites
them says so.
