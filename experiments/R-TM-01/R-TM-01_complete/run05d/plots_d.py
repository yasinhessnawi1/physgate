"""Figures for R-TM-01d: the feasible set per replicate, and paired accuracy."""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

INK, MUTED, GRID = "#1c1c1c", "#5e5e5e", "#d8d8d8"
C = {"TM": "#2f6fa8", "alt": "#c8701c", "ok": "#3f8f5f"}

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140, "font.size": 9,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
})


def fig_feasible(sweep, path):
    reps = ["1000", "1001", "1002"]
    floor_h = sweep["rule"]["humility_floor"]
    floor_a = sweep["fold_baselines"]["accuracy_floor"]
    fig, axes = plt.subplots(1, 3, figsize=(11.4, 3.9), sharey=True)
    for ax, rep in zip(axes, reps):
        grid = sweep["replicates"][rep]["grid"]
        x = [min(r["pseudo_ood_a_drop"], r["pseudo_ood_b_drop"]) for r in grid]
        y = [r["val_acc"] for r in grid]
        q = [r["qualifies"] for r in grid]
        ax.axhline(floor_a, color=INK, ls="--", lw=1)
        ax.axvline(floor_h, color=INK, ls="--", lw=1)
        ax.scatter([a for a, k in zip(x, q) if not k],
                   [b for b, k in zip(y, q) if not k],
                   s=28, color=MUTED, alpha=0.5)
        ax.scatter([a for a, k in zip(x, q) if k], [b for b, k in zip(y, q) if k],
                   s=70, color=C["ok"], edgecolor="white", linewidth=1.0, zorder=5)
        n = sweep["replicates"][rep]["n_qualifying"]
        sel = sweep["replicates"][rep]["selected"]
        title = (f"sweep seed {rep} — {n} of 48 qualify" if n else
                 f"sweep seed {rep} — none qualify")
        ax.set_title(title, loc="left", fontsize=9,
                     color=INK if n else C["alt"])
        if sel:
            ax.annotate(f"{sel['clauses']} clauses, T={sel['T']}, s={sel['s']}",
                        (min(sel["pseudo_ood_a_drop"], sel["pseudo_ood_b_drop"]),
                         sel["val_acc"]), xytext=(-8, -14),
                        textcoords="offset points", ha="right", fontsize=8)
        ax.set_xlabel("min pseudo-OOD confidence drop")
        ax.set_xlim(-0.06, 0.30)
    axes[0].set_ylabel("validation accuracy")
    axes[0].annotate("accuracy band\n(GBT − 3 pts)", (-0.055, floor_a),
                     xytext=(0, 6), textcoords="offset points", fontsize=8,
                     color=MUTED)
    axes[0].annotate("humility floor", (floor_h, 0.895), xytext=(4, 0),
                     textcoords="offset points", fontsize=8, color=MUTED)
    fig.suptitle("The feasible set, three independent runs of the same selection rule",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "Green = meets both floors. The humility floor is met by 12, 11 "
             "and 9 configurations; the accuracy band by 6, 3 and 1. The third draw "
             "leaves nothing.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93]); fig.savefig(path); plt.close(fig)


def fig_paired(stability, path):
    cfg = list(stability["configurations"].values())[0]
    pa = cfg["paired_accuracy"]
    keys = [("test_id", "Test-ID"), ("ood_a", "OOD-A\nattempt = 3"),
            ("ood_b", "OOD-B\ndomain = fw")]
    x = np.arange(len(keys)); w = 0.38
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.9))
    ax = axes[0]
    for k, (field, color, label) in enumerate([
            ("acc_split", C["alt"], "accuracy on the whole split"),
            ("acc_retained", C["TM"], "accuracy where it did not ask")]):
        vals = [pa[key][field] for key, _ in keys]
        bars = ax.bar(x + (k - 0.5) * w, vals, w * 0.92, color=color, label=label,
                      edgecolor="white", linewidth=0.8)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.3f}", (b.get_x() + b.get_width() / 2, v), fontsize=8,
                        ha="center", va="bottom", xytext=(0, 2),
                        textcoords="offset points")
    ax.set_xticks(x); ax.set_xticklabels([l for _, l in keys], fontsize=8)
    ax.set_ylim(0, 1.15); ax.set_ylabel("accuracy")
    ax.set_title("Never quote the left bar alone", loc="left", fontsize=9)
    ax.legend(frameon=False, fontsize=8, loc="lower left")

    ax = axes[1]
    vals = [pa[key]["routed_to_human"] for key, _ in keys]
    bars = ax.bar(x, vals, 0.5, color=C["TM"], edgecolor="white", linewidth=0.8)
    for b, v in zip(bars, vals):
        ax.annotate(f"{v:.3f}", (b.get_x() + b.get_width() / 2, v), fontsize=8,
                    ha="center", va="bottom", xytext=(0, 2), textcoords="offset points")
    ax.set_xticks(x); ax.set_xticklabels([l for _, l in keys], fontsize=8)
    ax.set_ylim(0, 1.0); ax.set_ylabel("fraction routed to a human")
    ax.set_title("What it hands over, at the 0.8 threshold", loc="left", fontsize=9)

    fig.suptitle("It gets worse at answering and much better at knowing when not to",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "Selected configuration, 500 clauses / T=40 / s=2.0, five seeds. "
             "Split accuracy falls off-distribution; accuracy on what it still answers "
             "does not.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93]); fig.savefig(path); plt.close(fig)


if __name__ == "__main__":
    out = sys.argv[1]
    sweep = json.load(open(os.path.join(out, "sweep.json")))
    stab = json.load(open(os.path.join(out, "stability.json")))
    fig_feasible(sweep, os.path.join(out, "fig1_feasible_set.png"))
    fig_paired(stab, os.path.join(out, "fig2_paired_accuracy.png"))
    print("figures written")
