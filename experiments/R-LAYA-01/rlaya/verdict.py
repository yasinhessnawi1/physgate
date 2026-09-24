"""Step 4 — aggregate the measurement, score the criteria, draw the diagrams.

Reads only what step 4's measurement produced. Constructs nothing, fits nothing,
and never touches a threshold: C1's 0.10 and 0.06, C2's 0.15 and 0.20 and C3's
0.95 are constants here, compared against and never adjusted.

Everything is *"on the mean over seeds"* (§6), with the per-seed values kept.

--------------------------------------------------------------------------
The one thing C2 and C3 do not say
--------------------------------------------------------------------------
C1 is explicit about temperature: *"≤ 0.10 raw, or ≤ 0.06 after temperature
scaling."* C2 and C3 say nothing, and temperature changes confidence, hence the
escalation rate, hence both of them.

Rather than invent a rule, this module evaluates **both configurations for
every criterion** and reports both. It also reports whether there is a *single*
configuration in which C1, C2 and C3 all hold, because "the backend" is one
thing and a pass assembled from two different temperatures is not a
configuration anybody could deploy. The headline verdict follows §7 literally —
each criterion judged as written — and the single-configuration view is
reported beside it. If the two disagree, `RESULT.md` says so and neither reading
is quietly preferred. Choosing between them is not this script's to make: a
tie-break invented here would be a rule the frozen criteria do not contain, and
it would be invented after the numbers existed.

R-TM-01's own A3, which C2 is transplanted from, used the **raw** probabilities
(`res["TM"]`, not `res["TM_temp"]`), and the paired accuracy that informed C3
did too. That is recorded here as context, not used as a tie-break.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import metrics, workload  # noqa: E402

C1_RAW, C1_SCALED = 0.10, 0.06
C2_CONF_DROP, C2_ESC_RISE = 0.15, 0.20
C3_SELECTIVE = 0.95
C4_P50_MS = 500.0
GATED_ECE = "ece"          # metrics.score_all's key for ece_conf_half

ARMS = ("L0", "L1", "T", "G", "R")
SPLITS = ("test_id", "test_id_nofw", "ood_a", "ood_b")
# C2's baseline per OOD set: each against the in-distribution reference of the
# model that scored it. score_d.py, verbatim in behaviour.
C2_BASELINE = {"ood_a": "test_id", "ood_b": "test_id_nofw"}
C2_BASELINE_LITERAL = {"ood_a": "test_id", "ood_b": "test_id"}


def ms(v):
    a = np.asarray(v, dtype=float)
    return {"mean": float(a.mean()), "sd": float(a.std()), "per_seed": [float(x) for x in a]}


def get(per_seed, arm, split, variant, key):
    """One metric, per seed, for an (arm, split, temperature) cell."""
    out = []
    for sr in per_seed:
        cell = sr["arms"][arm][split]
        v = cell.get(variant, cell.get("raw"))
        out.append(v[key])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--laptop", default=None, help="laptop latency json")
    ap.add_argument("--step2", default=None, help="step-2 dir, for arm T's fit times")
    ap.add_argument("--step3", default=None,
                    help="step-3 dir, for the training budget across all ten fits")
    args = ap.parse_args()

    raw = json.load(open(os.path.join(args.out_dir, "step4_raw.json")))
    armt = json.load(open(os.path.join(args.out_dir, "step4_arm_t.json")))

    # Merge arm T into the per-seed records.
    by_seed = {sr["seed"]: sr for sr in raw["per_seed"]}
    for sr in armt["per_seed"]:
        by_seed[sr["seed"]]["arms"]["T"] = sr["splits"]
    per_seed = [by_seed[s] for s in workload.SEEDS]

    variants = {"L0": ("raw", "s3", "shipped"), "L1": ("raw", "s3", "shipped"),
                "T": ("raw", "s3"), "G": ("raw",), "R": ("raw",)}

    summary = {}
    for arm in ARMS:
        summary[arm] = {}
        for split in SPLITS:
            summary[arm][split] = {}
            for var in variants[arm]:
                cell = {}
                for key in ("ece", "ece_conf_full_0_1", "ece_prob_bins",
                            "mean_confidence", "mean_confidence_laya_entropy",
                            "escalation_rate", "answer_rate",
                            "queue_rate_answer_or_low_confidence",
                            "accuracy_split", "selective_accuracy", "n_kept"):
                    cell[key] = ms(get(per_seed, arm, split, var, key))
                summary[arm][split][var] = cell

    # -------------------------------------------------------------- C1 -----
    c1 = {}
    for arm in ARMS:
        e_raw = summary[arm]["test_id"]["raw"][GATED_ECE]["mean"]
        e_s3 = (summary[arm]["test_id"]["s3"][GATED_ECE]["mean"]
                if "s3" in summary[arm]["test_id"] else None)
        c1[arm] = {
            "ece_raw": e_raw, "ece_s3": e_s3,
            "threshold_raw": C1_RAW, "threshold_scaled": C1_SCALED,
            "pass_raw": bool(e_raw <= C1_RAW),
            "pass_scaled": bool(e_s3 is not None and e_s3 <= C1_SCALED),
            "reported_not_gating": {
                "ece_conf_full_0_1_raw":
                    summary[arm]["test_id"]["raw"]["ece_conf_full_0_1"]["mean"],
                "ece_prob_bins_raw":
                    summary[arm]["test_id"]["raw"]["ece_prob_bins"]["mean"],
                "note": "reported because they exist, not because they decide anything",
            },
        }
        if "shipped" in summary[arm]["test_id"]:
            c1[arm]["ece_shipped_non_gating"] = \
                summary[arm]["test_id"]["shipped"][GATED_ECE]["mean"]
        c1[arm]["pass"] = bool(c1[arm]["pass_raw"] or c1[arm]["pass_scaled"])

    # -------------------------------------------------------------- C2 -----
    def c2_for(arm, var, baseline_map):
        out = {}
        for ood in ("ood_a", "ood_b"):
            base = baseline_map[ood]
            drops, rises = [], []
            for sr in per_seed:
                bc = sr["arms"][arm][base].get(var, sr["arms"][arm][base]["raw"])
                oc = sr["arms"][arm][ood].get(var, sr["arms"][arm][ood]["raw"])
                drops.append(bc["mean_confidence"] - oc["mean_confidence"])
                rises.append(oc["escalation_rate"] - bc["escalation_rate"])
            d, r = ms(drops), ms(rises)
            out[ood] = {
                "baseline_split": base,
                "confidence_drop": d, "threshold_confidence_drop": C2_CONF_DROP,
                "escalation_rise": r, "threshold_escalation_rise": C2_ESC_RISE,
                "pass_confidence": bool(d["mean"] >= C2_CONF_DROP),
                "pass_escalation": bool(r["mean"] >= C2_ESC_RISE),
            }
            out[ood]["pass"] = bool(out[ood]["pass_confidence"]
                                    and out[ood]["pass_escalation"])
        out["pass"] = bool(out["ood_a"]["pass"] and out["ood_b"]["pass"])
        out["fails_on_both"] = bool(not out["ood_a"]["pass"] and not out["ood_b"]["pass"])
        return out

    c2 = {arm: {var: c2_for(arm, var, C2_BASELINE) for var in variants[arm]}
          for arm in ARMS}
    c2_literal = {arm: {var: c2_for(arm, var, C2_BASELINE_LITERAL)
                        for var in variants[arm]} for arm in ARMS}

    # -------------------------------------------------------------- C3 -----
    def c3_for(arm, var):
        out = {}
        for split in ("test_id", "ood_a", "ood_b"):
            v = ms(get(per_seed, arm, split, var, "selective_accuracy"))
            out[split] = {"selective_accuracy": v, "threshold": C3_SELECTIVE,
                          "pass": bool(v["mean"] >= C3_SELECTIVE),
                          "escalation_rate": summary[arm][split][var]["escalation_rate"],
                          "answer_rate": summary[arm][split][var]["answer_rate"],
                          "accuracy_split": summary[arm][split][var]["accuracy_split"]}
        out["pass"] = bool(all(out[s]["pass"] for s in ("test_id", "ood_a", "ood_b")))
        return out

    c3 = {arm: {var: c3_for(arm, var) for var in variants[arm]} for arm in ARMS}

    # -------------------------------------------------------------- C4 -----
    lat = {"server": raw.get("latency", {}), "server_arm_t": armt.get("latency", {})}
    if args.laptop and os.path.exists(args.laptop):
        lat["laptop"] = json.load(open(args.laptop))
    c4 = {"threshold_p50_ms": C4_P50_MS, "gates": "L1 only (CRITERIA §7)",
          "laptop": None, "pass": None}
    lp = lat.get("laptop", {})
    if lp and "L1" in lp.get("per_seed_test_id", {}):
        cells = lp["per_seed_test_id"]["L1"]
        # A seed that could not be loaded on an 8 GB machine is a finding, not
        # something to route around: it is named here and the mean is taken over
        # the seeds that did load, with how many that was stated beside it.
        ok = {k: v for k, v in cells.items() if "p50_ms" in v}
        failed = {k: v.get("error") for k, v in cells.items() if "p50_ms" not in v}
        p50s = [v["p50_ms"] for v in ok.values()]
        c4["laptop"] = {
            "p50_ms_per_seed": {k: v["p50_ms"] for k, v in ok.items()},
            "p50_ms_mean": float(np.mean(p50s)) if p50s else None,
            "n_seeds_measured": len(p50s), "n_seeds_expected": len(workload.SEEDS),
            "seeds_that_would_not_load": failed,
            "pooled": lp.get("pooled_test_id", {}).get("L1"),
            "train_same_session": lp.get("pooled_train", {}).get("L1"),
            "machine": lp.get("machine"), "device_selected": lp.get("device_selected"),
            "load_at_start": lp.get("load_at_start"),
            "load_at_end": lp.get("load_at_end"),
            "peak_rss_bytes": lp.get("peak_rss_bytes"),
        }
        c4["pass"] = bool(p50s) and bool(np.mean(p50s) <= C4_P50_MS)
        if len(p50s) < len(workload.SEEDS):
            c4["deviation"] = (
                "C4 is on the mean over five seeds (§6). %d of %d checkpoints were "
                "measured; the rest are recorded above with the error that stopped "
                "them." % (len(p50s), len(workload.SEEDS)))

    # --------------------------------------------- single-configuration view -
    single = {}
    for arm in ARMS:
        single[arm] = {}
        for var in variants[arm]:
            e = summary[arm]["test_id"][var][GATED_ECE]["mean"]
            thr = C1_RAW if var == "raw" else C1_SCALED
            single[arm][var] = {
                "c1": bool(e <= thr), "c1_ece": e, "c1_threshold_used": thr,
                "c2": c2[arm][var]["pass"], "c3": c3[arm][var]["pass"],
                "all_three": bool(e <= thr and c2[arm][var]["pass"]
                                  and c3[arm][var]["pass"])}
        single[arm]["any_configuration_passes_all_three"] = bool(
            any(v["all_three"] for k, v in single[arm].items() if isinstance(v, dict)))

    # ---------------------------------------------------------- acceptance --
    l1 = {"C1": c1["L1"]["pass"],
          "C2_raw": c2["L1"]["raw"]["pass"], "C2_s3": c2["L1"]["s3"]["pass"],
          "C3_raw": c3["L1"]["raw"]["pass"], "C3_s3": c3["L1"]["s3"]["pass"],
          "C4": c4["pass"]}
    kill = {
        "C1_fails_after_temperature_scaling":
            bool(not c1["L1"]["pass_raw"] and not c1["L1"]["pass_scaled"]),
        "C2_fails_on_both_ood_raw": bool(c2["L1"]["raw"]["fails_on_both"]),
        "C2_fails_on_both_ood_s3": bool(c2["L1"]["s3"]["fails_on_both"]),
        "C3_fails_on_test_id_raw": bool(not c3["L1"]["raw"]["test_id"]["pass"]),
        "C3_fails_on_test_id_s3": bool(not c3["L1"]["s3"]["test_id"]["pass"]),
    }

    # ------------------------------ the fourth kill criterion ---------------
    # "L1 cannot be trained on the available accelerator within 12 hours."
    # **The arm is ten trainings, not five.** Every arm has a main fit and a
    # no-firmware fit, because OOD-B is measured against a retrained arm as
    # R-TM-01 defined it. The twelve hours is read against the whole arm rather
    # than one seed, because the criterion says "L1 cannot be trained on the
    # available accelerator within 12 hours" and L1 is an arm of five seeds, not
    # a seed. Step 3's 0.8971 h is the main five only; it was partial because the
    # no-fw requirement surfaced after it was written.
    budget = None
    if args.step3:
        m = json.load(open(os.path.join(args.step3, "step3_l1_main.json")))
        n = json.load(open(os.path.join(args.step3, "step3_l1_nofw.json")))
        main_h = {r["seed"]: r["train_hours"] for r in m["runs"]}
        nofw_h = {r["seed"]: r["train_hours"] for r in n["runs"]}
        tot = sum(main_h.values()) + sum(nofw_h.values())
        budget = {
            "criterion": "L1 cannot be trained on the available accelerator within 12 hours",
            "reading": "the twelve hours is the whole arm (orchestrator, 21.09.2026)",
            "arm_is_n_trainings": len(main_h) + len(nofw_h),
            "why_ten": ("OOD-B is measured against a retrained arm as R-TM-01 defined "
                        "it, so every seed has a main fit and a no-firmware fit"),
            "main_hours_per_seed": main_h, "nofw_hours_per_seed": nofw_h,
            "main_five_hours": float(sum(main_h.values())),
            "nofw_five_hours": float(sum(nofw_h.values())),
            "total_hours_all_ten": float(tot),
            "budget_hours": 12.0,
            "fraction_of_budget": float(tot / 12.0),
            "fires": bool(tot > 12.0),
            "step3_reported_main_five_only": m["total"]["train_hours_all_seeds"],
            "step3_figure_was_partial": (
                "step 3 reported %.4f h for the main five; the no-fw requirement "
                "surfaced afterwards, so that figure is a part of the arm, not the arm"
                % m["total"]["train_hours_all_seeds"]),
        }
    kill["L1_not_trainable_within_12h"] = bool(budget["fires"]) if budget else None
    out = {
        "experiment": "R-LAYA-01", "step": "4-verdict",
        "criteria_commit": "e12d153", "criteria_original": "7b85d29",
        "route_threshold": workload.ROUTE_THRESHOLD, "ece_bins": metrics.N_BINS,
        "gated_ece": "ece_conf_half, 10 equal-width bins over [0.5, 1.0]",
        "shipped_temperature": raw["shipped_temperature"],
        "shipped_temperature_source": raw["shipped_temperature_source"],
        "seeds": workload.SEEDS,
        "summary": summary, "C1": c1, "C2": c2,
        "C2_literal_test_id_baseline_for_ood_b": c2_literal,
        "C3": c3, "C4": c4, "latency": lat,
        "single_configuration_view": single,
        "L1_acceptance": l1, "kill_criteria": kill, "training_budget": budget,
        "arm_t_provenance": armt["provenance_caveat"],
        "examples": raw["examples"],
    }
    with open(os.path.join(args.out_dir, "step4_summary.json"), "w") as f:
        json.dump(out, f, indent=2)

    try:
        diagrams(per_seed, variants, args.out_dir)
        out["reliability_diagrams"] = "reliability_test_id.png, reliability_ood.png"
    except Exception as e:  # a missing plotting library is not a measurement failure
        out["reliability_diagrams_error"] = repr(e)
    with open(os.path.join(args.out_dir, "step4_summary.json"), "w") as f:
        json.dump(out, f, indent=2)

    print(json.dumps({"C1": c1, "C2_L1": c2["L1"], "C3_L1": c3["L1"], "C4": c4,
                      "L1_acceptance": l1, "kill": kill, "budget": budget,
                      "single": single}, indent=2))


def diagrams(per_seed, variants, out_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def bins_for(arm, split, var):
        acc, conf, n = np.zeros(metrics.N_BINS), np.zeros(metrics.N_BINS), np.zeros(metrics.N_BINS)
        for sr in per_seed:
            cell = sr["arms"][arm][split]
            rel = cell.get(var, cell["raw"])["reliability"]
            for i, b in enumerate(rel):
                if b["n"]:
                    acc[i] += b["acc"] * b["n"]
                    conf[i] += b["conf"] * b["n"]
                    n[i] += b["n"]
        m = n > 0
        return conf[m] / n[m], acc[m] / n[m], n[m]

    for fname, splits in (("reliability_test_id.png", ("test_id",)),
                          ("reliability_ood.png", ("ood_a", "ood_b"))):
        fig, axes = plt.subplots(1, len(splits), figsize=(6 * len(splits), 5), squeeze=False)
        for j, split in enumerate(splits):
            ax = axes[0][j]
            ax.plot([0.5, 1.0], [0.5, 1.0], "k--", lw=1, label="perfect")
            for arm in ARMS:
                var = "s3" if "s3" in variants[arm] else "raw"
                try:
                    c, a, _ = bins_for(arm, split, var)
                except Exception:
                    continue
                if len(c):
                    ax.plot(c, a, "o-", label=f"{arm} ({var})")
            ax.set_xlabel("confidence"); ax.set_ylabel("accuracy")
            ax.set_title(f"{split} — 10 equal-width bins on [0.5, 1.0]")
            ax.set_xlim(0.5, 1.0); ax.set_ylim(0.0, 1.02); ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, fname), dpi=130)
        plt.close(fig)


if __name__ == "__main__":
    main()
