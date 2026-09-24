# R-LAYA-01 step 3 — arm L1 trained. Five seeds, four epochs, nothing shortened.

**A step report, not the result.** `RESULT.md` is written at step 4. **Nothing was
scored.** Test-ID, OOD-A and OOD-B were not constructed in any process this step
ran.

Criteria frozen at `e12d153` (original `7b85d29`). Driver committed before the
run at `fb76a02`, per §6.1. Raw record: `step3_l1.json`; per-micro-batch arrays
in `L1_steps_seed{0..4}.npz`; calibration logits in `L1_calib_seed{0..4}.npz`.
The five fine-tuned checkpoints (842 609 220 B each) live on the server at
`~/rlaya01/out/step3/L1_seed{0..4}/` and are not in git.

---

## 1. The budget

| | |
|---|---|
| **Measured, five seeds** | **0.8971 h** |
| of which per-micro-batch finiteness instrumentation | 0.1152 h |
| **Training alone** | **0.7819 h** |
| Budget | 12 h |
| **Fraction of budget used** | **7.48 %** |
| Step 1 predicted (five seeds) | 0.7558 h |
| **Ratio, like for like** | **1.035** |

Step 1's extrapolation explicitly excluded the finiteness check as
instrumentation, so the honest comparison is **0.7819 against 0.7558 — 3.5 %
high**. Including the instrumentation the total is 1.187× the prediction, and the
difference is entirely the check: 20 000 micro-batches × ~20 ms.

Per seed:

| seed | wall clock | training alone | micro-batches | updates | s / micro-batch | peak memory |
|---|---|---|---|---|---|---|
| 0 | 0.1884 h | 0.1653 h | 4 000 | 500 | 0.1414 ± 0.0264 | 7.78 GiB |
| 1 | 0.1824 h | 0.1582 h | 4 000 | 500 | 0.1348 ± 0.0233 | 7.78 GiB |
| 2 | 0.1760 h | 0.1534 h | 4 000 | 500 | 0.1305 ± 0.0222 | 7.78 GiB |
| 3 | 0.1752 h | 0.1525 h | 4 000 | 500 | 0.1298 ± 0.0223 | 7.78 GiB |
| 4 | 0.1752 h | 0.1526 h | 4 000 | 500 | 0.1298 ± 0.0226 | 7.78 GiB |

4 000 micro-batches and 500 updates on every seed, which is 8 000 items ÷ 8 × 4
epochs and ÷ 8 accumulation — the recipe's count, unchanged. Peak memory is
identical to step 1's measurement to three significant figures.

**Nothing was shortened.** Four epochs, the full cosine schedule to `eta_min`
1e-6, the sigma ramp 0.4 → 0.1, effective batch 64. There was never a reason to
reach for a shortcut: the arm used a fourteenth of the budget.

---

## 2. Precision — said plainly

**fp16 is the training path, and it is the recipe's own.** The pinned notebook
targets 2×T4, which is compute capability 7.5 and has no bf16 either, so it
trains under `torch.autocast("cuda", dtype=torch.float16)` with
`torch.amp.GradScaler`. Nothing about the recipe was changed for precision.

**The fp32 pin recorded as C5 M10 is on *scoring*, not on training.** It applies
to the path that turns a state into a probability at steps 3 and 4, because under
fp16 that path is not a function of its input alone. It has no bearing on how the
weights were fitted.

Three adaptations, all forced by the hardware, none of them shortening training:
world size 2 → 1 so DDP is dropped; gradient accumulation 4 → 8, which holds the
recipe's effective batch at 64 sequences at world size 1; and fp16, which as
above is the recipe's own.

---

## 3. fp16 gradients — per seed, per step, and not only at start-up

**Default `torch.amp.GradScaler("cuda", enabled=True)`. No `init_scale`.** Setting
one would have been tuning after seeing step 1's numbers.

| seed | non-finite scaled-gradient micro-batches | rate | skipped updates | skip rate | scale: first → last (min) |
|---|---|---|---|---|---|
| 0 | 32 / 4 000 | 0.800 % | 6 / 500 | 1.2 % | 65 536 → **1 024** (1 024) |
| 1 | 31 / 4 000 | 0.775 % | 7 / 500 | 1.4 % | 65 536 → **512** (512) |
| 2 | 36 / 4 000 | 0.900 % | 7 / 500 | 1.4 % | 65 536 → **512** (512) |
| 3 | 27 / 4 000 | 0.675 % | 6 / 500 | 1.2 % | 65 536 → **1 024** (1 024) |
| 4 | 27 / 4 000 | 0.675 % | 6 / 500 | 1.2 % | 65 536 → **1 024** (1 024) |

**The loss was finite at every one of the 20 000 micro-batches, on every seed.**
Every non-finite gradient coincided with a skipped optimiser step; no parameter
was ever updated from one.

### The scale does not drift toward 1

It settles at **512 or 1 024** — 2⁹ to 2¹⁰ — and stays there. The full trajectory
per seed, as `(update, from → to)`:

| seed | scale changes |
|---|---|
| 0 | (0, 65536→32768) (1, 32768→16384) (28, 16384→8192) (30, 8192→4096) (31, 4096→2048) (37, 2048→1024) |
| 1 | (0, 65536→32768) (1, 32768→16384) (28, 16384→8192) (55, 8192→4096) (57, 4096→2048) (72, 2048→1024) **(443, 1024→512)** |
| 2 | (0, 65536→32768) (2, 32768→16384) (28, 16384→8192) (41, 8192→4096) (42, 4096→2048) **(247, 2048→1024)** **(300, 1024→512)** |
| 3 | (0, 65536→32768) (2, 32768→16384) (3, 16384→8192) (70, 8192→4096) **(230, 4096→2048)** **(255, 2048→1024)** |
| 4 | (0, 65536→32768) (1, 32768→16384) (28, 16384→8192) (33, 8192→4096) (36, 4096→2048) (41, 2048→1024) |

The bold entries are back-offs that happen **after** the opening transient. Seed 1
backs off at update 443 of 500 — 89 % of the way through.

### Excursion clusters, with the epoch they fall in

This is the part "finished with finite gradients" would have hidden. **Three of
the five seeds had an excursion after epoch 0.**

| seed | clusters, as (micro-batch range, epoch) | excursions by epoch | last excursion |
|---|---|---|---|
| 0 | (0–7, e0) (12–15, e0) (229–231, e0) (240–247, e0) (250–255, e0) (301–303, e0) | 32 / 0 / 0 / 0 | mb 303, epoch 0 |
| 1 | (0–7, e0) (10–15, e0) (230–231, e0) (444–447, e0) (459–463, e0) (581–583, e0) **(3549–3551, e3)** | 28 / 0 / 0 / **3** | **mb 3551, epoch 3** |
| 2 | (0–7, e0) (17–23, e0) (230–231, e0) (334–335, e0) (338–343, e0) **(1978–1983, e1)** **(2403–2407, e2)** | 25 / **6** / **5** / 0 | **mb 2407, epoch 2** |
| 3 | (0–7, e0) (20–23, e0) (28–31, e0) (566–567, e0) **(1847, e1)** **(2040–2047, e2)** | 18 / **1** / **8** / 0 | **mb 2047, epoch 2** |
| 4 | (0–7, e0) (10–15, e0) (226–231, e0) (268–271, e0) (294–295, e0) (335–335, e0) | 27 / 0 / 0 / 0 | mb 335, epoch 0 |

Seeds 0 and 4 are the clean case: everything in the first 350 micro-batches while
the scaler finds its level, then nothing for the remaining 3 650. Seeds 1, 2 and
3 are not, and a run that reported only its final state would have said the same
thing about all five.

The opening cluster (0–7) is the same in every seed and is the scaler's default
initial 2¹⁶ being one notch too high, exactly as step 1's static-scale ladder
predicted: fp32 gradients are finite and small, and fp16 holds them at 2¹⁵ and
below.

### Gradient norms, including the other tail

| seed | min | median | max | finite updates |
|---|---|---|---|---|
| 0 | 7.85e-07 | 3.66 | 2 003 | 494 / 500 |
| 1 | 2.59e-07 | 4.06 | 2 839 | 493 / 500 |
| 2 | 1.18e-02 | 5.27 | 2 961 | 493 / 500 |
| 3 | 1.11e-06 | 7.14 | 1 813 | 494 / 500 |
| 4 | 1.42e-06 | 8.53 | 2 375 | 494 / 500 |

The clip is 1.0, so the large norms are clipped and the update sizes are
unaffected by them. The small tail is the **other** fp16 effect and is worth
naming: at a settled scale of 512–1 024, a small gradient rounds to zero in fp16,
so an update with an unscaled norm of 1e-6 did essentially nothing. **How often
that happened is not recoverable from what was logged** — the driver kept the
minimum, median and maximum per seed but not the full per-update distribution.
That is an instrumentation gap, it is named here rather than glossed, and it
affects no number any criterion is scored on.

---

## 4. Training did something

Per-epoch means, over all 4 000 micro-batches of each seed.

| seed | loss e0 → e3 | reward e0 → e3 |
|---|---|---|
| 0 | 0.5138 → 0.3902 | 0.2772 → 0.5010 |
| 1 | 0.4969 → 0.3820 | 0.3617 → 0.5129 |
| 2 | 0.5545 → 0.3755 | 0.3056 → 0.5159 |
| 3 | 0.5189 → 0.3576 | 0.2921 → 0.5309 |
| 4 | 0.5598 → 0.4080 | 0.1765 → 0.5060 |

Loss falls and the proper-scoring-rule reward rises on every seed. Reported
without interpretation: these are training-set quantities and they say the
optimisation ran, not that the arm is any good. Two seeds are non-monotone in the
middle — seed 3's epoch-1 loss mean is 0.6699 against 0.5189 at epoch 0, seed 4's
is 0.6729 against 0.5598 — and both recover by epoch 3. Recorded because it is
there, not explained.

---

## 5. The resolution of D2 applied to the newly produced checkpoints — and what that turned up

The recipe ends by fitting temperatures with LBFGS on `items[::15][:400]` and
writing them into the checkpoint it saves. Those values, per seed:

| seed | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| recipe `temperature[noul]` | 5.2999 | 4.9368 | 4.8646 | 4.6687 | 4.7921 |
| recipe `temperature[choice]`, `[score]` | 1.2 | 1.2 | 1.2 | 1.2 | 1.2 |

`choice` and `score` stay at the recipe's 1.2 default because this workload
contains no question of those kinds — `fit_one_temp` is only reached for a type
that has items.

### The finding: that fitted value can never take effect

Verified by loading `L1_seed0` and asking the Agent which constant it would
apply, rather than by reading the code:

| | |
|---|---|
| `temperature` in the saved config | `[1.2, 1.2, **5.29985237121582**]` |
| `temperature_by_options["noul:2"]`, inherited from the **zero-shot** checkpoint | **1.983399510383606** |
| bucket for a two-option `noul` question | `noul:2` |
| **what `laya.Agent` actually applies** | **1.983399510383606** |
| **is the recipe's fresh fit reachable?** | **No** |

`laya/agent.py` resolves
`self.temperature_by_options.get(temp_bucket(qt, k), self.temperature[qt])` —
`temperature_by_options` wins — and the notebook writes only `cfg["temperature"]`.
So the recipe's post-training calibration is dead on arrival, and a stale
constant fitted by a different run on a different corpus takes precedence. This
is upstream's behaviour reproduced faithfully, not an artefact of the single-GPU
adaptation. **C5 M12.**

Two consequences for step 4, both stated now:

1. The non-gating shipped-temperature pass must use **1.9834** — the constant a
   user of the checkpoint would actually get — not the 5.30 the config
   advertises.
2. The resolution of D2 turns out to have been right for a reason nobody had
   named:
   without it, L1 would have been scaled by a **zero-shot** constant while arm T
   was scaled by a fit on this run's Train.

### What was neutralised, per seed

Both fields, in process, before anything was scored. The checkpoints on disk are
unmodified. Prior values, identical in structure on all five seeds:

- `temperature`: `[1.2, 1.2, <the recipe fit above>]`
- `temperature_by_options`: `{"choice:3-5": 1.7601518630981445, "choice:6-10": 1.0000158548355103, "score:3-5": 1.2514300346374512, "noul:2": 1.983399510383606, "choice:11+": 0.10058280825614929, "choice:2": 1.9063563346862793}`

Set to `[1.0, 1.0, 1.0]` and `{}`. R6 is untouched: a temperature is a
calibration constant in a JSON config, not a weight.

### The §3 temperature, fitted on `Train[0:500]`

Fitted against the **reloaded** checkpoint — the model step 4 will actually score
— rather than the in-memory one, and with `metrics.fit_temperature`, the same
function arms T and L0 used, on the same slice.

| seed | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| **L1, §3 fit** | **4.8531** | **4.4651** | **5.3140** | **4.8909** | **4.4965** |
| L1, recipe's own fit (different slice, different optimiser) | 5.2999 | 4.9368 | 4.8646 | 4.6687 | 4.7921 |
| L0, §3 fit (step 2) | 8.5625 | 1.1388 | 6.7908 | 1.6381 | 1.9541 |
| T main, §3 fit (step 2) | 0.1997 | 0.1720 | 0.1972 | 0.1764 | 0.1664 |

Two things worth recording, both about the fit and neither about performance:

- **L1's §3 temperature settles** — 4.47 to 5.31, a spread of 19 % — where L0's
  swung by a factor of 7.5 (C5 M11). Training gave the score enough signal for a
  500-sample fit to converge. This is the contrast M11 predicted and it is
  recorded before any test split is opened.
- **Two independent fits agree.** The §3 fit (scipy bounded scalar, `Train[0:500]`,
  fp32 scoring) and the recipe's own (LBFGS, `items[::15][:400]`, fp16 scoring)
  land within 9 % of each other on every seed. They share data and a model, so
  this is a consistency check rather than independent evidence — but had they
  disagreed by a factor, one of them would have been wrong.

---

## 6. Resolved environment, checkpoints and seeds

| | |
|---|---|
| Host | `coder-yasinh-declassifai-55c6d799db-tsskx`, Linux 6.8.0-64-generic, glibc 2.39 |
| GPU | Tesla V100-SXM3-32GB, compute capability **7.0**, 34 072 559 616 B, driver 570.172.08 |
| CPU | `nproc` 2 |
| Python | 3.12.14 |
| torch | **2.9.1+cu126**, CUDA 12.6, cuDNN 91002 |
| `torch.cuda.get_arch_list()` | `['sm_50','sm_60','sm_70','sm_75','sm_80','sm_86','sm_90']` |
| transformers / laya / numpy | 5.17.0 / 0.3.4 / 2.5.3 |
| Base checkpoint | `convaiinnovations/laya-typed-decisions` @ `f9ab0b228f0fc0f14d873dbc99038f135c2da1b2` |
| Recipe | `NandhaKishorM/laya` @ `42626c348753fbb17572a813127df2278a1ec527`, `notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb` |
| Scoring path | `cuda`, **`torch.float32`** (Laya would have chosen `torch.float16`), `sdpa`, `allow_tf32` **False** |

**Seeds 0, 1, 2, 3, 4.** Draw fingerprints recorded again in this step and
identical to steps 2's on all five.

**The produced checkpoints**, sha256 of `model.safetensors`:

| seed | sha256 (first 16) |
|---|---|
| 0 | `857fa9b6a84fe0d0` |
| 1 | `a67ee9e81b99f666` |
| 2 | `4676a47042152976` |
| 3 | `4f0e19119e419df1` |
| 4 | `24fd42c70c187ed4` |

Each is 842 609 220 bytes, stored **F16** — byte-identical in size and storage
dtype to the base checkpoint, which also ships F16. The recipe's `.half()` save
therefore introduces no precision step the checkpoint lineage did not already
have. Verified by reading the tensor dtype out of both files, not inferred.

---

## 7. One behaviour of the recipe worth stating, since it was visible in the log

`train_ddp.py` calls `scheduler.step()` inside the update block **unconditionally**,
including when `scaler.step(optimizer)` has just skipped the update. torch emits
the "Detected call of `lr_scheduler.step()` before `optimizer.step()`" warning on
the first update of every seed for exactly this reason — the first update is
always skipped while the scaler backs off from 2¹⁶.

The consequence is small and is recorded rather than fixed: a skipped update
still advances the cosine schedule, so a seed with 7 skips completes its 500-step
schedule having taken 493 optimiser steps. This is the recipe's own behaviour,
kept verbatim, and changing it would have been a modification to the recipe
rather than an adaptation the card forces.

---

## 8. What this step did not do

It did not score anything. Every number above is a training-set quantity, a
property of the environment, or a property of the optimisation. C1, C2, C3 and C4
are measured at step 4, on splits that still do not exist in any process this
experiment has run.
