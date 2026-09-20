"""Aggregate per-seed metrics, score A1-A5 and the kill criteria."""
import json, sys, os
import numpy as np


def ms(vals):
    a = np.array(vals, dtype=float)
    return float(a.mean()), float(a.std(ddof=0))


def main(outdir):
    res = json.load(open(os.path.join(outdir, "metrics_all.json")))
    g = lambda arm, split, key: [r[arm][split][key] for r in res]

    S = {}
    for arm in ["TM", "TM_temp", "LR", "GBT"]:
        S[arm] = {}
        for split in ["test_id", "ood_a", "test_id_nofw", "ood_b"]:
            if split not in res[0][arm]:
                continue
            S[arm][split] = {k: ms(g(arm, split, k))
                             for k in res[0][arm][split]
                             if isinstance(res[0][arm][split][k], (int, float))}
    S["RULE"] = {"test_id": {"acc": ms(g("RULE", "test_id", "acc"))},
                 "ood_a": {"acc": ms(g("RULE", "ood_a", "acc"))}}
    S["TM_temp_fresh_cal"] = {"test_id": {
        k: ms([r["TM_temp_fresh_cal"]["test_id"][k] for r in res])
        for k in res[0]["TM_temp_fresh_cal"]["test_id"]}}
    S["TM_platt"] = {"test_id": {
        k: ms([r["TM_platt"]["test_id"][k] for r in res])
        for k in res[0]["TM_platt"]["test_id"]}}
    S["clean_label_recovery"] = {k: ms([r["clean_label_recovery"][k]
                                        for r in res])
                                 for k in res[0]["clean_label_recovery"]}
    S["temperature"] = ms([r["TM_temp"]["temperature"] for r in res])

    # ------------------------------------------------------------ criteria --
    tm_acc = S["TM"]["test_id"]["acc_argmax"][0]
    gbt_acc = S["GBT"]["test_id"]["acc"][0]
    lr_acc = S["LR"]["test_id"]["acc"][0]
    a1 = {"tm": tm_acc, "gbt": gbt_acc, "lr": lr_acc,
          "within_3pts_of_gbt": (gbt_acc - tm_acc) <= 0.03,
          "at_least_5pts_above_lr": (tm_acc - lr_acc) >= 0.05}
    a1["pass"] = a1["within_3pts_of_gbt"] and a1["at_least_5pts_above_lr"]

    ece_raw = S["TM"]["test_id"]["ece"][0]
    ece_scaled = S["TM_temp"]["test_id"]["ece"][0]
    a2 = {"raw": ece_raw, "temperature_scaled": ece_scaled,
          "platt_scaled_2param": S["TM_platt"]["test_id"]["ece"][0],
          "pass": (ece_raw <= 0.10) or (ece_scaled <= 0.06)}

    drop_a = S["TM"]["test_id"]["mean_conf"][0] - S["TM"]["ood_a"]["mean_conf"][0]
    drop_b = (S["TM"]["test_id_nofw"]["mean_conf"][0]
              - S["TM"]["ood_b"]["mean_conf"][0])
    per_seed_a = [r["TM"]["test_id"]["mean_conf"] - r["TM"]["ood_a"]["mean_conf"]
                  for r in res]
    per_seed_b = [r["TM"]["test_id_nofw"]["mean_conf"]
                  - r["TM"]["ood_b"]["mean_conf"] for r in res]
    a3 = {"drop_ood_a": drop_a, "drop_ood_b": drop_b,
          "drop_ood_a_sd": float(np.std(per_seed_a)),
          "drop_ood_b_sd": float(np.std(per_seed_b)),
          "pass": (drop_a >= 0.15) and (drop_b >= 0.15)}

    gbt_drop_a = (S["GBT"]["test_id"]["mean_conf"][0]
                  - S["GBT"]["ood_a"]["mean_conf"][0])
    gbt_drop_b = (S["GBT"]["test_id_nofw"]["mean_conf"][0]
                  - S["GBT"]["ood_b"]["mean_conf"][0])
    a3["gbt_drop_ood_a"] = gbt_drop_a
    a3["gbt_drop_ood_b"] = gbt_drop_b
    a3["gbt_also_passes"] = (gbt_drop_a >= 0.15) and (gbt_drop_b >= 0.15)

    gain = S["TM"]["test_id"]["sel_gain"][0]
    a4 = {"gain": gain,
          "max_possible_gain_at_noise_ceiling": 0.95 - gain * 0 - S["TM"]["test_id"]["sel_base_acc"][0], "base": S["TM"]["test_id"]["sel_base_acc"][0],
          "kept": S["TM"]["test_id"]["sel_kept_acc"][0],
          "lr_gain": S["LR"]["test_id"]["sel_gain"][0],
          "gbt_gain": S["GBT"]["test_id"]["sel_gain"][0],
          "pass": gain >= 0.04}

    n_terms = [r["clauses"]["n_terms_in_top10"] for r in res]
    a5 = {"terms_per_seed": n_terms, "mean": float(np.mean(n_terms)),
          "pass": float(np.mean(n_terms)) >= 3}

    kill = {
        "A2_fails_even_scaled": not a2["pass"],
        "A3_fails_on_both_ood": (drop_a < 0.15) and (drop_b < 0.15),
        "A1_fails_against_LR": not a1["at_least_5pts_above_lr"],
        "run_exceeds_one_day": False,
    }
    verdict = {"A1": a1, "A2": a2, "A3": a3, "A4": a4, "A5": a5,
               "kill": kill, "killed": any(kill.values()),
               "all_five_pass": all(x["pass"] for x in [a1, a2, a3, a4, a5])}

    json.dump({"summary": S, "verdict": verdict},
              open(os.path.join(outdir, "summary.json"), "w"), indent=2)
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
