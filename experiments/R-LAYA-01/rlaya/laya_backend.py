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

    Runs under exactly the dtype and device `laya.Agent` chose for itself, which
    on a compute-capability-7.0 card is fp16 and on cpu/mps is fp32 — see
    `laya/agent.py`, which downgrades bf16 itself.
    """
    items = build_items(agent, states)
    out = np.empty((len(items), 2), dtype=np.float64)
    use_amp = agent.device.type == "cuda"
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

    `system_one` rounds to 4 dp, so that is the tolerance. Any disagreement means
    the batched path is not the path under test and the run stops.
    """
    lg = logits(agent, states[:n])
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


def load_agent(model_dir: str, device: str):
    """`laya.Agent` on the pinned checkpoint, with its own calibration removed."""
    import laya
    from laya.agent import _fix_tokenizer_config
    _fix_tokenizer_config(model_dir)
    agent = laya.Agent(model_dir, device=device)
    prior = neutralise_temperature(agent)
    info = {
        "device": str(agent.device),
        "dtype": str(agent.dtype),
        "reference_compile": getattr(agent.model.encoder.config, "reference_compile", "absent"),
        "attn_implementation": getattr(agent.model.encoder.config,
                                       "_attn_implementation", None),
        "neutralised_temperature_prior": prior,
        "max_len": agent.cfg.get("max_len"),
        "head_max_len": agent.cfg.get("head_max_len"),
        "model_dir": os.path.abspath(model_dir),
    }
    return agent, info
