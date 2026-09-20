"""R-TM-01 main run: 4 arms x 5 seeds, main model + no-fw retrain.

Corrections applied after the code audit (none touch S4's thresholds):
  * clause decoding restricted to the positive-polarity bank (tmu splits the
    clause budget in two; indices past n/2 are the against-the-class clauses);
  * clause ranking computed on TRAIN with the noiseless rule label, on distinct
    clause bodies (tmu clause banks are highly redundant);
  * A1 accuracy read off the TM's own argmax decision, not the 0.5 threshold on
    the class-sum probability;
  * one-parameter temperature scaling reported as the pre-registered variant,
    two-parameter Platt kept beside it;
  * the no-fw arm is the train/Test-ID draws with fw rows removed, per S2.
"""
import json, os, sys, time
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

import generator as G
import experiment as E

SEEDS = [0, 1, 2, 3, 4]
CAL_N = 500


def eval_probs(probs, y, acc_argmax=None):
    pred = (probs >= 0.5).astype(int)
    base, kept, gain = E.selective_gain(probs, y)
    out = {"acc": float((pred == y).mean()),
           "ece": E.ece(probs, y),
           "ece_prob_bins": E.ece_prob_bins(probs, y),
           "mean_conf": E.mean_confidence(probs),
           "sel_base_acc": base, "sel_kept_acc": kept, "sel_gain": gain}
    if acc_argmax is not None:
        out["acc_argmax"] = float(acc_argmax)
    return out


def clause_report(tm, Xtr, ytr_clean, n_top=10):
    """Top distinct positive-polarity clauses, ranked on TRAIN."""
    clauses = E.decode_clauses(tm, the_class=1, polarity=0)
    out = E.clause_outputs(clauses, Xtr)
    pos = ytr_clean == 1
    fire = out[pos].mean(axis=0)
    prec = out[pos].sum(axis=0) / np.maximum(out.sum(axis=0), 1)
    imp = fire * prec
    distinct = {}
    for i, l in enumerate(clauses):
        distinct.setdefault(tuple(sorted(l)), []).append(i)
    rows = sorted(((imp[v[0]], v[0], len(v)) for v in distinct.values()),
                  reverse=True)[:n_top]
    top = []
    for _, i, mult in rows:
        lits = clauses[i]
        top.append({"clause": int(i), "copies_in_bank": int(mult),
                    "n_literals": len(lits),
                    "fire_rate_on_escalate": float(fire[i]),
                    "precision": float(prec[i]), "importance": float(imp[i]),
                    "matches_terms": E.match_term(lits),
                    "literals": E.clause_str(lits)})
    covered = sorted({t for c in top for t in c["matches_terms"]})
    return {"top10": top, "terms_in_top10": covered,
            "n_terms_in_top10": len(covered),
            "n_distinct_bodies": len(distinct),
            "n_positive_clauses": len(clauses)}


def run_seed(seed, hp, outdir):
    d = G.build_all(seed)
    Xtr, ytr, ytrc = d["train"][0], d["train"][1], d["train"][2]
    Xid, yid = d["test_id"][0], d["test_id"][1]
    Xa, ya = d["ood_a"][0], d["ood_a"][1]
    Xtr2, ytr2 = d["train_nofw"][0], d["train_nofw"][1]
    Xid2, yid2 = d["test_id_nofw"][0], d["test_id_nofw"][1]
    Xb, yb = d["ood_b"][0], d["ood_b"][1]

    T = hp["T"]
    tm_seed = 1000 + seed          # tmu 0.8.3 hangs on an internal seed of 0
    res = {"seed": seed, "hp": hp, "tm_seed": tm_seed,
           "n_train_nofw": int(len(ytr2)), "n_test_id_nofw": int(len(yid2))}

    # ---------------------------------------------------------------- TM ----
    tm = E.fit_tm(Xtr, ytr, hp["clauses"], T, hp["s"], hp["epochs"], tm_seed)
    pr_id, cs_id, p_id = E.tm_predict(tm, Xid, T)
    pr_a, _, p_a = E.tm_predict(tm, Xa, T)
    _, cs_tr, _ = E.tm_predict(tm, Xtr, T)

    z = lambda cs: np.clip(cs[:, 1], -T, T) / T
    temp = E.fit_temperature(z(cs_tr)[:CAL_N], ytr[:CAL_N])       # 1 parameter
    plat = E.fit_platt(z(cs_tr)[:CAL_N], ytr[:CAL_N])             # 2 parameters
    zt_id, zt_a = z(cs_id), z(E.tm_predict(tm, Xa, T)[1])
    pt_id, pt_a = (E.apply_temperature(temp, zt_id),
                   E.apply_temperature(temp, zt_a))
    pp_id = E.apply_platt(plat, zt_id)

    # sanity variant: temperature fitted on 500 FRESH samples (not in train)
    rngc = np.random.default_rng(seed + 10_000)
    Xc, yc = G.make_split(CAL_N, rngc, attempts=(1, 2))[:2]
    temp_f = E.fit_temperature(z(E.tm_predict(tm, Xc, T)[1]), yc)
    pf_id = E.apply_temperature(temp_f, zt_id)

    res["TM"] = {"test_id": eval_probs(p_id, yid, (pr_id == yid).mean()),
                 "ood_a": eval_probs(p_a, ya, (pr_a == ya).mean())}
    res["TM_temp"] = {"test_id": eval_probs(pt_id, yid),
                      "ood_a": eval_probs(pt_a, ya), "temperature": temp}
    res["TM_platt"] = {"test_id": eval_probs(pp_id, yid)}
    res["TM_temp_fresh_cal"] = {"test_id": eval_probs(pf_id, yid),
                                "temperature": temp_f}

    # ---- no-fw retrain (OOD-B arm) ----
    tm2 = E.fit_tm(Xtr2, ytr2, hp["clauses"], T, hp["s"], hp["epochs"], tm_seed)
    pr_id2, cs_id2, p_id2 = E.tm_predict(tm2, Xid2, T)
    pr_b, cs_b, p_b = E.tm_predict(tm2, Xb, T)
    _, cs_tr2, _ = E.tm_predict(tm2, Xtr2, T)
    temp2 = E.fit_temperature(z(cs_tr2)[:CAL_N], ytr2[:CAL_N])
    res["TM"]["test_id_nofw"] = eval_probs(p_id2, yid2, (pr_id2 == yid2).mean())
    res["TM"]["ood_b"] = eval_probs(p_b, yb, (pr_b == yb).mean())
    res["TM_temp"]["test_id_nofw"] = eval_probs(
        E.apply_temperature(temp2, z(cs_id2)), yid2)
    res["TM_temp"]["ood_b"] = eval_probs(
        E.apply_temperature(temp2, z(cs_b)), yb)

    # -------------------------------------------------------- LR and GBT ----
    probs_store = {}
    for name, mk in [("LR", lambda: LogisticRegression(max_iter=2000)),
                     ("GBT", lambda: HistGradientBoostingClassifier(
                         random_state=seed))]:
        m = mk(); m.fit(Xtr, ytr)
        m2 = mk(); m2.fit(Xtr2, ytr2)
        pid = m.predict_proba(Xid)[:, 1]
        probs_store[name] = pid
        res[name] = {
            "test_id": eval_probs(pid, yid),
            "ood_a": eval_probs(m.predict_proba(Xa)[:, 1], ya),
            "test_id_nofw": eval_probs(m2.predict_proba(Xid2)[:, 1], yid2),
            "ood_b": eval_probs(m2.predict_proba(Xb)[:, 1], yb)}

    # -------------------------------------------------------------- RULE ----
    res["RULE"] = {
        "test_id": {"acc": float((E.rule_arm(d["test_id"][3]) == yid).mean())},
        "ood_a": {"acc": float((E.rule_arm(d["ood_a"][3]) == ya).mean())}}

    # ---------------------------------------- rule recovery (clean labels) ---
    lr = LogisticRegression(max_iter=2000).fit(Xtr, ytr)
    gbt = HistGradientBoostingClassifier(random_state=seed).fit(Xtr, ytr)
    yidc = d["test_id"][2]
    res["clean_label_recovery"] = {
        "TM": float((pr_id == yidc).mean()),
        "LR": float((lr.predict(Xid) == yidc).mean()),
        "GBT": float((gbt.predict(Xid) == yidc).mean()),
        "RULE": float((E.rule_arm(d["test_id"][3]) == yidc).mean())}

    # ------------------------------------------------------ clause report ----
    res["clauses"] = clause_report(tm, Xtr, ytrc)

    np.savez_compressed(os.path.join(outdir, f"preds_seed{seed}.npz"),
                        p_tm_id=p_id, p_tm_temp_id=pt_id, y_id=yid,
                        p_tm_a=p_a, y_a=ya, p_tm_b=p_b, y_b=yb,
                        p_tm_id_nofw=p_id2, y_id_nofw=yid2,
                        p_lr_id=probs_store["LR"], p_gbt_id=probs_store["GBT"])
    res["reliability_tm_test_id"] = E.reliability(p_id, yid)
    res["reliability_tm_temp_test_id"] = E.reliability(pt_id, yid)
    return res


def main(outdir, hp):
    os.makedirs(outdir, exist_ok=True)
    all_res = []
    for s in SEEDS:
        t0 = time.time()
        r = run_seed(s, hp, outdir)
        r["seconds"] = time.time() - t0
        json.dump(r, open(os.path.join(outdir, f"metrics_seed{s}.json"), "w"),
                  indent=2)
        all_res.append(r)
        print(f"seed {s} {r['seconds']:.1f}s  TM acc "
              f"{r['TM']['test_id']['acc_argmax']:.4f} ece "
              f"{r['TM']['test_id']['ece']:.3f} temp "
              f"{r['TM_temp']['temperature']:.3f} terms "
              f"{r['clauses']['terms_in_top10']}", flush=True)
    json.dump(all_res, open(os.path.join(outdir, "metrics_all.json"), "w"),
              indent=2)


if __name__ == "__main__":
    hp = json.load(open(sys.argv[2]))["best"]
    main(sys.argv[1], hp)
