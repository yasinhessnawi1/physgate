"""R-TM-01 — core machinery: arms, metrics, calibration, clause decoding."""
import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from tmu.models.classification.vanilla_classifier import TMClassifier

import generator as G

# ------------------------------------------------------------------ metrics --

def ece(probs, y, n_bins=10):
    """Expected calibration error, 10 equal-width bins on confidence."""
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


def ece_prob_bins(probs, y, n_bins=10):
    """Alternative ECE: bins on P(y=1) over [0,1] (independent check)."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (probs > lo) & (probs <= hi) if i > 0 else (probs >= lo) & (probs <= hi)
        if m.sum() == 0:
            continue
        total += (m.sum() / len(y)) * abs(y[m].mean() - probs[m].mean())
    return float(total)


def mean_confidence(probs):
    return float(np.mean(np.maximum(probs, 1 - probs)))


def selective_gain(probs, y, drop_frac=0.20):
    """Accuracy gain from abstaining on the lowest-confidence fraction."""
    conf = np.maximum(probs, 1 - probs)
    pred = (probs >= 0.5).astype(int)
    correct = (pred == y).astype(float)
    base = float(correct.mean())
    k = int(round(drop_frac * len(y)))
    keep = np.argsort(conf, kind="stable")[k:]
    kept = float(correct[keep].mean())
    return base, kept, kept - base


def reliability(probs, y, n_bins=10):
    conf = np.maximum(probs, 1 - probs)
    pred = (probs >= 0.5).astype(int)
    correct = (pred == y).astype(float)
    edges = np.linspace(0.5, 1.0, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf > lo) & (conf <= hi) if i > 0 else (conf >= lo) & (conf <= hi)
        out.append({"lo": lo, "hi": hi, "n": int(m.sum()),
                    "conf": float(conf[m].mean()) if m.sum() else None,
                    "acc": float(correct[m].mean()) if m.sum() else None})
    return out


# -------------------------------------------------------------- calibration --

def fit_platt(scores, y, max_iter=1000):
    """Two-parameter Platt scaling (scale AND bias) - reported as a secondary."""
    lr = LogisticRegression(C=1e6, max_iter=max_iter)
    lr.fit(scores.reshape(-1, 1), y)
    return lr


def apply_platt(lr, scores):
    return lr.predict_proba(scores.reshape(-1, 1))[:, 1]


def fit_temperature(scores, y):
    """One-parameter temperature scaling: p = sigmoid(scores / temp)."""
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


def apply_temperature(temp, scores):
    z = np.clip(scores / temp, -50, 50)
    return 1.0 / (1.0 + np.exp(-z))


# ---------------------------------------------------------------------- TM ---

def tm_probs(class_sums, T):
    """Helin et al. 2025 class-sum confidence, clipped to [0,1]."""
    v = np.clip(class_sums[:, 1], -T, T).astype(float)
    return np.clip(0.5 * (1.0 + v / T), 0.0, 1.0)


def fit_tm(X, y, clauses, T, s, epochs, seed):
    tm = TMClassifier(number_of_clauses=clauses, T=T, s=s, platform="CPU",
                      weighted_clauses=False, seed=seed)
    tm.fit(X, y, epochs=epochs)
    return tm


def tm_predict(tm, X, T):
    pred, cs = tm.predict(X, return_class_sums=True)
    return np.asarray(pred), np.asarray(cs), tm_probs(np.asarray(cs), T)


# --------------------------------------------------------- clause decoding --

def decode_clauses(tm, the_class=1, polarity=0, n_bits=G.N_BITS):
    """Literals of each clause of one polarity bank.

    tmu splits number_of_clauses evenly into a positive (polarity 0, weight +1,
    votes FOR the class) and a negative (polarity 1, weight -1) bank, each
    indexed 0..n/2-1.  Iterating past n/2 silently re-reads the other bank.
    """
    out = []
    for c in range(tm.number_of_clauses // 2):
        lits = []
        for ta in range(2 * n_bits):
            if tm.get_ta_action(c, ta, the_class=the_class, polarity=polarity):
                lits.append((ta % n_bits, ta >= n_bits))
        out.append(lits)
    return out


def clause_outputs(clauses, X):
    """Boolean matrix (n_samples, n_clauses): does clause c fire on sample i."""
    n, _ = X.shape
    out = np.ones((n, len(clauses)), dtype=bool)
    Xb = X.astype(bool)
    for j, lits in enumerate(clauses):
        if not lits:
            out[:, j] = False        # empty clause: treat as uninformative
            continue
        col = np.ones(n, dtype=bool)
        for bit, neg in lits:
            col &= (~Xb[:, bit]) if neg else Xb[:, bit]
        out[:, j] = col
    return out


def lit_str(bit, neg):
    return ("NOT " if neg else "") + G.BIT_NAMES[bit]


def clause_str(lits):
    return " AND ".join(lit_str(b, n) for b, n in lits) if lits else "(empty)"


# Which hidden-rule term does a clause recognisably encode?
NAME = {n: i for i, n in enumerate(G.BIT_NAMES)}
GATE_BITS = [NAME[g] for g in G.GATES]


def match_term(lits):
    pos = {b for b, n in lits if not n}
    neg = {b for b, n in lits if n}
    extras = len(lits)

    def ok(req_pos, req_neg, allow_any_of=None, slack=2):
        need = len(req_pos) + len(req_neg) + (1 if allow_any_of else 0)
        if not req_pos.issubset(pos) or not req_neg.issubset(neg):
            return False
        if allow_any_of and not (allow_any_of & (pos | neg)):
            return False
        return extras <= need + slack

    hits = []
    # R1: attempt >= 3
    if ok({NAME["attempt>=3"]}, set()):
        hits.append(1)
    # R2: some gate fails AND verdict == accept
    if (NAME["verdict=accept"] in pos and (set(GATE_BITS) & neg)
            and extras <= 4):
        hits.append(2)
    # R3: cross-domain AND interface AND verdict == uncertain
    if ok({NAME["cross_domain_quantity_changed"], NAME["interface_node_touched"],
           NAME["verdict=uncertain"]}, set()):
        hits.append(3)
    # R4: verdict == reject AND confidence high AND prior failures >= 2
    if ok({NAME["verdict=reject"], NAME["reviewer_conf>=high"],
           NAME["prior_failures>=2"]}, set()):
        hits.append(4)
    # R5: propagation gate fails AND domain in {elec, ctrl}
    if (NAME["gate_propagation_pass"] in neg
            and ({NAME["domain=elec"], NAME["domain=ctrl"]} & pos
                 or {NAME["domain=mech"], NAME["domain=fw"]} <= neg)
            and extras <= 5):
        hits.append(5)
    return hits


# -------------------------------------------------------------- rule arm ----
def rule_arm(raw):
    """Hand-coded current rule (ARCH-030/040 as implemented today).

    ASSUMPTION (the source spec does not print the rule): escalate at the third
    attempt, or when any verification gate fails.  Reported on A1 only.
    """
    any_gate_fail = np.zeros(len(raw["attempt"]), dtype=bool)
    for g in G.GATES:
        any_gate_fail |= raw[g] == 0
    return ((raw["attempt"] == 3) | any_gate_fail).astype(int)
