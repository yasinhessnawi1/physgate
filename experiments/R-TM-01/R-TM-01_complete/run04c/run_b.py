"""R-TM-01b run: 4 arms x 5 seeds, main model + no-fw retrain, mixed stream.

Criteria frozen in runs/run03b/R-TM-01b.md before this script was first executed.
"""
import json, os, sys, time
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

import generator_b as G
import experiment as E

SEEDS = [0, 1, 2, 3, 4]
CAL_N = 500
ROUTE_THRESHOLD = 0.8          # ARCH-131: below this, route to ARCH-130
MIX = (("test_id", 0.70), ("ood_a", 0.15), ("ood_b", 0.15))
MIX_N = 2000

NAME = E.NAME
GATE_BITS = [NAME[g] for g in G.GATES]

# --------------------------------------------------------- A5 term recovery --
# Each learnable term as (required literals, label).  A literal is (bit, negated).
TERM_SHAPES = {
    "R2a": [[(g, True), (NAME["verdict=reject"], True)] for g in GATE_BITS],
    "R2b": [[(g, False) for g in GATE_BITS] + [(NAME["verdict=reject"], False)]],
    "R3": [[(NAME["cross_domain_quantity_changed"], False),
            (NAME["interface_node_touched"], False),
            (NAME["verdict=uncertain"], False)]],
    "R4": [[(NAME["verdict=reject"], False), (NAME["reviewer_conf>=high"], False),
            (NAME["prior_failures>=2"], False)]],
    "R5": [[(NAME["gate_propagation_pass"], True), (NAME["domain=elec"], False),
            (NAME["spec_coverage>=mid"], True)],
           [(NAME["gate_propagation_pass"], True), (NAME["domain=ctrl"], False),
            (NAME["spec_coverage>=mid"], True)],
           [(NAME["gate_propagation_pass"], True), (NAME["domain=mech"], True),
            (NAME["domain=fw"], True), (NAME["spec_coverage>=mid"], True)]],
}
PRECISION_MIN, COVERAGE_MIN, EXTRA_MAX = 0.85, 0.25, 1


def term_recovery(clauses, Xtr, terms_tr):
    """Which hidden-rule terms are recovered, per S4's definition."""
    out_fire = E.clause_outputs(clauses, Xtr)
    support = out_fire.sum(axis=0)
    found = {}
    detail = {}
    for label, shapes in TERM_SHAPES.items():
        term_idx = {"R2a": 1, "R2b": 1, "R3": 2, "R4": 3, "R5": 4}[label]
        term_pos = terms_tr[term_idx]
        best = None
        for j, lits in enumerate(clauses):
            lset = set(lits)
            if not any(set(sh).issubset(lset) and len(lits) - len(sh) <= EXTRA_MAX
                       for sh in shapes):
                continue
            fires = out_fire[:, j]
            if support[j] == 0:
                continue
            prec = float((fires & term_pos).sum() / support[j])
            cov = float((fires & term_pos).sum() / max(term_pos.sum(), 1))
            score = (prec >= PRECISION_MIN and cov >= COVERAGE_MIN, prec * cov)
            cand = {"clause": int(j), "precision": prec, "coverage": cov,
                    "literals": E.clause_str(lits), "qualifies": bool(score[0])}
            if best is None or (cand["qualifies"], prec * cov) > \
                    (best["qualifies"], best["precision"] * best["coverage"]):
                best = cand
        detail[label] = best
        found[label] = bool(best and best["qualifies"])
    recovered = []
    if found["R2a"] and found["R2b"]:
        recovered.append("R2")
    for t in ["R3", "R4", "R5"]:
        if found[t]:
            recovered.append(t)
    return {"recovered": recovered, "n_recovered": len(recovered),
            "best_clause_per_shape": detail}


def legibility(clauses, Xid, p_id):
    """How many distinct clause bodies cover 80 % of escalate decisions."""
    esc = p_id >= 0.5
    if esc.sum() == 0:
        return None
    out = E.clause_outputs(clauses, Xid[esc])
    seen, cols = {}, []
    for i, l in enumerate(clauses):
        k = tuple(sorted(l))
        if k not in seen:
            seen[k] = i
            cols.append(i)
    remaining = np.ones(esc.sum(), dtype=bool)
    target = 0.8 * esc.sum()
    covered, used = 0, 0
    while covered < target and cols:
        gains = [(out[:, c] & remaining).sum() for c in cols]
        b = int(np.argmax(gains))
        if gains[b] == 0:
            break
        remaining &= ~out[:, cols[b]]
        covered = esc.sum() - remaining.sum()
        cols.pop(b)
        used += 1
    return {"clauses_to_cover_80pct": used,
            "fraction_covered": float(covered / esc.sum())}


def eval_probs(probs, y, acc_argmax=None):
    pred = (probs >= 0.5).astype(int)
    base, kept, gain = E.selective_gain(probs, y)
    conf = np.maximum(probs, 1 - probs)
    out = {"acc": float((pred == y).mean()), "ece": E.ece(probs, y),
           "ece_prob_bins": E.ece_prob_bins(probs, y),
           "mean_conf": E.mean_confidence(probs),
           "route_rate_at_0.8": float((conf < ROUTE_THRESHOLD).mean()),
           "sel_base_acc": base, "sel_kept_acc": kept, "sel_gain": gain}
    if acc_argmax is not None:
        out["acc_argmax"] = float(acc_argmax)
    return out


def error_reduction(probs, y, drop_frac=0.20):
    conf = np.maximum(probs, 1 - probs)
    err = ((probs >= 0.5).astype(int) != y).astype(float)
    keep = np.argsort(conf, kind="stable")[int(round(drop_frac * len(y))):]
    e0, e1 = float(err.mean()), float(err[keep].mean())
    return {"error_full": e0, "error_at_80pct": e1,
            "reduction": float(1 - e1 / e0) if e0 > 0 else 0.0}


def mixed_indices(d, rng):
    out = []
    for key, frac in MIX:
        n = len(d[key][1])
        k = min(int(round(frac * MIX_N)), n)
        out.append((key, rng.choice(n, size=k, replace=False)))
    return out


def run_seed(seed, hp, outdir):
    d = G.build_all(seed)
    Xtr, ytr, ytrc, terms_tr = d["train"][0], d["train"][1], d["train"][2], d["train"][4]
    Xid, yid = d["test_id"][0], d["test_id"][1]
    Xa, ya = d["ood_a"][0], d["ood_a"][1]
    Xtr2, ytr2 = d["train_nofw"][0], d["train_nofw"][1]
    Xid2, yid2 = d["test_id_nofw"][0], d["test_id_nofw"][1]
    Xb, yb = d["ood_b"][0], d["ood_b"][1]

    T = hp["T"]
    tm_seed = 1000 + seed
    res = {"seed": seed, "hp": hp, "tm_seed": tm_seed}

    tm = E.fit_tm(Xtr, ytr, hp["clauses"], T, hp["s"], hp["epochs"], tm_seed)
    pr_id, cs_id, p_id = E.tm_predict(tm, Xid, T)
    pr_a, cs_a, p_a = E.tm_predict(tm, Xa, T)
    _, cs_tr, _ = E.tm_predict(tm, Xtr, T)

    z = lambda cs: np.clip(cs[:, 1], -T, T) / T
    temp = E.fit_temperature(z(cs_tr)[:CAL_N], ytr[:CAL_N])
    pt_id, pt_a = (E.apply_temperature(temp, z(cs_id)),
                   E.apply_temperature(temp, z(cs_a)))

    res["TM"] = {"test_id": eval_probs(p_id, yid, (pr_id == yid).mean()),
                 "ood_a": eval_probs(p_a, ya, (pr_a == ya).mean())}
    res["TM_temp"] = {"test_id": eval_probs(pt_id, yid),
                      "ood_a": eval_probs(pt_a, ya), "temperature": temp}

    tm2 = E.fit_tm(Xtr2, ytr2, hp["clauses"], T, hp["s"], hp["epochs"], tm_seed)
    pr_id2, cs_id2, p_id2 = E.tm_predict(tm2, Xid2, T)
    pr_b, cs_b, p_b = E.tm_predict(tm2, Xb, T)
    _, cs_tr2, _ = E.tm_predict(tm2, Xtr2, T)
    temp2 = E.fit_temperature(z(cs_tr2)[:CAL_N], ytr2[:CAL_N])
    res["TM"]["test_id_nofw"] = eval_probs(p_id2, yid2, (pr_id2 == yid2).mean())
    res["TM"]["ood_b"] = eval_probs(p_b, yb, (pr_b == yb).mean())
    res["TM_temp"]["test_id_nofw"] = eval_probs(E.apply_temperature(temp2, z(cs_id2)), yid2)
    res["TM_temp"]["ood_b"] = eval_probs(E.apply_temperature(temp2, z(cs_b)), yb)

    # ---- mixed stream (A4) --------------------------------------------------
    rng = np.random.default_rng(seed + 5000)
    idx = mixed_indices(d, rng)
    tm_probs_by_split = {"test_id": p_id, "ood_a": p_a, "ood_b": p_b}
    pm = np.concatenate([tm_probs_by_split[k][i] for k, i in idx])
    ym = np.concatenate([d[k][1][i] for k, i in idx])
    res["TM"]["mixed"] = {**eval_probs(pm, ym), **error_reduction(pm, ym)}

    # ---- LR / GBT -----------------------------------------------------------
    probs_store = {}
    for name, mk in [("LR", lambda: LogisticRegression(max_iter=2000)),
                     ("GBT", lambda: HistGradientBoostingClassifier(random_state=seed))]:
        m = mk().fit(Xtr, ytr)
        m2 = mk().fit(Xtr2, ytr2)
        pid = m.predict_proba(Xid)[:, 1]
        probs_store[name] = pid
        by = {"test_id": pid, "ood_a": m.predict_proba(Xa)[:, 1],
              "ood_b": m2.predict_proba(Xb)[:, 1]}
        pmx = np.concatenate([by[k][i] for k, i in idx])
        res[name] = {
            "test_id": eval_probs(pid, yid),
            "ood_a": eval_probs(by["ood_a"], ya),
            "test_id_nofw": eval_probs(m2.predict_proba(Xid2)[:, 1], yid2),
            "ood_b": eval_probs(by["ood_b"], yb),
            "mixed": {**eval_probs(pmx, ym), **error_reduction(pmx, ym)}}

    res["RULE"] = {
        "test_id": {"acc": float((E.rule_arm(d["test_id"][3]) == yid).mean())},
        "ood_a": {"acc": float((E.rule_arm(d["ood_a"][3]) == ya).mean())}}

    lr = LogisticRegression(max_iter=2000).fit(Xtr, ytr)
    gbt = HistGradientBoostingClassifier(random_state=seed).fit(Xtr, ytr)
    yidc = d["test_id"][2]
    res["clean_label_recovery"] = {
        "TM": float((pr_id == yidc).mean()),
        "LR": float((lr.predict(Xid) == yidc).mean()),
        "GBT": float((gbt.predict(Xid) == yidc).mean()),
        "RULE": float((E.rule_arm(d["test_id"][3]) == yidc).mean())}

    # ---- A5 -----------------------------------------------------------------
    clauses = E.decode_clauses(tm, the_class=1, polarity=0)
    res["a5"] = term_recovery(clauses, Xtr, terms_tr)
    res["a5"]["legibility"] = legibility(clauses, Xid, p_id)
    res["a5"]["n_distinct_bodies"] = len({tuple(sorted(c)) for c in clauses})

    np.savez_compressed(os.path.join(outdir, f"preds_seed{seed}.npz"),
                        p_tm_id=p_id, p_tm_temp_id=pt_id, y_id=yid,
                        p_tm_a=p_a, y_a=ya, p_tm_b=p_b, y_b=yb,
                        p_tm_id_nofw=p_id2, y_id_nofw=yid2,
                        p_lr_id=probs_store["LR"], p_gbt_id=probs_store["GBT"])
    return res


def main(outdir, hp):
    os.makedirs(outdir, exist_ok=True)
    all_res = []
    for s in SEEDS:
        t0 = time.time()
        r = run_seed(s, hp, outdir)
        r["seconds"] = time.time() - t0
        json.dump(r, open(os.path.join(outdir, f"metrics_seed{s}.json"), "w"), indent=2)
        all_res.append(r)
        print(f"seed {s} {r['seconds']:.1f}s acc {r['TM']['test_id']['acc_argmax']:.4f} "
              f"ece {r['TM']['test_id']['ece']:.3f} "
              f"mixedred {r['TM']['mixed']['reduction']:.3f} "
              f"A5 {r['a5']['recovered']}", flush=True)
    json.dump(all_res, open(os.path.join(outdir, "metrics_all.json"), "w"), indent=2)


if __name__ == "__main__":
    main(sys.argv[1], json.load(open(sys.argv[2]))["best"])
