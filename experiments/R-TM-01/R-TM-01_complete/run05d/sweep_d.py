"""R-TM-01d selection: the rule executed independently at three sweep seeds.

Per replicate, per configuration: three fits inside the training split
  * accuracy fit     - 6500 rows -> accuracy (probability rule) / ECE on 1500 held out
  * pseudo-OOD-B fit - same fold with domain == mech removed
  * pseudo-OOD-A fit - same fold with attempt == 2 removed
Qualifying requires the humility floor on BOTH slices AND validation accuracy inside
A1's band against LR and GBT fitted on the same fold.  No test split is read.
"""
import json, sys, time, itertools
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

import generator_b as G
import experiment as E

SWEEP_SEED = 0
REPLICATES = [1000, 1001, 1002]
EPOCHS = 60
CLAUSES = [200, 300, 500]
T_VALUES = [20, 40, 80, 160]
S_VALUES = [2.0, 3.0, 5.0, 10.0]
HUMILITY_FLOOR = 0.15
GBT_BAND = 0.03
LR_MARGIN = 0.05
N_FIT = 6500


def conf(p):
    return float(np.mean(np.maximum(p, 1 - p)))


def acc_prob(tm, X, y, T):
    """Accuracy under the single decision rule: p >= 0.5 on the class-sum probability."""
    p = E.tm_predict(tm, X, T)[2]
    return float(((p >= 0.5).astype(int) == y).mean()), p


def main(outpath):
    d = G.build_all(SWEEP_SEED)
    X, y, raw = d["train"][0], d["train"][1], d["train"][3]
    Xfit, yfit, Xval, yval = X[:N_FIT], y[:N_FIT], X[N_FIT:], y[N_FIT:]
    dom_fit, dom_val = raw["domain"][:N_FIT], raw["domain"][N_FIT:]
    att_fit, att_val = raw["attempt"][:N_FIT], raw["attempt"][N_FIT:]

    XB, yB = Xfit[dom_fit != "mech"], yfit[dom_fit != "mech"]
    val_b_id, val_b_ood = Xval[dom_val != "mech"], Xval[dom_val == "mech"]
    XA, yA = Xfit[att_fit != 2], yfit[att_fit != 2]
    val_a_id, val_a_ood = Xval[att_val != 2], Xval[att_val == 2]

    # A1's band, computed inside the training split
    lr = LogisticRegression(max_iter=2000).fit(Xfit, yfit)
    gbt = HistGradientBoostingClassifier(random_state=0).fit(Xfit, yfit)
    lr_val = float((lr.predict(Xval) == yval).mean())
    gbt_val = float((gbt.predict(Xval) == yval).mean())
    acc_floor = max(gbt_val - GBT_BAND, lr_val + LR_MARGIN)
    print(f"fold baselines: LR {lr_val:.4f}  GBT {gbt_val:.4f}  "
          f"-> accuracy floor {acc_floor:.4f}", flush=True)

    out = {"replicates": {}, "fold_baselines": {"lr_val_acc": lr_val,
                                                "gbt_val_acc": gbt_val,
                                                "accuracy_floor": acc_floor},
           "rule": {"humility_floor": HUMILITY_FLOOR, "gbt_band": GBT_BAND,
                    "lr_margin": LR_MARGIN, "decision_rule": "p >= 0.5",
                    "test_data_used": "none"}}
    t0 = time.time()
    for rep in REPLICATES:
        rows = []
        for c, T, s in itertools.product(CLAUSES, T_VALUES, S_VALUES):
            tm = E.fit_tm(Xfit, yfit, c, T, s, EPOCHS, seed=rep)
            acc, p_val = acc_prob(tm, Xval, yval, T)
            ece = E.ece(p_val, yval)
            tb = E.fit_tm(XB, yB, c, T, s, EPOCHS, seed=rep)
            hb = conf(E.tm_predict(tb, val_b_id, T)[2]) - conf(E.tm_predict(tb, val_b_ood, T)[2])
            ta = E.fit_tm(XA, yA, c, T, s, EPOCHS, seed=rep)
            ha = conf(E.tm_predict(ta, val_a_id, T)[2]) - conf(E.tm_predict(ta, val_a_ood, T)[2])
            q = bool(ha >= HUMILITY_FLOOR and hb >= HUMILITY_FLOOR and acc >= acc_floor)
            rows.append({"clauses": c, "T": T, "s": s, "epochs": EPOCHS,
                         "val_acc": acc, "val_ece": ece,
                         "pseudo_ood_a_drop": float(ha), "pseudo_ood_b_drop": float(hb),
                         "meets_humility": bool(ha >= HUMILITY_FLOOR and hb >= HUMILITY_FLOOR),
                         "meets_accuracy_band": bool(acc >= acc_floor),
                         "qualifies": q})
        qual = [r for r in rows if r["qualifies"]]
        best = (sorted(qual, key=lambda r: (-r["val_acc"], r["val_ece"]))[0]
                if qual else None)
        out["replicates"][str(rep)] = {"grid": rows, "n_qualifying": len(qual),
                                       "selected": best}
        print(f"replicate {rep}: {len(qual)}/48 qualify -> "
              f"{ {k: best[k] for k in ('clauses','T','s')} if best else 'NONE'}",
              flush=True)

    sel = [out["replicates"][str(r)]["selected"] for r in REPLICATES]
    out["all_replicates_selected"] = all(s is not None for s in sel)
    out["distinct_selected"] = sorted({(s["clauses"], s["T"], s["s"]) for s in sel
                                       if s is not None})
    out["seconds"] = time.time() - t0
    json.dump(out, open(outpath, "w"), indent=2)
    print("distinct selected configurations:", out["distinct_selected"])


if __name__ == "__main__":
    main(sys.argv[1])
