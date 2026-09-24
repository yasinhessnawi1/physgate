"""Step 4 — arm T's half of the measurement, in arm T's own environment.

The amended CRITERIA §3 requires arm T to run under Python 3.11.15 with its own
pinned packages, which is not the environment the Laya arms need. So arm T is
scored here — but **it does not construct the splits**. `measure.py` constructs
them once and exports the bit matrices and labels to `splits_seed{s}.npz`; this
script loads those arrays. There is one construction of the test splits in this
experiment and it is in `measure.py`.

Scoring follows `run_b.py` exactly: the main model scores `test_id` and `ood_a`,
the no-firmware retrain scores `test_id_nofw` and `ood_b`, probabilities come
from the class sums via `tm_probs`, and the §3 temperature is applied to
`clip(class_sum, -T, T) / T`.

Usage:  python measure_arm_t.py <out_dir> --step2 DIR
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import os
import pickle  # noqa: S403 - loads only this experiment's own step-2 artefacts.
import platform
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import metrics, workload  # noqa: E402

TEST_SPLITS = ("test_id", "test_id_nofw", "ood_a", "ood_b")
MAIN_SPLITS = ("test_id", "ood_a")


def tm_probs(class_sums, T):
    """VERBATIM from run05d/experiment.py:tm_probs."""
    v = np.clip(class_sums[:, 1], -T, T).astype(float)
    return np.clip(0.5 * (1.0 + v / T), 0.0, 1.0)


def tm_score(class_sums, T):
    """VERBATIM from run_b.py's ``z`` lambda."""
    return np.clip(class_sums[:, 1], -T, T) / T


def scored(probs, y):
    out = metrics.score_all(np.asarray(probs, dtype=float), np.asarray(y),
                            workload.ROUTE_THRESHOLD)
    out["reliability"] = metrics.reliability(np.asarray(probs, dtype=float),
                                             np.asarray(y), metrics.N_BINS)
    return out


def pct(ts):
    a = np.array(ts, dtype=float)
    return {"n": int(len(a)), "p50_ms": float(np.percentile(a, 50)),
            "p90_ms": float(np.percentile(a, 90)), "p99_ms": float(np.percentile(a, 99)),
            "mean_ms": float(a.mean()), "min_ms": float(a.min()), "max_ms": float(a.max())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--step2", required=True)
    ap.add_argument("--latency-n", type=int, default=200)
    args = ap.parse_args()

    import scipy
    import sklearn
    import tmu  # noqa: F401
    step2t = json.load(open(os.path.join(args.step2, "step2_arm_t.json")))
    HP = step2t["fits"][0]["hp"]
    T = HP["T"]
    temps = {r["seed"]: {"main": r["fits"]["main"]["temperature_fitted"],
                         "nofw": r["fits"]["nofw"]["temperature_fitted"]}
             for r in step2t["fits"]}
    fp = {r["seed"]: {"main": r["fits"]["main"]["train_class_sums_sha256"],
                      "nofw": r["fits"]["nofw"]["train_class_sums_sha256"]}
          for r in step2t["fits"]}

    rec = {
        "experiment": "R-LAYA-01", "step": "4-measurement", "arm": "T",
        "criteria_commit": "e12d153",
        "hp": HP, "route_threshold": workload.ROUTE_THRESHOLD,
        "env": {"python": platform.python_version(), "platform": platform.platform(),
                "node": subprocess.run(["hostname"], capture_output=True,
                                       text=True).stdout.strip(),
                "tmu": md.version("tmu"), "numpy": np.__version__,
                "scikit_learn": sklearn.__version__, "scipy": scipy.__version__},
        "provenance_caveat": (
            "CRITERIA §9: the configuration rerun here was selected in a region first "
            "identified with the out-of-distribution sets in hand, so these numbers are "
            "a transferability check of a known answer, not an independent result. "
            "R-TM-01 recorded no hardware at all, so the latency below is a fresh "
            "measurement on a named machine, not a reproduction of anything."),
        "splits_source": "splits_seed{s}.npz, exported by measure.py; not reconstructed",
        "per_seed": [], "latency": {},
    }

    for s in workload.SEEDS:
        z = np.load(os.path.join(args.out_dir, f"splits_seed{s}.npz"))
        seed_rec = {"seed": s, "splits": {}}
        for split in TEST_SPLITS:
            tag = "main" if split in MAIN_SPLITS else "nofw"
            with open(os.path.join(args.step2, f"T_{tag}_seed{s}.pkl"), "rb") as f:
                tm = pickle.load(f)
            X, y = z[f"X_{split}"], z[f"y_{split}"]
            _, cs = tm.predict(X, return_class_sums=True)
            cs = np.asarray(cs)
            p_raw = tm_probs(cs, T)
            p_s3 = metrics.apply_temperature(temps[s][tag], tm_score(cs, T))
            seed_rec["splits"][split] = {
                "raw": scored(p_raw, y), "s3": scored(p_s3, y),
                "temperature_s3": float(temps[s][tag]),
                "model": f"T_{tag}_seed{s}",
                "train_class_sums_sha256_from_step2": fp[s][tag]}
            np.savez_compressed(
                os.path.join(args.out_dir, f"probs_T_{split}_seed{s}.npz"),
                class_sums=cs, p_raw=p_raw, p_s3=p_s3, y=y)
            if s == 0 and split == "test_id":
                ts = []
                for i in range(args.latency_n):
                    t0 = time.perf_counter()
                    tm.predict(X[i:i + 1], return_class_sums=True)
                    ts.append((time.perf_counter() - t0) * 1000.0)
                rec["latency"]["T"] = pct(ts)
        rec["per_seed"].append(seed_rec)
        print("seed", s, "done", flush=True)

    with open(os.path.join(args.out_dir, "step4_arm_t.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(json.dumps({"env": rec["env"], "latency": rec["latency"]}, indent=2))


if __name__ == "__main__":
    main()
