"""R-TM-01c sweep: accuracy subject to a humility floor, measured train-internally.

Three fits per configuration, all inside the 8 000-row train split:
  * accuracy fit      - 6500 rows -> accuracy / ECE on the held-out 1500
  * pseudo-OOD-B fit  - the same 6500 with domain == mech removed
  * pseudo-OOD-A fit  - the same 6500 with attempt == 2 removed
No test split is touched.
"""
import json, sys, time, itertools
import numpy as np

import generator_b as G
import experiment as E

SWEEP_SEED = 0
EPOCHS = 60
CLAUSES = [200, 300, 500]
T_VALUES = [20, 40, 80, 160]
S_VALUES = [2.0, 3.0, 5.0, 10.0]
HUMILITY_FLOOR = 0.15
N_FIT = 6500


def conf(p):
    return float(np.mean(np.maximum(p, 1 - p)))


def main(outpath):
    d = G.build_all(SWEEP_SEED)
    X, y, raw = d["train"][0], d["train"][1], d["train"][3]
    Xfit, yfit = X[:N_FIT], y[:N_FIT]
    Xval, yval = X[N_FIT:], y[N_FIT:]
    dom_fit = raw["domain"][:N_FIT]
    dom_val = raw["domain"][N_FIT:]
    att_fit = raw["attempt"][:N_FIT]
    att_val = raw["attempt"][N_FIT:]

    # pseudo-OOD-B: hold out a whole domain from fitting
    keep_b = dom_fit != "mech"
    XB, yB = Xfit[keep_b], yfit[keep_b]
    val_b_id, val_b_ood = Xval[dom_val != "mech"], Xval[dom_val == "mech"]
    # pseudo-OOD-A: hold out attempt 2 from fitting
    keep_a = att_fit != 2
    XA, yA = Xfit[keep_a], yfit[keep_a]
    val_a_id, val_a_ood = Xval[att_val != 2], Xval[att_val == 2]

    rows, t0 = [], time.time()
    for c, T, s in itertools.product(CLAUSES, T_VALUES, S_VALUES):
        tm = E.fit_tm(Xfit, yfit, c, T, s, EPOCHS, seed=1000)
        pred, _, p_val = E.tm_predict(tm, Xval, T)
        acc, ece = float((pred == yval).mean()), E.ece(p_val, yval)

        tb = E.fit_tm(XB, yB, c, T, s, EPOCHS, seed=1000)
        hb = conf(E.tm_predict(tb, val_b_id, T)[2]) - conf(E.tm_predict(tb, val_b_ood, T)[2])
        ta = E.fit_tm(XA, yA, c, T, s, EPOCHS, seed=1000)
        ha = conf(E.tm_predict(ta, val_a_id, T)[2]) - conf(E.tm_predict(ta, val_a_ood, T)[2])

        rows.append({"clauses": c, "T": T, "s": s, "epochs": EPOCHS,
                     "val_acc": acc, "val_ece": ece,
                     "pseudo_ood_a_drop": float(ha), "pseudo_ood_b_drop": float(hb),
                     "qualifies": bool(ha >= HUMILITY_FLOOR and hb >= HUMILITY_FLOOR)})
        print(f"c={c} T={T} s={s} acc={acc:.4f} ece={ece:.3f} "
              f"pA={ha:+.3f} pB={hb:+.3f} {'OK' if rows[-1]['qualifies'] else ''}",
              flush=True)

    qual = [r for r in rows if r["qualifies"]]
    if qual:
        best = sorted(qual, key=lambda r: (-r["val_acc"], r["val_ece"]))[0]
        note = (f"{len(qual)} of {len(rows)} configurations met the {HUMILITY_FLOOR} "
                f"humility floor on both pseudo-OOD slices; highest validation accuracy "
                f"among them selected")
        floor_met = True
    else:
        best = sorted(rows, key=lambda r: -min(r["pseudo_ood_a_drop"],
                                               r["pseudo_ood_b_drop"]))[0]
        note = ("NO configuration met the humility floor on both pseudo-OOD slices; "
                "fell back to the largest min(pseudo-A, pseudo-B) as pre-registered")
        floor_met = False

    json.dump({"grid": rows, "best": best, "floor": HUMILITY_FLOOR,
               "floor_met": floor_met, "n_qualifying": len(qual),
               "selection_note": note, "seconds": time.time() - t0},
              open(outpath, "w"), indent=2)
    print("BEST", best)
    print(note)


if __name__ == "__main__":
    main(sys.argv[1])
