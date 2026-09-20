"""Post-hoc diagnostics. Nothing here changes the pre-registered S4 verdict.

1. Bayes ceiling on Test-ID (the noiseless rule's own accuracy against noisy y).
2. Feasibility of A1's "5 points above LR" given that ceiling.
3. Out-of-spec TM capacity check (more clauses / epochs) - is the TM's gap a
   tuning artefact?
4. Weighted-clause TM read of A5 (real clause weights instead of a proxy).
5. Lenient A5 matching (a term counted when a weakened form of it appears).
"""
import json, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from tmu.models.classification.vanilla_classifier import TMClassifier

import generator as G
import experiment as E

SEEDS = [0, 1, 2, 3, 4]


def lenient_match(lits):
    """Weaker than E.match_term: a term counts if its most distinctive
    literals are present, even when a conjunct is missing."""
    pos = {b for b, n in lits if not n}
    neg = {b for b, n in lits if n}
    N = E.NAME
    hits = []
    if N["attempt>=3"] in pos:
        hits.append(1)
    if N["verdict=accept"] in pos and (set(E.GATE_BITS) & neg):
        hits.append(2)
    if len({N["cross_domain_quantity_changed"], N["interface_node_touched"],
            N["verdict=uncertain"]} & pos) >= 2:
        hits.append(3)
    if len({N["verdict=reject"], N["reviewer_conf>=high"],
            N["prior_failures>=2"]} & pos) >= 2:
        hits.append(4)
    if N["gate_propagation_pass"] in neg:
        hits.append(5)
    return hits


def main(outdir):
    out = {}

    # ---- 1/2. Bayes ceiling and A1 feasibility -----------------------------
    ceil, lr_accs, tm_caps = [], [], []
    for s in SEEDS:
        d = G.build_all(s)
        Xid, yid, yclean = d["test_id"][0], d["test_id"][1], d["test_id"][2]
        ceil.append(float((yclean == yid).mean()))
        lr = LogisticRegression(max_iter=2000).fit(d["train"][0], d["train"][1])
        lr_accs.append(float((lr.predict(Xid) == yid).mean()))
    out["bayes_ceiling_test_id"] = [float(np.mean(ceil)), float(np.std(ceil))]
    out["lr_acc"] = [float(np.mean(lr_accs)), float(np.std(lr_accs))]
    out["a1_required_tm_acc"] = float(np.mean(lr_accs)) + 0.05
    out["a1_feasible"] = out["a1_required_tm_acc"] <= out["bayes_ceiling_test_id"][0]

    # ---- 3. capacity check (OUT OF SPEC: clauses/epochs beyond S3) ---------
    caps = {}
    for clauses, epochs, T, s_ in [(500, 60, 40, 5.0), (1000, 150, 80, 5.0),
                                   (2000, 300, 160, 5.0)]:
        accs = []
        for seed in SEEDS[:3]:
            d = G.build_all(seed)
            tm = E.fit_tm(d["train"][0], d["train"][1], clauses, T, s_, epochs,
                          1000 + seed)
            pred, _, _ = E.tm_predict(tm, d["test_id"][0], T)
            accs.append(float((pred == d["test_id"][1]).mean()))
        caps[f"c{clauses}_T{T}_s{s_}_e{epochs}"] = [float(np.mean(accs)),
                                                    float(np.std(accs))]
        print("capacity", clauses, epochs, np.mean(accs), flush=True)
    out["tm_capacity_check_3seeds"] = caps

    # ---- 4/5. A5 re-read ---------------------------------------------------
    strict_w, lenient_w, strict_u, lenient_u = [], [], [], []
    weighted_top = None
    for seed in SEEDS:
        d = G.build_all(seed)
        Xtr, ytr = d["train"][0], d["train"][1]
        Xid, yid = d["test_id"][0], d["test_id"][1]

        # unweighted TM, distinct clause bodies, importance ranking
        tm = E.fit_tm(Xtr, ytr, 500, 40, 5.0, 60, 1000 + seed)
        cl = E.decode_clauses(tm)
        o = E.clause_outputs(cl, Xid)
        pos = yid == 1
        fp = o[pos].mean(0)
        pr = o[pos].sum(0) / np.maximum(o.sum(0), 1)
        imp = fp * pr
        seen = {}
        for i, l in enumerate(cl):
            seen.setdefault(tuple(sorted(l)), []).append(i)
        rows = sorted(((imp[v[0]], v[0]) for v in seen.values()), reverse=True)
        top = [i for _, i in rows[:10]]
        strict_u.append(len({t for i in top for t in E.match_term(cl[i])}))
        lenient_u.append(len({t for i in top for t in lenient_match(cl[i])}))

        # weighted-clause TM, ranked by real clause weight
        tmw = TMClassifier(number_of_clauses=500, T=40, s=5.0, platform="CPU",
                           weighted_clauses=True, seed=1000 + seed)
        tmw.fit(Xtr, ytr, epochs=60)
        clw = E.decode_clauses(tmw)
        w = np.array([tmw.get_weight(1, 0, c) for c in range(len(clw))])
        seenw = {}
        for i, l in enumerate(clw):
            seenw.setdefault(tuple(sorted(l)), []).append(i)
        roww = sorted(((w[v[0]], v[0]) for v in seenw.values()), reverse=True)
        topw = [i for _, i in roww[:10]]
        strict_w.append(len({t for i in topw for t in E.match_term(clw[i])}))
        lenient_w.append(len({t for i in topw for t in lenient_match(clw[i])}))
        if seed == 0:
            weighted_top = [{"weight": float(w[i]),
                             "literals": E.clause_str(clw[i]),
                             "strict": E.match_term(clw[i]),
                             "lenient": lenient_match(clw[i])} for i in topw]

    out["a5_unweighted_strict"] = strict_u
    out["a5_unweighted_lenient"] = lenient_u
    out["a5_weighted_strict"] = strict_w
    out["a5_weighted_lenient"] = lenient_w
    out["a5_weighted_top10_seed0"] = weighted_top

    json.dump(out, open(f"{outdir}/diagnostics.json", "w"), indent=2)
    print(json.dumps({k: v for k, v in out.items()
                      if k != "a5_weighted_top10_seed0"}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
