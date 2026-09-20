"""R-TM-01d run-level verdict: every replicate's selected configuration must pass A1-A4."""
import json, os, subprocess, sys
import numpy as np

PY_BIN = "/tmp/tmenv/bin/python"
OUT = "runs/run05d"


def tag(cfg):
    return f"c{cfg['clauses']}_T{cfg['T']}_s{cfg['s']}"


def retained(evaldir, kp, ky, thr=0.8):
    acc_all, acc_kept, kept_f = [], [], []
    for s in range(5):
        z = np.load(f"{evaldir}/preds_seed{s}.npz")
        p, y = z[kp], z[ky]
        c = np.maximum(p, 1 - p); keep = c >= thr
        pred = (p >= 0.5).astype(int)
        acc_all.append(float((pred == y).mean()))
        kept_f.append(float(keep.mean()))
        acc_kept.append(float((pred[keep] == y[keep]).mean()) if keep.sum() else np.nan)
    return {"acc_split": float(np.mean(acc_all)),
            "routed_to_human": float(1 - np.mean(kept_f)),
            "acc_retained": float(np.nanmean(acc_kept))}


def main():
    sw = json.load(open(f"{OUT}/sweep.json"))
    reps = sw["replicates"]
    results = {}
    for cfg in sw["distinct_selected"]:
        hp = {"clauses": cfg[0], "T": cfg[1], "s": cfg[2], "epochs": 60}
        t = tag(hp)
        ev = f"{OUT}/eval_{t}"
        os.makedirs(ev, exist_ok=True)
        json.dump({"best": hp}, open(f"{ev}/sweep.json", "w"))
        subprocess.run([PY_BIN, "run_b.py", ev, f"{ev}/sweep.json"],
                       check=True, capture_output=True)
        if not os.path.exists(f"{ev}/pilot.json"):
            json.dump(json.load(open("runs/run03b/pilot.json")),
                      open(f"{ev}/pilot.json", "w"))
        subprocess.run([PY_BIN, "score_d.py", ev], check=True, capture_output=True)
        v = json.load(open(f"{ev}/summary.json"))["verdict"]
        results[t] = {
            "hp": hp,
            "A1": {"tm": v["A1"]["tm"], "gbt": v["A1"]["gbt"], "lr": v["A1"]["lr"],
                   "pass": v["A1"]["pass"]},
            "A2": {"raw": v["A2"]["raw"], "scaled": v["A2"]["temperature_scaled"],
                   "pass": v["A2"]["pass"]},
            "A3": {"ood_a": v["A3"]["drop_ood_a"], "ood_b": v["A3"]["drop_ood_b"],
                   "per_seed_a": v["A3"]["per_seed_a"],
                   "per_seed_b": v["A3"]["per_seed_b"], "pass": v["A3"]["pass"]},
            "A4": {"reduction": v["A4"]["reduction"], "pass": v["A4"]["pass"]},
            "A5_reported": v["A5"]["mean"],
            "all_four_pass": v["gating_criteria_pass"],
            "paired_accuracy": {
                "test_id": retained(ev, "p_tm_id", "y_id"),
                "ood_a": retained(ev, "p_tm_a", "y_a"),
                "ood_b": retained(ev, "p_tm_b", "y_b")}}
        print(t, "all four pass:", results[t]["all_four_pass"], flush=True)

    per_rep = {}
    for rep, r in reps.items():
        sel = r["selected"]
        per_rep[rep] = {"selected": None if sel is None else
                        {k: sel[k] for k in ("clauses", "T", "s")},
                        "n_qualifying": r["n_qualifying"],
                        "passes": None if sel is None else
                        results[tag(sel)]["all_four_pass"]}
    run_pass = (sw["all_replicates_selected"]
                and all(v["passes"] for v in per_rep.values()))
    verdict = {"per_replicate": per_rep, "configurations": results,
               "every_replicate_selected_a_config": sw["all_replicates_selected"],
               "every_selected_config_passes_all_four": run_pass,
               "RUN_PASSES": bool(run_pass)}
    json.dump(verdict, open(f"{OUT}/stability.json", "w"), indent=2)
    print(json.dumps(per_rep, indent=2))
    print("RUN PASSES:", run_pass)


if __name__ == "__main__":
    main()
