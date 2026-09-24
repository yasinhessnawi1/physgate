# C5 — assumption mismatches

CRITERIA §6 C5: *"A written list, one entry per place Laya's model had to be
worked around: what ARCH-131 needs, what Laya offers, what was done, and whether
resolving it would require changing ARCH-131 or ARCH-010. Written during
implementation, not after seeing the numbers."*

**This list was opened at step 1, before any arm was trained and before any
criterion produced a number.** Each entry is dated. Entries are appended as they
are found; nothing already written here is rewritten once a metric exists, and
`RESULT.md` carries the list as it stands at measurement.

The first six entries, M1 to M6, were written on 2026-09-21 during the L1
feasibility check, which produced no metric that any criterion is scored on. M7 to
M11, and the addendum to M4, were written the same day during step 2, which fits
arms on Train and scores nothing. M12 was written the same day during step 3,
which trains arm L1 on Train and scores nothing.

**Wording corrected 2026-09-24 in four entries — M5, M6, M11 and M12 — and in
nothing else.** Each had named a *ruling* where the reason was what mattered;
each now states what was resolved and why, and the `D` labels they cite point at
the step report where the resolution is written out. **No entry was added or
removed and no content, date, verdict, table or number changed.** The sentence
above about nothing being rewritten is about content, and none was.

---

## M1 — The checkpoint's declared AMP dtype is bf16; the card has no bf16

**Dated** 2026-09-21, during step 1.

**What ARCH-131 needs.** Nothing about numeric precision. ARCH-131 needs a
backend whose weights are frozen at a recorded version and whose confidence is
meaningful — and confidence is exactly what a loss computed in a narrow dynamic
range can corrupt without any error being raised.

**What Laya offers.** `rl_agent_config.json` in the pinned checkpoint declares
`"amp_dtype": "bf16"`, and `laya.common.amp_dtype` maps that string to
`torch.bfloat16` for **inference** in `laya.Agent`. The available card is a
Tesla V100-SXM3-32GB, compute capability 7.0, which has no bfloat16 tensor
cores. Measured on the machine, not assumed:
`torch.cuda.is_bf16_supported(including_emulation=False)` → `False`, while the
default `torch.cuda.is_bf16_supported()` → `True`, i.e. torch will report bf16
as available because it can emulate it. A run that trusted the default would
silently take an emulated path.

**What was done.** fp16 with a gradient scaler, which CRITERIA §3 already
declares as the adaptation for arm L1. Two facts found during step 1 that make
this less of a departure than it first looked, and both are recorded because
they change how the result should be read:

1. **The repository's own fine-tuning recipe is already fp16.** The pinned
   notebook `notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb`
   (commit `42626c34`) trains under
   `torch.autocast("cuda", dtype=torch.float16)` with
   `torch.amp.GradScaler("cuda", enabled=True)`, because it targets 2×T4, which
   is compute capability 7.5 and also has no bf16. The `amp_dtype: bf16` field
   is the checkpoint's inference default, not the training recipe. So for L1,
   fp16 is the upstream recipe rather than a substitution for it.
2. The loss is a strictly proper scoring rule — log score plus spherical score —
   with a log floor at `-9.21` and probabilities clamped at `1e-12`. The
   reward is computed under `no_grad` in fp32 (`logits.float()` before any of
   it), so the scoring rule itself never runs in fp16. What runs in fp16 is the
   encoder forward and backward.

**Would resolving it require changing ARCH-131 or ARCH-010?** No. It requires a
card of compute capability ≥ 8.0. Neither the interface nor the graph schema has
an opinion about numeric precision. Recorded here as a hardware constraint on
the evidence, not a design mismatch.

**Open risk carried into the result.** fp16 overflow during training would show
up as a loss scaler that keeps halving and optimiser steps that are skipped. The
step-1 run logs finiteness at every micro-batch and every scaler action, and the
result reports the rate rather than the final state.

---

## M2 — Flash-attention-2 is unavailable at compute capability 7.0

**Dated** 2026-09-21, during step 1.

**What ARCH-131 needs.** A per-subtask latency the interface can live with
(C4 gates p50 ≤ 500 ms on the laptop), and a backend whose behaviour is
reproducible from a recorded version. The attention kernel is part of that
recorded version, because a different kernel is a different function.

**What Laya offers.** The encoder is `ModernBertForMaskedLM`, 28 layers
alternating `full_attention` and `sliding_attention` with
`global_attn_every_n_layers: 3` and `local_attention: 128`. ModernBERT's
reference implementation is written for flash-attention-2, which requires
compute capability ≥ 8.0 and will not run on a V100. The checkpoint's
`encoder/config.json` sets `deterministic_flash_attn: false`.

**What was done.** Nothing had to be worked around, and that is the finding:
`laya.common.build_model` **hard-codes** `attn_implementation="sdpa"` on both of
its construction paths, so Laya never asks for flash-attention-2 in the first
place. The sdpa path is what runs, on this card and on any card. The
implementation actually in force is recorded from
`model.encoder.config._attn_implementation` in the run's resolved config rather
than assumed, together with the layer types and the local-attention window, so a
reader can check that the sliding-window layers are on the same path.

**Would resolving it require changing ARCH-131 or ARCH-010?** No. It is a kernel
availability question. It does mean the latency numbers under C4 are sdpa
numbers; a flash-attention-2 run on a newer card would be faster and would not be
this measurement.

---

## M3 — A recent stack, a recent accelerator build, and a Volta card do not all hold at once

**Dated** 2026-09-21, during step 1.

**What ARCH-131 needs.** A backend pinned at a recorded version that can
actually be instantiated, and the pins recorded so a later run can reproduce it.

**What Laya offers.** `laya==0.3.4` declares only floors —
`torch>=2.0.0`, `transformers>=4.45.0`, `safetensors>=0.4.0`,
`huggingface_hub>=0.20.0`, `numpy>=1.20.0` — no ceilings. The encoder needs a
recent `transformers` (ModernBERT; the checkpoint's `encoder/config.json`
records `transformers_version: 5.17.0`). A recent `transformers` wants a recent
torch, and recent torch CUDA builds have dropped Volta.

**What was done.** Measured against the installed wheels, not documentation
(standards §9), and pinned the newest build that still carries `sm_70`:

| wheel | `torch.cuda.get_arch_list()` | sm_70 |
|---|---|---|
| `torch==2.14.0+cu130` (current default on PyPI) | `sm_75 sm_80 sm_86 sm_90 sm_100 sm_120` | **no** |
| `torch==2.13.0+cu129` | `sm_75 sm_80 sm_86 sm_90 sm_100 sm_120` | **no** |
| `torch==2.9.1+cu126` | `sm_50 sm_60 **sm_70** sm_75 sm_80 sm_86 sm_90` | **yes** |

`cu126` is the newest CUDA line PyTorch still builds, and it stops at 2.9.1, so
`torch==2.9.1+cu126` is the newest wheel that runs on this card at all. It is
pinned for the whole experiment and recorded with every number.

**Would resolving it require changing ARCH-131 or ARCH-010?** No. It is a
statement about the hardware generation available to this thesis, not about the
interface or the graph. It is recorded because it has an expiry date: the next
torch release that drops `cu126` closes this path entirely, and any later
attempt to reproduce arm L1 on a V100 will have to build torch from source.

---

## M4 — `laya.Agent` selects the inference dtype from the same bf16 field

**Dated** 2026-09-21, during step 1. **Affects arms L0 and L1 at measurement,
and C4's latency numbers, not the feasibility answer.**

**What ARCH-131 needs.** `decide()` returns `(answer, confidence, backend_id,
latency_ms)`, and confidence is the quantity C1 and C2 are scored on. The
numeric path that produces it is part of what must be recorded.

**What Laya offers.** `laya.Agent` reads `amp_dtype` from the checkpoint config
and runs `system_one` under `torch.autocast(device_type, dtype=self.dtype)`, so
on the pinned checkpoint the default inference path is bf16 — on a card with no
bf16 hardware, and with torch reporting bf16 as supported by emulation.

**What was done at step 1.** Nothing yet; recorded so that steps 2 and 4 make the
choice explicitly rather than inheriting it. The inference dtype for every Laya
measurement will be stated in the resolved config, and the laptop path (C4's
gated measurement) is CPU or MPS, where `use_amp` is off entirely.

**Would resolving it require changing ARCH-131 or ARCH-010?** No.

---

## M5 — The recipe is written for two GPUs; there is one

**Dated** 2026-09-21, during step 1.

**What ARCH-131 needs.** Nothing about the training topology. Recorded because
it changes a number a reader will want to check against upstream.

**What Laya offers.** The pinned notebook's `train_ddp.py` runs
`torchrun --nproc_per_node=2` with `MICRO_BATCH = 8`, `GRAD_ACCUM = 4`, and
states its effective batch as 64 sequences (8 × 2 GPUs × 4). The server has one
V100.

**What was done.** World size 1, DDP dropped, `MICRO_BATCH = 8` unchanged and
`GRAD_ACCUM = 8`, which preserves the recipe's effective batch of 64 sequences
per optimiser update. Gradient accumulation is inside what CRITERIA §3 admits:
it pins arm L1 to the repository's own notebook *"adapted to the available
accelerator"* and nothing more, and holding the recipe's effective batch on one
card is that adaptation and no other. **Epochs stay at the recipe's 4 and no
schedule is shortened** — an adaptation that bought clock by training less would
fall outside what was pre-registered, and the feasibility answer is reported
against the full recipe.

The consequence for reading the numbers: the optimiser-update count per seed
halves relative to a two-GPU run of the same data, while the number of
forward/backward passes is identical. Throughput in this result is therefore
reported per micro-batch and per sequence as well as per update, so it can be
compared to a run with a different accumulation factor.

**Would resolving it require changing ARCH-131 or ARCH-010?** No.

---

## M6 — Laya fits its own calibration temperature, and CRITERIA §3 admits only one fit

**Dated** 2026-09-21, during step 1. **Affects L0 and L1 at measurement, not the
feasibility answer. Raised as prospective deviation D2 in
`step1_feasibility/FEASIBILITY.md`, and resolved there before step 2 began.**

**What ARCH-131 needs.** A confidence on one scale, comparable across backends,
because the 0.8 routing threshold is *"a property of the interface, not of a
backend, so every backend is judged on the same routing rule."* A backend that
quietly rescales its own confidence is being judged on a different rule.

**What Laya offers.** Calibration is what Laya is optimised for, and it carries
its own. The pinned recipe ends by fitting per-question-type temperatures with
LBFGS on 400 held-out-from-shuffle training items and writing them into
`rl_agent_config.json`; `laya.Agent` then applies `temperature_by_options` per
bucket at inference. The pinned zero-shot checkpoint already carries
`"noul:2": 1.983399510383606` — the exact bucket this experiment uses.

**What was done at step 1.** Nothing, and nothing may be: CRITERIA §3 is frozen
and says the temperature is fitted on a 500-sample slice of Train, identical for
every arm. Left alone, L0 and L1 would be scaled twice — Laya's fit, then the
experiment's — while arm T is scaled once. Recorded now so that step 3 makes the
choice in the open.

**Would resolving it require changing ARCH-131 or ARCH-010?** No, but it is the
first entry on this list that touches what ARCH-131 actually cares about. It says
something real about admitting a *calibrated* backend behind a fixed threshold:
the register's entry condition should state whose calibration is in force, or two
backends can pass the same 0.8 rule while meaning different things by it. Worth
carrying into ARCH-132's row text if `laya` enters — as a note on the row, not a
change to the interface.

---

## M4 — addendum, 2026-09-21, during step 2

**The entry above overstated the risk, and the correction belongs next to it
rather than inside it.** M4 was written from `laya.common.amp_dtype`, which maps
`"bf16"` to `torch.bfloat16` and nothing else. `laya.Agent.__init__` then
overrides it:

```
self.dtype = amp_dtype(self.cfg.get("amp_dtype", "fp16"))
if self.device.type == "cuda" and torch.cuda.get_device_capability(self.device)[0] < 8:
    self.dtype = torch.float16
elif self.device.type in ("cpu", "mps"):
    self.dtype = torch.float32
```

So Laya already refuses bf16 on a compute-capability-7.0 card and already uses
fp32 on cpu and mps. **Nothing had to be done about bf16 at inference.** The
entry stands as written, dated, with this correction under it; what it got wrong
was reading one function instead of its caller. A different decision was needed
about inference precision, but for a different reason — see M10.

---

## M7 — ARCH-010 and ARCH-012 do not name eight of the twelve state fields

**Dated** 2026-09-21, during step 2. Raised as prospective deviation D6.

**What ARCH-131 needs.** `state` is *"the structured subtask record at the end of
an attempt — the ledger line, the gate result, the reviewer verdict, the
changed-node summary."* R3 requires the JSON Laya sees to carry *"exactly the raw
generator fields, under the ARCH-010/ARCH-012 field names."*

**What is actually available.** ARCH-010 defines a graph **node** schema; ARCH-012
describes a ledger **line** in prose. Neither is a subtask-state schema, and
between them they name one of the generator's twelve fields:

| generator field | ARCH counterpart |
|---|---|
| `domain` | **ARCH-010 `domain`** — the only exact field-name match |
| `attempt` | ARCH-012 "attempt count"; ARCH-030's three-attempt budget |
| `reviewer_verdict` | ARCH-012 "review result"; ARCH-131 "the reviewer verdict" |
| `gate_unit_pass`, `gate_magnitude_pass`, `gate_power_pass`, `gate_propagation_pass` | ARCH-012 "gate result", ARCH-031, ARCH-080 — as one result, not four named gates |
| `cross_domain_quantity_changed` | ARCH-010 quantities marked `cross`, ARCH-051 sizing; ARCH-131 "changed-node summary". No field name |
| `interface_node_touched` | ARCH-010 `kind: interface`, ARCH-011; ARCH-131 "changed-node summary". No field name |
| `reviewer_confidence` | **none** |
| `prior_failures_module` | **none** |
| `spec_coverage` | **none** (ARCH-022 is about what a spec contains, not a per-attempt state field) |

**What was done.** The fixture keeps the generator's own field names, and the
table above is committed in `rlaya/fixture.py` and reproduced in `RESULT.md`.
The reading is not a convenience: **R3's own two examples, `"attempt": 2` and
`"reviewer_verdict": "accept"`, are verbatim two of the generator's raw field
names**, so "the ARCH-010/ARCH-012 field names" means these. The contrast R3 is
drawing is with `generator.BIT_NAMES` — `"attempt>=3"`, `"verdict=accept"`,
`"reviewer_conf>=high"` — which are the derived features R3 forbids. Renaming
would also have invented schema ARCH-010 does not define, and would have broken
R2's "one source" between the bit-consuming arms and the JSON-consuming one.

One value-level choice inside this: `domain` keeps the generator's vocabulary
(`mech`, `elec`, `ctrl`, `fw`) rather than ARCH-010's
(`mechanical | electrical | control | firmware`). Translating a *value* is a
substitution, not a rendering, and R3 says "exactly the raw generator fields".

**Would resolving it require changing ARCH-131 or ARCH-010?** **Yes, and this is
the first entry on this list where the answer is yes.** ARCH-131 promises
`decide(question, state)` over "the structured subtask record", and no ARCH
decision says what that record's fields are. Three of the twelve fields the
escalation question turns on have no home in the specification at all. A backend
register that admits bindings on measured evidence needs the thing being measured
to be defined somewhere; today it is defined only in R-TM-01's generator. The
proposal — for the orchestrator, not for this experiment — is a decision that
writes the subtask-state schema down, with ARCH-131 depending on it.

---

## M8 — Laya has two confidence functions and picks by question type

**Dated** 2026-09-21, during step 2. **Checked in the library; no work-around was
needed, and it is recorded because it very nearly was.**

**What ARCH-131 needs.** *"A confidence below 0.8 routes to ARCH-130 whatever the
answer. The threshold is a property of the interface, not of a backend, so every
backend is judged on the same routing rule."* Every arm must therefore be on one
confidence scale, and C1 needs that scale to be a probability of being right,
because ECE compares it to an observed accuracy.

**What Laya offers.** Both, depending on the question kind.
`laya/agent.py` computes `conf_score = confidence_from_probs(p, k)`, normalised
Shannon entropy `1 - H(p)/log k`, and reports it for `choice` and `score`. For
`noul` it reports something else, at line 335:
`"confidence": round(max(float(p[1]), 1.0 - float(p[1])), 4)`.

**What was done.** Nothing, because `noul` is the only kind this experiment
exercises (§8: *"Only `yes_no` is tested"*) and `max(p, 1-p)` is exactly the scale
arms R, G and T are on. Had the entropy figure been in force, the 0.8 threshold
would have cut at `p = 0.8` for three arms and at `p ≈ 0.969` for the two Laya
arms, and C2's escalation rates would not have been comparable across arms.
`metrics.laya_entropy_confidence` computes what that would have been and it is
reported as **non-gating context**.

**Would resolving it require changing ARCH-131 or ARCH-010?** Not for this
experiment. But ARCH-131 asserts a threshold without defining the quantity it
thresholds, and this backend happens to agree with the experiment's reading only
for one of its three question kinds. If `choice` and `score` are ever exercised —
§8 puts them out of scope here — ARCH-131 will need to say what confidence means
before a threshold on it means anything.

---

## M9 — arm R can express two of ARCH-130's three escalation sources

**Dated** 2026-09-21, during step 2.

**What ARCH-131 needs.** The default binding is *"exactly the deterministic
conditions ARCH-030 and ARCH-040 already specify, emitted at confidence 1.0"*,
and ARCH-130's queue has *"three sources: gate escalation, exhausted repair
budget, unresolved arbitration."*

**What the workload offers.** Two of the three:

| ARCH-130 source | condition | in the generator's state? |
|---|---|---|
| exhausted repair budget | ARCH-030, attempt 3 | yes — `attempt == 3` |
| gate escalation | ARCH-031, ARCH-080 | yes — any of the four gates fails |
| **unresolved arbitration** | **ARCH-040** | **no field exists** |

ARCH-040's condition is a conflict between sizing and a domain on a shared
quantity that survives both precedence rules. The generator has
`cross_domain_quantity_changed`, which records that a shared quantity moved — not
that two roles disagreed about it. There is no way to key on the third source.

**What was done.** `metrics.rule_arm` is kept **byte-identical** to
`run05d/experiment.py:rule_arm`, so arm R is the same rule R-TM-01 measured, and
the gap is recorded rather than patched. R-TM-01's own docstring flagged an
assumption because *"the source spec does not print the rule"*; it is printed
now, and the assumption turns out to have been right about two conditions and
silent about a third.

The practical consequence is small and should be stated so it is not overstated:
arm R is a baseline, §7 rests the entry decision on L1 alone, and a rule that
escalated on a third condition would escalate *more*, so R's reported
selective accuracy is if anything flattered by the omission.

**Would resolving it require changing ARCH-131 or ARCH-010?** No — it needs a
generator that can represent an arbitration conflict. Worth carrying into any
future workload: a state schema that cannot express one of the three things the
approval queue exists for is not a complete test of the interface.

---

## M10 — under fp16, the answer depends on which batch the state was scored in

**Dated** 2026-09-21, during step 2. **Found by a check that was expected to
pass.**

**What ARCH-131 needs.** A backend is admitted on measured evidence with *"its
weights frozen at a recorded version"*, and every call records *"answer,
confidence, backend id and latency in the ledger, so a backend's behaviour is
auditable after the fact."* An audit means the same state gives the same answer.

**What Laya offers.** `laya.Agent` evaluates one state per call and picks fp16 on
this card. The experiment scores 8 000 states per seed and so batches them. The
agreement check between the two paths **failed**: 1.6e-3 in probability against
the 1e-4 that `system_one`'s own rounding allows.

**What it turned out to be.** Not the code path. Measured on 64 Train states:

| | batch 32 vs batch 1, max |p| difference | mean |
|---|---|---|
| fp16 | **2.65e-3** | 4.63e-4 |
| fp32 | 3.46e-6 | 6.83e-7 |

and fp32 against fp16 at batch 1: max 1.81e-3, mean 4.59e-4, **0 of 64 decisions
crossed 0.5**. A batch pads to its own longest sequence and the fp16 reductions
differ, so the same state scores differently depending on its neighbours.

**What was done.** fp32 pinned as the experiment's inference precision on every
device, and the agreement check re-run at batch size 1 on both sides so that it
tests the code path rather than the arithmetic of batching. It then agrees
**exactly** to `system_one`'s four decimals. Three reasons for fp32 rather than
"use a fixed batch size":

1. C4 gates on the laptop, which is cpu or mps and therefore fp32 already
   (`agent.py` sets it). Scoring the server in fp16 would mean the two machines
   disagree about what the backend answered for the same state.
2. A criterion must not depend on a batch size nobody chose deliberately.
3. There is no tf32 on compute capability 7.0, so fp32 here is true fp32.

**Would resolving it require changing ARCH-131 or ARCH-010?** No, but it sharpens
ARCH-131's audit clause. "Weights frozen at a recorded version" is not sufficient
for reproducibility: the precision and the batching are part of the function too,
and a ledger that records the answer without them cannot be replayed. Worth a
sentence in ARCH-132's row text for any backend that runs on an accelerator.

---

## M11 — Laya's own temperature is fitted on 400 items; §3's is fitted on 500, and for L0 it does not settle

**Dated** 2026-09-21, during step 2. **An observation on Train, not a result;
L0 is not scored until step 4.**

**What ARCH-131 needs.** A confidence that means the same thing from call to
call, since a fixed 0.8 threshold is applied to it.

**What Laya offers, and what was done.** Per the resolution of D2 the
checkpoint's own
calibration was set to identity — `temperature` was
`[1.0148, 1.0374, 1.0575]` and `temperature_by_options` carried
`"noul:2": 1.983399510383606` among five others — and the §3 fit applied instead,
identically for L0, L1 and T.

**What the fit did.** Arm T's temperature is stable across the five seeds:
0.1997, 0.1720, 0.1972, 0.1764, 0.1664. Arm L0's is not: **8.5625, 1.1388,
6.7908, 1.6381, 1.9541** — a factor of 7.5 between seeds, from 500-sample fits
on draws that differ only in seed.

The reason is visible in the scores and costs nothing to state: L0's logit
difference on the calibration slice has mean ≈ 0.09 and standard deviation
≈ 0.32 on every seed, so there is very little signal for the fit to lock onto and
the likelihood is nearly flat in the temperature. A large fitted temperature
flattens an already-flat distribution towards `p = 0.5`.

**What must not be read into it.** This is a property of the fit on Train, and
§3's protocol is frozen and was followed exactly. It is recorded now, before any
test split is read, precisely so that it cannot later look like an explanation
constructed after seeing L0 fail — which §3 says outright is expected.

**Would resolving it require changing ARCH-131 or ARCH-010?** No. It is a note
about a 500-sample calibration set, and a note that a temperature fitted on a
near-uninformative score is not a meaningful quantity.

---

## M12 — the recipe fits a temperature the shipped checkpoint cannot reach

**Dated** 2026-09-21, during step 3. **Verified by loading the fine-tuned
checkpoint and asking the Agent which constant it would apply, not by reading
the code.**

**What ARCH-131 needs.** A confidence on a known scale, since a fixed 0.8
threshold is applied to it, and a backend *"frozen at a recorded version"* whose
behaviour is auditable. The calibration constant is part of what the version has
to record.

**What Laya offers.** Two places to put a temperature, and a lookup that prefers
the one the recipe does not write. `laya/agent.py`:

```
t_scale = self.temperature_by_options.get(temp_bucket(qt, k), self.temperature[qt])
```

`temperature_by_options` wins; `temperature` is the fallback. The pinned
fine-tuning notebook ends by fitting fresh temperatures with LBFGS and writing
**`cfg["temperature"] = fitted_temps`** — and leaves `cfg["temperature_by_options"]`
exactly as it came off the base checkpoint.

**What that means, measured on `L1_seed0`:**

| | |
|---|---|
| `temperature` (what the recipe just fitted) | `[1.2, 1.2, **5.29985237121582**]` |
| `temperature_by_options["noul:2"]` (inherited from the zero-shot checkpoint) | **1.983399510383606** |
| bucket for a `noul` question with two options | `noul:2` |
| **temperature the Agent actually applies** | **1.983399510383606** |
| **is the recipe's fit reachable?** | **No** |

So the recipe's own post-training calibration is **dead on arrival** for this
question kind: it fits a constant, writes it to the config, and ships a
checkpoint in which a stale constant from a different training run on a different
dataset takes precedence. This is the upstream notebook's behaviour, reproduced
faithfully; it is not an artefact of the single-GPU adaptation.

**What was done.** Nothing to the recipe — it is reproduced as written, and the
fitted value is recorded per seed. The resolution of D2 then neutralises **both**
fields
before anything is scored, so L1 is temperature-scaled exactly once, by the §3
fit, like every other arm.

Two consequences to carry into step 4:

1. The non-gating "shipped temperature" pass must use **1.9834**, the constant
   that would actually apply, not the 5.30 the config advertises. Reporting 5.30
   as "Laya's own calibration" would report a number no user of the checkpoint
   would ever get.
2. The resolution of D2 turns out to have been right for a reason nobody had
   named:
   without it, L1 would have been scaled by a **zero-shot** constant, fitted by a
   different run on a different corpus, while arm T was scaled by a fit on this
   run's Train.

**Would resolving it require changing ARCH-131 or ARCH-010?** No. It is a defect
in the checkpoint-writing path of the thing under test. It is recorded here
because it is exactly the class of thing ARCH-132's "frozen at a recorded
version" is supposed to make visible, and it was invisible until the constant was
asked for by name.
