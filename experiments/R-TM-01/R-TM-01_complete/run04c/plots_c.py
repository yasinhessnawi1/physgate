"""Figures for R-TM-01c: reliability, routing, the sweep landscape, autonomy."""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plots_b import pooled, fig_reliability, fig_routing, INK, MUTED, C

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140, "font.size": 9,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": "#d8d8d8", "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
})


def fig_sweep(sweep, path):
    """What the humility floor selected, and what it excluded."""
    grid, best, floor = sweep["grid"], sweep["best"], sweep["floor"]
    x = [min(r["pseudo_ood_a_drop"], r["pseudo_ood_b_drop"]) for r in grid]
    y = [r["val_acc"] for r in grid]
    q = [r["qualifies"] for r in grid]
    fig, ax = plt.subplots(figsize=(7.0, 4.6))
    ax.axvspan(floor, max(x) + 0.02, color=C["TM"], alpha=0.06)
    ax.scatter([a for a, k in zip(x, q) if not k], [b for b, k in zip(y, q) if not k],
               s=34, color=MUTED, alpha=0.55, label="below the humility floor")
    ax.scatter([a for a, k in zip(x, q) if k], [b for b, k in zip(y, q) if k],
               s=44, color=C["TM"], edgecolor="white", linewidth=0.8,
               label=f"meets the {floor:.2f} floor on both pseudo-OOD slices")
    bx = min(best["pseudo_ood_a_drop"], best["pseudo_ood_b_drop"])
    ax.scatter([bx], [best["val_acc"]], s=150, facecolor="none", edgecolor=INK,
               linewidth=1.6, zorder=6)
    ax.annotate(f"selected: {best['clauses']} clauses, T={best['T']}, s={best['s']}",
                (bx, best["val_acc"]), xytext=(-12, -14), textcoords="offset points",
                ha="right", fontsize=8)
    tie = [r for r in grid if not r["qualifies"]
           and abs(r["val_acc"] - best["val_acc"]) < 1e-9]
    for r in tie:
        tx = min(r["pseudo_ood_a_drop"], r["pseudo_ood_b_drop"])
        ax.annotate(f"same accuracy, {floor - tx:.3f} under the floor\n"
                    f"(T={r['T']}, s={r['s']}) — fails A3 on test",
                    (tx, r["val_acc"]), xytext=(4, -30), textcoords="offset points",
                    ha="left", fontsize=8, color=MUTED,
                    arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.axvline(floor, color=INK, ls="--", lw=1)
    ax.set_xlabel("min pseudo-OOD confidence drop (measured inside train)")
    ax.set_ylabel("validation accuracy")
    ax.set_title("The sweep landscape: 48 configurations, 12 qualifying",
                 loc="left", fontsize=10)
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    fig.text(0.01, 0.01, "No test split is used anywhere in this plot; both axes are "
             "computed inside the 8,000-row training split.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.04, 1, 1]); fig.savefig(path); plt.close(fig)


def fig_autonomy(runs, path):
    """How much the gate decides by itself, and how often it is right there."""
    splits = [("p_tm_id", "y_id", "Test-ID"), ("p_tm_a", "y_a", "OOD-A\nattempt = 3"),
              ("p_tm_b", "y_b", "OOD-B\ndomain = fw")]
    data = {}
    for label, run in runs:
        rows = []
        for kp, ky, _ in splits:
            keep_f, acc_k = [], []
            for s in range(5):
                z = np.load(f"runs/{run}/preds_seed{s}.npz")
                p, y = z[kp], z[ky]
                c = np.maximum(p, 1 - p); keep = c >= 0.8
                pred = (p >= 0.5).astype(int)
                keep_f.append(keep.mean())
                acc_k.append((pred[keep] == y[keep]).mean() if keep.sum() else np.nan)
            rows.append((float(np.mean(keep_f)), float(np.nanmean(acc_k))))
        data[label] = rows

    x = np.arange(len(splits)); w = 0.38
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.8))
    for ax, idx, title, ylab in [
            (axes[0], 0, "Decided without a human", "fraction of decisions kept"),
            (axes[1], 1, "Accuracy on those decisions", "accuracy where it did not ask")]:
        for k, (label, _) in enumerate(runs):
            vals = [data[label][i][idx] for i in range(len(splits))]
            color = C["LR"] if k == 0 else C["TM"]
            bars = ax.bar(x + (k - 0.5) * w, vals, w * 0.92, color=color, label=label,
                          edgecolor="white", linewidth=0.8)
            for b, v in zip(bars, vals):
                ax.annotate(f"{v:.2f}", (b.get_x() + b.get_width() / 2, v), fontsize=8,
                            ha="center", va="bottom", xytext=(0, 2),
                            textcoords="offset points")
        ax.set_xticks(x); ax.set_xticklabels([s[2] for s in splits], fontsize=8)
        ax.set_ylim(0, 1.12); ax.set_ylabel(ylab)
        ax.set_title(title, loc="left", fontsize=9)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle("At the 0.8 routing threshold: what the gate keeps, and whether it is right",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "R-TM-01c keeps far fewer out-of-domain decisions than "
             "R-TM-01b and is right on almost all of the ones it keeps.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.05, 1, 0.93]); fig.savefig(path); plt.close(fig)


if __name__ == "__main__":
    outdir = sys.argv[1]
    S = json.load(open(os.path.join(outdir, "summary.json")))["summary"]
    sweep = json.load(open(os.path.join(outdir, "sweep.json")))
    fig_reliability(pooled(outdir), os.path.join(outdir, "fig1_reliability.png"))
    fig_routing(S, os.path.join(outdir, "fig2_routing.png"))
    fig_sweep(sweep, os.path.join(outdir, "fig3_sweep_landscape.png"))
    fig_autonomy([("R-TM-01b (T=20)", "run03b"), ("R-TM-01c (T=40)", "run04c")],
                 os.path.join(outdir, "fig4_autonomy.png"))
    print("figures written")
