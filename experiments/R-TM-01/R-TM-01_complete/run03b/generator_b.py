"""R-TM-01b generator: same state schema, repaired difficulty.

Two changes from R-TM-01, both aimed at the feasibility failures the first run
exposed:

  * label noise 5 % -> 1 %, so the accuracy ceiling rises from 0.950 to 0.990
    and an accuracy margin between arms can exist at all;
  * the dominant near-linear term is replaced by a parity term, so a linear
    baseline cannot recover the rule by memorising marginals.

Everything else - the 21 bits, the split structure, the OOD design - is
unchanged from R-TM-01, so the two runs stay comparable.
"""
import numpy as np

from generator import (GATES, VERDICTS, DOMAINS, BIT_NAMES, N_BITS,
                       booleanise, _choice)

# ---------------------------------------------------------------- marginals --
# Gate-failure and reject rates were set on pilot seeds 900-902 using LR and GBT
# only (see runs/run03b/generator_tuning.json), to leave a real accuracy margin
# between a linear baseline and the ceiling.  The TM was never run on pilot data.
# The propagation gate is the flaky one; it is also the gate R5 keys on, which
# keeps that term's support large enough to be learnable.
P_GATE_PASS = {"gate_unit_pass": 0.90, "gate_magnitude_pass": 0.90,
               "gate_power_pass": 0.90, "gate_propagation_pass": 0.83}
P_ATTEMPT = {1: 0.60, 2: 0.25, 3: 0.15}
P_VERDICT = {"accept": 0.60, "reject": 0.25, "uncertain": 0.15}
P_CONF = {"low": 0.25, "mid": 0.40, "high": 0.35}
P_DOMAIN = {"mech": 0.30, "elec": 0.30, "ctrl": 0.25, "fw": 0.15}
P_CROSS_DOMAIN = 0.25
P_INTERFACE = 0.30
P_PRIOR = {0: 0.55, 1: 0.25, 2: 0.20}
P_SPEC = {"low": 0.30, "mid": 0.40, "high": 0.30}

LABEL_NOISE = 0.01

HIDDEN_RULE_TERMS = [
    "R1: attempt == 3",
    "R2: (any gate fails) XOR (reviewer_verdict == reject) - the automated "
    "checks and the reviewer disagree in either direction",
    "R3: cross_domain_quantity_changed AND interface_node_touched AND "
    "reviewer_verdict == uncertain",
    "R4: reviewer_verdict == reject AND reviewer_confidence == high AND "
    "prior_failures_module >= 2",
    "R5: NOT gate_propagation_pass AND domain in {elec, ctrl} AND "
    "spec_coverage == low",
]


def sample_raw(n, rng, attempts=(1, 2, 3), domains=tuple(DOMAINS)):
    att_table = {a: P_ATTEMPT[a] for a in attempts}
    dom_table = {d: P_DOMAIN[d] for d in domains}
    raw = {g: (rng.random(n) < P_GATE_PASS[g]).astype(np.int8) for g in GATES}
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
    any_gate_fail = np.zeros(len(raw["attempt"]), dtype=bool)
    for g in GATES:
        any_gate_fail |= raw[g] == 0
    verdict = raw["reviewer_verdict"]
    conf = raw["reviewer_confidence"]

    t1 = raw["attempt"] == 3
    t2 = any_gate_fail ^ (verdict == "reject")              # parity term
    t3 = ((raw["cross_domain_quantity_changed"] == 1)
          & (raw["interface_node_touched"] == 1) & (verdict == "uncertain"))
    t4 = ((verdict == "reject") & (conf == "high")
          & (raw["prior_failures_module"] >= 2))
    t5 = ((raw["gate_propagation_pass"] == 0)
          & np.isin(raw["domain"], ["elec", "ctrl"])
          & (raw["spec_coverage"] == "low"))
    terms = np.stack([t1, t2, t3, t4, t5])
    return terms.any(axis=0).astype(np.int8), terms


def make_split(n, rng, attempts=(1, 2, 3), domains=tuple(DOMAINS),
               noise=LABEL_NOISE):
    raw = sample_raw(n, rng, attempts=attempts, domains=domains)
    y_clean, terms = hidden_rule(raw)
    flip = rng.random(n) < noise
    y = np.where(flip, 1 - y_clean, y_clean).astype(np.uint32)
    return booleanise(raw), y, y_clean.astype(np.uint32), raw, terms


def _drop_fw(split):
    X, y, yc, raw, terms = split
    keep = raw["domain"] != "fw"
    return X[keep], y[keep], yc[keep], {k: v[keep] for k, v in raw.items()}, \
        terms[:, keep]


def build_all(seed):
    rng = np.random.default_rng(seed)
    d = {}
    d["train"] = make_split(8000, rng, attempts=(1, 2))
    d["test_id"] = make_split(2000, rng, attempts=(1, 2))
    d["ood_a"] = make_split(1000, rng, attempts=(3,))
    d["train_nofw"] = _drop_fw(d["train"])
    d["test_id_nofw"] = _drop_fw(d["test_id"])
    d["ood_b"] = make_split(1000, rng, attempts=(1, 2), domains=("fw",))
    return d
