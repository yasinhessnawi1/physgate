"""Post-hoc diagnostics for R-TM-01b. Nothing here changes the frozen verdict.

1. The T frontier: how accuracy, calibration and OOD humility trade off against
   the one hyperparameter the sweep chose on accuracy alone.
2. Marginal term support: how many rows each hidden-rule term is the ONLY reason
   to escalate - i.e. how much a learner is rewarded for recovering it.
3. A5 matcher sanity: are the term shapes absent from the clause bank, or merely
   outside the one-extra-literal budget the criterion allows?
"""
import json, sys
import numpy as np

import generator_b as G
import experiment as E
import run_b as R

SEEDS = [0, 1, 2]
T_GRID = [10, 20, 40, 80, 160]


def conf(p):
    return float(np.mean(np.maximum(p, 1 - p)))


def main(outdir):
    out = {}

    # ---- 1. the T frontier -------------------------------------------------
    frontier = {}
    for T in T_GRID:
        acc, ece, da, db, red = [], [], [], [], []
        for s in SEEDS:
            d = G.build_all(s)
            tm = E.fit_tm(d["train"][0], d["train"][1], 500, T, 5.0, 60, 1000 + s)
            pr, _, p_id = E.tm_predict(tm, d["test_id"][0], T)
            _, _, p_a = E.tm_predict(tm, d["ood_a"][0], T)
            acc.append(float((pr == d["test_id"][1]).mean()))
            ece.append(E.ece(p_id, d["test_id"][1]))
            da.append(conf(p_id) - conf(p_a))

            tm2 = E.fit_tm(d["train_nofw"][0], d["train_nofw"][1], 500, T, 5.0, 60,
                           1000 + s)
            _, _, p_id2 = E.tm_predict(tm2, d["test_id_nofw"][0], T)
            _, _, p_b = E.tm_predict(tm2, d["ood_b"][0], T)
            db.append(conf(p_id2) - conf(p_b))

            rng = np.random.default_rng(s + 5000)
            idx = R.mixed_indices(d, rng)
            by = {"test_id": p_id, "ood_a": p_a, "ood_b": p_b}
            pm = np.concatenate([by[k][i] for k, i in idx])
            ym = np.concatenate([d[k][1][i] for k, i in idx])
            red.append(R.error_reduction(pm, ym)["reduction"])
        frontier[f"T={T}"] = {"acc": float(np.mean(acc)), "ece": float(np.mean(ece)),
                              "drop_ood_a": float(np.mean(da)),
                              "drop_ood_b": float(np.mean(db)),
                              "mixed_reduction": float(np.mean(red))}
        print("T", T, frontier[f"T={T}"], flush=True)
    out["t_frontier_3seeds"] = frontier

    # ---- 2. marginal term support -----------------------------------------
    marg, tot = [], []
    for s in SEEDS:
        d = G.build_all(s)
        terms = d["train"][4]                      # (5, n) booleans
        tot.append(terms.sum(axis=1))
        only = []
        for i in range(5):
            others = np.delete(terms, i, axis=0).any(axis=0)
            only.append(int((terms[i] & ~others).sum()))
        marg.append(only)
    out["term_support_total"] = {f"R{i+1}": float(np.mean([t[i] for t in tot]))
                                 for i in range(5)}
    out["term_support_marginal_only_reason"] = {
        f"R{i+1}": float(np.mean([m[i] for m in marg])) for i in range(5)}

    # ---- 3. A5 matcher sanity ---------------------------------------------
    sanity = {}
    for extra in [1, 2, 3, 6]:
        hits = {k: 0 for k in R.TERM_SHAPES}
        for s in SEEDS:
            d = G.build_all(s)
            tm = E.fit_tm(d["train"][0], d["train"][1], 500, 20, 5.0, 60, 1000 + s)
            cl = E.decode_clauses(tm, the_class=1, polarity=0)
            for label, shapes in R.TERM_SHAPES.items():
                for lits in cl:
                    ls = set(lits)
                    if any(set(sh).issubset(ls) and len(lits) - len(sh) <= extra
                           for sh in shapes):
                        hits[label] += 1
                        break
        sanity[f"extra<={extra}"] = {k: f"{v}/{len(SEEDS)} seeds" for k, v in hits.items()}
        print("matcher", extra, sanity[f"extra<={extra}"], flush=True)
    out["a5_matcher_sanity_shape_present_in_bank"] = sanity

    json.dump(out, open(f"{outdir}/diagnostics.json", "w"), indent=2)
    print(json.dumps(out, indent=2)[:1500])


if __name__ == "__main__":
    main(sys.argv[1])
