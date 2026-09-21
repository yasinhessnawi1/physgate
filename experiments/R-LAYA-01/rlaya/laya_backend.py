"""The Laya scoring path, shared by arms L0 and L1.

Everything Laya sees comes through `fixture.serialise`. This module turns a list
of serialised states into raw per-option logits, batched, using Laya's own
`build_sequence`, `collate_items` and `DecisionModel` — the same objects
`laya.Agent.system_one` uses, in the same order.

Why not just call `system_one`
------------------------------
`system_one` evaluates typed questions over **one** state per call and rounds
what it returns to four decimal places. This experiment needs 8 000 states per
seed and needs an unrounded score to temperature-scale, because
`metrics.fit_temperature` fits ``p = sigmoid(score / T)`` and recovering a score
from a rounded probability is undefined at the extremes.

So `logits()` batches instead — and `verify_matches_system_one()` checks, on a
sample, that the batched path reproduces `system_one`'s reported `noul`
probability to the four decimals it prints. The public path is the reference;
this one is checked against it.

Temperature
-----------
`neutralise_temperature()` sets the checkpoint's own `temperature` and
`temperature_by_options` to identity and returns what they held, per the
orchestrator's D2 ruling of 2026-09-21. "Raw" in C1 means identity temperature —
native logits, no scaling from any source — and the §3 fit is then applied on
top of that, identically for L0, L1 and T. R6 is untouched: a temperature is a
calibration constant in a JSON config, not a weight, and the weights stay frozen
at the recorded revision.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import torch

from laya.common import QTYPES, build_sequence, collate_items

# CRITERIA §2, verbatim.
QUESTION_ID = "escalate"
QUESTION = {
    QUESTION_ID: {
        "type": "noul",
        "instructions": "Should this subtask be escalated to a human reviewer?",
    }
}
Q_INTERNAL = {"t": "noul",
              "ins": QUESTION["escalate"]["instructions"],
              "crit": None}


def neutralise_temperature(agent) -> Dict[str, Any]:
    """Set the checkpoint's own calibration to identity. Returns the prior values."""
    prior = {
        "temperature": list(agent.temperature),
        "temperature_by_options": dict(agent.temperature_by_options),
        "cfg_temperature": list(agent.cfg.get("temperature", [])),
        "cfg_temperature_by_options": dict(agent.cfg.get("temperature_by_options", {})),
    }
    agent.temperature = [1.0, 1.0, 1.0]
    agent.temperature_by_options = {}
    agent.cfg["temperature"] = [1.0, 1.0, 1.0]
    agent.cfg["temperature_by_options"] = {}
    return prior


def build_items(agent, states: Sequence[str]) -> List[Dict[str, Any]]:
    """One tokenised item per state, through Laya's own `build_sequence`."""
    max_len = agent.cfg.get("max_len", 512)
    head_max_len = agent.cfg.get("head_max_len", 192)
    items = []
    for s in states:
        ids, markers = build_sequence(agent.tok, s, Q_INTERNAL, max_len, head_max_len)
        if len(markers) != 2:
            raise ValueError("noul must produce two option markers, got %d" % len(markers))
        items.append({"ids": ids, "markers": markers, "qtype": QTYPES["noul"]})
    return items


@torch.no_grad()
def logits(agent, states: Sequence[str], batch_size: int = 32,
           progress: bool = False) -> np.ndarray:
    """Raw per-option logits, shape (n, 2), order [false, true]. No temperature.

    Runs under `agent.dtype`. `load_agent(..., force_fp32=True)` — which is what
    this experiment uses — makes that fp32 on every device. See C5 M10: under
    fp16 the reported probability moves by ~1.6e-3 depending on which batch a
    state happened to be scored in, and a criterion must not depend on that.
    """
    items = build_items(agent, states)
    out = np.empty((len(items), 2), dtype=np.float64)
    use_amp = agent.device.type == "cuda" and agent.dtype != torch.float32
    for i in range(0, len(items), batch_size):
        chunk = items[i:i + batch_size]
        b = collate_items([chunk], agent.tok.pad_token_id)
        with torch.autocast(device_type=agent.device.type, dtype=agent.dtype,
                            enabled=use_amp):
            lg, _ = agent.model(
                b["input_ids"].to(agent.device),
                b["attention_mask"].to(agent.device),
                b["marker_pos"].to(agent.device),
                b["marker_mask"].to(agent.device),
                b["qtype"].to(agent.device))
        out[i:i + len(chunk)] = lg.float().cpu().numpy()[:, :2]
        if progress and (i // batch_size) % 20 == 0:
            print("  logits %d/%d" % (i, len(items)), flush=True)
    return out


def numeric_sensitivity(agent, states: Sequence[str], n: int = 64) -> Dict[str, Any]:
    """How much does the reported probability depend on dtype and batch shape?

    Not a criterion. It is the evidence for pinning fp32, and it is the reason
    the agreement check below holds dtype fixed: comparing a batched fp32 path to
    a batch-of-one fp16 path measures fp16, not batching.
    """
    import torch as _t
    s = list(states[:n])
    keep = agent.dtype
    out: Dict[str, Any] = {"n": len(s)}
    per = {}
    for name, dt in (("fp32", _t.float32), ("fp16", _t.float16)):
        if dt == _t.float16 and agent.device.type != "cuda":
            continue
        agent.dtype = dt
        p_b = probs_raw(logits(agent, s, batch_size=32))
        p_1 = probs_raw(logits(agent, s, batch_size=1))
        per[name] = {
            "batch32_vs_batch1_max_abs_dp": float(np.abs(p_b - p_1).max()),
            "batch32_vs_batch1_mean_abs_dp": float(np.abs(p_b - p_1).mean()),
            "p_batch1_first4": [round(float(x), 6) for x in p_1[:4]],
        }
        per[name]["_p1"] = p_1
    if "fp32" in per and "fp16" in per:
        d = np.abs(per["fp32"]["_p1"] - per["fp16"]["_p1"])
        out["fp32_vs_fp16_at_batch1"] = {
            "max_abs_dp": float(d.max()), "mean_abs_dp": float(d.mean()),
            "n_decisions_flipped_at_0.5": int(
                ((per["fp32"]["_p1"] >= 0.5) != (per["fp16"]["_p1"] >= 0.5)).sum()),
        }
    for v in per.values():
        v.pop("_p1", None)
    out["per_dtype"] = per
    agent.dtype = keep
    return out


def score(lg: np.ndarray) -> np.ndarray:
    """The logit-difference score that temperature scaling divides.

    ``p_true = sigmoid(score / T)`` reproduces Laya's own
    ``softmax(logits / T)[1]`` exactly for two options, which is what makes the
    §3 fit and Laya's own temperature the same operation on the same quantity.
    """
    return lg[:, 1] - lg[:, 0]


def probs_raw(lg: np.ndarray) -> np.ndarray:
    """P(escalate) at identity temperature — C1's "raw"."""
    return 1.0 / (1.0 + np.exp(-np.clip(score(lg), -50, 50)))


def verify_matches_system_one(agent, states: Sequence[str],
                              n: int = 8) -> Dict[str, Any]:
    """Check the batched path against Laya's public one, to four decimals.

    `system_one` rounds to 4 dp, so that is the tolerance, and the comparison is
    run at **batch size 1** so that what is being checked is the code path and
    not the arithmetic of batching. `numeric_sensitivity` measures the batching
    effect separately. Any disagreement here means the batched path is not the
    path under test and the run stops.
    """
    lg = logits(agent, states[:n], batch_size=1)
    mine = probs_raw(lg)
    theirs, theirs_conf = [], []
    for s in states[:n]:
        r = agent.system_one(s, QUESTION)[ "answers" ][QUESTION_ID]
        theirs.append(r["noul"])
        theirs_conf.append(r["confidence"])
    theirs = np.asarray(theirs, dtype=float)
    d = np.abs(np.round(mine, 4) - theirs)
    ok = bool((d <= 1e-4 + 1e-9).all())
    return {
        "n_checked": int(n),
        "max_abs_difference_at_4dp": float(d.max()),
        "agrees": ok,
        "batched_noul": [round(float(x), 4) for x in mine],
        "system_one_noul": [float(x) for x in theirs],
        "system_one_confidence": [float(x) for x in theirs_conf],
        "note": "system_one rounds to 4 dp; that is the tolerance.",
    }


def load_agent(model_dir: str, device: str, force_fp32: bool = True):
    """`laya.Agent` on the pinned checkpoint, calibration removed, dtype pinned.

    `force_fp32` is the experiment's pinned inference precision, on every device.
    `laya.Agent` would choose fp16 on a compute-capability-7.0 card and fp32 on
    cpu and mps. Three reasons it is pinned to fp32 here, recorded as C5 M10:

    * **C4 gates on the laptop**, which is cpu/mps and therefore fp32 already.
      Scoring the server in fp16 and the laptop in fp32 would mean the two
      machines disagree about what the backend answered.
    * **fp16 makes the answer depend on the batch.** Measured, not assumed: the
      reported probability moves by up to 1.6e-3 depending on which batch a
      state was scored in. A criterion must not depend on that.
    * There is no tf32 on this card, so fp32 here is true fp32.
    """
    import laya
    import torch as _t
    from laya.agent import _fix_tokenizer_config
    _fix_tokenizer_config(model_dir)
    agent = laya.Agent(model_dir, device=device)
    dtype_chosen_by_laya = str(agent.dtype)
    if force_fp32:
        agent.dtype = _t.float32
        agent.model.float()
    prior = neutralise_temperature(agent)
    info = {
        "device": str(agent.device),
        "dtype": str(agent.dtype),
        "dtype_laya_would_have_chosen": dtype_chosen_by_laya,
        "dtype_forced_fp32": bool(force_fp32),
        "allow_tf32": bool(getattr(_t.backends.cuda.matmul, "allow_tf32", False)),
        "reference_compile": getattr(agent.model.encoder.config, "reference_compile", "absent"),
        "attn_implementation": getattr(agent.model.encoder.config,
                                       "_attn_implementation", None),
        "neutralised_temperature_prior": prior,
        "max_len": agent.cfg.get("max_len"),
        "head_max_len": agent.cfg.get("head_max_len"),
        "model_dir": os.path.abspath(model_dir),
    }
    return agent, info
