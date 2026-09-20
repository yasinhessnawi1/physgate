"""Score one configuration of R-TM-01d against the frozen S4 criteria.

A1 uses the single decision rule (class-sum probability >= 0.5), per Change 3."""
import json, os, sys
import numpy as np


def ms(v):
    a = np.array(v, dtype=float)
    return [float(a.mean()), float(a.std())]


def main(outdir):
    res = json.load(open(os.path.join(outdir, "metrics_all.json")))
    pilot = json.load(open(os.path.join(outdir, "pilot.json")))
    g = lambda arm, split, key: [r[arm][split][key] for r in res]

    S = {}
    for arm in ["TM", "TM_temp", "LR", "GBT"]:
        S[arm] = {}
        for split in ["test_id", "ood_a", "test_id_nofw", "ood_b", "mixed"]:
            if split not in res[0][arm]:
                continue
            S[arm][split] = {k: ms(g(arm, split, k)) for k in res[0][arm][split]
                             if isinstance(res[0][arm][split][k], (int, float))}
    S["RULE"] = {"test_id": {"acc": ms(g("RULE", "test_id", "acc"))},
                 "ood_a": {"acc": ms(g("RULE", "ood_a", "acc"))}}
    S["clean_label_recovery"] = {k: ms([r["clean_label_recovery"][k] for r in res])
                                 for k in res[0]["clean_label_recovery"]}
    S["temperature"] = ms([r["TM_temp"]["temperature"] for r in res])

    tm_acc = S["TM"]["test_id"]["acc"][0]   # probability rule, not argmax
    gbt_acc, lr_acc = S["GBT"]["test_id"]["acc"][0], S["LR"]["test_id"]["acc"][0]
    a1 = {"tm": tm_acc, "gbt": gbt_acc, "lr": lr_acc,
          "within_3pts_of_gbt": (gbt_acc - tm_acc) <= 0.03,
          "at_least_5pts_above_lr": (tm_acc - lr_acc) >= 0.05}
    a1["within_3pts_of_gbt"] = bool(a1["within_3pts_of_gbt"])
    a1["at_least_5pts_above_lr"] = bool(a1["at_least_5pts_above_lr"])
    a1["pass"] = bool(a1["within_3pts_of_gbt"] and a1["at_least_5pts_above_lr"])

    a2 = {"raw": S["TM"]["test_id"]["ece"][0],
          "temperature_scaled": S["TM_temp"]["test_id"]["ece"][0]}
    a2["pass"] = bool((a2["raw"] <= 0.10) or (a2["temperature_scaled"] <= 0.06))

    per_a = [r["TM"]["test_id"]["mean_conf"] - r["TM"]["ood_a"]["mean_conf"] for r in res]
    per_b = [r["TM"]["test_id_nofw"]["mean_conf"] - r["TM"]["ood_b"]["mean_conf"] for r in res]
    a3 = {"drop_ood_a": ms(per_a), "drop_ood_b": ms(per_b),
          "per_seed_a": per_a, "per_seed_b": per_b,
          "gbt_drop_ood_a": S["GBT"]["test_id"]["mean_conf"][0] - S["GBT"]["ood_a"]["mean_conf"][0],
          "gbt_drop_ood_b": S["GBT"]["test_id_nofw"]["mean_conf"][0] - S["GBT"]["ood_b"]["mean_conf"][0]}
    a3["pass"] = bool((np.mean(per_a) >= 0.15) and (np.mean(per_b) >= 0.15))
    a3["fails_on_both"] = bool((np.mean(per_a) < 0.15) and (np.mean(per_b) < 0.15))

    red = [r["TM"]["mixed"]["reduction"] for r in res]
    a4 = {"reduction": ms(red), "per_seed": red,
          "lr_reduction": ms([r["LR"]["mixed"]["reduction"] for r in res]),
          "gbt_reduction": ms([r["GBT"]["mixed"]["reduction"] for r in res]),
          "mixed_error_full": S["TM"]["mixed"]["error_full"],
          "pass": bool(float(np.mean(red)) >= 0.40)}

    rec = [r["a5"]["n_recovered"] for r in res]
    a5 = {"n_recovered_per_seed": rec, "mean": float(np.mean(rec)),
          "recovered_per_seed": [r["a5"]["recovered"] for r in res],
          "clauses_to_cover_80pct": ms([r["a5"]["legibility"]["clauses_to_cover_80pct"]
                                        for r in res]),
          "distinct_bodies": ms([r["a5"]["n_distinct_bodies"] for r in res]),
          "pass": bool(float(np.mean(rec)) >= 3)}

    # ARCH-132 amendment: A5 is reported, not gating.
    kill = {"A2_fails_even_scaled": not a2["pass"],
            "A3_fails_on_both_ood": bool(a3["fails_on_both"]),
            "A1_fails_against_LR": not a1["at_least_5pts_above_lr"],
            "run_exceeds_one_day": False}
    verdict = {"A1": a1, "A2": a2, "A3": a3, "A4": a4, "A5": a5, "kill": kill,
               "killed": any(kill.values()),
               "gating_criteria_pass": all(x["pass"] for x in [a1, a2, a3, a4]),
               "a5_reported_not_gating": a5["pass"],
               "pilot_reference": {k: pilot[k] for k in
                                   ["ceiling_test_id", "LR_acc", "GBT_acc",
                                    "mixed_stream_error_reduction_at_80pct"]}}
    json.dump({"summary": S, "verdict": verdict},
              open(os.path.join(outdir, "summary.json"), "w"), indent=2)
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
