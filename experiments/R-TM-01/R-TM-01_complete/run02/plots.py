"""Figures for R-TM-01: reliability diagrams, OOD confidence, risk-coverage."""
import json, os, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import generator as G
import experiment as E
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

SEEDS = [0, 1, 2, 3, 4]
INK, MUTED, GRID = "#1c1c1c", "#5e5e5e", "#d8d8d8"
C = {"TM": "#2f6fa8", "TM_scaled": "#7a5ba6", "LR": "#c8701c", "GBT": "#3f8f5f"}

plt.rcParams.update({
    "figure.dpi": 140, "savefig.dpi": 140, "font.size": 9,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
})


def load_pooled(outdir):
    d = {k: [] for k in ["p_tm_id", "p_tm_temp_id", "y_id", "p_tm_a", "y_a",
                         "p_tm_b", "y_b", "p_lr_id", "p_gbt_id"]}
    for s in SEEDS:
        z = np.load(os.path.join(outdir, f"preds_seed{s}.npz"))
        for k in d:
            d[k].append(z[k])
    return {k: np.concatenate(v) for k, v in d.items()}


def reliability_panel(ax, probs, y, color, title):
    bins = E.reliability(probs, y, 10)
    xs = [b["conf"] for b in bins if b["n"] > 0]
    ys = [b["acc"] for b in bins if b["n"] > 0]
    ns = np.array([b["n"] for b in bins if b["n"] > 0], dtype=float)
    ax.plot([0.5, 1], [0.5, 1], ls="--", lw=1, color=MUTED, zorder=1)
    ax.plot(xs, ys, lw=2, color=color, zorder=3)
    ax.scatter(xs, ys, s=20 + 120 * ns / ns.max(), color=color,
               edgecolor="white", linewidth=1.2, zorder=4)
    ax.set_xlim(0.48, 1.02); ax.set_ylim(min(0.38, min(ys) - 0.05), 1.02)
    ax.set_title(f"{title}   ECE {E.ece(probs, y):.3f}", loc="left", fontsize=9)
    ax.set_xlabel("mean confidence in bin"); ax.set_ylabel("accuracy in bin")


def fig_reliability(P, path):
    fig, axes = plt.subplots(2, 2, figsize=(7.6, 6.4))
    reliability_panel(axes[0, 0], P["p_tm_id"], P["y_id"], C["TM"],
                      "TM — class-sum confidence")
    reliability_panel(axes[0, 1], P["p_tm_temp_id"], P["y_id"],
                      C["TM_scaled"], "TM — temperature-scaled (1 param)")
    reliability_panel(axes[1, 0], P["p_lr_id"], P["y_id"], C["LR"],
                      "Logistic regression")
    reliability_panel(axes[1, 1], P["p_gbt_id"], P["y_id"], C["GBT"],
                      "Gradient-boosted trees")
    fig.suptitle("Reliability on Test-ID, 10 bins, 5 seeds pooled (10,000 samples)",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "Marker area ∝ samples in bin. Dashed line = perfect "
             "calibration.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.03, 1, 0.96]); fig.savefig(path); plt.close(fig)


def fig_confidence(P, outdir, path):
    """TM and GBT confidence on Test-ID vs the two out-of-domain sets.

    The OOD-B panel belongs to the no-fw retrained model, so its like-for-like
    reference is that model's own Test-ID confidence, drawn as a dashed line."""
    S = json.load(open(os.path.join(outdir, "summary.json")))["summary"]
    ref_nofw = {"Tsetlin machine": S["TM"]["test_id_nofw"]["mean_conf"][0],
                "Gradient-boosted trees": S["GBT"]["test_id_nofw"]["mean_conf"][0]}
    gbt = {"id": [], "a": [], "b": []}
    for s in SEEDS:
        d = G.build_all(s)
        m = HistGradientBoostingClassifier(random_state=s).fit(
            d["train"][0], d["train"][1])
        m2 = HistGradientBoostingClassifier(random_state=s).fit(
            d["train_nofw"][0], d["train_nofw"][1])
        f = lambda mm, X: np.maximum(mm.predict_proba(X)[:, 1],
                                     1 - mm.predict_proba(X)[:, 1])
        gbt["id"].append(f(m, d["test_id"][0]))
        gbt["a"].append(f(m, d["ood_a"][0]))
        gbt["b"].append(f(m2, d["ood_b"][0]))
    gbt = {k: np.concatenate(v) for k, v in gbt.items()}
    conf = lambda p: np.maximum(p, 1 - p)
    rows = [("Tsetlin machine", C["TM"],
             [conf(P["p_tm_id"]), conf(P["p_tm_a"]), conf(P["p_tm_b"])]),
            ("Gradient-boosted trees", C["GBT"],
             [gbt["id"], gbt["a"], gbt["b"]])]
    titles = ["Test-ID (seen distribution)", "OOD-A: attempt = 3 (unseen value)",
              "OOD-B: domain = fw (unseen category)"]
    fig, axes = plt.subplots(2, 3, figsize=(9.6, 5.2), sharex=True, sharey="row")
    for r, (name, color, data) in enumerate(rows):
        for c, (vals, t) in enumerate(zip(data, titles)):
            ax = axes[r, c]
            ax.hist(vals, bins=np.linspace(0.5, 1.0, 26), color=color,
                    alpha=0.85, edgecolor="white", linewidth=0.4)
            mu = vals.mean()
            ax.axvline(mu, color=INK, lw=1.4)
            ax.annotate(f"mean {mu:.3f}", xy=(mu, ax.get_ylim()[1] * 0.92),
                        xytext=(4, 0), textcoords="offset points", fontsize=8)
            if r == 0:
                ax.set_title(t, loc="left", fontsize=9)
            if c == 0:
                ax.set_ylabel(f"{name}\nsamples", fontsize=9)
            if c == 2:
                ax.axvline(ref_nofw[name], color=INK, lw=1.2, ls="--")
                ax.annotate(f"same-model\nTest-ID {ref_nofw[name]:.3f}",
                            xy=(ref_nofw[name], ax.get_ylim()[1] * 0.60),
                            xytext=(-6, 0), textcoords="offset points",
                            ha="right", fontsize=8, color=MUTED)
            if r == 1:
                ax.set_xlabel("confidence in predicted class")
    fig.suptitle("Confidence in-distribution vs out-of-domain (5 seeds pooled)",
                 x=0.01, ha="left", fontsize=10)
    fig.text(0.01, 0.01, "A3 asks for a drop of at least 0.15 from Test-ID to "
             "each OOD set, on the same model.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=[0, 0.04, 1, 0.95]); fig.savefig(path); plt.close(fig)


def fig_risk_coverage(P, path):
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for key, name in [("p_tm_id", "TM"), ("p_lr_id", "LR"), ("p_gbt_id", "GBT")]:
        p, y = P[key], P["y_id"]
        conf = np.maximum(p, 1 - p)
        correct = ((p >= 0.5).astype(int) == y).astype(float)
        order = np.argsort(-conf, kind="stable")
        acc = np.cumsum(correct[order]) / np.arange(1, len(y) + 1)
        cov = np.arange(1, len(y) + 1) / len(y)
        m = cov >= 0.05
        ax.plot(cov[m], acc[m], lw=2, color=C[name], label=name)
        i = int(0.80 * len(y)) - 1
        ax.scatter([cov[i]], [acc[i]], s=42, color=C[name], edgecolor="white",
                   zorder=5)
    ax.axvline(0.80, color=MUTED, ls="--", lw=1)
    ax.annotate("80% coverage\n(A4 abstains on the lowest 20%)", xy=(0.80, 0.90),
                xytext=(-8, 0), textcoords="offset points", ha="right",
                fontsize=8, color=MUTED)
    ax.set_xlabel("coverage (fraction of Test-ID kept, most confident first)")
    ax.set_ylabel("accuracy on kept samples")
    ax.set_title("Risk-coverage on Test-ID, 5 seeds pooled", loc="left",
                 fontsize=10)
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(path); plt.close(fig)


if __name__ == "__main__":
    outdir = sys.argv[1]
    P = load_pooled(outdir)
    fig_reliability(P, os.path.join(outdir, "fig1_reliability.png"))
    fig_confidence(P, outdir, os.path.join(outdir, "fig2_confidence_ood.png"))
    fig_risk_coverage(P, os.path.join(outdir, "fig3_risk_coverage.png"))
    print("figures written")
