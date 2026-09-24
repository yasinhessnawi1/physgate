"""Step 2 — fit arm T on Train, in arm T's own environment.

CRITERIA §3, as amended at `e12d153`: *"Tsetlin machine, the configuration
R-TM-01d selected. **Rerun in its own environment, not this project's**: Python
3.11.15 with `tmu==0.8.3`, `numpy==2.4.6`, `scikit-learn==1.9.1`,
`scipy==1.17.1`, `matplotlib==3.11.2` and the two `tmu` source patches recorded
in R-TM-01's config, because that is the environment that produced the numbers
being rerun. The machine it runs on is recorded in the resolved config."*

R-TM-01 recorded its software environment in full and **its hardware not at
all**, which is why §6 says the timings here are a fresh measurement on a named
machine rather than a reproduction of anything. The machine is recorded below.

Two fits per seed, both on Train, exactly as `run_b.py` does them: the main
model on Train, and the no-firmware retrain on Train-without-fw that OOD-B is
measured against at step 4.

Usage:  python fit_arm_t.py <out_dir>
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
import pickle
import platform
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import metrics, workload  # noqa: E402

# The configuration R-TM-01d selected, from run05d/config.json
# ["selected_config_evaluation"]["hp"].
HP = {"clauses": 500, "T": 40, "s": 2.0, "epochs": 60}


def tm_probs(class_sums, T):
    """VERBATIM from run05d/experiment.py:tm_probs — Helin et al. class-sum confidence."""
    v = np.clip(class_sums[:, 1], -T, T).astype(float)
    return np.clip(0.5 * (1.0 + v / T), 0.0, 1.0)


def tm_score(class_sums, T):
    """The temperature-scaling score for the TM, as `run_b.py` defines it.

    `run_b.py`:  ``z = lambda cs: np.clip(cs[:, 1], -T, T) / T``  then
    ``fit_temperature(z(cs_tr)[:CAL_N], ytr[:CAL_N])``. Reproduced exactly so
    arm T's calibration is the one R-TM-01 measured.
    """
    return np.clip(class_sums[:, 1], -T, T) / T


def check_patches():
    """The two `tmu` patches R-TM-01 recorded, verified in the installed package.

    run02/config.json: *"tmu 0.8.3 patched for numpy>=2: np.uint32(~0) ->
    np.uint32(0xFFFFFFFF) in clause_bank/clause_bank.py:136,145 and
    clause_bank_cuda.py:169; tmu hangs when its internal seed is 0, so TM seeds
    are 1000+seed"*.

    The second is a convention, not a source change, and is applied by
    `workload.TM_SEED_OFFSET`. The first is a source change and is applied here,
    to the installed copy, with the before-and-after recorded.
    """
    import tmu
    root = os.path.dirname(tmu.__file__)
    out = {"tmu_root": root, "files": {}}
    for rel in ("clause_bank/clause_bank.py", "clause_bank/clause_bank_cuda.py"):
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            out["files"][rel] = {"present": False}
            continue
        src = open(p).read()
        before = sha256_text(src)
        n = src.count("np.uint32(~0)")
        if n:
            src = src.replace("np.uint32(~0)", "np.uint32(0xFFFFFFFF)")
            open(p, "w").write(src)
        out["files"][rel] = {
            "present": True,
            "occurrences_of_np_uint32_tilde_0": n,
            "sha256_before": before,
            "sha256_after": sha256_text(open(p).read()),
            "patched_now": bool(n),
        }
    out["seed_patch"] = {
        "kind": "convention, not a source change",
        "rule": "TM seed = 1000 + data seed, because tmu hangs when its internal seed is 0",
        "offset": workload.TM_SEED_OFFSET,
    }
    return out


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def sha256_array(a) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64).tobytes()).hexdigest()


def vendor_equivalence():
    """Assert `metrics.py`'s copies behave identically to `vendor/experiment.py`.

    `metrics.py` copies six functions out of `experiment.py` because that module
    imports `tmu` at module scope and so cannot be imported in the Python 3.12
    environment the Laya arms use. This environment *has* `tmu`, so here the two
    can be run side by side. If they ever disagree, the copies are wrong and
    every number that used them is wrong.
    """
    sys.path.insert(0, os.path.join(HERE, "vendor"))
    import experiment as E

    rng = np.random.default_rng(7)
    p = rng.random(2000)
    y = (rng.random(2000) < p).astype(np.uint32)
    z = rng.normal(size=2000)
    checks = {
        "ece": (E.ece(p, y, 10), metrics.ece_conf_half(p, y, 10)),
        "ece_prob_bins": (E.ece_prob_bins(p, y, 10), metrics.ece_prob_bins(p, y, 10)),
        "mean_confidence": (E.mean_confidence(p), metrics.mean_confidence(p)),
        "fit_temperature": (E.fit_temperature(z, y), metrics.fit_temperature(z, y)),
    }
    t = checks["fit_temperature"][0]
    checks["apply_temperature"] = (float(E.apply_temperature(t, z).sum()),
                                   float(metrics.apply_temperature(t, z).sum()))
    _, _, _, raw, _ = workload.train_only(0)
    checks["rule_arm"] = (float(E.rule_arm(raw).sum()), float(metrics.rule_arm(raw).sum()))
    out = {k: {"vendor": v[0], "copy": v[1], "identical": v[0] == v[1]}
           for k, v in checks.items()}
    bad = [k for k, v in out.items() if not v["identical"]]
    if bad:
        raise RuntimeError("metrics.py copies disagree with vendor/experiment.py: %s" % bad)
    return out


def fit_seed(seed, outdir):
    from tmu.models.classification.vanilla_classifier import TMClassifier

    Xtr, ytr = workload.train_only(seed)[0], workload.train_only(seed)[1]
    Xtr2, ytr2 = workload.train_nofw_only(seed)[0], workload.train_nofw_only(seed)[1]
    T = HP["T"]
    tm_seed = workload.TM_SEED_OFFSET + seed

    res = {"arm": "T", "seed": seed, "tm_seed": tm_seed, "hp": dict(HP)}
    out = {}
    for tag, (X, y) in (("main", (Xtr, ytr)), ("nofw", (Xtr2, ytr2))):
        t0 = time.perf_counter()
        tm = TMClassifier(number_of_clauses=HP["clauses"], T=T, s=HP["s"],
                          platform="CPU", weighted_clauses=False, seed=tm_seed)
        tm.fit(X, y, epochs=HP["epochs"])
        secs = time.perf_counter() - t0

        pred, cs = tm.predict(X, return_class_sums=True)
        pred, cs = np.asarray(pred), np.asarray(cs)
        probs = tm_probs(cs, T)
        out[tag] = {
            "fit_seconds": secs, "n_train": int(len(y)),
            "train_accuracy_in_sample": float((pred == y).mean()),
            "train_mean_confidence_in_sample": metrics.mean_confidence(probs),
            # The fingerprint step 4 checks a refit against, so the model does not
            # have to survive a pickle to be the same model.
            "train_class_sums_sha256": sha256_array(cs),
        }
        sl = workload.calibration_slice()
        z = tm_score(cs, T)
        out[tag]["temperature_fitted"] = float(metrics.fit_temperature(z[sl], y[sl]))
        np.savez_compressed(os.path.join(outdir, f"T_{tag}_trainscores_seed{seed}.npz"),
                            class_sums=cs, score=z, y=y)
        try:
            with open(os.path.join(outdir, f"T_{tag}_seed{seed}.pkl"), "wb") as f:
                pickle.dump(tm, f)
            out[tag]["pickled"] = True
        except Exception as e:  # tmu holds C-extension state; a refit is the fallback
            out[tag]["pickled"] = False
            out[tag]["pickle_error"] = repr(e)
    res["fits"] = out
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    import scipy
    import sklearn
    import tmu
    rec = {
        "experiment": "R-LAYA-01", "step": "2-fixture-and-arms", "arm": "T",
        "criteria_commit": "e12d153",
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "node": subprocess.run(["hostname"], capture_output=True,
                                   text=True).stdout.strip(),
            "tmu": md.version("tmu"), "numpy": np.__version__,
            "scikit_learn": sklearn.__version__, "scipy": scipy.__version__,
            "matplotlib": md.version("matplotlib"),
            "tmu_module": tmu.__file__,
        },
        "hardware_note": (
            "R-TM-01 recorded its software environment in full and its hardware not at "
            "all. CRITERIA §6: arm T's timings here are a fresh measurement on a named "
            "machine, not a reproduction of anything."),
        "hardware": {},
        "tmu_patches": check_patches(),
        "hp_source": "run05d/config.json selected_config_evaluation.hp",
        "seeds": workload.SEEDS,
        "draw_fingerprint": {},
        "vendor_equivalence": None,
        "fits": [],
    }
    try:
        rec["hardware"]["cpu_model"] = subprocess.run(
            ["bash", "-lc", "lscpu | grep -m1 'Model name'"],
            capture_output=True, text=True).stdout.strip()
        rec["hardware"]["nproc"] = subprocess.run(
            ["nproc"], capture_output=True, text=True).stdout.strip()
        rec["hardware"]["mem_total"] = subprocess.run(
            ["bash", "-lc", "grep MemTotal /proc/meminfo"],
            capture_output=True, text=True).stdout.strip()
        rec["hardware"]["cgroup_cpu_max"] = open("/sys/fs/cgroup/cpu.max").read().strip()
    except Exception as e:
        rec["hardware"]["error"] = repr(e)

    rec["vendor_equivalence"] = vendor_equivalence()
    print("vendor equivalence OK", flush=True)

    for s in workload.SEEDS:
        rec["draw_fingerprint"][str(s)] = workload.draw_fingerprint(s)
        t0 = time.perf_counter()
        r = fit_seed(s, args.out_dir)
        r["seed_total_seconds"] = time.perf_counter() - t0
        rec["fits"].append(r)
        print("seed %d done in %.1fs  train acc main %.4f  temp %.4f"
              % (s, r["seed_total_seconds"],
                 r["fits"]["main"]["train_accuracy_in_sample"],
                 r["fits"]["main"]["temperature_fitted"]), flush=True)

    with open(os.path.join(args.out_dir, "step2_arm_t.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(json.dumps({"env": rec["env"], "hardware": rec["hardware"],
                      "patches": rec["tmu_patches"],
                      "fingerprint_seed0": rec["draw_fingerprint"]["0"],
                      "fit_seed0": rec["fits"][0]}, indent=2))


if __name__ == "__main__":
    main()
