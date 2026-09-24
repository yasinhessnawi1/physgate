"""R-TM-01 synthetic state generator.

Structured subtask state at the end of a control-loop attempt, booleanised to 21
bits, labelled by a hidden 5-term rule with interactions and negations, then 5%
label flip noise.  The learner never sees the rule.
"""
import numpy as np

# ---------------------------------------------------------------- marginals --
P_GATE_PASS = 0.85                       # each gate, independently
P_ATTEMPT = {1: 0.60, 2: 0.25, 3: 0.15}
P_VERDICT = {"accept": 0.70, "reject": 0.20, "uncertain": 0.10}
P_CONF = {"low": 0.25, "mid": 0.45, "high": 0.30}
P_DOMAIN = {"mech": 0.30, "elec": 0.30, "ctrl": 0.25, "fw": 0.15}
P_CROSS_DOMAIN = 0.20
P_INTERFACE = 0.25
P_PRIOR = {0: 0.60, 1: 0.25, 2: 0.15}    # 2 means "2+"
P_SPEC = {"low": 0.25, "mid": 0.45, "high": 0.30}

GATES = ["gate_unit_pass", "gate_magnitude_pass", "gate_power_pass",
         "gate_propagation_pass"]
VERDICTS = ["accept", "reject", "uncertain"]
DOMAINS = ["mech", "elec", "ctrl", "fw"]

BIT_NAMES = [
    "gate_unit_pass", "gate_magnitude_pass", "gate_power_pass",
    "gate_propagation_pass",
    "attempt>=2", "attempt>=3",
    "verdict=accept", "verdict=reject", "verdict=uncertain",
    "reviewer_conf>=mid", "reviewer_conf>=high",
    "domain=mech", "domain=elec", "domain=ctrl", "domain=fw",
    "cross_domain_quantity_changed", "interface_node_touched",
    "prior_failures>=1", "prior_failures>=2",
    "spec_coverage>=mid", "spec_coverage>=high",
]
N_BITS = len(BIT_NAMES)
assert N_BITS == 21

HIDDEN_RULE_TERMS = [
    "R1: attempt == 3",
    "R2: any gate fails AND reviewer_verdict == accept",
    "R3: cross_domain_quantity_changed AND interface_node_touched AND "
    "reviewer_verdict == uncertain",
    "R4: reviewer_verdict == reject AND reviewer_confidence == high AND "
    "prior_failures_module >= 2",
    "R5: NOT gate_propagation_pass AND domain in {elec, ctrl}",
]

LABEL_NOISE = 0.05


def _choice(rng, table, n):
    keys = list(table.keys())
    probs = np.array([table[k] for k in keys], dtype=float)
    probs = probs / probs.sum()
    idx = rng.choice(len(keys), size=n, p=probs)
    return np.array(keys, dtype=object)[idx]


def sample_raw(n, rng, attempts=(1, 2, 3), domains=tuple(DOMAINS)):
    """Sample raw (un-booleanised) state, restricting attempt/domain support."""
    att_table = {a: P_ATTEMPT[a] for a in attempts}
    dom_table = {d: P_DOMAIN[d] for d in domains}
    raw = {g: (rng.random(n) < P_GATE_PASS).astype(np.int8) for g in GATES}
    raw["attempt"] = _choice(rng, att_table, n).astype(int)
    raw["reviewer_verdict"] = _choice(rng, P_VERDICT, n)
    raw["reviewer_confidence"] = _choice(rng, P_CONF, n)
    raw["domain"] = _choice(rng, dom_table, n)
    raw["cross_domain_quantity_changed"] = (rng.random(n) < P_CROSS_DOMAIN).astype(np.int8)
    raw["interface_node_touched"] = (rng.random(n) < P_INTERFACE).astype(np.int8)
    raw["prior_failures_module"] = _choice(rng, P_PRIOR, n).astype(int)
    raw["spec_coverage"] = _choice(rng, P_SPEC, n)
    return raw


def hidden_rule(raw):
    """Clean label from the generator's hidden rule (no noise)."""
    any_gate_fail = np.zeros(len(raw["attempt"]), dtype=bool)
    for g in GATES:
        any_gate_fail |= raw[g] == 0
    verdict = raw["reviewer_verdict"]
    conf = raw["reviewer_confidence"]
    dom = raw["domain"]

    t1 = raw["attempt"] == 3
    t2 = any_gate_fail & (verdict == "accept")
    t3 = ((raw["cross_domain_quantity_changed"] == 1)
          & (raw["interface_node_touched"] == 1) & (verdict == "uncertain"))
    t4 = ((verdict == "reject") & (conf == "high")
          & (raw["prior_failures_module"] >= 2))
    t5 = (raw["gate_propagation_pass"] == 0) & np.isin(dom, ["elec", "ctrl"])
    terms = np.stack([t1, t2, t3, t4, t5])
    return terms.any(axis=0).astype(np.int8), terms


def booleanise(raw):
    n = len(raw["attempt"])
    X = np.zeros((n, N_BITS), dtype=np.uint32)
    for i, g in enumerate(GATES):
        X[:, i] = raw[g]
    X[:, 4] = (raw["attempt"] >= 2).astype(np.uint32)
    X[:, 5] = (raw["attempt"] >= 3).astype(np.uint32)
    for i, v in enumerate(VERDICTS):
        X[:, 6 + i] = (raw["reviewer_verdict"] == v).astype(np.uint32)
    X[:, 9] = np.isin(raw["reviewer_confidence"], ["mid", "high"]).astype(np.uint32)
    X[:, 10] = (raw["reviewer_confidence"] == "high").astype(np.uint32)
    for i, d in enumerate(DOMAINS):
        X[:, 11 + i] = (raw["domain"] == d).astype(np.uint32)
    X[:, 15] = raw["cross_domain_quantity_changed"]
    X[:, 16] = raw["interface_node_touched"]
    X[:, 17] = (raw["prior_failures_module"] >= 1).astype(np.uint32)
    X[:, 18] = (raw["prior_failures_module"] >= 2).astype(np.uint32)
    X[:, 19] = np.isin(raw["spec_coverage"], ["mid", "high"]).astype(np.uint32)
    X[:, 20] = (raw["spec_coverage"] == "high").astype(np.uint32)
    return X


def make_split(n, rng, attempts=(1, 2, 3), domains=tuple(DOMAINS), noise=LABEL_NOISE):
    raw = sample_raw(n, rng, attempts=attempts, domains=domains)
    y_clean, terms = hidden_rule(raw)
    flip = rng.random(n) < noise
    y = np.where(flip, 1 - y_clean, y_clean).astype(np.uint32)
    return booleanise(raw), y, y_clean.astype(np.uint32), raw, terms


def _drop_fw(split):
    X, y, yc, raw, terms = split
    keep = raw["domain"] != "fw"
    raw2 = {k: v[keep] for k, v in raw.items()}
    return X[keep], y[keep], yc[keep], raw2, terms[:, keep]


def build_all(seed):
    """All splits for one seed.

    Main arm   : train on attempts {1,2}, all domains.
    OOD-B arm  : train on attempts {1,2}, domains without fw (retrain).
    """
    rng = np.random.default_rng(seed)
    d = {}
    d["train"] = make_split(8000, rng, attempts=(1, 2))
    d["test_id"] = make_split(2000, rng, attempts=(1, 2))
    d["ood_a"] = make_split(1000, rng, attempts=(3,))
    # S2: "domain == fw only, with fw removed from train (retrain for this arm)"
    # -> the no-fw arm is the SAME train/Test-ID draws with fw rows dropped.
    d["train_nofw"] = _drop_fw(d["train"])
    d["test_id_nofw"] = _drop_fw(d["test_id"])
    d["ood_b"] = make_split(1000, rng, attempts=(1, 2), domains=("fw",))
    return d
