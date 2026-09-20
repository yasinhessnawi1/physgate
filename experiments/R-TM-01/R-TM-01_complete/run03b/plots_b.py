"""Figures for R-TM-01b."""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import experiment as E

SEEDS = [0, 1, 2, 3, 4]
INK, MUTED, GRID = "#1c1c1c", "#5e5e5e", "#d8d8d8"
C = {"TM": "#2f6fa8", "TM_temp": "#7a5ba6", "LR": "#c8701c", "GBT": "#3f8f5f"}

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140, "font.size": 9,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
})


def pooled(outdir):
    keys = ["p_tm_id", "p_tm_temp_id", "y_id", "p_lr_id", "p_gbt_id"]
    d = {k: [] for k in keys}
    for s in SEEDS:
        z = np.load(os.path.join(outdir, f"preds_seed{s}.npz"))
        for k in keys:
            d[k].append(z[k])
    return {k: np.concatenate(v) for k, v in d.items()}


def panel(ax, probs, y, color, title):
    bins = E.reliability(probs, y, 10)
    xs = [b["conf"] for b in bins if b["n"] > 0]
    ys = [b["acc"] for b in bins if b["n"] > 0]
    ns = np.array([b["n"] for b in bins if b["n"] > 0], dtype=float)
    ax.plot([0.5, 1], [0.5, 1], ls="--", lw=1, color=MUTED, zorder=1)
    ax.plot(xs, ys, lw=2, color=color, zorder=3)
    ax.scatter(xs, ys, s=20 + 120 * ns / ns.max(), color=color,
               edgecolor="white", linewidth=1.2, zorder=4)
    ax.set_xlim(0.48, 1.02); ax.set_ylim(min(0.35, min(ys) - 0.05), 1.02)
    ax.set_title(f"{title}   ECE {E.ece(probs, y):.3f}", loc="left", fontsize=9)
    ax.set_xlabel("mean confidence in bin"); ax.set_ylabel("accuracy in bin")


def fig_reliability(P, path):
    fig, ax = plt.subplots(2, 2, figsize=(7.6, 6.4))
    panel(ax[0, 0], P["p_tm_id"], P["y_id"], C["TM"], "TM — class-sum confidence")
    panel(ax[0, 1], P["p_tm_temp_id"], P["y_id"], C["TM_temp"], "TM — temperature-scaled")
    panel(ax[1, 0], P["p_lr_id"], P["y_id"], C["LR"], "Logistic regression")
    panel(ax[1, 1], P["p_gbt_id"], P["y_id"], C["GBT"], "Gradient-boosted trees")
    fig.suptitle("R-TM-01b reliability on Test-ID, 10 bins, 5 seeds pooled",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "Marker area ∝ samples in bin. Dashed line = perfect calibration.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.03, 1, 0.96]); fig.savefig(path); plt.close(fig)


def fig_routing(summary, path):
    """ARCH-131's actual question: what fraction of decisions reach a human?"""
    splits = [("test_id", "Test-ID"), ("ood_a", "OOD-A\nattempt = 3"),
              ("test_id_nofw", "Test-ID\n(no-fw model)"), ("ood_b", "OOD-B\ndomain = fw"),
              ("mixed", "Mixed stream")]
    x = np.arange(len(splits)); w = 0.38
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    for k, (arm, label) in enumerate([("TM", "Tsetlin machine"),
                                      ("GBT", "Gradient-boosted trees")]):
        vals = [summary[arm][s]["route_rate_at_0.8"][0] if s in summary[arm] else 0
                for s, _ in splits]
        errs = [summary[arm][s]["route_rate_at_0.8"][1] if s in summary[arm] else 0
                for s, _ in splits]
        bars = ax.bar(x + (k - 0.5) * w, vals, w * 0.92, yerr=errs, capsize=2,
                      color=C[arm], label=label, edgecolor="white", linewidth=0.8)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v), fontsize=8,
                        ha="center", va="bottom", xytext=(0, 2),
                        textcoords="offset points")
    ax.set_xticks(x); ax.set_xticklabels([l for _, l in splits], fontsize=8)
    ax.set_ylabel("fraction of decisions routed to a human")
    ax.set_title("Routing rate at the 0.8 escalation threshold (ARCH-131)",
                 loc="left", fontsize=10)
    ax.legend(frameon=False, loc="upper left")
    fig.text(0.01, 0.01, "The TM sends roughly three times as many novel-state "
             "decisions to a human as familiar ones; the GBT sends the same "
             "near-zero share everywhere.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.04, 1, 1]); fig.savefig(path); plt.close(fig)


def fig_frontier(diag, chosen_T, path):
    f = diag["t_frontier_3seeds"]
    Ts = [int(k.split("=")[1]) for k in f]
    series = [("acc", "Test-ID accuracy", None),
              ("ece", "ECE (raw)", 0.10),
              ("drop_ood_a", "confidence drop, OOD-A", 0.15),
              ("drop_ood_b", "confidence drop, OOD-B", 0.15)]
    fig, axes = plt.subplots(1, 4, figsize=(11.2, 3.2))
    for ax, (key, title, thresh) in zip(axes, series):
        vals = [f[k][key] for k in f]
        ax.plot(Ts, vals, lw=2, color=C["TM"], marker="o", ms=5,
                markeredgecolor="white")
        if thresh is not None:
            ax.axhline(thresh, ls="--", lw=1, color=MUTED)
            ax.annotate(f"criterion {thresh:.2f}", (Ts[0], thresh), fontsize=8,
                        color=MUTED, xytext=(0, 3), textcoords="offset points")
        i = Ts.index(chosen_T)
        ax.scatter([chosen_T], [vals[i]], s=90, facecolor="none",
                   edgecolor=INK, linewidth=1.4, zorder=5)
        ax.annotate("chosen by the\naccuracy sweep", (chosen_T, vals[i]), fontsize=8,
                    xytext=(6, -18), textcoords="offset points", color=INK)
        ax.set_xscale("log"); ax.set_xticks(Ts)
        ax.set_xticklabels([str(t) for t in Ts])
        ax.set_xlabel("T"); ax.set_title(title, loc="left", fontsize=9)
    fig.suptitle("What T buys and what it costs (3 seeds, 500 clauses, s = 5)",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "Accuracy peaks at small T; out-of-domain humility needs "
             "a larger one. The sweep optimised accuracy alone and landed at T = 20.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93]); fig.savefig(path); plt.close(fig)


if __name__ == "__main__":
    outdir = sys.argv[1]
    S = json.load(open(os.path.join(outdir, "summary.json")))["summary"]
    diag = json.load(open(os.path.join(outdir, "diagnostics.json")))
    hp = json.load(open(os.path.join(outdir, "sweep.json")))["best"]
    fig_reliability(pooled(outdir), os.path.join(outdir, "fig1_reliability.png"))
    fig_routing(S, os.path.join(outdir, "fig2_routing.png"))
    fig_frontier(diag, hp["T"], os.path.join(outdir, "fig3_t_frontier.png"))
    print("figures written")
