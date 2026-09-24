# R-LAYA-01 — Result

**Criteria frozen before any model ran.** Original `7b85d29`, amended once at
`e12d153`; both are on `master` with nothing of this implementation among them.
The amendment corrected arm T's environment description and moved no threshold,
split, definition or acceptance rule, and no metric existed to steer it. This
run was scored against `e12d153`. **`CRITERIA.md` was not edited at any point.**

**Measurement commit** `a3a03a8`, extended at `201166f` — both before the test
splits were constructed, per standards §6.1. The splits were built exactly once,
by `rlaya/measure.py`, which is the only caller that passes
`workload.splits(..., allow_test=True)`.

**What the outputs do not record: the commit that produced them.** No driver
stamps one and none has been added now. The commit named above is supported by
the surrounding record — content checksums that resolve to exactly one commit
each, the commit order, a clean tree, and a file-time sequence that corroborates
it — rather than recorded by the artefact. §12 sets out exactly which is which,
what the timeline is and is not, and what the single read of the splits does and
does not establish.

---

## Verdict

**L1 does not satisfy the acceptance rule. `laya` does not enter ARCH-132.**

| | | |
|---|---|---|
| **C1 Calibration** | ECE 0.0264 raw, 0.0070 after the §3 fit, against ≤ 0.10 / ≤ 0.06 | **pass** |
| **C2 Humility** | confidence drop ≈ 0.0000 and escalation rise **exactly 0.0000** on both OOD sets, against ≥ 0.15 and ≥ 20 points | **fail, on both** |
| **C3 Selective accuracy** | 0.9736 Test-ID, **0.4522 OOD-A**, 0.9826 OOD-B, against ≥ 0.95 on all three | **fail** |
| **C4 Latency** | p50 236.26 ms on the laptop, mean over five checkpoints, against ≤ 500 ms | **pass** |

**The second kill criterion fires**: *"C2 fails on **both** out-of-distribution
sets."* §7 admits `laya` only if L1 satisfies C1, C2, C3 **and** C4. It satisfies
C1 and C4 and fails C2 and C3, so the backend is parked.

### Which of these rests on which evidence

The two statements above do not stand on the same records, and a reader should
not have to work that out.

**The non-entry verdict does not need the no-firmware models at all.** C2 and C3
both fail on the **first** out-of-distribution set, OOD-A — confidence drop
+0.0000 and escalation rise +0.0000 for C2, selective accuracy 0.4522 for C3 —
and OOD-A is scored by the *main* five checkpoints, as is Test-ID. §7 admits
`laya` only if L1 satisfies all four criteria, so one unsatisfied criterion parks
it, and two are unsatisfied on main-model splits alone. The conclusion that
`laya` does not enter ARCH-132 therefore rests on
the main models, whose per-seed metrics are in `step4_summary.json` and
`step4_raw.json` and whose training record is `step3_l1.json` — all of them in
this repository, checkable today.

**What does depend on the no-firmware models is the narrower statement that the
second kill criterion fired.** That criterion is *"C2 fails on **both**
out-of-distribution sets"*, and OOD-B is scored by the no-firmware retrain, as
R-TM-01 defined it. Its records are `step3_l1_main.json` and `step3_l1_nofw.json`
— the two filenames `rlaya/verdict.py:250-251` reads — and **`step3_l1_nofw.json`
is not in this repository.** `step3_l1.json`, which is, is byte-identical to
`step3_l1_main.json` and contains the main five seeds and no `nofw` key at all.

So: the verdict is checkable from the repository as it stands; the sentence
naming the second kill criterion is not, until that record is committed. It is
listed as an outstanding item in §12 with the name and hash it must match. This
is stated rather than worked around, and the verdict is not restated to depend on
less than it does.

The one-line reason, and it is the same reason for both failures: **L1 answers
every state at confidence 1.0000.** It is maximally confident on the
distribution it was trained on and equally confident on the two it was not. At
the ARCH-131 threshold of 0.8 it therefore escalates nothing, anywhere — so
there is no rise to measure for C2, and every decision it makes is a decision it
keeps, which is why C3 on OOD-A is simply its accuracy there: 0.4522, worse than
a coin.

**This is a proxy measurement, and the register must say so.** ARCH-131 states
that its `state` schema is deliberately undefined, and that *"any row in ARCH-132
whose evidence was gathered on a generated state says so, because a backend
measured on a shape the system does not yet emit has been measured on a proxy."*
Every number in this document was gathered on R-TM-01's generated state. The gap
is left open deliberately, not overlooked: ARCH-131's trigger is the ledger line
(ARCH-012), the gate result (ARCH-080) and the reviewer verdict (ARCH-060), and
**two of those three do not exist in code yet**. Recorded as C5 M7, and raised at
step 2 as the one gap here that only a change to ARCH-131 or ARCH-010 could
close, rather than something this experiment could work around.

---

## 1. What was measured, and how it was read

All at the ARCH-131 routing threshold of **0.8**, on the **mean over five
seeds** (0–4), with per-seed values in `step4_summary.json`.

| split | n per seed | scored by |
|---|---|---|
| Test-ID | 2 000 | the main fit |
| Test-ID-nofw | 1 693 | the no-firmware retrain |
| Test-OOD-A (`attempt == 3`) | 1 000 | the main fit |
| Test-OOD-B (unseen domain) | 1 000 | the no-firmware retrain |

**OOD-B is measured against retrained arms**, as R-TM-01 defined it. Every arm
that can be retrained has a main fit and a no-firmware fit; L0 cannot (there is
nothing to retrain in a zero-shot checkpoint) and R cannot (it is deterministic).

### Four readings applied, all of them interpretations rather than changes

**C1's gated number is `ece_conf_half`** — 10 equal-width bins over **[0.5, 1.0]**
on confidence, `n_bins` passed explicitly. This is `run05d/experiment.py:ece`
verbatim. C1 is R-TM-01d's criterion A2 transplanted word for word
(`experiments/R-TM-01/R-TM-01_complete/_reports/06_R-TM-01d_prereg.md:97` —
*"ECE on Test-ID, 10 bins | ≤ 0.10 raw, or ≤ 0.06 after temperature scaling"*),
and the threshold was set against that function. `ece_conf_full` and
`ece_prob_bins` are reported in §2 **because they exist, not because they decide
anything**: over [0, 1] the lower five bins are empty by construction for a
binary decision, so ten bins there behave like five.

**Temperature.** For every Laya checkpoint, zero-shot and fine-tuned,
`temperature` and `temperature_by_options` were set to identity **in process**
before anything was scored, and only the §3 fit applied — identically for L0, L1
and T. The checkpoints on disk were not modified, so R6 is intact: a temperature
is a calibration constant in a JSON config, not a weight. **"Raw" in C1 therefore
means identity temperature** — native logits, no scaling from any source — and it
means the same thing for every arm.

**The §3 calibration slice is `Train[0:500]`**, per `run_b.py:14` `CAL_N = 500`.
§3 says the slice is drawn *"once with a fixed seed"* without naming a seed; the
fixed seed that actually exists is the data seed that drew Train, and an index
range is identical for every arm by construction. For a no-firmware model the
slice is the first 500 rows of Train-without-firmware, which is what `run_b.py`
does and the only way such a model can have a temperature at all.

**Escalation rate is routing by confidence**, R-TM-01's convention and the one
C2 and C3 are written in. **Answer rate is reported beside it for every arm**,
because the question under test is *"Should this subtask be escalated?"* and an
arm can also send work to the queue by answering yes. Arm R makes the distinction
unavoidable: it emits confidence 1.0 by construction, so its escalation rate is
0 — it never abstains — while its answer rate is the fraction its conditions
escalate.

### A non-gating pass that scores nothing

For L0 and L1 a third pass applies **1.9834**, which is the constant
`laya.Agent` actually resolves for this question — *not* the ~5.30 the
fine-tuned configs advertise. A reader can check the resolution rather than take
the number: `laya/agent.py:304` reads

```
t_scale = self.temperature_by_options.get(temp_bucket(qt, k), self.temperature[qt])
```

so `temperature_by_options` wins, and `laya/common.py:209-211` maps a two-option
`noul` question to exactly `"noul:2"`, a key the inherited dict contains. The
recipe writes only `cfg["temperature"]`, so its own post-training fit is
unreachable. **C5 M12.** This pass decides nothing.

---

## 2. C1 — calibration on Test-ID. **L1 passes.**

Mean over five seeds. The gated column is `ece_conf_half`.

| arm | raw | after the §3 fit | verdict |
|---|---|---|---|
| **L1** | **0.0264** | **0.0070** | **pass** (both halves) |
| L0 | 0.0456 | 0.0136 | pass |
| T | 0.0815 | 0.0131 | pass |
| G | 0.0069 | not scaled (§3) | pass |
| R | 0.2442 | not scaled (§3) | **fail** |

Reported because they exist, not because they decide anything:

| arm | `ece_conf_full` (raw) | `ece_prob_bins` (raw) | shipped-temperature pass |
|---|---|---|---|
| L1 | 0.0264 | 0.0264 | 0.0263 |
| L0 | 0.0453 | 0.0728 | 0.0181 |
| T | 0.0792 | 0.0799 | — |
| G | 0.0050 | 0.0062 | — |
| R | 0.2442 | 0.2442 | — |

**C1 passes and the pass should not be read as calibration.** L1's confidence is
1.0000 on Test-ID and its accuracy there is 0.9736, so the expected calibration
error *is* 0.0264 — the gap between a maximal confidence and a high accuracy. A
saturated arm that happens to be accurate in distribution satisfies this
criterion; the same saturation gives **ECE 0.5478 on OOD-A**, where accuracy is
0.4522 and confidence is still 1.0000. C1 is scored on Test-ID as frozen, and it
passes as frozen. The OOD figure is not part of C1 and is recorded here so the
pass is not mistaken for a property it does not have.

**The saturation is Laya's own report, not an artefact of this harness.** The
batched scoring path was checked against `laya.Agent.system_one` on eight Test-ID
states of seed 0: maximum difference **0.0** at `system_one`'s four decimals, and
`system_one`'s own reported confidence is **1.0 on all eight**. The choice of
confidence function does not rescue it either — Laya's entropy confidence (C5 M8,
non-gating) is 0.999944–1.000000 on Test-ID and 0.999187–1.000000 on OOD-A.

---

## 3. C2 — humility. **L1 fails, on both out-of-distribution sets.**

Both halves are reported for every arm even where one fails. Each OOD set is
compared against the in-distribution reference of the model that scored it —
OOD-A against Test-ID, OOD-B against Test-ID-nofw — which is `score_d.py`'s own
convention; comparing a no-firmware model's OOD-B confidence to a *different*
model's Test-ID confidence would confound the retrain with the distribution shift
that the retrain exists to separate. The literal reading (both against Test-ID)
is computed and kept in `step4_summary.json` under
`C2_literal_test_id_baseline_for_ood_b`; it changes no verdict here.

### L1

| set | confidence drop (≥ 0.15) | escalation rise (≥ 0.20) | |
|---|---|---|---|
| OOD-A, raw | **+0.0000** | **+0.0000** | fail, fail |
| OOD-B, raw | **−0.0000** | **+0.0000** | fail, fail |
| OOD-A, §3 | +0.0001 | +0.0002 | fail, fail |
| OOD-B, §3 | −0.0003 | −0.0002 | fail, fail |
| OOD-A, shipped | +0.0001 | +0.0004 | fail, fail |
| OOD-B, shipped | −0.0000 | +0.0000 | fail, fail |

The escalation rise is exactly zero because the escalation rate is exactly zero
on **all four splits**: mean confidence 1.0000 everywhere, and the threshold is
0.8. There is no configuration of the temperature in which this changes, because
temperature scaling a saturated logit difference leaves it saturated — the §3 fit
moves mean confidence from 1.0000 to 0.9778 and the escalation rate from 0.0000
to 0.0002.

### Every arm, raw

| arm | OOD-A drop / rise | OOD-B drop / rise | C2 |
|---|---|---|---|
| **L1** | +0.0000 / +0.0000 | −0.0000 / +0.0000 | **fail on both** |
| L0 | −0.0029 / +0.0000 | −0.0090 / +0.0000 | fail on both |
| **T** | **+0.2159 / +0.6284** | **+0.1811 / +0.5188** | **pass on both** |
| G | +0.0009 / +0.0005 | −0.0016 / −0.0020 | fail on both |
| R | +0.0000 / +0.0000 | +0.0000 / +0.0000 | fail on both |

Arm T under the §3 fit passes OOD-A (+0.1555 / +0.3766) but fails OOD-B's
confidence half (+0.1243 against 0.15) while passing its escalation half
(+0.2862). Arm T's raw configuration is the one that passes both.

**L0's zero rise is a ceiling, not a flatness.** L0 escalates **100 %** of every
split — its mean confidence is ≈ 0.565, comfortably below 0.8 everywhere — so the
rate cannot rise above the Test-ID rate because it is already at 1.0. The
confidence half fails on its own terms: the drop is −0.003 and −0.009, i.e. L0 is
marginally *more* confident off distribution.

---

## 4. C3 — selective accuracy. **L1 fails on OOD-A.**

Accuracy on the decisions the arm does **not** escalate. Mean over five seeds,
raw configuration.

| arm | Test-ID | OOD-A | OOD-B | C3 |
|---|---|---|---|---|
| **L1** | **0.9736** ✓ | **0.4522** ✗ | **0.9826** ✓ | **fail** |
| L0 | undefined | undefined | undefined | **fail** (see below) |
| **T** | **0.9879** ✓ | **0.9889** ✓ | **0.9618** ✓ | **pass** |
| G | 0.9891 ✓ | 0.4664 ✗ | 0.9796 ✓ | fail |
| R | 0.7558 ✗ | 0.9886 ✓ | 0.7468 ✗ | fail |

L1 escalates nothing, so its selective accuracy is its accuracy. On OOD-A —
third-attempt states — it is right on 45 % of what it keeps, at confidence
1.0000. **The kill criterion attached to C3 is "C3 fails on Test-ID", and that
does not fire**: Test-ID is 0.9736. C3 as a criterion fails, because it is
written as ≥ 0.95 on all three.

**Deviation: C3 cannot be computed for L0 and is scored as failed.** L0 escalates
every decision on every split, so the set of kept decisions is empty on all five
seeds (`n_kept = 0`) and the selective accuracy is undefined rather than low.
CRITERIA §3 says L0 is reported for completeness and the entry decision does not
rest on it; per the frozen rule, a measurement impossible as written is recorded
as a deviation and the criterion scored as **failed**, never rewritten.

### The ceiling C3 is read against, stated plainly

CRITERIA §5 says, verbatim:

> The label is the same hidden-rule output with the same **5 % noise**, which
> puts the achievable accuracy ceiling at about 0.95.

The generator §5 pins says otherwise. `run05d/generator_b.py:36` reads
`LABEL_NOISE = 0.01`, and R-TM-01b's own pre-registration records the
consequence at
`experiments/R-TM-01/R-TM-01_complete/_reports/02_R-TM-01b_prereg.md:88`:

> | Accuracy ceiling on Test-ID (1 % noise) | 0.9907 ± 0.0006 |

**That 0.9907 is a pilot value from R-TM-01b, not a measurement on these
splits.** It is quoted from where it was measured, with its location, and is not
re-derived here.

**So C3 is a weaker criterion than the frozen document presents it as.** A reader
told the bar sits at the noise ceiling reads heroism into a 0.95 threshold; the
truth is roughly four points of headroom between the threshold and the ceiling.
Leaving that inference to the reader would be a quiet overstatement in the
direction that flatters the thing under test, so it is stated here instead. No
threshold moved: every criterion is scored against the numbers exactly as frozen.
The irony is worth naming, because §5 exists to prevent exactly this class of
error — a ceiling asserted rather than checked.

---

## 5. C4 — latency. **L1 passes on the machine the criterion names.**

**Gated: p50 per decision ≤ 500 ms on the laptop**, mean over the five
checkpoints, one state per call at batch size 1, as `decide()` is called. Three
warm-up calls discarded, 100 timed calls per checkpoint per split.

| | p50 | p90 | p99 |
|---|---|---|---|
| **Test-ID, mean over five seeds** | **236.26 ms** | 286.39 ms | 404.54 ms |
| Test-ID, worst seed (seed 0) | 273.39 ms | 435.23 ms | 712.67 ms |
| Train, same session, mean over five seeds | 226.99 ms | 253.26 ms | 288.03 ms |

**Pass: 236.26 ms against 500 ms.** All five checkpoints loaded and were
measured; none had to be skipped.

Per seed, Test-ID p50: 273.39, 240.96, 236.04, 208.91, 221.98 ms.

**The same-session Train reference says the machine was behaving.** 226.99 ms
against 236.26 ms — within 4 % — so the gated figure is not an artefact of the
split. The one place the two separate is seed 0, whose Test-ID p99 is 712.67 ms
against a Train p99 of 351.52 ms on the same checkpoint minutes later: seed 0 is
the first model loaded in the session and pays the Metal shader compilation that
three warm-up calls did not fully absorb, and it ran at the highest load of the
session. It is reported, not smoothed.

### The machine the criterion names, which nothing else records

| | |
|---|---|
| Model | **MacBookPro17,1**, Apple **M1** |
| Cores | **8** — 4 performance, 4 efficiency |
| Memory | **8 GB** (8 589 934 592 B) |
| OS | macOS **26.2**, build **25C56** |
| torch | 2.9.1, `torch.get_num_threads()` 4, MPS available |

**Device: `mps`, chosen by `laya.Agent` with `device=None`.** The selection was
made by the library and recorded before anything was timed, and the alternative
was timed afterwards purely as context — the choice was fixed in committed code
at `201166f`, before any latency number existed, precisely so it could not be
made by which device gave the better figure. **The gated figure is unaffected by
anything in this paragraph**, and that is the point of fixing the device in code
first: the selection was made by the library before a number existed to prefer,
so no reading of the context run can put the gate in doubt.

**The context run on cpu: p50 16 393 ms, p99 46 742 ms.** Those are the measured
values and they stay. **No multiple is drawn from them, because the measurement
cannot carry one.** It was taken in the same session with the model still resident
on the other device, on 8 GB under the swap pressure described below, and the
spread says so on its own — a minimum of 322 ms against a maximum of 47 869 ms
across 100 calls. That is a machine paging, not a processor computing. The number
is a record of what happened on this laptop in that session; it does not isolate
cpu inference, so it cannot be divided by the mps figure to say how much slower
cpu inference is, and no such ratio is claimed here. `laya.Agent` would itself
have chosen fp32 on mps, so the M10 pin changes nothing here.

### The load, and what else was running

**The machine was not quiet, and could not be made quiet: it is the machine this
session runs on.** The load average was 14.09 at the start of the run and 8.43 at
the end, on 8 cores, with per-seed samples between 5.37 and 9.69. At the start
the heaviest processes were an unrelated Python at 86.2 %, a VS Code plugin
helper at 43.4 %, a second Python at 29.4 %, `fseventsd` at 22.2 % and Chrome;
at the end, a Python at 284 %, `BackgroundShortcutRunner` at 95.2 %, a VS Code
plugin helper at 45.9 % and `trustd` at 33.5 %. A 4.0 GB checkpoint transfer had
just completed and Spotlight was indexing it.

**Memory was the binding constraint and it is worth recording plainly.**
ModernBERT-large is 421 293 827 parameters, about 1.7 GB in fp32 before
activations, on a machine with 8 GB that is also running this session. During the
run swap use was measured at **11.3 GB of 12.3 GB**, and the process spent long
stretches in uninterruptible wait, paging. The whole five-checkpoint pass took
about 50 minutes of wall clock for roughly 1 000 timed calls. **Peak process RSS
was 1 585 201 152 B** (1.48 GiB) from seed 1 onward — this is `ru_maxrss`, which
is cumulative over the process and does not capture MPS allocations, so it is a
floor on the true footprint rather than the footprint.

The honest summary: the gated number passes comfortably, and it was taken on a
machine under heavy memory pressure, which is the condition the criterion
describes — *"where the orchestrator and its sessions actually run"* — rather
than a defect in the measurement.

### Reported, not gated

Server — `coder-yasinh-declassifai-55c6d799db-tsskx`, Tesla V100-SXM3-32GB,
Intel Xeon Platinum 8168 @ 2.70 GHz, **2 cores**, `torch.get_num_threads()` 2,
fp32 on cuda:

| arm | p50 | p90 | p99 |
|---|---|---|---|
| L1, mean over five seeds | **25.05 ms** | 25.31 ms | 25.68 ms |
| L1, Train, same session | 25.00 ms | 25.25 ms | 25.48 ms |
| L1, seed 0 | 26.24 ms | 26.50 ms | 26.79 ms |
| L0, seed 0 | 26.25 ms | 26.46 ms | 26.84 ms |
| G, seed 0 | 1.384 ms | 1.411 ms | 1.504 ms |
| **T**, seed 0 | **0.0450 ms** | 0.0531 ms | 0.0624 ms |
| R, seed 0 | 0.0127 ms | 0.0132 ms | 0.0292 ms |

L0 and L1 are within 0.05 % of each other on the same machine, which is what one
expects — same encoder, same head, same sequence length — and is why L0 was not
separately timed on the laptop. Laptop context: G p50 **9.63 ms**.

**Arm T's timing is a fresh measurement on a named machine, not a reproduction.**
R-TM-01 recorded no hardware at all, so its earlier speed is not a quantity this
run can compare against. See §6.

**Two things in this section could not be measured and are named rather than
worked around.** Arm T cannot be timed on the laptop at all: the amended §3 pins
it to Python 3.11.15 with `tmu` 0.8.3 and two source patches, an environment the
laptop does not have, so the server figure is its only one. Arm R's laptop timing
failed with `ValueError: Object arrays cannot be loaded when allow_pickle=False`
— the exported raw fields contain string columns — and **it was not retried**,
because by then the splits were open and the rule is report, do not repair. Both
are non-gating context; neither touches C4's verdict, which is about L1 alone.

**The frozen criteria describe the server as having "two CPU cores"; that is not
the machine.** The workspace exports `OMP_NUM_THREADS=2`, which is why `nproc`
reported two, and threaded libraries ran on two threads. The workspace itself may
use all 96 cores of its host under a quota worth six CPUs. The criteria's sentence
is frozen and stays as written; the server figures in this result are two-thread
figures, which is the correct description, and they remain non-gating.

### The cross-machine check that the fp32 pin was for

The same states scored on both machines, 100 per seed, all five seeds:

| | |
|---|---|
| maximum absolute difference in probability | **1.9e-7 to 5.7e-7** |
| mean absolute difference | 1.5e-8 to 2.4e-8 |
| **decisions crossing 0.5** | **0, on every seed** |

Server fp32 on cuda against laptop fp32 on mps, agreeing to seven decimal
places. This is what M10's pin bought, and it is the evidence that the two
machines answer the same question the same way.

---

## 6. Findings

### M10 — the precision pin, and what it costs

**The fp32 pin is on *scoring*, not on training. Nothing about the recipe
changed.** Arm L1 was trained under `torch.autocast("cuda", dtype=torch.float16)`
with `torch.amp.GradScaler`, which is the pinned notebook's own choice — it
targets 2×T4, compute capability 7.5, which has no bfloat16 either. The pin
applies to the path that turns a state into a probability at steps 3 and 4, and
it has no bearing on how the weights were fitted.

**C4 therefore reports the slower configuration, and that is the trade worth
naming.** The faster one exists — fp16 inference is available on the V100 and
`laya.Agent` would have chosen it — but it does not give a well-defined answer
under batching. Measured on 64 Train states at step 2: fp16 moves the reported
probability by up to **2.65e-3** between batch 32 and batch 1, against **3.46e-6**
for fp32. A batch pads to its own longest sequence and the fp16 reductions differ,
so under fp16 the same state scores differently depending on which states it was
scored with. A criterion must not depend on a batch size nobody chose, and
ARCH-131's audit clause — *"every call records answer, confidence, backend id and
latency in the ledger, so a backend's behaviour is auditable after the fact"* —
means the same state must give the same answer. The speed was given up for that.

**It was found by a check that failed.** The agreement check between the batched
path and `laya.Agent.system_one` was expected to pass and did not: 1.6e-3 in
probability against the 1e-4 that `system_one`'s own rounding allows. That is
written down here because the checks that pass are the ones that get written up,
and this run would have reported a cleaner-looking number and a quieter method
section if the check had never been run.

A consequence for ARCH-132's row text, for any backend that runs on an
accelerator: *"weights frozen at a recorded version"* is not sufficient for
reproducibility. The precision and the batching are part of the function too, and
a ledger that records the answer without them cannot be replayed.

### Two things this record does not establish, stated rather than closed

**The exploration noise in L1's training is not seeded.** `train_l1.py:238` draws
the GRPO exploration perturbations with `torch.randn(...)`, which uses torch's
global default generator, and nothing in this experiment calls
`torch.manual_seed`. The only seeding in the training loop is the recipe's own
`random.seed(42 + epoch)` before the item shuffle, at `train_l1.py:214`.

What that affects: **the ten checkpoints are not reproducible from the data seed
and the code alone.** Re-running `train_l1.py` on the same seed would draw
different exploration noise and land on different weights, so the sha256 in §8
would not come back. What it does not affect: the data draw, which is seeded per
seed and fingerprinted and checked across environments (`workload.draw_fingerprint`);
the item order, which is seeded; the §3 calibration slice, which is an index
range; scoring, which is a deterministic fp32 forward pass pinned by M10; and
**every number in this document given those checkpoints**, because the
checkpoints are fixed artefacts hashed before they were loaded. The reproducible
object here is the measurement, not the training. This is recorded, not fixed:
adding a seed now would change the code that produced the numbers.

**Some of C4's machine facts are recorded in an artefact and some are assertions
in this document.** `step4_latency_laptop.json` records the model, the CPU, the
core count and its split into performance and efficiency cores, the memory size
in bytes, the OS version and build, the Python and torch versions, the thread
count, MPS availability, the selected device and dtype, peak RSS per seed, the
load average before and after every seed, and the process lists at the start and
the end. Those are the numbers in the machine table and the load paragraph, and
they can be checked.

Four claims in §5 and §8 have no artefact behind them and are this author's
report of the session: the **swap figure of 11.3 GB of 12.3 GB**; that the
process **spent long stretches in uninterruptible wait**; that the whole
five-checkpoint pass took **about 50 minutes of wall clock**, which no field
records; and that a **4.0 GB checkpoint transfer had just completed with
Spotlight indexing it**. §8's statement that the five main checkpoints were
**re-hashed on arrival on the laptop and matched** is the same kind of claim:
`step4_latency_laptop.json` contains no hash of any kind. All five are left as
written and are marked here as assertions rather than records, so that no reader
takes them for measurements. They are context for the gated figure and none of
them enters a criterion.

### The rest of C5

`C5-assumption-mismatches.md` holds **M1–M12**, opened at step 1 and appended to
at steps 2 and 3 — during implementation, as §6 C5 requires. **Nothing was added
to it that depends on a number in this document**, and nothing already in it was
rewritten once a metric existed. It is final as it stands.

**One correction of 2026-09-24, named so that sentence stays exact.** Four
entries — M5, M6, M11 and M12 — said a question had been settled by a *ruling*
and now state what was resolved and why, and the seven `D` questions the step
reports define now carry their resolutions in those reports. **No entry was added
or removed, no content or verdict changed, and no number anywhere moved**; the
diff is prose and cross-references, in markdown only. Finality here is a claim
about the list's content, and that content is exactly as it stood at measurement.
What changed is that a reader who follows `D2` out of the code or out of an
artefact now lands on the answer rather than on the open question.

Three of its entries carry weight here. **M12** is why the shipped-temperature
pass uses 1.9834 rather than the ~5.30 the fine-tuned configs advertise: the
recipe fits a temperature the checkpoint cannot reach. **M7** is the one entry
whose answer to *"would resolving it require changing ARCH-131 or ARCH-010"* is
**yes** — ARCH-010 and ARCH-012 between them name one of the twelve state fields,
and three have no home in the specification at all. **M11** is L0's, below.

### L0 failed, as CRITERIA §3 predicted it would

§3 says of L0: *"Expected to fail. Reported for completeness; the entry decision
does not rest on it."* It failed. It escalates 100 % of every split at a mean
confidence of ≈ 0.565, fails both halves of C2 on both sets, and has no defined
selective accuracy because it keeps nothing.

The property behind it was recorded at step 2, **before any test split was
opened**, as C5 M11: L0's §3 temperature does not settle. Across five seeds whose
draws differ only in the data seed it takes the values **8.5625, 1.1388, 6.7908,
1.6381, 1.9541** — a factor of **7.5** — because its logit difference on the
calibration slice has mean ≈ 0.09 and standard deviation ≈ 0.32, so the likelihood
is nearly flat in the temperature and there is very little for the fit to lock
onto. Arm T's temperature, fitted by the same function on the same slice, is
stable to within 20 %. That contrast was written down before the splits existed
precisely so it could not later look like an explanation constructed after seeing
L0 fail. **An arm that fails as predicted is evidence the design was understood.**

### Arm T, and the caveat that travels with it

Arm T is the only arm that passes C1, C2 and C3, and it does so in a single
configuration — raw. **CRITERIA §9 attaches two things to that result and both
are repeated here rather than left in the frozen file.**

**The configuration rerun here was selected in a region first identified with the
out-of-distribution sets in hand.** Its numbers in this run are a transferability
check of a known answer, not an independent result, and any summary that cites
them says so. This experiment's contribution on arm T is that the answer
transferred: the configuration behaves the same way on a fresh draw scored by
this harness.

**Its original hardware was never recorded at all.** R-TM-01 recorded its
software environment in full and its hardware not at all, so the timing in §5 is
a fresh measurement on a named machine —
`coder-yasinh-declassifai-55c6d799db-tsskx`, Intel Xeon Platinum 8168 @ 2.70 GHz,
2 cores available — and **not a reproduction of a speed nobody wrote down**. Any
statement that arm T is faster or slower than it was must name the machine, or
not be made.

Arm T also carries the §9 note that C3's framing and threshold were informed by
R-TM-01d's post-hoc observation, which makes this run the **first prospective
test of the selective-accuracy criterion**. It was applied identically to all
five arms, including the two baselines never proposed as backends.

---

## 7. The fourth kill criterion — the training budget

*"L1 cannot be trained on the available accelerator within 12 hours."* The twelve
hours is read against **the whole arm**, not one seed: the criterion names L1,
and L1 is an arm of five seeds, so the budget is the arm's. Read per seed it
would be a far weaker criterion than the frozen text says, and the weaker reading
is the one that flatters the thing under test, so it is not taken.

**The arm is ten trainings, not five.** Every seed has a main fit and a
no-firmware fit, because OOD-B is measured against a retrained arm as R-TM-01
defined it. Step 3's figure of **0.8971 h** is kept visible below because it is
what step 3 reported — and it was **partial**, covering the main five only,
because the no-firmware requirement surfaced after step 3 was written.

| seed | main (h) | no-fw (h) |
|---|---|---|
| 0 | 0.1884 | 0.1500 |
| 1 | 0.1824 | 0.1503 |
| 2 | 0.1760 | 0.1512 |
| 3 | 0.1752 | 0.1505 |
| 4 | 0.1752 | 0.1502 |
| **five-seed total** | **0.8971** | **0.7523** |

| | |
|---|---|
| **All ten trainings** | **1.6494 h** |
| Budget | 12 h |
| **Fraction of budget** | **13.745 %** |
| step 3's main-five figure, kept visible | 0.8971 h (partial, as above) |

**The criterion does not fire.** Four epochs, the recipe's full schedule,
effective batch 64, nothing shortened — the arm used about a seventh of its
budget.

**Arm T also has two fits per seed**, for the same reason, and the same figure is
given for it:

| seed | main (s) | no-fw (s) | both (s) |
|---|---|---|---|
| 0 | 1.1073 | 0.9697 | 2.0769 |
| 1 | 1.1064 | 0.9484 | 2.0549 |
| 2 | 1.1382 | 0.9987 | 2.1368 |
| 3 | 1.1311 | 0.9554 | 2.0865 |
| 4 | 1.1570 | 0.9743 | 2.1313 |
| **all ten** | | | **10.4864 s = 0.002913 h = 0.024 % of 12 h** |

---

## 8. R6 — zero tokens, frozen weights, recorded version

**Stated outright, because ARCH-131 admits a backend only if both hold.**

**Zero tokens were spent on the decision.** Not few — none. Every arm evaluates a
state by a forward pass or an arithmetic rule; no `anthropic` or `openai` client
exists anywhere in this experiment, and Laya is non-autoregressive and generates
no text by construction.

**The weights are frozen at a recorded version.** The base checkpoint is
`convaiinnovations/laya-typed-decisions` at revision
**`f9ab0b228f0fc0f14d873dbc99038f135c2da1b2`**, whose `model.safetensors` is
842 609 220 B, sha256
`4fa56de72383a9d3efa9cfa78955733c81b9fc8067a587ca4beb82c78107a24e`. The ten
fine-tuned checkpoints were hashed and sized **before any of them was loaded**,
by the measurement driver itself, and each is 842 609 220 B:

| seed | L1 main | L1 no-fw |
|---|---|---|
| 0 | `857fa9b6a84fe0d093180ad9310ec5cac1f751302e6311308e3211aded768578` | `878bf2e7695770aca657bce096d00ba31fd4011060423baa2f173a7c608352e3` |
| 1 | `a67ee9e81b99f666404298fb848b4e660956e8bf360118c5156947c292e38dae` | `49de3cdbb0614ebfd41f5ebd84c262f522d28d93174dd48038afac02f62512be` |
| 2 | `4676a470421529767e9f9c4dbdc561397cfc7310511f8b796ffa91f76197fb1f` | `5a87d9b8a4a6074e530fd9bc92ebd2e6ecd3f5a8c2a1875f7b3510b0f13365bd` |
| 3 | `4f0e19119e419df13d4e8e5d74b69f8cf6ee2ec6379652215d11f66b8f2155ae` | `d6ee5075eb512b469b1af0f2468dd80a3839e678524107fe1ef479ebf4fb8d10` |
| 4 | `24fd42c70c187ed4df68a124a9d45ee2b3b8fea899d8e926f7582b765b90308a` | `90da848a4c2c2d474375419eede8bfd3fdd8ea879ca454e2d5a0319c67a7441b` |

The five main hashes match those step 3 recorded, independently recomputed here.
The five main checkpoints were transferred to the laptop for C4 and re-hashed on
arrival; all five matched byte for byte.

**Neutralising the temperature does not touch this.** A temperature is a
calibration constant in a JSON config, not a weight; it was set to identity in
process and the files on disk were not modified, which is why the hashes above
are the hashes of what was scored.

---

## 9. R3 — the serialisation fixture, one example per split

One function, `rlaya/fixture.py:serialise`, produces the JSON for every Laya
call. It emits exactly the raw generator fields with readable values, contains no
derived feature, no engineered summary, and never the label or anything computed
from it. The Train example is in `step2_fixture_and_arms/STEP2.md`; the three
below were deferred to measurement because R3 says *"committed with the run"*
without saying when, and a deferred example costs nothing while an early read
cannot be undone. **This closes R3.** All three are seed 0, index 0.

**Test-ID**

```json
{"gate_unit_pass": true, "gate_magnitude_pass": true, "gate_power_pass": false, "gate_propagation_pass": false, "attempt": 1, "reviewer_verdict": "accept", "reviewer_confidence": "low", "domain": "mech", "cross_domain_quantity_changed": false, "interface_node_touched": false, "prior_failures_module": 1, "spec_coverage": "low"}
```

**Test-OOD-A** (`attempt == 3`)

```json
{"gate_unit_pass": true, "gate_magnitude_pass": true, "gate_power_pass": true, "gate_propagation_pass": false, "attempt": 3, "reviewer_verdict": "accept", "reviewer_confidence": "mid", "domain": "ctrl", "cross_domain_quantity_changed": false, "interface_node_touched": true, "prior_failures_module": 0, "spec_coverage": "low"}
```

**Test-OOD-B** (unseen domain — firmware)

```json
{"gate_unit_pass": true, "gate_magnitude_pass": false, "gate_power_pass": true, "gate_propagation_pass": true, "attempt": 1, "reviewer_verdict": "accept", "reviewer_confidence": "high", "domain": "fw", "cross_domain_quantity_changed": false, "interface_node_touched": false, "prior_failures_module": 0, "spec_coverage": "mid"}
```

Reliability diagrams for Test-ID and for the two out-of-distribution sets are
`step4_measurement/reliability_test_id.png` and `reliability_ood.png`, drawn from
the per-seed bin counts the single measurement pass recorded. Each arm is plotted
in its scaled configuration where it has one, raw otherwise.

**Read L1's line with the bin counts in hand.** Because L1 is saturated, almost
all of its mass sits in the topmost bin and the middle bins hold a handful of
points each, so its line swings between 0.33 and 1.00 across bins that are
nearly empty. The swing is sampling noise in bins of size ~3, not structure. The
number that matters on those plots is the endpoint: on OOD-A, L1 sits at accuracy
≈ 0.45 at confidence ≈ 1.0, far below the diagonal, which is the picture of a
backend that is confidently wrong. Per-bin `n` for every arm, split and seed is
in `step4_summary.json`.

---

## 10. Acceptance — §7, checked criterion by criterion

> `laya` enters ARCH-132 as a contingent backend only if **L1** satisfies **C1,
> C2, C3 and C4**.

| | L1 | |
|---|---|---|
| C1 Calibration | 0.0264 raw / 0.0070 scaled vs ≤ 0.10 / ≤ 0.06 | **satisfied** |
| C2 Humility | fails both halves on both OOD sets, in every temperature configuration | **not satisfied** |
| C3 Selective accuracy | 0.4522 on OOD-A vs ≥ 0.95 | **not satisfied** |
| C4 Latency | 236.26 ms vs ≤ 500 ms | **satisfied** |

**`laya` does not enter ARCH-132.**

### The four kill criteria, each checked explicitly

| kill criterion | fires? | the number |
|---|---|---|
| C1 fails after temperature scaling | **no** | 0.0070 ≤ 0.06 |
| **C2 fails on both out-of-distribution sets** | **YES** | drop ≈ 0.0000 and rise = 0.0000 on OOD-A and OOD-B, raw, §3 and shipped alike |
| C3 fails on Test-ID | **no** | 0.9736 ≥ 0.95 |
| L1 cannot be trained on the available accelerator within 12 hours | **no** | 1.6494 h across all ten trainings, 13.745 % of budget |

One fires, and one is enough: **the backend is parked.**

### No ARCH-132 row is proposed

§7 authorises a draft replacement row **only if L1 passes**. It
did not, so none is drafted here and the architecture specification is not
edited. What this run produces is the evidence: the row for `laya`
currently reads *contingent, under test — R-LAYA-01*, and R-LAYA-01 now has a
result. ARCH-132's own acceptance clause already says *"a row whose experiment has
not passed reads contingent"*, so the status word does not change; the evidence
column is updated when this result has been reviewed, not here, and if it is
updated it must carry the proxy sentence from the verdict above.

**A note for whatever row is eventually written.**
Arm T is the only arm in this run that satisfies C1, C2 and C3, and it does so in
a single deployable configuration (raw) rather than by assembling a pass from two
different temperatures — `single_configuration_view` in `step4_summary.json`
records that for every arm. That is a transferability check of R-TM-01's known
answer, with §9's provenance caveat attached, and it is not a new result about
`tsetlin`. It is stated because this run measured it, not because anything here
proposes to change that row.

---

## 11. Deviations

Recorded here, never by editing the frozen file. Each names what could not be
measured as written, why, and how it was scored.

**D-1. C3 is undefined for arm L0 and is scored as failed.** L0 escalates every
decision on every split, so the set of kept decisions is empty on all five seeds
and selective accuracy has no value. CRITERIA §6 C3 asks for accuracy on
non-escalated decisions and does not define the empty case. Per the frozen rule
the criterion is scored **failed** rather than rewritten. L0's entry decision does
not rest on it (§3) and this changes nothing about L1.

**D-2. Arm R's laptop latency was not measured.** The export of Test-ID's raw
generator fields contains string columns, and `numpy.load` refuses object arrays
without `allow_pickle`. The failure surfaced after the splits were open, and
under R5 the run reports rather than repairs, so it was left. Arm R's latency is
non-gating context and it **is** measured on the server (p50 0.0127 ms). Arm T's
laptop latency was never possible at all — the amended §3 pins it to a Python
3.11 environment the laptop does not have — and that is a property of the
criteria, not a failure of this run.

**D-3. C2's baseline for OOD-B.** C2 asks for a drop *"below the Test-ID mean"*
and does not say which Test-ID when the OOD-B arm is a different model. The gated
reading follows `score_d.py`: OOD-A against Test-ID, **OOD-B against
Test-ID-nofw**, each against the in-distribution reference of the model that
scored it, because comparing a no-firmware model's OOD-B confidence to a
different model's Test-ID confidence would confound the retrain with the
distribution shift the retrain exists to separate. The literal reading is
computed for every arm and kept in `step4_summary.json`. **It changes no verdict
in this run.**

**D-4. Reliability diagrams were drawn on the laptop, not the server.** The
server environment has no `matplotlib`. The diagrams are a deliverable, not a
criterion, and they are drawn from the per-seed bin counts the single measurement
pass recorded — no split was re-read to produce them.

**D-5 (for the record, not a deviation from the criteria).** C1's range, the §3
slice, the escalation convention and the temperature treatment were all decided,
and committed in code, before the splits were opened, and are set out in §1. They are interpretations of
the frozen text, not changes to it, and a reader who prefers a different reading
has the alternative numbers: all three ECE variants and all three temperature
configurations are reported for every arm.

---

## 12. Artefacts and how to reproduce

Everything below was produced from commit `201166f`, which was committed before
`workload.splits(..., allow_test=True)` was called for the first time.

### What the artefacts record about their own provenance, and what they do not

**No output file in this experiment records the commit that produced it.** The
drivers do not stamp one: nothing under `rlaya/` calls `git rev-parse`, and none
of `step1_seed0.json`, `step2_*.json`, `step3_l1*.json` or `step4_*.json` carries
a commit, a branch or a run timestamp. **No stamp has been added now and no
driver has been edited to add one.** A commit id written into an artefact after
the fact would be an assertion dressed as a record, and it would be worse than
the gap, because it would read as evidence.

So the commit named above is **supported by the surrounding record rather than
recorded by the artefact**, and the difference is worth being exact about. What
the artefacts do carry is `criteria_commit` (`e12d153`) and `criteria_original`
(`7b85d29`) — the commits of the frozen *criteria*, not of the code — and, at
steps 2 and 3, `code_checksums`: the sha256 of each driver file as it stood when
it ran. **For those two steps that is stronger than a stamp, because it can be
checked against the history rather than believed.** Recomputing the files at each
commit on this branch resolves them to exactly one commit each:

| recorded in | file | sha256 (first 16) | the commit it matches |
|---|---|---|---|
| `step2_arms_gr_l0.json` | `fixture.py`, `workload.py`, `metrics.py`, `laya_backend.py`, `fit_arms.py` | all five | `d91ff88`, step 2 |
| `step3_l1_main.json` | `train_l1.py` | `075d9f5a2f941bed` | `fb76a02`, *"the L1 training driver, before the run"*, and no later commit |
| `step3_l1_nofw.json` | `train_l1.py` | `8b69d0181fd87796` | `6d48430`, *"arm L1 needs the no-fw retrain OOD-B is measured against"*, onward |

The third row is the record named as outstanding below, so that one cannot be
checked from this repository until it is committed; the first two can be, today.
The two step-3 records deliberately disagree, and the disagreement is the point:
the main five trainings were produced by the driver as it stood at `fb76a02`, and
the no-firmware five by the driver after the retrain fix at `6d48430`. A content
hash discriminates between those two commits; a stamp claiming one commit for the
whole step would have been wrong.

**Step 4 has no such field.** `step4_raw.json` records the environment and the
pins but no `code_checksums`, so step 4's code is pinned by commit order alone —
`a3a03a8` and `201166f` are in the history before `587be95`, with messages saying
they were committed before the splits were opened, and the tree was clean at each.
That is the weakest link in this chain and it is named rather than smoothed over.

**A consequence of correcting these files.** The docstring corrections in
`fa988b0` change the sha256 of `fixture.py`, `fit_arms.py`, `laya_backend.py`,
`measure.py`, `metrics.py`, `train_l1.py` and `verdict.py`, so five of them no
longer match the `code_checksums` above. That is stated rather than hidden. The
recorded checksums are the hashes of the files **as they were when they produced
the numbers**, which is what they are for; the later commit changed docstrings
and comments only, proven by parsing each file before and after and comparing the
syntax tree with docstrings stripped and source positions excluded — the trees
are identical, and no statement, expression, name or default changed.

| file | sha256 when it ran (first 16) | after the docstring correction |
|---|---|---|
| `fixture.py` | `1b3dec1677a5b629` | `d449208a46c41c59` |
| `fit_arms.py` | `6d0e2b30bf98e6e4` | `7481fbab4ae63f1f` |
| `laya_backend.py` | `7eb5b50ae629513d` | `081ce68710670d8d` |
| `metrics.py` | `adf7998652528d0b` | `603c87b16b33f2c5` |
| `train_l1.py` (no-fw) | `8b69d0181fd87796` | `beea65b731048c91` |
| `workload.py` | `88f6819203aff6ae` | unchanged |

`measure.py` and `verdict.py` were corrected too; no artefact records a checksum
for either.

### The timeline on the machine that ran it — corroboration, not a stamp

File modification times on the training machine, read on 2026-09-24, set against
this branch's commit times. **Commit times are converted to UTC here**; git
records them at `+0200`, and the server's file times are UTC, so the two are not
comparable as written.

| what | UTC |
|---|---|
| `fb76a02`, the L1 training driver, committed | 17:27:46 |
| first output it produced, `L1_seed0/model.safetensors` | 17:40:15 |
| main seeds' arrays, first to last | 17:40:28 → 18:25:00 |
| `step3_l1_main.json` written | 18:25:02 |
| `e326e33`, step 3 committed | 18:32:18 |
| `6d48430`, the no-firmware retrain, committed | 18:45:02 |
| first output it produced, `L1nofw_seed0/model.safetensors` | 18:54:37 |
| no-firmware seeds' arrays, first to last | 18:54:51 → 19:32:59 |
| `step3_l1_nofw.json` written | 19:33:01 |
| `201166f`, the measurement extended, committed | 19:40:12 |
| `587be95`, step 4 committed | 21:05:40 |

Each driver's first output lands after the commit of the driver that produced it,
each summary lands about two seconds after its own last array, and the sequence
is monotone throughout.

**The durations already in the record reconcile with those times, and that part
is checkable from the records themselves.** `step3_l1_main.json` puts seed 0 at
0.1884 h — 11.30 min — against a 12.48 min gap from the driver's commit to the
first checkpoint on disk, the difference being the model load. It puts all five
at 53.83 min against a 57.23 min window. The no-firmware record puts seed 0 at
0.1500 h — 9.00 min — against a 9.58 min gap, and all five at 45.14 min against a
47.95 min window. Nothing in the timeline requires a training run that the
recorded durations do not account for.

**What this is not.** A modification time is mutable metadata. It is not a
signature, it is not reproducible by a later reader, and it does not become one
by being tabulated. The finding stands exactly as it was: the outputs do not
record their own commit. This is agreement between two records kept separately,
which is a reason to believe the named commit, not a proof of it. The load-bearing
provenance is the `code_checksums` above, which anyone with this repository can
recompute.

### The single read of the splits is supported by the code, not independently checkable

The claim at the head of this document — the splits were built exactly once — is
what the code supports, and no more. `workload.splits()` raises unless it is
called with `allow_test=True`; `rlaya/measure.py:207` is the only call site in
the experiment that passes it, and the fence is a `RuntimeError`, not a comment;
`measure_arm_t.py` loads the arrays `measure.py` exported rather than
constructing anything, and `step4_arm_t.json` records `splits_source` as exactly
that. **Nothing outside the code proves it.** No artefact carries a construction
count, a run log or a stamp, and a script run twice would leave the same tree as
a script run once. The claim is as strong as the fence and the call sites, and
this paragraph is the whole of what backs it.

### The artefacts

| file | what |
|---|---|
| `step4_measurement/step4_raw.json` | every per-seed metric, the ten checkpoint hashes, the server latency, the three R3 examples |
| `step4_measurement/step4_arm_t.json` | arm T, scored in Python 3.11.15 with `tmu` 0.8.3 |
| `step4_measurement/step4_latency_laptop.json` | C4's gated run: per-seed percentiles, machine, device, load samples, process lists, peak RSS, cross-machine agreement |
| `step4_measurement/step4_summary.json` | the scoreboard, the verdicts, the single-configuration view, the budget |
| `step4_measurement/reliability_test_id.png`, `reliability_ood.png` | reliability diagrams, ten equal-width bins on [0.5, 1.0] |
| `C5-assumption-mismatches.md` | M1–M12, final |

**Outstanding: two step-3 records the verdict script reads are not yet in git.**
`rlaya/verdict.py:250-251` opens `step3_l1_main.json` and `step3_l1_nofw.json`.
Neither name is in this repository. `step3_l1.json`, which is, is byte-identical
to `step3_l1_main.json` — the same record under a shorter name — and contains the
main five seeds and no `nofw` key. Both records exist on the machine that wrote
them, at `~/rlaya01/out/step3/`, and must be committed **unchanged, byte for
byte**, under exactly those two names, into `step3_train_l1/`. They must match:

```
8cb25d78f5099713f3e13ed083707141a244dec1d79c38abc4248fd5f597dc25  step3_l1_main.json  (30 593 B)
8b5cd7b65b3095470b29d41a2db98884d193ae2928d7168e08b2c80a030364c8  step3_l1_nofw.json  (30 957 B)
```

Until `step3_l1_nofw.json` is committed, the statement that the second kill
criterion fired is not checkable from this repository; the non-entry verdict is,
as the Verdict's *"Which of these rests on which evidence"* sets out. Nothing has
been reconstructed, regenerated or renamed to stand in for either file, and
`step3_l1.json` has not been renamed to fill one of the two names.

Per-seed probability arrays (`probs_<arm>_<split>_seed<s>.npz`), the exported
splits and the serialised states stay on the server at `~/rlaya01/out/step4/`;
they are large and are not in git. The five fine-tuned checkpoints and their five
no-firmware counterparts stay at `~/rlaya01/out/step3/`, hashed in §8.

**Pins.** Repository `NandhaKishorM/laya` @
`42626c348753fbb17572a813127df2278a1ec527`; `laya==0.3.4`; checkpoint
`convaiinnovations/laya-typed-decisions` @
`f9ab0b228f0fc0f14d873dbc99038f135c2da1b2`. Server: Python 3.12.14,
torch 2.9.1+cu126, transformers 5.17.0, numpy 2.5.3, scikit-learn 1.9.1, on
Tesla V100-SXM3-32GB (compute capability 7.0, driver 570.172.08), host
`coder-yasinh-declassifai-55c6d799db-tsskx`, Xeon Platinum 8168, 2 cores. Arm T:
Python 3.11.15, `tmu` 0.8.3, numpy 2.4.6, scikit-learn 1.9.1, scipy 1.17.1, with
the two recorded `tmu` source patches. Laptop: Python 3.12.6, torch 2.9.1, mps,
MacBookPro17,1 / Apple M1 / 8 cores / 8 GB / macOS 26.2 build 25C56.
Seeds 0, 1, 2, 3, 4 throughout; the TM seed is 1000 + the data seed, because
`tmu` hangs on internal seed 0.

**Generator checksums**, vendored copies byte-identical to
`experiments/R-TM-01/R-TM-01_complete/run05d/`, which was not modified:

```
ead13b9b8041851d7b03e72100d7da7ba98a784c1e73ffad0d9e935f614b038d  generator_b.py
6e913b3bfc55b43869638c23463c3deb417216ffaaf981c747b78a157c75c16e  generator.py
```
