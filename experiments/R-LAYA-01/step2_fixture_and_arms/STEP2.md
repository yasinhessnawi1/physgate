# R-LAYA-01 step 2 — the R3 fixture, the workload, and arms T, G, R, L0 on Train

**A step report, not the result.** `RESULT.md` is written at step 4. **No arm was
scored on any test split.** Test-ID, OOD-A and OOD-B were not constructed in any
process this step ran, and the code that could construct them refuses to unless
step 4 asks it to.

Criteria frozen at `e12d153` (original `7b85d29`). Harness committed before each
fitting run per §6.1: `7433c51`, then `0396efb`, then `cf70c9c`, which is the
commit the artefacts in this directory were produced from. Raw records:
`step2_arms_gr_l0.json`, `step2_arm_t.json`.

---

## 1. The fixture, and the Train example

`rlaya/fixture.py`. One function, `serialise(raw, i)`; nothing else in the
experiment serialises a state.

**Seed 0, Train, item 0** — 147 tokens through Laya's own `build_sequence`:

```json
{"gate_unit_pass": true, "gate_magnitude_pass": true, "gate_power_pass": true,
 "gate_propagation_pass": true, "attempt": 2, "reviewer_verdict": "accept",
 "reviewer_confidence": "mid", "domain": "mech",
 "cross_domain_quantity_changed": false, "interface_node_touched": false,
 "prior_failures_module": 0, "spec_coverage": "mid"}
```

The Test-ID, OOD-A and OOD-B examples are generated at step 4, at measurement,
and committed with the run then. Settled on 2026-09-21, before any test split
existed: R3 says "committed with the run" without saying when, and a deferred
example costs nothing while an early read of a test split cannot be undone.

### Token lengths under the real fixture, against step 1's provisional

| | min | p50 | mean | p90 | p99 | max |
|---|---|---|---|---|---|---|
| step 1, provisional | 146 | 147 | 146.752125 | 147 | 148 | 148 |
| **step 2, the fixture** | **146** | **147** | **146.752125** | **147** | **148** | **148** |

They are not merely close. The driver compared the **8 000 serialised strings**
rather than their summary statistics: `n_differing_strings: 0`. The provisional
serialisation and the fixture emit byte-identical JSON on every Train item of
seed 0. The fixture added the ARCH provenance, the uniform boolean rule and the
documentation; it changed no output.

**So step 1's wall-clock arithmetic stands exactly as written** — 0.1512 h per
seed, **0.756 h for the five-seed arm** — because it was computed on precisely
these strings. Nothing needs restating.

### The two things the fixture had to get right

**Field names.** R3 asks for "the ARCH-010/ARCH-012 field names". The mapping was
made deliberately and most of it does not exist: see §2. The fixture keeps the
generator's own names, and the reading is forced by R3's own examples —
`"attempt": 2` and `"reviewer_verdict": "accept"` are verbatim two of the
generator's raw field names, so those *are* what the phrase points at. What R3 is
excluding is `generator.BIT_NAMES`, the 21 booleanised names (`"attempt>=3"`,
`"verdict=accept"`, `"reviewer_conf>=high"`), which are the derived features it
forbids.

**Boolean rendering.** Applied uniformly to the four gates and the two flags —
every field the generator stores as `int8` 0/1 and no others — stated in the
fixture's docstring and named here as a judgement call the orchestrator made on
2026-09-21, so a reader can disagree with it. `attempt` and
`prior_failures_module` stay integers. `domain` keeps the generator's vocabulary
(`mech`, `elec`, `ctrl`, `fw`) rather than ARCH-010's, because translating a
*value* is a substitution rather than a rendering.

---

## 2. The ARCH-010 / ARCH-012 mapping, and what did not map

Recorded in `rlaya/fixture.py:ARCH_PROVENANCE` and as **C5 M7**.

| generator field | ARCH counterpart |
|---|---|
| `domain` | **ARCH-010 `domain`** — the only exact field-name match |
| `attempt` | ARCH-012 "attempt count"; ARCH-030's three-attempt repair budget |
| `reviewer_verdict` | ARCH-012 "review result"; ARCH-131 "the reviewer verdict" |
| `gate_unit_pass`, `gate_magnitude_pass`, `gate_power_pass`, `gate_propagation_pass` | ARCH-012 "gate result", ARCH-031, ARCH-080 — as **one** result, not four named gates |
| `cross_domain_quantity_changed` | ARCH-010 quantities marked `cross`, ARCH-051 sizing; ARCH-131 "the changed-node summary". **No field name** |
| `interface_node_touched` | ARCH-010 `kind: interface`, ARCH-011; ARCH-131 "the changed-node summary". **No field name** |
| `reviewer_confidence` | **none** |
| `prior_failures_module` | **none** |
| `spec_coverage` | **none** — ARCH-022 is about what a spec contains, not a per-attempt state field |

**One of twelve fields has a literal ARCH field name.** ARCH-010 defines a graph
*node*; ARCH-012 describes a ledger *line* in prose. Neither is a subtask-state
schema, and ARCH-131 promises `decide(question, state)` over "the structured
subtask record at the end of an attempt" without any decision defining that
record. Three of the twelve fields the escalation question turns on have no home
in the specification at all.

This is the first C5 entry whose "would resolving it require changing ARCH-131 or
ARCH-010" answer is **yes** — see §7 D6.

---

## 3. Arm T — Tsetlin, in its own environment, on a named machine

The configuration R-TM-01d selected, from `run05d/config.json`
`selected_config_evaluation.hp`: **clauses 500, T 40, s 2.0, epochs 60**. Two
fits per seed on Train, exactly as `run_b.py` does them — the main model on
Train, and the no-firmware retrain on Train-without-fw that OOD-B is measured
against at step 4.

**Environment, exactly as the amended §3 specifies:**

| | |
|---|---|
| Python | **3.11.15** |
| `tmu` | **0.8.3** |
| `numpy` | **2.4.6** |
| `scikit-learn` | **1.9.1** |
| `scipy` | **1.17.1** |
| `matplotlib` | **3.11.2** |

**The machine, which R-TM-01 never recorded** — §6: arm T's timings here are a
fresh measurement on a named machine, not a reproduction of anything:

| | |
|---|---|
| Host | `coder-yasinh-declassifai-55c6d799db-tsskx` (`ssh main.DeclassifAI.yasinh.coder`) |
| CPU | **Intel Xeon Platinum 8168 @ 2.70 GHz** |
| Cores available | `nproc` 2; cgroup `cpu.max` `600000 100000` |
| Memory | 1 583 915 700 kB |
| OS | Linux 6.8.0-64-generic, glibc 2.39 |

**The two patches, applied to the installed package and recorded with
before-and-after checksums:**

| file | occurrences of `np.uint32(~0)` | sha256 before → after |
|---|---|---|
| `clause_bank/clause_bank.py` | **2** (R-TM-01 recorded lines 136, 145) | `d8e2b816…` → `7888809c…` |
| `clause_bank/clause_bank_cuda.py` | **1** (line 169) | `02a4c180…` → `9608f2de…` |

The second "patch" is a convention rather than a source change and is applied as
`workload.TM_SEED_OFFSET`: TM seed = 1000 + data seed, because `tmu` hangs when
its internal seed is 0.

**Fits, five seeds, Train only:**

| seed | TM seed | fit s (both models) | Train accuracy, in sample | §3 temperature, main | §3 temperature, nofw |
|---|---|---|---|---|---|
| 0 | 1000 | 2.46 | 0.9714 | 0.1997 | 0.1856 |
| 1 | 1001 | 2.50 | 0.9740 | 0.1720 | 0.1587 |
| 2 | 1002 | 2.51 | 0.9708 | 0.1972 | 0.1575 |
| 3 | 1003 | 2.46 | 0.9724 | 0.1764 | 0.1927 |
| 4 | 1004 | 2.52 | 0.9702 | 0.1664 | 0.1906 |

Both models pickled successfully for every seed. A fingerprint of the Train class
sums is recorded as well, so a refit at step 4 can be shown to be the same model
without depending on a pickle surviving: seed 0 main `4ec607b1b4c0…`.

`train_accuracy_in_sample` is a fit artefact, not a criterion — it is measured on
the data the model was fitted on. It is reported only so that a reader can see
the fit did something, and it sits in the region R-TM-01d reported on Test-ID
(0.9706).

**Equivalence of the copied metric functions.** `rlaya/metrics.py` copies six
functions out of `vendor/experiment.py`, which cannot be imported in the Laya
arms' Python 3.12 environment because it imports `tmu` at module scope. This
environment has `tmu`, so both were run side by side and asserted identical
before any fit:

| function | vendor | copy | identical |
|---|---|---|---|
| `ece` | 0.024692645250192505 | 0.024692645250192505 | yes |
| `ece_prob_bins` | 0.020920781955274453 | 0.020920781955274453 | yes |
| `mean_confidence` | 0.7491170619370814 | 0.7491170619370814 | yes |
| `fit_temperature` | 41.330210361974906 | 41.330210361974906 | yes |
| `apply_temperature` (sum) | 999.9181480966928 | 999.9181480966928 | yes |
| `rule_arm` (sum) | 3081.0 | 3081.0 | yes |

---

## 4. Arms G, R and L0

One environment for all three, on the same machine:

| | |
|---|---|
| Python | 3.12.14 |
| numpy / scikit-learn / scipy | 2.5.3 / 1.9.1 / 1.17.1 |
| torch | 2.9.1+cu126, arch list carries `sm_70` |
| transformers / laya | 5.17.0 / 0.3.4 |
| GPU | Tesla V100-SXM3-32GB, cc 7.0 (L0 only) |

### G — HistGradientBoosting

`HistGradientBoostingClassifier(random_state=seed)`, exactly as `run_b.py`
constructs it, fitted on Train and on Train-without-fw. §3 says G is **not**
temperature-scaled and reports native probabilities, so there is no calibration
step. Fit time 0.52–0.56 s per seed for both models. In-sample Train accuracy
0.9899, 0.9920, 0.9905, 0.9909, 0.9898 — again a fit artefact, not a criterion.
Ten pickles committed as artefacts on the server, not in git.

### R — the deterministic rule

Nothing is fitted. `metrics.rule_arm` is byte-identical to
`run05d/experiment.py:rule_arm`. Three things asserted rather than assumed, in
code, so the run fails if any stops being true:

- every confidence is exactly **1.0** — ARCH-131's *"emitted at confidence 1.0"*;
- the answers are in {0, 1};
- at the 0.8 threshold the **escalation rate is 0.0** — at confidence 1.0 nothing
  is ever routed for uncertainty.

That last one is why `routing_report` now reports an **answer rate** beside the
escalation rate. R sends work to the queue by *answering* yes, not by abstaining:

| seed | answer rate (Train) | escalation rate at 0.8 | Train accuracy |
|---|---|---|---|
| 0 | 0.3851 | 0.0 | 0.7524 |
| 1 | 0.3951 | 0.0 | 0.7482 |
| 2 | 0.3952 | 0.0 | 0.7521 |
| 3 | 0.3972 | 0.0 | 0.7595 |
| 4 | 0.3987 | 0.0 | 0.7519 |

Reporting only the escalation rate would read as "the hand rule never escalates",
which is the opposite of what it does. Both are carried into step 4.

**What R cannot express.** ARCH-130's queue has three sources and the generator's
state supports two of them — exhausted repair budget (ARCH-030, `attempt == 3`)
and gate escalation. **Unresolved arbitration (ARCH-040) has no field to key on.**
Recorded as C5 M9 rather than patched, so arm R stays the rule R-TM-01 measured.

### L0 — Laya zero-shot, pipeline built and §3 temperature fitted. Not scored.

The checkpoint's own calibration was set to identity first, per the resolution
of D2.
**What was neutralised, and what it held:**

| field | prior value |
|---|---|
| `temperature` | `[1.0148024559020996, 1.0374259948730469, 1.0575125217437744]` |
| `temperature_by_options` | `{"choice:3-5": 1.7601518630981445, "choice:6-10": 1.0000158548355103, "score:3-5": 1.2514300346374512, "`**`noul:2`**`": `**`1.983399510383606`**`, "choice:11+": 0.10058280825614929, "choice:2": 1.9063563346862793}` |
| `cfg["temperature"]`, `cfg["temperature_by_options"]` | the same two, on the config object |

Set to `[1.0, 1.0, 1.0]` and `{}` in process. **The checkpoint on disk was not
modified**, and R6 is untouched: a temperature is a calibration constant in a
JSON config, not a weight, and the weights stay frozen at revision
`f9ab0b22…`. "Raw" in C1 therefore means identity temperature for every arm.

**The §3 temperature, fitted on the first 500 rows of Train:**

| seed | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| L0 temperature | **8.5625** | **1.1388** | **6.7908** | **1.6381** | **1.9541** |
| score sd on the slice | 0.3168 | 0.3329 | 0.3327 | 0.3356 | 0.3132 |
| score mean on the slice | 0.0981 | 0.0926 | 0.0895 | 0.0998 | 0.0869 |

**This does not settle**, and it is recorded now, before any test split is read,
so that it cannot later look like an explanation constructed after seeing L0
fail. A factor of 7.5 between seeds, from 500-sample fits that differ only in the
data seed. The reason is in the two rows under it: L0's logit difference has mean
≈ 0.09 and sd ≈ 0.32 on every seed, so the likelihood is nearly flat in the
temperature and there is very little for the fit to lock onto. Arm T's
temperature, fitted by the same function on the same slice, is stable to within
20 %. C5 M11. §3 is frozen and was followed exactly; nothing here was adjusted.

**L0 is not scored.** Its metrics are produced at step 4 with every other arm.

---

## 5. Two checks that were expected to pass, and one that did not

### The draw is identical across environments — verified, not assumed

R1 lets arms run in different environments and requires the draw to be the same.
Arm T runs numpy **2.4.6** under Python 3.11; the other three run numpy **2.5.3**
under 3.12. numpy's stream-compatibility policy says a `default_rng` stream is
stable across versions, but standards §9 says a claim about a library is verified
by running it. Both drivers checksum their Train draw:

| seed | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| `X` sha256, both environments | `761060775707…` | `413bfb99ca94…` | `f5a0991e892b…` | `7e342ec89eea…` | `25c130e53644…` |

Identical on `X`, `y`, `y_clean` and the raw fields, on all five seeds. Seed 0
Train: n = 8 000, `sum_y` = 3 692.

### The fp16 check that failed, and what it found

The batched Laya path was checked against `laya.Agent.system_one` and
**disagreed** — 1.6e-3 in probability, against the 1e-4 that `system_one`'s own
rounding allows. It was not the code path. Measured on 64 Train states:

| | batch 32 vs batch 1, max Δp | mean Δp |
|---|---|---|
| **fp16** | **2.65e-3** | 4.63e-4 |
| **fp32** | 3.46e-6 | 6.83e-7 |

fp32 against fp16 at batch 1: max Δp 1.81e-3, mean 4.59e-4, and **0 of 64
decisions crossed 0.5**. A batch pads to its own longest sequence and the fp16
reductions differ, so under fp16 the same state scores differently depending on
which states it was scored with.

**Resolved by pinning fp32 as the experiment's inference precision on every
device**, and re-running the agreement check at batch size 1 on both sides so it
tests the code path rather than the arithmetic. It then agrees **exactly** to
`system_one`'s four decimals — max difference `0.0` on all 8 states. Three
reasons fp32 rather than a fixed batch size: C4 gates on the laptop, which is
cpu/mps and fp32 already, so fp16 on the server would put the two machines on
different answers for the same state; a criterion must not depend on a batch size
nobody chose; and there is no tf32 on cc 7.0, so fp32 here is true fp32. C5 M10.

Cost: 9.5 ms per state on the V100 in fp32, batched — 4.76 s for a 500-state
calibration slice.

### The test-split fence

`workload.splits()` raises unless called with `allow_test=True`, which only step
4's measurement passes. Everything this step fitted came from `train_only()` and
`train_nofw_only()`, which reproduce `build_all(seed)["train"]` and its
no-firmware filter **without constructing Test-ID, OOD-A or OOD-B in memory at
all**. Reading a test split at step 2 would have required editing a committed
file, and that edit would be in the diff.

---

## 6. C5 — five new entries and one correction

`../C5-assumption-mismatches.md` now holds M1–M11. Added this step:

- **M4 addendum** — M4 overstated its risk. `laya.Agent.__init__` already
  downgrades bf16 to fp16 on compute capability < 8 and to fp32 on cpu/mps.
  Nothing had to be done about bf16 at inference; the entry was written from
  `amp_dtype()` without reading its caller. Appended and dated rather than edited.
- **M7** — ARCH-010 and ARCH-012 name one of the twelve state fields. **The first
  entry whose answer to "would resolving it require changing ARCH-131 or
  ARCH-010" is yes.**
- **M8** — Laya has two confidence functions and picks by question kind; `noul`
  gets `max(p, 1-p)`, which is the scale every other arm is on, so no work-around
  was needed. Recorded because it nearly was one.
- **M9** — arm R can express two of ARCH-130's three escalation sources.
- **M10** — fp16 makes the answer depend on the batch.
- **M11** — the §3 temperature does not settle for L0.

---

## 7. Prospective deviations, and how each was resolved before step 4

### D4 — C1 says "10 bins" and does not say over what range

§6 C1: *"Expected calibration error, 10 bins, on Test-ID."* Equal-width bins over
equal-mass, and passing `n_bins` explicitly rather than inheriting the library's
default, were both settled on 2026-09-21 under D3. Neither settles the **range**,
and the available conventions give different numbers:

| | definition | equal-width? |
|---|---|---|
| `ece_conf_half` | 10 bins over **[0.5, 1.0]** on confidence — `run05d/experiment.py:ece`, verbatim | yes |
| `ece_conf_full` | 10 bins over **[0, 1]** on confidence — what `laya.common.ece_score` computes | yes |
| `ece_prob_bins` | 10 bins over [0, 1] on P(y=1) — `run05d/experiment.py:ece_prob_bins` | yes |

Confirmed in the library: `laya.common.ece_score` uses
`edges = np.linspace(0, 1, bins + 1)` — **equal-width**, not equal-mass, and its
default is 15 bins, which is why the experiment passes 10 explicitly. For a
binary decision confidence is ≥ 0.5 by construction, so the lower five bins of
the [0, 1] version are always empty and ten bins there behave like five.

**Recommendation: `ece_conf_half` as the gated number**, because it is
`run05d/experiment.py:ece` verbatim, because C1's framing and its thresholds come
from that run, and because it is the only one of the three that actually uses ten
bins. All three are computed for every arm and reported; the other two are
context. **No threshold moves either way** — this is which of three numbers the
frozen 0.10 / 0.06 is compared against, and it should be settled before the
numbers exist rather than after.

**Resolved before step 3 began; no test split had been read.** The gated
calibration figure is computed by the function the threshold was set against:
ten equal-width bins over confidence in [0.5, 1.0], as in the earlier Tsetlin
run whose scored values this criterion's thresholds were taken from. A threshold
compared against a different function would silently change what the threshold
means. The other two calibration figures are computed and reported for every arm
as context and decide nothing. This supersedes the range left open under D3.

### D5 — confirm the §3 calibration slice is the first 500 rows of Train

§3: *"a 500-sample slice of Train only, drawn once with a fixed seed and
identical for every arm."* **It does not name a seed.** Implemented as
`Train[0:500]`, which is what `run_b.py` did (`CAL_N = 500`, `ytr[:CAL_N]`), and
whose "fixed seed" is the data seed that drew Train. Inventing a second seed here
would be choosing a number the criteria do not name; reusing R-TM-01's convention
keeps arm T comparable to the run being rerun, and an index range is identical for
every arm by construction. **Confirm or correct before step 4.**

**Resolved before step 3 began.** The calibration slice is the first 500 rows of
Train, as drawn by the data seed that drew Train. No second seed is introduced:
the criteria name none, and an index range is identical for every arm by
construction.

### D6 — ARCH-131 promises a `state` no ARCH decision defines

Raised as C5 M7 and repeated here because it is the one finding this step
produced that is about the architecture rather than about the experiment. It
changes nothing in this run and needs no resolution for step 4. Carried forward
as a note on the architecture rather than on the experiment:
ARCH-132 admits bindings on measured evidence, and the thing being measured —
"the structured subtask record at the end of an attempt" — is defined today only
in R-TM-01's generator. A decision that writes the subtask-state schema down,
with ARCH-131 depending on it, would close it.

**Resolved before step 3 began; nothing in this run changes.** ARCH-131 now
states that the state's schema is deliberately not defined yet: it is the
composition of the task ledger line, the gate result and the reviewer verdict,
and it is written as its own decision once all three exist in code. Until then,
any ARCH-132 row whose evidence was gathered on a generated state says so. This
run's evidence was gathered on a generated state, and its result says that next
to its verdict.

### D7 — a reporting convention to confirm, not a deviation

C2's "escalation rate" is read as routing by **confidence**, which is R-TM-01's
convention and the one the numbers C3's framing cites were computed in. Under it,
arm R's escalation rate is 0 by construction. The **answer rate** is reported
beside it for every arm so R is not misread. Confirm this reading before step 4;
no threshold depends on it, but the scoreboard's legibility does.

**Resolved before step 3 began.** Escalation rate is computed by confidence
against the ARCH-131 threshold of 0.8, the convention in which the earlier
Tsetlin run's cited numbers were computed. The answer rate is reported beside it.
No threshold depends on the choice.

---

## 8. What this step did not do

It did not score anything. Every number above is either a fit artefact measured
on the data the arm was fitted on, a property of the environment, or a check.
C1, C2, C3 and C4 are measured at step 4, on splits that do not yet exist in any
process this experiment has run.
