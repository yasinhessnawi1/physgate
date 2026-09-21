"""R-LAYA-01 step 1 - is arm L1 trainable on the available accelerator at all?

Answers CRITERIA sec.7's fourth kill criterion, and nothing else. It does not
train a model, does not produce a metric that any criterion is scored on, and
does not read a test split.

What it does:

  1. Draws **Train only** from R-TM-01's ``generator_b.py`` (vendored unmodified,
     checksum recorded). Test-ID, OOD-A and OOD-B are never constructed.
  2. Serialises the raw fields with the **provisional** serialisation of
     ``serialisation_provisional.py`` (not the R3 fixture - see that module) and
     tokenises them with Laya's own ``build_sequence``, so the timed sequences
     have realistic lengths. Reports the token-length distribution.
  3. Runs the repository's own fine-tuning step - the GRPO-against-proper-scoring
     -rules loop from ``notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb``
     at the pinned commit - on a deliberately tiny slice, single GPU, and
     measures seconds per micro-batch and per optimiser update, and peak memory.
  4. Checks finite gradients **at every micro-batch**, not only at the end, and
     records the fp16 loss-scaler trajectory and every skipped optimiser step.

Usage:  python feasibility_l1.py <model_dir> <out.json> [--micro-batches N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import generator_b as G  # noqa: E402  (vendored, unmodified)
from serialisation_provisional import serialise  # noqa: E402

from laya.common import QTYPES, build_model, proper_reward, build_sequence  # noqa: E402
from laya.agent import _fix_tokenizer_config  # noqa: E402
from safetensors.torch import load_file  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

# ---------------------------------------------------------------------------
# The question, exactly as CRITERIA sec.2 writes it.
QUESTION = {
    "escalate": {
        "type": "noul",
        "instructions": "Should this subtask be escalated to a human reviewer?",
    }
}

# The recipe, from the pinned notebook's train_ddp.py. The only departures are
# the two the card forces and CRITERIA sec.3 already declares - see C5.
EPOCHS = 4          # notebook: EPOCHS = 4
MICRO_BATCH = 8     # notebook: MICRO_BATCH = 8, sequences per forward pass per GPU
GRAD_ACCUM = 8      # notebook: 4 at world_size 2. 8 at world_size 1 keeps the
                    # recipe's effective batch of 64 sequences per update.
GROUP_SIZE = 4      # notebook: GROUP_SIZE = 4
LR_ENCODER = 2.5e-5
LR_HEAD = 1.0e-4
SIGMA_START, SIGMA_END = 0.4, 0.1
W_SPH, W_RPS, CE_WEIGHT, CLIP = 0.75, 1.0, 1.0, 1.0
WEIGHT_DECAY = 0.01

TRAIN_N = 8000      # generator_b.build_all: d["train"] = make_split(8000, ..., attempts=(1, 2))
SEEDS = 5           # CRITERIA sec.3: five seeds wherever training is involved


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def train_split_only(seed):
    """Exactly ``build_all(seed)["train"]``, without constructing any test split.

    ``build_all`` draws train first from a fresh ``default_rng(seed)``, so the
    same call on a fresh generator reproduces it byte for byte. Test-ID, OOD-A
    and OOD-B are never materialised in this process (rule R4, standards I-5).
    """
    rng = np.random.default_rng(seed)
    return G.make_split(TRAIN_N, rng, attempts=(1, 2))


def collate(items, pad_id):
    """The notebook's collate_train_batch, verbatim in behaviour."""
    n, L = len(items), max(len(it["ids"]) for it in items)
    kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, L), pad_id, dtype=torch.long)
    att = torch.zeros((n, L), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax), dtype=torch.float32)
    for i, it in enumerate(items):
        ids[i, : len(it["ids"])] = torch.tensor(it["ids"])
        att[i, : len(it["ids"])] = 1
        k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"])
        mmask[i, :k] = True
        target[i, : len(it["target"])] = torch.tensor(it["target"], dtype=torch.float32)
    return {
        "input_ids": ids, "attention_mask": att, "marker_pos": mpos,
        "marker_mask": mmask, "target": target,
        "qtype": torch.tensor([it["qtype"] for it in items]),
    }


def compute_loss(model, batch, dev, sigma, autocast_dtype):
    """The pinned notebook's per-micro-batch loss, verbatim in behaviour.

    ``autocast_dtype=None`` runs the whole thing in fp32, which is the reference
    the fp16 path is checked against.
    """
    with torch.autocast("cuda", dtype=autocast_dtype or torch.float16,
                        enabled=autocast_dtype is not None):
        logits, act = model(
            batch["input_ids"].to(dev), batch["attention_mask"].to(dev),
            batch["marker_pos"].to(dev), batch["marker_mask"].to(dev),
            batch["qtype"].to(dev))
    logits = logits.float()
    mask = batch["marker_mask"].to(dev)
    k = mask.sum(-1, keepdim=True).float()
    target = batch["target"].to(dev)

    eps = torch.randn((GROUP_SIZE,) + logits.shape, device=dev) * sigma * mask
    eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
    z = logits.detach().unsqueeze(0) + eps
    qd = torch.softmax(z.masked_fill(~mask, -1e4), -1)
    with torch.no_grad():
        r = proper_reward(qd, target.unsqueeze(0), batch["qtype"].to(dev),
                          mask, w_sph=W_SPH, w_rps=W_RPS)
        adv = r - r.mean(0, keepdim=True)
        adv = adv / (adv.std() + 1e-6)
    logp = -(((z - logits.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma ** 2)
    loss_rl = -(adv * logp).mean()
    loss_ce = -(target * torch.log_softmax(logits.masked_fill(~mask, -1e4), -1)).sum(-1).mean()
    loss = (loss_rl + CE_WEIGHT * loss_ce) / GRAD_ACCUM + 0.0 * act.sum()
    return loss, float(r.mean().item())


def grad_report(params):
    """Finiteness and magnitude of the gradients currently on ``params``."""
    n_bad, n_with = 0, 0
    mx = 0.0
    with torch.no_grad():
        for p in params:
            if p.grad is None:
                continue
            n_with += 1
            g = p.grad
            if not torch.isfinite(g).all():
                n_bad += 1
            else:
                mx = max(mx, float(g.abs().max().item()))
    return {"tensors_with_grad": n_with, "nonfinite_tensors": n_bad,
            "max_abs_grad_over_finite_tensors": mx}


def scale_probe(model, batch, dev, params, sigma):
    """Is the fp16 path non-finite because of the loss scaler, or by itself?

    Runs the same backward at fp32, at fp16 unscaled, and at fp16 over a ladder
    of static loss scales, and reports the largest scale whose gradients are
    finite. This distinguishes "the scaler starts too high and has to back off",
    which is ordinary and self-correcting, from "fp16 cannot represent these
    gradients at any useful scale", which is a kill.
    """
    out = {}
    model.zero_grad(set_to_none=True)
    loss, _ = compute_loss(model, batch, dev, sigma, autocast_dtype=None)
    loss.backward()
    out["fp32_unscaled"] = grad_report(params)
    out["fp32_unscaled"]["loss"] = float(loss.item()) * GRAD_ACCUM

    ladder = []
    for e in range(16, -1, -1):
        scale = float(2 ** e)
        model.zero_grad(set_to_none=True)
        loss, _ = compute_loss(model, batch, dev, sigma, autocast_dtype=torch.float16)
        (loss * scale).backward()
        g = grad_report(params)
        g["scale"] = scale
        g["scale_exponent"] = e
        g["loss"] = float(loss.item()) * GRAD_ACCUM
        ladder.append(g)
        if g["nonfinite_tensors"] == 0 and "largest_finite_scale" not in out:
            out["largest_finite_scale"] = scale
            out["largest_finite_scale_exponent"] = e
    out["fp16_scale_ladder"] = ladder
    model.zero_grad(set_to_none=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out")
    ap.add_argument("--micro-batches", type=int, default=64)
    ap.add_argument("--warmup", type=int, default=8)
    ap.add_argument("--ref-micro-batches", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rec = {"experiment": "R-LAYA-01", "step": "1-feasibility", "seed": args.seed}

    # ---------------------------------------------------------------- env ----
    dev = torch.device("cuda")
    props = torch.cuda.get_device_properties(0)
    import transformers, laya, safetensors, huggingface_hub
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            cgroup_cpu_max = f.read().strip()
    except OSError:
        cgroup_cpu_max = None
    rec["env"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "torch_cuda_arch_list": torch.cuda.get_arch_list(),
        "cudnn": torch.backends.cudnn.version(),
        "driver": subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True).stdout.strip(),
        "transformers": transformers.__version__,
        "laya": laya.__version__,
        "numpy": np.__version__,
        "safetensors": safetensors.__version__,
        "huggingface_hub": huggingface_hub.__version__,
        "gpu": props.name,
        "compute_capability": [props.major, props.minor],
        "gpu_memory_total_bytes": props.total_memory,
        # os.cpu_count() reports the host's cores; this container is cgroup-limited
        # and `nproc` says 2. Both are recorded so neither can be mistaken for the other.
        "cpu_count_host": os.cpu_count(),
        "cpu_affinity": len(os.sched_getaffinity(0)),
        "cpu_nproc": subprocess.run(["nproc"], capture_output=True, text=True).stdout.strip(),
        "cgroup_cpu_max": cgroup_cpu_max,
        "torch_num_threads": torch.get_num_threads(),
        "bf16_including_emulation": torch.cuda.is_bf16_supported(),
        "bf16_hardware": torch.cuda.is_bf16_supported(including_emulation=False),
    }
    here = os.path.dirname(os.path.abspath(__file__))
    rec["checksums"] = {
        "generator_b.py": sha256(os.path.join(here, "vendor", "generator_b.py")),
        "generator.py": sha256(os.path.join(here, "vendor", "generator.py")),
        "serialisation_provisional.py": sha256(os.path.join(here, "serialisation_provisional.py")),
        "feasibility_l1.py": sha256(os.path.abspath(__file__)),
        "model.safetensors": sha256(os.path.join(args.model_dir, "model.safetensors")),
    }

    _fix_tokenizer_config(args.model_dir)
    tok = AutoTokenizer.from_pretrained(os.path.join(args.model_dir, "tokenizer"))
    with open(os.path.join(args.model_dir, "rl_agent_config.json")) as f:
        cfg = json.load(f)
    rec["checkpoint_config"] = cfg
    cfg["gradient_checkpointing"] = True
    cfg["max_tokens_per_batch"] = 4096
    cfg["max_len"] = 1024
    cfg["head_max_len"] = 256

    # ----------------------------------------------------- data + lengths ----
    X, y, y_clean, raw, terms = train_split_only(args.seed)
    assert len(y) == TRAIN_N
    qdef = QUESTION["escalate"]
    q_internal = {"t": qdef["type"], "ins": qdef["instructions"], "crit": qdef.get("criteria")}

    t0 = time.perf_counter()
    items = []
    for i in range(TRAIN_N):
        seq, markers = build_sequence(tok, serialise(raw, i), q_internal,
                                      cfg["max_len"], cfg["head_max_len"])
        items.append({
            "ids": seq, "markers": markers, "qtype": QTYPES["noul"],
            # noul target order is [false, true]; the label is the escalate bit.
            "target": [1.0 - float(y[i]), float(y[i])],
        })
    tok_secs = time.perf_counter() - t0
    lens = np.array([len(it["ids"]) for it in items])
    rec["tokenisation"] = {
        "n_items": int(TRAIN_N),
        "seconds_total": tok_secs,
        "items_per_second": TRAIN_N / tok_secs,
        "token_len_min": int(lens.min()), "token_len_max": int(lens.max()),
        "token_len_mean": float(lens.mean()), "token_len_p50": float(np.percentile(lens, 50)),
        "token_len_p90": float(np.percentile(lens, 90)), "token_len_p99": float(np.percentile(lens, 99)),
        "max_len_cfg": cfg["max_len"],
        "serialisation": "PROVISIONAL - not the R3 fixture",
        "example_serialised_state": serialise(raw, 0),
        "example_token_len": int(lens[0]),
    }

    # ---------------------------------------------------------- the model ----
    t0 = time.perf_counter()
    model = build_model(cfg, encoder_dir=os.path.join(args.model_dir, "encoder"))
    weights = load_file(os.path.join(args.model_dir, "model.safetensors"))
    model.load_state_dict(weights, strict=True)
    model.encoder.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False})
    model.head_checkpointing = True
    model.to(dev)
    model.train()
    load_secs = time.perf_counter() - t0
    rec["model"] = {
        "load_seconds": load_secs,
        "n_params": sum(p.numel() for p in model.parameters()),
        "n_trainable": sum(p.numel() for p in model.parameters() if p.requires_grad),
        "encoder_class": type(model.encoder).__name__,
        "attn_implementation": getattr(model.encoder.config, "_attn_implementation", None),
        "reference_compile": getattr(model.encoder.config, "reference_compile", "absent"),
        "layer_types_unique": sorted(set(getattr(model.encoder.config, "layer_types", []))),
        "local_attention": getattr(model.encoder.config, "local_attention", None),
        "gradient_checkpointing": bool(getattr(model.encoder, "gradient_checkpointing", False)),
    }

    enc = [p for n, p in model.named_parameters() if "encoder." in n]
    head = [p for n, p in model.named_parameters() if "encoder." not in n]
    opt = torch.optim.AdamW(
        [{"params": enc, "lr": LR_ENCODER}, {"params": head, "lr": LR_HEAD}],
        weight_decay=WEIGHT_DECAY)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    params = [p for p in model.parameters() if p.requires_grad]

    random.seed(42 + args.seed)
    random.shuffle(items)
    sigma = SIGMA_START  # epoch 0 value, the largest of the schedule

    # ---- is fp16 workable at all, before any timing is done with it? --------
    probe_batch = collate(items[:MICRO_BATCH], tok.pad_token_id)
    rec["fp16_scale_probe"] = scale_probe(model, probe_batch, dev, params, sigma)
    opt.zero_grad(set_to_none=True)

    steps, updates = [], []
    n_total = args.warmup + args.micro_batches
    torch.cuda.reset_peak_memory_stats()
    opt.zero_grad(set_to_none=True)
    accum = 0
    wall0 = time.perf_counter()

    for s in range(n_total):
        chunk = items[(s * MICRO_BATCH) % (len(items) - MICRO_BATCH):][:MICRO_BATCH]
        tc0 = time.perf_counter()
        batch = collate(chunk, tok.pad_token_id)
        collate_secs = time.perf_counter() - tc0

        torch.cuda.synchronize()
        t0 = time.perf_counter()
        loss, reward = compute_loss(model, batch, dev, sigma, torch.float16)
        scaler.scale(loss).backward()
        torch.cuda.synchronize()
        step_secs = time.perf_counter() - t0

        # ---- finite check, every micro-batch, timed apart from the step ----
        t0 = time.perf_counter()
        with torch.no_grad():
            bad = sum(1 for p in params
                      if p.grad is not None and not torch.isfinite(p.grad).all())
        check_secs = time.perf_counter() - t0

        rec_step = {
            "i": s, "warmup": s < args.warmup,
            "n_seq": len(chunk), "max_tok": int(batch["input_ids"].shape[1]),
            "n_tokens_padded": int(batch["input_ids"].numel()),
            "n_tokens_real": int(batch["attention_mask"].sum().item()),
            "collate_seconds": collate_secs,
            "step_seconds": step_secs,
            "finite_check_seconds": check_secs,
            "loss": float(loss.item()) * GRAD_ACCUM,
            "reward_mean": reward,
            "loss_finite": bool(np.isfinite(float(loss.item()))),
            "nonfinite_scaled_grad_tensors": bad,
            "scaler_scale": float(scaler.get_scale()),
        }
        accum += 1
        if accum % GRAD_ACCUM == 0:
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            scale_before = scaler.get_scale()
            scaler.unscale_(opt)
            gnorm = torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            upd_secs = time.perf_counter() - t0
            scale_after = scaler.get_scale()
            updates.append({
                "after_micro_batch": s, "warmup": s < args.warmup,
                "update_seconds": upd_secs,
                "grad_norm": float(gnorm),
                "grad_norm_finite": bool(np.isfinite(float(gnorm))),
                "scale_before": float(scale_before), "scale_after": float(scale_after),
                "step_skipped_by_scaler": bool(scale_after < scale_before),
            })
            rec_step["optimiser_update"] = True
        steps.append(rec_step)

    wall = time.perf_counter() - wall0
    rec["peak_memory_bytes_workload"] = int(torch.cuda.max_memory_allocated())
    rec["peak_memory_reserved_bytes"] = int(torch.cuda.max_memory_reserved())
    rec["steps"] = steps
    rec["updates"] = updates

    hot = [s for s in steps if not s["warmup"]]
    hot_u = [u for u in updates if not u["warmup"]]
    step_t = np.array([s["step_seconds"] for s in hot])
    upd_t = np.array([u["update_seconds"] for u in hot_u]) if hot_u else np.array([0.0])
    col_t = np.array([s["collate_seconds"] for s in hot])

    # Per optimiser update, at the recipe's effective batch of 64 sequences.
    sec_per_update = float(step_t.mean() * GRAD_ACCUM + upd_t.mean())
    micro_per_seed = (TRAIN_N // MICRO_BATCH) * EPOCHS
    upd_per_seed = micro_per_seed // GRAD_ACCUM
    seed_secs = micro_per_seed * float(step_t.mean() + col_t.mean()) + upd_per_seed * float(upd_t.mean())

    rec["measured"] = {
        "micro_batches_timed": len(hot),
        "warmup_discarded": args.warmup,
        "wall_seconds_total_including_warmup": wall,
        "step_seconds_mean": float(step_t.mean()),
        "step_seconds_sd": float(step_t.std()),
        "step_seconds_p50": float(np.percentile(step_t, 50)),
        "step_seconds_min": float(step_t.min()), "step_seconds_max": float(step_t.max()),
        "collate_seconds_mean": float(col_t.mean()),
        "finite_check_seconds_mean": float(np.mean([s["finite_check_seconds"] for s in hot])),
        "update_seconds_mean": float(upd_t.mean()),
        "sequences_per_second": MICRO_BATCH / float(step_t.mean()),
        "seconds_per_optimiser_update_eff_batch_64": sec_per_update,
        "nonfinite_scaled_grad_micro_batches": sum(
            1 for s in steps if s["nonfinite_scaled_grad_tensors"] > 0),
        "nonfinite_loss_micro_batches": sum(1 for s in steps if not s["loss_finite"]),
        "nonfinite_unscaled_grad_norm_updates": sum(
            1 for u in updates if not u["grad_norm_finite"]),
        "scaler_skipped_updates": sum(1 for u in updates if u["step_skipped_by_scaler"]),
        "n_updates": len(updates),
        "scaler_scale_first": float(steps[0]["scaler_scale"]),
        "scaler_scale_last": float(steps[-1]["scaler_scale"]),
    }

    # -------- reference-length pass, for the upstream 1.96 h comparison ------
    # The workload's sequences are ~147 tokens. Upstream's per-update sequence
    # count and token length are not recorded anywhere in the checkpoint, so the
    # only honest like-for-like is to also measure at the recipe's own ceiling,
    # max_len = 1024, same batch shape. Reported alongside; it is not the number
    # the extrapolation uses.
    ref_steps = []
    torch.cuda.reset_peak_memory_stats()
    ref_batch = collate(items[:MICRO_BATCH], tok.pad_token_id)
    L = cfg["max_len"]
    pad_id = tok.pad_token_id
    n = ref_batch["input_ids"].shape[0]
    ids = torch.full((n, L), pad_id, dtype=torch.long)
    att = torch.zeros((n, L), dtype=torch.long)
    ids[:, : ref_batch["input_ids"].shape[1]] = ref_batch["input_ids"]
    # fill the rest with real vocabulary so the attention mask is genuinely full
    ids[:, ref_batch["input_ids"].shape[1]:] = ref_batch["input_ids"][
        :, : L - ref_batch["input_ids"].shape[1]].repeat(
        1, (L // ref_batch["input_ids"].shape[1]) + 1)[:, : L - ref_batch["input_ids"].shape[1]]
    att[:] = 1
    ref_batch["input_ids"], ref_batch["attention_mask"] = ids, att
    opt.zero_grad(set_to_none=True)
    for s in range(args.ref_micro_batches + 2):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        loss, _ = compute_loss(model, ref_batch, dev, sigma, torch.float16)
        scaler.scale(loss).backward()
        torch.cuda.synchronize()
        ref_steps.append({"i": s, "warmup": s < 2,
                          "step_seconds": time.perf_counter() - t0,
                          "loss_finite": bool(np.isfinite(float(loss.item())))})
        opt.zero_grad(set_to_none=True)
    rt = np.array([s["step_seconds"] for s in ref_steps if not s["warmup"]])
    rec["reference_length_1024"] = {
        "tokens_per_sequence": L,
        "sequences_per_micro_batch": MICRO_BATCH,
        "step_seconds_mean": float(rt.mean()), "step_seconds_sd": float(rt.std()),
        "seconds_per_optimiser_update_eff_batch_64": float(rt.mean() * GRAD_ACCUM),
        "peak_memory_bytes": int(torch.cuda.max_memory_allocated()),
        "steps": ref_steps,
    }
    rec["extrapolation"] = {
        "recipe": {"epochs": EPOCHS, "micro_batch": MICRO_BATCH, "grad_accum": GRAD_ACCUM,
                   "effective_batch_sequences": MICRO_BATCH * GRAD_ACCUM,
                   "source": "notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb @ 42626c34"},
        "train_items_per_seed": TRAIN_N,
        "micro_batches_per_seed": micro_per_seed,
        "optimiser_updates_per_seed": upd_per_seed,
        "seconds_per_seed": seed_secs,
        "hours_per_seed": seed_secs / 3600.0,
        "seeds": SEEDS,
        "hours_all_seeds": seed_secs * SEEDS / 3600.0,
        "excludes": "model load, one-off tokenisation, post-training temperature fit",
    }
    with open(args.out, "w") as f:
        json.dump(rec, f, indent=2)
    summary = {k: rec[k] for k in
               ("env", "model", "tokenisation", "measured", "extrapolation")}
    summary["peak_memory_bytes_workload"] = rec["peak_memory_bytes_workload"]
    summary["fp16_scale_probe"] = {
        k: v for k, v in rec["fp16_scale_probe"].items() if k != "fp16_scale_ladder"}
    summary["reference_length_1024"] = {
        k: v for k, v in rec["reference_length_1024"].items() if k != "steps"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
