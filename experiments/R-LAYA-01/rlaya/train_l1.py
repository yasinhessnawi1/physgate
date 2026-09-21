"""Step 3 — train arm L1. Five seeds, the recipe's four epochs, nothing shortened.

CRITERIA §3: *"Laya fine-tuned on Train only, using the repository's own
reinforcement-learning fine-tuning notebook adapted to the available accelerator
(fp16; the card has no bfloat16). **The entry decision rests on this arm**."*

The recipe is `notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb` at the
pinned commit `42626c348753fbb17572a813127df2278a1ec527`. Everything below that
is not an adaptation the card forces is verbatim from `train_ddp.py` in that
notebook: four epochs, micro-batch 8, GRPO group size 4, encoder lr 2.5e-5, head
lr 1.0e-4, exploration sigma 0.4 → 0.1 across epochs, AdamW weight decay 0.01,
cosine schedule to 1e-6, gradient clip 1.0, the proper-scoring-rule reward at
w_sph 0.75, the full 1.0 soft cross-entropy term, and the post-training LBFGS
temperature fit on `items[::15][:400]`.

**Three adaptations, all of them forced by the hardware, none of them shortening
training** (the kickoff's ruling of 2026-09-21):

* world size 2 → 1, so DDP is dropped;
* gradient accumulation 4 → 8, which keeps the recipe's effective batch of 64
  sequences per optimiser update at world size 1;
* fp16 — which is what the notebook itself uses, because it targets 2×T4.

**No epoch count is reduced, no schedule truncated, nothing traded for clock.**
Step 1 measured the arm at 0.756 h against a 12 h budget, so there is no reason
to reach for one, and reaching for one would be the finding rather than a fix.

**Precision, said plainly: fp16 is the training path, and it is the recipe's own.
The fp32 pin of C5 M10 is on *scoring*, not on training.** Nothing about the
recipe changed.

**Loss scaler: the default `torch.amp.GradScaler("cuda", enabled=True)`, with no
`init_scale`.** Setting one would be tuning after seeing step 1's numbers.
Per-micro-batch finiteness is logged so that the answer is a rate and a set of
indices rather than "it finished".

Usage:  python train_l1.py <model_dir> <out_dir> [--seeds 0 1 2 3 4]
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import fixture, metrics, workload  # noqa: E402
from rlaya import laya_backend as LB  # noqa: E402

from laya.common import QTYPES, build_model, build_sequence, proper_reward  # noqa: E402
from laya.agent import _fix_tokenizer_config  # noqa: E402
from safetensors.torch import load_file, save_file  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

# ---- the recipe, from train_ddp.py in the pinned notebook -------------------
EPOCHS = 4
MICRO_BATCH = 8
GRAD_ACCUM = 8           # notebook: 4 at world size 2. 8 here keeps eff. batch 64.
GROUP_SIZE = 4
LR_ENCODER = 2.5e-5
LR_HEAD = 1.0e-4
SIGMA_START, SIGMA_END = 0.4, 0.1
W_SPH, W_RPS = 0.75, 1.0
CE_WEIGHT = 1.0
CLIP = 1.0
WEIGHT_DECAY = 0.01
ETA_MIN = 1e-6
CALIB_STRIDE, CALIB_MAX = 15, 400   # notebook: all_items[::15][:400]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def collate(items, pad_id):
    """VERBATIM in behaviour from train_ddp.py:collate_train_batch."""
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
    return {"input_ids": ids, "attention_mask": att, "marker_pos": mpos,
            "marker_mask": mmask, "target": target,
            "qtype": torch.tensor([it["qtype"] for it in items]),
            "label": torch.tensor([it["label"] for it in items])}


def fit_one_temp(sel):
    """VERBATIM from train_ddp.py:fit_one_temp — the recipe's own calibration.

    Its output is recorded per seed and then **neutralised** before anything is
    scored, per the D2 ruling: L1 is temperature-scaled once, by the §3 fit, like
    every other arm. The value is kept because it is interesting and because step
    4 reports a non-gating pass under the shipped temperature.
    """
    if len(sel) < 10:
        return 1.0
    kmax = max(len(z) for z, _ in sel)
    Z = torch.full((len(sel), kmax), -1e4)
    T = torch.zeros((len(sel), kmax))
    for i, (z, t) in enumerate(sel):
        Z[i, :len(z)] = torch.tensor(z)
        T[i, :len(t)] = torch.tensor(t, dtype=torch.float32)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        opt.zero_grad()
        loss = -(T * torch.log_softmax(Z / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss

    opt.step(closure)
    return float(torch.clamp(log_t.exp(), 0.1, 10.0).item())


def build_train_items(tok, cfg, seed, variant="main"):
    """Train only, through the R3 fixture. No test split is constructed.

    ``variant="nofw"`` is Train with the firmware domain dropped - the split
    R-TM-01 retrains on and measures OOD-B against (CRITERIA §5: *"Test-OOD-B
    (unseen domain, with the retrained arm for OOD-B as R-TM-01 defined it)"*).
    It is a filter of Train and contains no test sample.
    """
    src = workload.train_nofw_only if variant == "nofw" else workload.train_only
    _, y, _, raw, _ = src(seed)
    items = []
    for i in range(len(y)):
        ids, markers = build_sequence(tok, fixture.serialise(raw, i), LB.Q_INTERNAL,
                                      cfg["max_len"], cfg["head_max_len"])
        items.append({"ids": ids, "markers": markers, "qtype": QTYPES["noul"],
                      # noul target order is [false, true]
                      "target": [1.0 - float(y[i]), float(y[i])],
                      "label": int(y[i])})
    return items, y


def clusters(indices):
    """Contiguous runs, so an excursion is reported as a cluster not a list."""
    out = []
    for i in indices:
        if out and i == out[-1][1] + 1:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [{"from": a, "to": b, "n": b - a + 1} for a, b in out]


def train_seed(seed, model_dir, out_dir, device, variant="main"):
    dev = torch.device(device)
    _fix_tokenizer_config(model_dir)
    tok = AutoTokenizer.from_pretrained(os.path.join(model_dir, "tokenizer"))
    with open(os.path.join(model_dir, "rl_agent_config.json")) as f:
        cfg = json.load(f)
    cfg["gradient_checkpointing"] = True
    cfg["max_tokens_per_batch"] = 4096
    cfg["max_len"] = 1024
    cfg["head_max_len"] = 256

    items, y = build_train_items(tok, cfg, seed, variant)
    all_items = list(items)            # save order, for the recipe's calib slice

    model = build_model(cfg, encoder_dir=os.path.join(model_dir, "encoder"))
    model.load_state_dict(load_file(os.path.join(model_dir, "model.safetensors")),
                          strict=True)
    model.encoder.gradient_checkpointing_enable(
        gradient_checkpointing_kwargs={"use_reentrant": False})
    model.head_checkpointing = True
    model.to(dev)
    model.train()

    enc = [p for n, p in model.named_parameters() if "encoder." in n]
    head = [p for n, p in model.named_parameters() if "encoder." not in n]
    opt = torch.optim.AdamW([{"params": enc, "lr": LR_ENCODER},
                             {"params": head, "lr": LR_HEAD}],
                            weight_decay=WEIGHT_DECAY)
    total_updates = (len(items) // (MICRO_BATCH * GRAD_ACCUM)) * EPOCHS
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=max(1, total_updates), eta_min=ETA_MIN)
    scaler = torch.amp.GradScaler("cuda", enabled=True)
    params = [p for p in model.parameters() if p.requires_grad]

    torch.cuda.reset_peak_memory_stats()
    step_t, step_loss, step_scale, step_bad, step_reward, step_epoch = [], [], [], [], [], []
    updates = []
    check_secs_total = 0.0
    mb_index = 0
    wall0 = time.perf_counter()

    for epoch in range(EPOCHS):
        random.seed(42 + epoch)        # train_ddp.py: 42 + epoch + rank, rank 0
        random.shuffle(items)
        opt.zero_grad(set_to_none=True)
        accum = 0
        progress = epoch / max(1, EPOCHS - 1)
        sigma = SIGMA_START + (SIGMA_END - SIGMA_START) * progress

        for b in range(0, len(items), MICRO_BATCH):
            chunk = items[b:b + MICRO_BATCH]
            if not chunk:
                continue
            batch = collate(chunk, tok.pad_token_id)

            torch.cuda.synchronize()
            t0 = time.perf_counter()
            with torch.autocast("cuda", dtype=torch.float16):
                lg, act = model(batch["input_ids"].to(dev), batch["attention_mask"].to(dev),
                                batch["marker_pos"].to(dev), batch["marker_mask"].to(dev),
                                batch["qtype"].to(dev))
            lg = lg.float()
            mask = batch["marker_mask"].to(dev)
            k = mask.sum(-1, keepdim=True).float()
            target = batch["target"].to(dev)

            eps = torch.randn((GROUP_SIZE,) + lg.shape, device=dev) * sigma * mask
            eps = (eps - eps.sum(-1, keepdim=True) / k) * mask
            z = lg.detach().unsqueeze(0) + eps
            q = torch.softmax(z.masked_fill(~mask, -1e4), -1)
            with torch.no_grad():
                r = proper_reward(q, target.unsqueeze(0), batch["qtype"].to(dev),
                                  mask, w_sph=W_SPH, w_rps=W_RPS)
                adv = r - r.mean(0, keepdim=True)
                adv = adv / (adv.std() + 1e-6)
            logp = -(((z - lg.unsqueeze(0)) ** 2) * mask).sum(-1) / (2 * sigma ** 2)
            loss_rl = -(adv * logp).mean()
            loss_ce = -(target * torch.log_softmax(lg.masked_fill(~mask, -1e4), -1)).sum(-1).mean()
            loss = (loss_rl + CE_WEIGHT * loss_ce) / GRAD_ACCUM + 0.0 * act.sum()
            scaler.scale(loss).backward()
            torch.cuda.synchronize()
            step_t.append(time.perf_counter() - t0)

            # per-micro-batch finiteness, timed apart from the step
            tc = time.perf_counter()
            with torch.no_grad():
                bad = sum(1 for p in params
                          if p.grad is not None and not torch.isfinite(p.grad).all())
            check_secs_total += time.perf_counter() - tc

            step_loss.append(float(loss.item()) * GRAD_ACCUM)
            step_scale.append(float(scaler.get_scale()))
            step_bad.append(int(bad))
            step_reward.append(float(r.mean().item()))
            step_epoch.append(epoch)

            accum += 1
            if accum % GRAD_ACCUM == 0 or (b + MICRO_BATCH) >= len(items):
                before = scaler.get_scale()
                scaler.unscale_(opt)
                gn = torch.nn.utils.clip_grad_norm_(model.parameters(), CLIP)
                scaler.step(opt)
                scaler.update()
                sched.step()
                opt.zero_grad(set_to_none=True)
                after = scaler.get_scale()
                updates.append({
                    "update": len(updates), "epoch": epoch, "micro_batch": mb_index,
                    "grad_norm": float(gn), "grad_norm_finite": bool(np.isfinite(float(gn))),
                    "scale_before": float(before), "scale_after": float(after),
                    "skipped": bool(after < before), "lr": float(sched.get_last_lr()[0]),
                })
            mb_index += 1

    train_secs = time.perf_counter() - wall0
    peak = int(torch.cuda.max_memory_allocated())

    # ---- the recipe's own post-training temperature fit --------------------
    model.eval()
    calib_items = all_items[::CALIB_STRIDE][:CALIB_MAX]
    preds = []
    with torch.no_grad():
        for c in range(0, len(calib_items), 16):
            cc = calib_items[c:c + 16]
            cb = collate(cc, tok.pad_token_id)
            with torch.autocast("cuda", dtype=torch.float16):
                ls, _ = model(cb["input_ids"].to(dev), cb["attention_mask"].to(dev),
                              cb["marker_pos"].to(dev), cb["marker_mask"].to(dev),
                              cb["qtype"].to(dev))
            ln = ls.float().cpu().numpy()
            for rr, it in enumerate(cc):
                preds.append((it["qtype"], ln[rr, :len(it["markers"])], it["target"]))
    recipe_temps = [1.2, 1.2, 1.2]
    for qt in range(3):
        sel = [(zz, tt) for q_type, zz, tt in preds if q_type == qt]
        if sel:
            recipe_temps[qt] = fit_one_temp(sel)

    # ---- save, exactly as the recipe saves -------------------------------
    tag = "L1" if variant == "main" else "L1nofw"
    ck = os.path.join(out_dir, f"{tag}_seed{seed}")
    os.makedirs(ck, exist_ok=True)
    sd = {kk: v.half().contiguous().cpu() for kk, v in model.state_dict().items()}
    save_file(sd, os.path.join(ck, "model.safetensors"))
    model.encoder.config.save_pretrained(os.path.join(ck, "encoder"))
    tok.save_pretrained(os.path.join(ck, "tokenizer"))
    out_cfg = dict(cfg)
    out_cfg["fine_tuned"] = True
    out_cfg["model_name"] = "laya-typed-decisions"
    out_cfg["temperature"] = recipe_temps
    out_cfg["training"] = {"updates": len(updates), "epochs_completed": EPOCHS,
                           "hours": train_secs / 3600.0, "world_size": 1,
                           "fine_tuned_from_checkpoint": True,
                           "experiment": "R-LAYA-01 arm L1", "data_seed": seed,
                           "variant": variant}
    with open(os.path.join(ck, "rl_agent_config.json"), "w") as f:
        json.dump(out_cfg, f, indent=2)

    del model, opt, scaler, sched
    torch.cuda.empty_cache()

    # ---- D2: neutralise, then fit §3's temperature on Train[0:500] ---------
    agent, ainfo = LB.load_agent(ck, "cuda")   # forces fp32 scoring, neutralises
    src = workload.train_nofw_only if variant == "nofw" else workload.train_only
    _, ytr, _, raw, _ = src(seed)
    sl = workload.calibration_slice()
    states = [fixture.serialise(raw, i) for i in range(sl.start, sl.stop)]
    lg_cal = LB.logits(agent, states)
    z_cal = LB.score(lg_cal)
    temp_s3 = metrics.fit_temperature(z_cal, ytr[sl])
    np.savez_compressed(os.path.join(out_dir, f"{tag}_calib_seed{seed}.npz"),
                        logits=lg_cal, score=z_cal, y=ytr[sl])

    bad_idx = [i for i, b in enumerate(step_bad) if b > 0]
    skipped = [u for u in updates if u["skipped"]]
    scales = [u["scale_after"] for u in updates]
    np.savez_compressed(
        os.path.join(out_dir, f"{tag}_steps_seed{seed}.npz"),
        step_seconds=np.array(step_t), loss=np.array(step_loss),
        scale=np.array(step_scale), nonfinite=np.array(step_bad, dtype=np.int32),
        reward=np.array(step_reward), epoch=np.array(step_epoch, dtype=np.int8))

    st = np.array(step_t)
    return {
        "arm": "L1", "variant": variant, "seed": seed,
        "recipe": {"epochs": EPOCHS, "micro_batch": MICRO_BATCH,
                   "grad_accum": GRAD_ACCUM,
                   "effective_batch_sequences": MICRO_BATCH * GRAD_ACCUM,
                   "group_size": GROUP_SIZE, "lr_encoder": LR_ENCODER,
                   "lr_head": LR_HEAD, "sigma": [SIGMA_START, SIGMA_END],
                   "clip": CLIP, "weight_decay": WEIGHT_DECAY, "eta_min": ETA_MIN,
                   "nothing_shortened": True,
                   "source": "notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb @ 42626c34"},
        "n_train": int(len(y)),
        "micro_batches": len(step_t), "updates": len(updates),
        "train_seconds": train_secs, "train_hours": train_secs / 3600.0,
        "finite_check_seconds_total": check_secs_total,
        "train_hours_excluding_instrumentation": (train_secs - check_secs_total) / 3600.0,
        "step_seconds_mean": float(st.mean()), "step_seconds_sd": float(st.std()),
        "peak_memory_bytes": peak,
        "fp16": {
            "nonfinite_scaled_grad_micro_batches": len(bad_idx),
            "nonfinite_rate": len(bad_idx) / max(1, len(step_t)),
            "excursion_clusters": clusters(bad_idx),
            "skipped_updates": len(skipped),
            "skip_rate": len(skipped) / max(1, len(updates)),
            "skipped_at_update": [u["update"] for u in skipped],
            "scale_first": scales[0] if scales else None,
            "scale_last": scales[-1] if scales else None,
            "scale_min": min(scales) if scales else None,
            "scale_trajectory_changes": [
                {"update": u["update"], "from": u["scale_before"], "to": u["scale_after"]}
                for u in updates if u["scale_after"] != u["scale_before"]],
            "nonfinite_loss_micro_batches": int(sum(
                1 for v in step_loss if not np.isfinite(v))),
            "grad_norm_finite_updates": int(sum(1 for u in updates if u["grad_norm_finite"])),
            "grad_norm_min": float(min(u["grad_norm"] for u in updates if u["grad_norm_finite"])),
            "grad_norm_median": float(np.median(
                [u["grad_norm"] for u in updates if u["grad_norm_finite"]])),
            "grad_norm_max": float(max(u["grad_norm"] for u in updates if u["grad_norm_finite"])),
        },
        "loss_first10": [round(v, 4) for v in step_loss[:10]],
        "loss_last10": [round(v, 4) for v in step_loss[-10:]],
        "reward_first_epoch_mean": float(np.mean(
            [v for v, e in zip(step_reward, step_epoch) if e == 0])),
        "reward_last_epoch_mean": float(np.mean(
            [v for v, e in zip(step_reward, step_epoch) if e == EPOCHS - 1])),
        "recipe_fitted_temperature": {"choice": recipe_temps[0], "score": recipe_temps[1],
                                      "noul": recipe_temps[2],
                                      "note": "written into the saved checkpoint by the recipe, "
                                              "then neutralised per D2 before anything is scored"},
        "d2_neutralised": ainfo["neutralised_temperature_prior"],
        "scoring_agent": {kk: ainfo[kk] for kk in
                          ("device", "dtype", "dtype_laya_would_have_chosen",
                           "dtype_forced_fp32", "attn_implementation", "allow_tf32")},
        "temperature_s3_fitted": float(temp_s3),
        "s3_slice": {"start": sl.start, "stop": sl.stop},
        "checkpoint": {"path": ck,
                       "model_safetensors_sha256": sha256_file(
                           os.path.join(ck, "model.safetensors")),
                       "saved_dtype": "float16, as the recipe saves it"},
        "artefacts": [f"{tag}_seed{seed}/", f"{tag}_calib_seed{seed}.npz",
                      f"{tag}_steps_seed{seed}.npz"],
        "not_scored": "L1's metrics are produced at step 4 with every other arm.",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seeds", type=int, nargs="*", default=workload.SEEDS)
    ap.add_argument("--variant", choices=("main", "nofw"), default="main")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    import laya
    import transformers
    props = torch.cuda.get_device_properties(0)
    rec = {
        "experiment": "R-LAYA-01", "step": "3-train-L1", "arm": "L1",
        "variant": args.variant,
        "criteria_commit": "e12d153", "criteria_original": "7b85d29",
        "env": {
            "python": platform.python_version(), "platform": platform.platform(),
            "node": subprocess.run(["hostname"], capture_output=True,
                                   text=True).stdout.strip(),
            "torch": torch.__version__, "torch_cuda": torch.version.cuda,
            "torch_cuda_arch_list": torch.cuda.get_arch_list(),
            "cudnn": torch.backends.cudnn.version(),
            "transformers": transformers.__version__, "laya": laya.__version__,
            "numpy": np.__version__,
            "gpu": props.name, "compute_capability": [props.major, props.minor],
            "gpu_memory_total_bytes": props.total_memory,
            "driver": subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True).stdout.strip(),
            "cpu_nproc": subprocess.run(["nproc"], capture_output=True,
                                        text=True).stdout.strip(),
        },
        "checkpoint_pin": {
            "repo": "convaiinnovations/laya-typed-decisions",
            "revision": "f9ab0b228f0fc0f14d873dbc99038f135c2da1b2",
            "model_safetensors_sha256": sha256_file(
                os.path.join(args.model_dir, "model.safetensors")),
        },
        "precision_note": (
            "fp16 is the TRAINING path and it is the recipe's own; the notebook "
            "targets 2xT4 and uses torch.autocast(float16) with GradScaler. The fp32 "
            "pin recorded as C5 M10 is on SCORING, not on training. Nothing about "
            "the recipe changed."),
        "step1_extrapolation_hours_per_seed": 0.15115224475092773,
        "step1_extrapolation_hours_all_seeds": 0.7557612237546386,
        "code_checksums": {n: sha256_file(os.path.join(HERE, n)) for n in
                           ("fixture.py", "workload.py", "metrics.py",
                            "laya_backend.py", "train_l1.py", "vendor/generator.py",
                            "vendor/generator_b.py")},
        "seeds": args.seeds, "draw_fingerprint": {}, "runs": [],
    }
    for s in args.seeds:
        rec["draw_fingerprint"][str(s)] = workload.draw_fingerprint(s)
        print(f"=== seed {s} ===", flush=True)
        r = train_seed(s, args.model_dir, args.out_dir, args.device, args.variant)
        rec["runs"].append(r)
        print(" %.4f h  skips %d/%d  scale %s->%s  s3 temp %.4f  recipe noul temp %.4f"
              % (r["train_hours"], r["fp16"]["skipped_updates"], r["updates"],
                 r["fp16"]["scale_first"], r["fp16"]["scale_last"],
                 r["temperature_s3_fitted"],
                 r["recipe_fitted_temperature"]["noul"]), flush=True)
        with open(os.path.join(args.out_dir, f"step3_l1_{args.variant}.json"), "w") as f:
            json.dump(rec, f, indent=2)

    tot = sum(r["train_hours"] for r in rec["runs"])
    rec["total"] = {
        "train_hours_all_seeds": tot,
        "train_hours_all_seeds_excluding_instrumentation": sum(
            r["train_hours_excluding_instrumentation"] for r in rec["runs"]),
        "budget_hours": 12.0,
        "fraction_of_budget": tot / 12.0,
        "step1_predicted_hours_all_seeds": rec["step1_extrapolation_hours_all_seeds"],
        "ratio_measured_to_predicted": tot / rec["step1_extrapolation_hours_all_seeds"],
    }
    with open(os.path.join(args.out_dir, f"step3_l1_{args.variant}.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(json.dumps(rec["total"], indent=2))


if __name__ == "__main__":
    main()
