"""Metrics for C1, C2 and C3, and the calibration fit for §3.

Every arm is scored by these functions and no arm brings its own. ARCH-131:
*"The threshold is a property of the interface, not of a backend, so every
backend is judged on the same routing rule."*

--------------------------------------------------------------------------
Confidence
--------------------------------------------------------------------------
``confidence(p) = max(p, 1 - p)``, for every arm.

Neither CRITERIA nor ARCH-131 defines the function; both assume one. Three
things settle it, and the third was checked in the library rather than assumed:

* **C1 is an expected *calibration* error.** ECE compares a confidence to an
  observed accuracy, which requires the confidence to be an estimate of the
  probability of being right. ``max(p, 1-p)`` is exactly that.
* **Every arm on the same rule.** ARCH-131: *"The threshold is a property of the
  interface, not of a backend."* ``R`` emits 1.0 by construction and ``G``
  reports native probabilities (§3); both are on this scale.
* **It is also what Laya reports for this question kind.** Laya has two
  confidence functions and picks by question type. ``choice`` and ``score`` get
  ``confidence_from_probs``, normalised Shannon entropy ``1 - H(p)/log k``. But
  ``noul`` — the only kind this experiment exercises (§8: *"Only ``yes_no`` is
  tested"*) — gets ``round(max(p[1], 1 - p[1]), 4)``, at
  ``laya/agent.py:335``. So there is **no scale mismatch to work around**: the
  common scale and Laya's native scale are the same function here.

That last point is worth stating because it very nearly went the other way. Had
the entropy confidence been in force, the 0.8 threshold would have cut at
``p = 0.8`` for arms R, G and T and at ``p ≈ 0.969`` for the Laya arms, and the
escalation rates in C2 would not have been comparable. ``laya_entropy_confidence``
below computes what that would have been, and it is reported as **non-gating
context** only. Recorded as C5 M8.

--------------------------------------------------------------------------
Provenance of the copied functions
--------------------------------------------------------------------------
``ece_conf_half``, ``ece_prob_bins``, ``mean_confidence``, ``fit_temperature``,
``apply_temperature`` and ``rule_arm`` are **verbatim copies** of
``experiment.py`` from ``R-TM-01/R-TM-01_complete/run05d/`` (sha256
``095982966f0bb6dc80c182b044a72c0790fc71ecf75e35fd1beb553252055269``), renamed
only where this module needed a clearer name. They are copied rather than
imported because ``experiment.py`` imports ``tmu`` at module scope, which exists
only in arm T's Python 3.11 environment. ``test_vendor_equivalence.py`` runs both
against the same inputs in that environment and asserts they agree exactly.
"""
from __future__ import annotations

import math
import os
import sys
from typing import Dict

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import generator as G_BASE  # noqa: E402  (for GATES, in rule_arm)

N_BINS = 10  # CRITERIA §6 C1: "Expected calibration error, 10 bins"


# ------------------------------------------------------------- confidence --

def confidence(probs: np.ndarray) -> np.ndarray:
    """P(the decision is right), for a binary decision. See module docstring."""
    return np.maximum(probs, 1.0 - probs)


def laya_entropy_confidence(probs: np.ndarray, k: int = 2) -> np.ndarray:
    """Laya's own confidence, ``1 - H(p)/log k`` — reported, never gated on.

    Behaviourally identical to ``laya.common.confidence_from_probs`` for k = 2.
    """
    p = np.stack([1.0 - probs, probs], axis=-1)
    ent = -(p * np.log(np.clip(p, 1e-12, 1.0))).sum(-1)
    return np.clip(1.0 - ent / math.log(k), 0.0, 1.0)


def mean_confidence(probs: np.ndarray) -> float:
    """VERBATIM from run05d/experiment.py:mean_confidence."""
    return float(np.mean(np.maximum(probs, 1 - probs)))


# --------------------------------------------------------------------- ECE --

def ece_conf_half(probs: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> float:
    """VERBATIM from run05d/experiment.py:ece.

    Expected calibration error, ``n_bins`` **equal-width** bins on confidence
    over ``[0.5, 1.0]``. Equal-width, not equal-mass: the edges are
    ``np.linspace(0.5, 1.0, n_bins + 1)``.
    """
    conf = np.maximum(probs, 1 - probs)
    pred = (probs >= 0.5).astype(int)
    correct = (pred == y).astype(float)
    edges = np.linspace(0.5, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf > lo) & (conf <= hi) if i > 0 else (conf >= lo) & (conf <= hi)
        if m.sum() == 0:
            continue
        total += (m.sum() / len(y)) * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def ece_conf_full(probs: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> float:
    """The same quantity with ``n_bins`` equal-width bins over ``[0, 1]``.

    This is what ``laya.common.ece_score`` computes (also equal-width; its default
    is 15 bins, which is why the experiment passes ``n_bins`` explicitly). For a
    binary decision, confidence is at least 0.5 by construction, so the lower half
    of the bins is always empty and ten bins here behave like five. Reported for
    comparison; see prospective deviation D4.
    """
    conf = np.maximum(probs, 1 - probs)
    correct = ((probs >= 0.5).astype(int) == y).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf > lo) & (conf <= hi) if i > 0 else (conf >= lo) & (conf <= hi)
        if m.sum() == 0:
            continue
        total += (m.sum() / len(y)) * abs(correct[m].mean() - conf[m].mean())
    return float(total)


def ece_prob_bins(probs: np.ndarray, y: np.ndarray, n_bins: int = N_BINS) -> float:
    """VERBATIM from run05d/experiment.py:ece_prob_bins. Independent check."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (probs > lo) & (probs <= hi) if i > 0 else (probs >= lo) & (probs <= hi)
        if m.sum() == 0:
            continue
        total += (m.sum() / len(y)) * abs(y[m].mean() - probs[m].mean())
    return float(total)


def reliability(probs: np.ndarray, y: np.ndarray, n_bins: int = N_BINS):
    """VERBATIM from run05d/experiment.py:reliability. For the diagrams."""
    conf = np.maximum(probs, 1 - probs)
    correct = ((probs >= 0.5).astype(int) == y).astype(float)
    edges = np.linspace(0.5, 1.0, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf > lo) & (conf <= hi) if i > 0 else (conf >= lo) & (conf <= hi)
        out.append({"lo": float(lo), "hi": float(hi), "n": int(m.sum()),
                    "conf": float(conf[m].mean()) if m.sum() else None,
                    "acc": float(correct[m].mean()) if m.sum() else None})
    return out


# ------------------------------------------------------------- calibration --

def fit_temperature(scores: np.ndarray, y: np.ndarray) -> float:
    """VERBATIM from run05d/experiment.py:fit_temperature.

    One-parameter temperature scaling, ``p = sigmoid(score / temp)``, fitted by
    bounded scalar minimisation of the negative log likelihood.
    """
    from scipy.optimize import minimize_scalar
    y = np.asarray(y, dtype=float)

    def nll(log_t):
        t = np.exp(log_t)
        z = np.clip(scores / t, -50, 50)
        p = 1.0 / (1.0 + np.exp(-z))
        p = np.clip(p, 1e-9, 1 - 1e-9)
        return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())

    r = minimize_scalar(nll, bounds=(-6.0, 6.0), method="bounded")
    return float(np.exp(r.x))


def apply_temperature(temp: float, scores: np.ndarray) -> np.ndarray:
    """VERBATIM from run05d/experiment.py:apply_temperature."""
    z = np.clip(scores / temp, -50, 50)
    return 1.0 / (1.0 + np.exp(-z))


# ------------------------------------------------------- routing and C2/C3 --

def routing_report(probs: np.ndarray, y: np.ndarray,
                   threshold: float = 0.8) -> Dict[str, float]:
    """Everything C2 and C3 need, at the ARCH-131 threshold.

    ``escalation_rate`` is the fraction routed to ARCH-130, i.e. confidence below
    the threshold, *"whatever the answer"*. ``selective_accuracy`` is C3: accuracy
    on the decisions the backend does **not** escalate.
    """
    conf = confidence(probs)
    pred = (probs >= 0.5).astype(int)
    correct = (pred == np.asarray(y)).astype(float)
    escalate = conf < threshold
    kept = ~escalate
    return {
        "n": int(len(y)),
        "threshold": float(threshold),
        "mean_confidence": float(conf.mean()),
        "mean_confidence_laya_entropy": float(laya_entropy_confidence(probs).mean()),
        "escalation_rate": float(escalate.mean()),
        "escalation_rate_laya_entropy": float(
            (laya_entropy_confidence(probs) < threshold).mean()),
        "accuracy_split": float(correct.mean()),
        "n_kept": int(kept.sum()),
        "selective_accuracy": float(correct[kept].mean()) if kept.any() else float("nan"),
    }


def score_all(probs: np.ndarray, y: np.ndarray,
              threshold: float = 0.8) -> Dict[str, float]:
    """C1's three ECE variants plus the routing report, in one dict."""
    out = dict(routing_report(probs, y, threshold))
    out["ece"] = ece_conf_half(probs, y)
    out["ece_conf_full_0_1"] = ece_conf_full(probs, y)
    out["ece_prob_bins"] = ece_prob_bins(probs, y)
    return out


# ------------------------------------------------------------- the R arm ----

def rule_arm(raw) -> np.ndarray:
    """VERBATIM from run05d/experiment.py:rule_arm — R-TM-01's hand rule.

    Kept byte-identical so arm R is the same rule R-TM-01 measured. The original
    docstring flagged an assumption because *"the source spec does not print the
    rule"*; it is printed now, in ARCH-030, ARCH-040 and ARCH-130, and the
    comparison is written up as C5 M9. In short: this covers two of ARCH-130's
    three sources — exhausted repair budget (ARCH-030, attempt 3) and gate
    escalation — and the third, unresolved arbitration (ARCH-040), has no field
    in the generator's state to key on.
    """
    any_gate_fail = np.zeros(len(raw["attempt"]), dtype=bool)
    for g in G_BASE.GATES:
        any_gate_fail |= raw[g] == 0
    return ((raw["attempt"] == 3) | any_gate_fail).astype(int)
