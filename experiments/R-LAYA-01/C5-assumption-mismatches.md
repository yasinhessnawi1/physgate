# C5 — assumption mismatches

CRITERIA §6 C5: *"A written list, one entry per place Laya's model had to be
worked around: what ARCH-131 needs, what Laya offers, what was done, and whether
resolving it would require changing ARCH-131 or ARCH-010. Written during
implementation, not after seeing the numbers."*

**This list was opened at step 1, before any arm was trained and before any
criterion produced a number.** Each entry is dated. Entries are appended as they
are found; nothing already written here is rewritten once a metric exists, and
`RESULT.md` carries the list as it stands at measurement.

The first four entries below were written on 2026-09-21 during the L1
feasibility check, which produced no metric that any criterion is scored on.

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
per optimiser update. Gradient accumulation is explicitly within what the
kickoff's ruling allows adaptation to cover. **Epochs stay at the recipe's 4 and
no schedule is shortened** — the same ruling forbids trading training for
clock, and the feasibility answer is reported against the full recipe.

The consequence for reading the numbers: the optimiser-update count per seed
halves relative to a two-GPU run of the same data, while the number of
forward/backward passes is identical. Throughput in this result is therefore
reported per micro-batch and per sequence as well as per update, so it can be
compared to a run with a different accumulation factor.

**Would resolving it require changing ARCH-131 or ARCH-010?** No.
