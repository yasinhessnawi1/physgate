"""Short TM hyperparameter sweep. Train data only — no test split is touched."""
import json, time, itertools, sys
import numpy as np
import generator_b as G
import experiment as E

SWEEP_SEED = 0
EPOCHS = 60
CLAUSES = [200, 300, 500]
T_VALUES = [20, 40, 80, 160]
S_VALUES = [2.0, 3.0, 5.0, 10.0]


def main(outpath):
    d = G.build_all(SWEEP_SEED)
    X, y = d["train"][0], d["train"][1]
    n_tr = 6500                                   # internal split of TRAIN only
    Xtr, ytr, Xva, yva = X[:n_tr], y[:n_tr], X[n_tr:], y[n_tr:]

    rows = []
    t0 = time.time()
    for c, T, s in itertools.product(CLAUSES, T_VALUES, S_VALUES):
        tm = E.fit_tm(Xtr, ytr, c, T, s, EPOCHS, seed=1000)
        pred, cs, p = E.tm_predict(tm, Xva, T)
        acc = float((pred == yva).mean())
        e = E.ece(p, yva)
        rows.append({"clauses": c, "T": T, "s": s, "epochs": EPOCHS,
                     "val_acc": acc, "val_ece": e})
        print(f"c={c} T={T} s={s}  acc={acc:.4f} ece={e:.3f}", flush=True)
    rows.sort(key=lambda r: (-r["val_acc"], r["val_ece"]))
    best = rows[0]
    json.dump({"grid": rows, "best": best, "seconds": time.time() - t0,
               "note": "selected on a 1500-sample validation slice carved from "
                       "the 8000-sample TRAIN split; no test data used"},
              open(outpath, "w"), indent=2)
    print("BEST", best)


if __name__ == "__main__":
    main(sys.argv[1])
