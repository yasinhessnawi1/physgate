# R-LAYA-01 step 1 — is arm L1 trainable on the available accelerator?

**This is a step report, not the result.** `RESULT.md` is written at step 4, and
the numbers here are scored against exactly one thing: CRITERIA §7's fourth kill
criterion, *"L1 cannot be trained on the available accelerator within 12 hours."*
Nothing here is a metric for C1, C2, C3 or C4, and no test split was constructed,
let alone read.

Criteria frozen at `e12d153`, the amendment of `7b85d29`. Harness committed
before the run at `da57940`, per standards §6.1; the raw record is
`step1_seed0.json`, produced by `feasibility_l1.py` at that commit, seed 0.

---

## Verdict

**L1 trains, and the fourth kill criterion does not fire.**

The arm — five seeds, the recipe's four epochs, nothing shortened — extrapolates
to **0.756 h**, about 45 minutes, against a 12-hour budget. The margin is a
factor of about 16.

Three things had to be true and all three are, measured on the machine rather
than assumed:

1. A torch wheel that still carries `sm_70` exists and was found: `2.9.1+cu126`.
   The current default wheel does not.
2. The fp16 step runs and its gradients are finite wherever the optimiser uses
   them. The loss scaler backed off six times over 51 updates and absorbed every
   excursion; no parameter was ever updated from a non-finite gradient.
3. Memory is not close to the limit: 7.8 GiB peak of 31.7 GiB.

---

## 1. The budget arithmetic

The extrapolation is **the whole arm, five seeds**, on the orchestrator's ruling
of 21.09.2026 that "L1 cannot be trained within 12 hours" is a statement about
the arm and not about one seed. The per-seed number is given separately so a
reader who prefers the other reading can use it. **Nothing is shortened to fit**:
epochs stay at the recipe's 4 and the schedule is the recipe's schedule.

| | |
|---|---|
| Train items per seed | 8 000 (`generator_b.build_all(seed)["train"]`) |
| Micro-batch | 8 sequences (recipe) |
| Gradient accumulation | 8 (recipe is 4 at world size 2; 8 at world size 1 keeps the recipe's effective batch of 64) |
| Epochs | 4 (recipe) |
| Micro-batches per seed | 8 000 / 8 × 4 = **4 000** |
| Optimiser updates per seed | 4 000 / 8 = **500** |
| Measured seconds per micro-batch | **0.1291** (sd 0.0216, p50 0.1258, min 0.1181, max 0.3300; 400 timed, 8 warm-up discarded) |
| Measured seconds per collate (host) | 0.000608 |
| Measured seconds per optimiser update (unscale, clip, step) | 0.0503 |

```
per seed = 4000 × (0.12914 + 0.000608) + 500 × 0.05031 = 544.1 s = 0.1512 h
five seeds = 544.1 × 5 = 2720.6 s = 0.756 h
```

**Assumptions named.** The rate is assumed constant across the run; it was
measured over 400 consecutive micro-batches with the encoder, gradient
checkpointing, the scaler and AdamW all live, so it includes everything in the
loop. Excluded, because they are one-off and small against the total: model load
(8.6 s), tokenisation (3.4 s per seed), and the recipe's post-training
temperature fit (400 items, forward only). Adding all of these at five seeds
moves the total by under a minute.

**Two sensitivity bounds, both still inside the budget:**

| | five seeds |
|---|---|
| measured mean | **0.756 h** |
| mean + 2 sd per micro-batch | 0.995 h |
| every sequence padded to the recipe's ceiling of 1024 tokens | **3.97 h** |

The last row is the one that matters for the provisional-serialisation caveat
below: even if step 2's real R3 fixture produced sequences seven times longer
than the ones measured here — the recipe's maximum, `max_len` 1024 — the arm
still finishes in under four hours. The verdict does not depend on the
provisional serialisation being right about length.

---

## 2. Throughput, and the upstream comparison

The checkpoint records its own training in `rl_agent_config.json`:
`updates: 7313`, `epochs_completed: 1`, `hours: 1.96`, `world_size: 1` — that is
**0.9649 s per update**. It records neither the sequences per update nor the
token lengths behind them, and names no hardware. So it is a comparison point,
not a controlled one, and two bracketing numbers are given rather than one.

| | s / optimiser update at 64 sequences | vs upstream 0.9649 |
|---|---|---|
| this workload, ~147 tokens per sequence | **1.0834** | ×1.12 |
| same batch at the recipe's ceiling, 1024 tokens | **5.6581** | ×5.86 |

Read honestly: **if** upstream's updates were 64 sequences at the full 1024-token
length, this V100 is **5.9× slower** than whatever card produced the checkpoint.
If upstream's sequences were short, the factor is nearer 1.1. The true factor is
somewhere in that bracket and the checkpoint does not record enough to close it.
What *is* certain is the absolute number on this card: 0.1291 s per micro-batch
of 8 × 147 tokens, 61.9 sequences/s, 7.8 GiB peak.

**Which of the two things a hypothetical kill would be about.** It is not
academic here, because the criterion did not fire — but for a later run: this
result is a statement about *the hardware*, not about Laya. Laya's own recipe
runs on 2×T4 in "~4 to 6 minutes" for 6 000 items × 4 epochs. Nothing about the
engine makes it slow. A newer card would simply move 0.756 h down.

**The host is not the bottleneck.** Collate is 0.6 ms against a 129 ms step
(0.5 %), and tokenisation runs at 2 379 items/s, i.e. 3.4 s for a whole seed's
Train, once. The machine's CPU allocation is worth stating carefully because
three sources disagree: `nproc` reports **2**, the cgroup quota at
`/sys/fs/cgroup/cpu.max` reads `600000 100000` (6 cores), the affinity mask has
96, and torch chose 2 threads. Whichever is true, the GPU step dominates by more
than two orders of magnitude, so the two-core figure that C4 rests on does not
threaten the training budget. It may still matter for C4's latency, which is a
step-4 measurement.

---

## 3. Were the gradients finite — throughout, not at the end?

**No, and that is the accurate answer.** There were four excursions. Every one of
them was absorbed by the loss scaler, and no optimiser step ever consumed a
non-finite gradient.

**Is fp16 the problem, or is the scaler just starting high?** Answered before any
timing was kept, by re-running the same backward at a ladder of static scales:

| path | non-finite parameter tensors (of 205 with gradients) | max abs gradient |
|---|---|---|
| fp32, unscaled | **0** | 0.624 |
| fp16, static scale 2¹⁶ = 65 536 | **199** | — |
| fp16, static scale 2¹⁵ = 32 768 | **0** | 2.30e4 |
| fp16, static scale 2¹⁴ and below | **0** | ≤ 8.30e3 |

So the fp32 gradients are finite and small, and fp16 represents them fine at any
scale from 2¹⁵ down. `torch.amp.GradScaler`'s default initial scale is exactly
2¹⁶, one notch too high. The opening overflow is the scaler doing its job.

**The per-micro-batch log, over 408 micro-batches and 51 updates:**

| | |
|---|---|
| micro-batches with a non-finite **scaled** gradient | **28 of 408 (6.9 %)** |
| indices | 0–7, 12–15, 227–231, 238–239, 246–247, 369–375 |
| optimiser updates **skipped** by the scaler | **6 of 51 (11.8 %)** |
| updates whose unscaled gradient norm was non-finite | 6 — the same 6 |
| updates that stepped with a finite gradient norm | 45 (min 2.45, median 40.95, max 1104.52) |
| loss non-finite at any micro-batch | **0 of 408** |
| scaler scale trajectory | 65 536 → 32 768 → 16 384 (held 26 updates) → 8 192 → 4 096 → 2 048 (held 16) → 1 024 |

**The part that "it finished fine" would have hidden:** the excursions are *not*
only a start-up transient. Two of the four clusters are at micro-batches 227–247
and 369–375, deep into the run, and the scale had to come down twice more. The
scaler handled it each time. The reason is visible in the gradient norms: they
grow from ~2.5 to over 1 100 as training proceeds, so the headroom that 16 384
bought at the start is gone by the middle. This is a property of the recipe under
fp16, and step 3 must log it the same way for the full arm rather than reporting
a final state. **A drift down to a scale near 1 would be the warning sign**; over
51 updates it settled at 1 024, which is ordinary.

Recorded against C5 M1. The gradient clip is 1.0, so the large norms are clipped
and the update magnitudes are not affected by them; only the fp16 representation
is.

---

## 4. Resolved environment

Every version was read from the installed artefact, not from documentation
(standards §9). Reproduced verbatim from `step1_seed0.json`.

**Server** — `ssh main.DeclassifAI.yasinh.coder`

| | |
|---|---|
| OS | Linux 6.8.0-64-generic, glibc 2.39 (Ubuntu 24.04) |
| GPU | Tesla V100-SXM3-32GB, compute capability **7.0**, 34 072 559 616 B (31.73 GiB) |
| Driver | 570.172.08 |
| CPU | `nproc` 2; cgroup `cpu.max` `600000 100000`; affinity mask 96; torch threads 2 |
| System memory | 1 510 GB |
| bf16, hardware | **False** (`torch.cuda.is_bf16_supported(including_emulation=False)`) |
| bf16, default query | True — torch reports emulation as support; the default query is misleading on this card |

There was no Python on the machine. `uv 0.12.17` was installed to `~/.local/bin`
and a fresh virtual environment built at `~/rlaya01/.venv`. The pre-existing
`~/venv` was not touched and is not used.

| pin | value |
|---|---|
| Python | 3.12.14 (uv-managed CPython) |
| torch | **2.9.1+cu126** |
| torch CUDA | 12.6 |
| `torch.cuda.get_arch_list()` | `['sm_50', 'sm_60', 'sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90']` |
| cuDNN | 91002 |
| transformers | 5.17.0 |
| laya | **0.3.4** (CRITERIA §2 pin) |
| numpy | 2.5.3 |
| safetensors | 0.8.0 |
| huggingface_hub | 1.32.0 |
| checkpoint | `convaiinnovations/laya-typed-decisions` @ `f9ab0b228f0fc0f14d873dbc99038f135c2da1b2` (CRITERIA §2 pin) |
| recipe source | `NandhaKishorM/laya` @ `42626c348753fbb17572a813127df2278a1ec527`, `notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb` (CRITERIA §2 pin) |

**Why 2.9.1 and not something newer.** Measured, not looked up:
`torch==2.14.0+cu130` and `torch==2.13.0+cu129` both report
`['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']` — **no `sm_70`**. The
`cu126` line is the newest CUDA line PyTorch still builds for Volta and it stops
at 2.9.1. That is the ceiling, and it has an expiry date: see C5 M3.

**Attention implementation, confirmed on the instantiated model, not inferred.**
`model.encoder.config._attn_implementation` is `sdpa`.
`laya.common.build_model` hard-codes `attn_implementation="sdpa"` on both
construction paths, so flash-attention-2 is never requested and there is no
fallback to detect — Laya simply does not use it. The sliding-window layers are
on the same path: `layer_types` holds both `full_attention` and
`sliding_attention` with `local_attention` 128 and `global_attn_every_n_layers`
3, as the checkpoint's config specifies. `reference_compile` is **absent** from
the config, so nothing needed disabling; the model ran without any
`torch.compile` step, which is what you want on two cores.

**Model.** `ModernBertModel` encoder plus Laya's typed head,
**421 293 827 parameters**, all trainable, gradient checkpointing on for the
encoder and `head_checkpointing = True`, loaded from `model.safetensors`
(842 609 220 B, sha256 `4fa56de7…07a24e`) with `strict=True`.

**Generator checksums** (vendored copies, byte-identical to
`experiments/R-TM-01/R-TM-01_complete/run05d/`, which was not modified):

```
ead13b9b8041851d7b03e72100d7da7ba98a784c1e73ffad0d9e935f614b038d  generator_b.py
6e913b3bfc55b43869638c23463c3deb417216ffaaf981c747b78a157c75c16e  generator.py
```

---

## 5. The provisional serialisation, and what it measured

**Stated plainly: the serialisation used here is provisional and is not the R3
fixture.** The fixture is step 2's deliverable. This one exists so that the
timing above runs on sequences of a realistic length rather than on invented
ones. It is committed as `serialisation_provisional.py` so step 2 can diff
against it.

It emits exactly the raw generator fields, in the generator's own order, with
readable values, no derived feature and never the label. One choice in it is a
judgement step 2 has to make deliberately: the generator stores gates and the two
flags as `int8` 0/1, and this module renders them as JSON booleans.

Example, seed 0, Train, item 0 — **147 tokens**:

```json
{"gate_unit_pass": true, "gate_magnitude_pass": true, "gate_power_pass": true,
 "gate_propagation_pass": true, "attempt": 2, "reviewer_verdict": "accept",
 "reviewer_confidence": "mid", "domain": "mech",
 "cross_domain_quantity_changed": false, "interface_node_touched": false,
 "prior_failures_module": 0, "spec_coverage": "mid"}
```

**Token length over all 8 000 Train items**, through Laya's own
`build_sequence` with the CRITERIA §2 question at `max_len` 1024,
`head_max_len` 256:

| min | p50 | mean | p90 | p99 | max |
|---|---|---|---|---|---|
| 146 | 147 | 146.75 | 147 | 148 | 148 |

The distribution is almost a point mass, because the state has a fixed set of
twelve fields whose values are short. A different serialisation could change it
— but only upward, and the 1024-token bound in §1 shows the verdict survives
even the maximum. **If step 2's fixture moves the p99 materially above ~150
tokens, re-check §1's arithmetic against the 1024-token row rather than assuming
it still holds at 0.756 h.**

---

## 6. Rules observed

- **R4 / I-5, no test split.** `feasibility_l1.py` does not call
  `generator_b.build_all`. It calls `make_split(8000, default_rng(seed),
  attempts=(1, 2))`, which is byte-for-byte `build_all(seed)["train"]` because
  `build_all` draws Train first from a fresh generator. Test-ID, OOD-A and OOD-B
  are never constructed in the process, so they cannot have been looked at.
- **R-TM-01 untouched.** `generator.py` and `generator_b.py` were copied out and
  their checksums verified against the originals. `git status` shows no change
  under `experiments/R-TM-01/`.
- **§6.1, commit before the run.** Harness at `3ef2c1a`, probe additions at
  `da57940`; the run that produced `step1_seed0.json` started from `da57940`.
- **CRITERIA.md unchanged.** Two things that cannot be measured as written are
  recorded as prospective deviations in §7 below, for the orchestrator to rule on
  before step 2. Neither is edited into the frozen file.

---

## 7. Prospective deviations — for the orchestrator, before step 2

Raised now, with no metric in hand, so that the decision is not made after seeing
a number.

### D1 — CRITERIA §5's stated label noise and accuracy ceiling do not match the generator it pins

CRITERIA §5 says the label is *"the same hidden-rule output with the same **5 %
noise**, which puts the achievable accuracy ceiling at about 0.95"*, and says
that ceiling is written down *"because R-TM-01's first pre-registration was
killed by a threshold that sat above its own ceiling."*

The generator it pins says otherwise. `generator_b.py` — the file §5 names, whose
checksum §5 records, byte-identical across runs 03b, 04c and 05d — sets
`LABEL_NOISE = 0.01`, and its own docstring states the change as deliberate:
*"label noise 5 % -> 1 %, so the accuracy ceiling rises from 0.950 to 0.990."*
R-TM-01d's frozen pre-registration agrees: *"1 % label noise; train 8 000
(attempts 1–2), Test-ID 2 000, OOD-A 1 000."* The 5 % figure belongs to
`generator.py`, R-TM-01's original.

**Why it matters, and why it is not an excuse for anything.** The ceiling is
**0.99, not 0.95**. C3's threshold is ≥ 0.95 on retained decisions, so the
threshold is *not* at its ceiling — the error makes C3 look tighter than it is
and moves no bar in the direction of the thing under test. R-TM-01d's retained
accuracies of 0.962–0.989 are consistent with the 0.99 ceiling and would have
been impossible against a 0.95 one.

**Recommendation.** No threshold changes, because none can. `RESULT.md` records
the frozen sentence, the measured value of `LABEL_NOISE` in the pinned file, and
the correct ceiling, and every criterion is scored against the thresholds exactly
as frozen. The irony is worth stating in the result: this is the same class of
error — a ceiling asserted rather than checked — that §5 exists to prevent.

### D2 — L1 will carry two temperature fits, and CRITERIA §3 admits only one

CRITERIA §3: temperature for L0, L1 and T is fitted on a 500-sample slice of
Train, drawn once, *"identical for every arm, so that temperature fitting is not
itself a source of difference between arms."*

But Laya fits its own. The pinned recipe ends with `fit_one_temp` on 400 held
items and writes `cfg["temperature"]` into the fine-tuned checkpoint, and
`laya.Agent` applies `temperature_by_options` per question bucket — the pinned
zero-shot checkpoint already carries `"noul:2": 1.983399510383606`. Left alone,
**L0 and L1 would be temperature-scaled twice**: once by Laya's own fit, once by
the experiment's. That is exactly the confound §3 was written to remove, and it
would apply to the Laya arms and not to T.

**Recommendation, for a ruling before step 3.** At measurement, neutralise the
checkpoint's own scaling — `temperature` and `temperature_by_options` set to
identity — and apply only the §3 fit, identically for L0, L1 and T. This keeps
§3's sentence exactly as written and changes no threshold. The alternative,
leaving Laya's fit in and stacking the §3 fit on top, breaks §3's "identical for
every arm" and should not be chosen silently. Whichever is ruled, `RESULT.md`
states it and reports C1 both raw and scaled as §6 C1 requires.

### D3 — a smaller one, flagged so it is not discovered late

CRITERIA §6 C1 specifies ECE at **10 bins**. `laya.common.ece_score` defaults to
15. The experiment's own scorer must pass `bins=10`; no deviation is needed, only
care.

---

## 8. What this step did not answer

Whether L1 is any *good*. Feasibility is not calibration, humility, selective
accuracy or latency. C1–C4 are measured at step 4, on splits not yet
constructed, and the fourth kill criterion not firing says only that the budget
allows the question to be asked.
