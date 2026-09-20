"""R-TM-01b generator pilot. LR and GBT only - the TM is never run on pilot data.

Purpose: establish, before any criterion is frozen, (a) the accuracy ceiling,
(b) where a linear baseline lands, (c) how much selective prediction can
possibly buy at 80 % coverage, and (d) that every hidden-rule term has enough
support in train to be learnable.  Pilot seeds are 900-902; the run proper uses
seeds 0-4, which the pilot never touches.
"""
import json, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

import generator_b as G

PILOT_SEEDS = [900, 901, 902]


def selective(probs, y, drop_frac=0.20):
    conf = np.maximum(probs, 1 - probs)
    err = ((probs >= 0.5).astype(int) != y).astype(float)
    keep = np.argsort(conf, kind="stable")[int(round(drop_frac * len(y))):]
    return float(err.mean()), float(err[keep].mean())


def mixed_stream(m, d, rng, n=2000, w=(0.70, 0.15, 0.15)):
    """Traffic the escalation layer actually faces: mostly seen states, some
    novel ones.  Returns (probs, y) for the mixed stream."""
    parts = [("test_id", w[0]), ("ood_a", w[1]), ("ood_b", w[2])]
    P, Y = [], []
    for key, frac in parts:
        X, y = d[key][0], d[key][1]
        k = int(round(frac * n))
        idx = rng.choice(len(y), size=min(k, len(y)), replace=False)
        P.append(m.predict_proba(X[idx])[:, 1]); Y.append(y[idx])
    return np.concatenate(P), np.concatenate(Y)


def main(path):
    out = {"pilot_seeds": PILOT_SEEDS, "arms": ["LR", "GBT"],
           "tm_never_run_on_pilot": True}
    ceil, base_rate, lr_a, gbt_a, red_lr, red_gbt, supports = ([] for _ in range(7))
    ood_drop = {"LR": [], "GBT": []}
    for s in PILOT_SEEDS:
        d = G.build_all(s)
        Xtr, ytr = d["train"][0], d["train"][1]
        Xid, yid, yidc = d["test_id"][0], d["test_id"][1], d["test_id"][2]
        ceil.append(float((yidc == yid).mean()))
        base_rate.append(float(yidc.mean()))
        supports.append([int(t.sum()) for t in d["train"][4]])

        lr = LogisticRegression(max_iter=2000).fit(Xtr, ytr)
        gbt = HistGradientBoostingClassifier(random_state=s).fit(Xtr, ytr)
        lr_a.append(float((lr.predict(Xid) == yid).mean()))
        gbt_a.append(float((gbt.predict(Xid) == yid).mean()))
        for name, m in [("LR", lr), ("GBT", gbt)]:
            e0, e1 = selective(m.predict_proba(Xid)[:, 1], yid)
            (red_lr if name == "LR" else red_gbt).append(
                float(1 - e1 / e0) if e0 > 0 else 0.0)
            c = lambda X: float(np.mean(np.maximum(m.predict_proba(X)[:, 1],
                                                   1 - m.predict_proba(X)[:, 1])))
            ood_drop[name].append(c(Xid) - c(d["ood_a"][0]))

    # mixed-stream selective prediction (the A4 re-specification)
    mixed = {"LR": [], "GBT": []}
    for s in PILOT_SEEDS:
        d = G.build_all(s)
        rng = np.random.default_rng(s)
        for name, mk in [("LR", lambda: LogisticRegression(max_iter=2000)),
                         ("GBT", lambda: HistGradientBoostingClassifier(random_state=s))]:
            m = mk().fit(d["train"][0], d["train"][1])
            pm, ym = mixed_stream(m, d, rng)
            e0, e1 = selective(pm, ym)
            mixed[name].append(float(1 - e1 / e0) if e0 > 0 else 0.0)

    ms = lambda v: [float(np.mean(v)), float(np.std(v))]
    out["mixed_stream_error_reduction_at_80pct"] = {k: ms(v) for k, v in mixed.items()}
    out["ceiling_test_id"] = ms(ceil)
    out["escalate_base_rate"] = ms(base_rate)
    out["LR_acc"] = ms(lr_a)
    out["GBT_acc"] = ms(gbt_a)
    out["LR_error_reduction_at_80pct_coverage"] = ms(red_lr)
    out["GBT_error_reduction_at_80pct_coverage"] = ms(red_gbt)
    out["baseline_conf_drop_ood_a"] = {k: ms(v) for k, v in ood_drop.items()}
    out["train_term_support"] = {f"R{i+1}": ms([s[i] for s in supports])
                                 for i in range(5)}
    out["headroom_above_LR"] = out["ceiling_test_id"][0] - out["LR_acc"][0]
    json.dump(out, open(path, "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
