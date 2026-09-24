"""Step 2 — fit arms G, R and L0 on Train. Nothing is scored on a test split.

`RESULT.md`'s numbers are produced at step 4. What this script produces is
fitted objects, the §3 temperature, and the artefacts needed to show the fits
were honest: the draw fingerprint, the environment, the seeds, the pins.

Usage:  python fit_arms.py <out_dir> [--model-dir DIR] [--device cuda|cpu] [--skip-l0]
"""
from __future__ import annotations

import argparse
import hashlib
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

from rlaya import fixture, metrics, workload  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def code_checksums():
    out = {}
    for name in ("fixture.py", "workload.py", "metrics.py", "laya_backend.py",
                 "fit_arms.py", "vendor/generator.py", "vendor/generator_b.py",
                 "vendor/experiment.py"):
        p = os.path.join(HERE, name)
        if os.path.exists(p):
            out[name] = sha256_file(p)
    return out


def base_env():
    import scipy
    import sklearn
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "node": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


# --------------------------------------------------------------------- G ----

def fit_g(seed, outdir):
    """HistGradientBoosting, exactly as R-TM-01's run_b.py constructs it.

    `HistGradientBoostingClassifier(random_state=seed)`, fitted on Train, and the
    no-firmware retrain on Train-without-fw that OOD-B is measured against. §3
    says G is not temperature-scaled and reports its native probabilities, so
    there is no calibration step here.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    Xtr, ytr = workload.train_only(seed)[0], workload.train_only(seed)[1]
    Xtr2, ytr2 = workload.train_nofw_only(seed)[0], workload.train_nofw_only(seed)[1]

    t0 = time.perf_counter()
    m = HistGradientBoostingClassifier(random_state=seed).fit(Xtr, ytr)
    m2 = HistGradientBoostingClassifier(random_state=seed).fit(Xtr2, ytr2)
    secs = time.perf_counter() - t0

    for tag, mm in (("main", m), ("nofw", m2)):
        with open(os.path.join(outdir, f"G_{tag}_seed{seed}.pkl"), "wb") as f:
            pickle.dump(mm, f)

    ptr = m.predict_proba(Xtr)[:, 1]
    return {
        "arm": "G", "seed": seed, "fit_seconds": secs,
        "temperature_scaled": False,
        "temperature_note": "CRITERIA §3: G is not temperature-scaled; native probabilities.",
        "n_train": int(len(ytr)), "n_train_nofw": int(len(ytr2)),
        "train_accuracy_in_sample": float(((ptr >= 0.5).astype(int) == ytr).mean()),
        "train_mean_confidence_in_sample": metrics.mean_confidence(ptr),
        "params": {k: str(v) for k, v in m.get_params().items()},
        "artefacts": [f"G_main_seed{seed}.pkl", f"G_nofw_seed{seed}.pkl"],
    }


# --------------------------------------------------------------------- R ----

def fit_r(seed):
    """Nothing to fit. Confirm the rule runs and that confidence is 1.0.

    ARCH-131: the default binding is *"exactly the deterministic conditions
    ARCH-030 and ARCH-040 already specify, emitted at confidence 1.0."* §3: *"`R`
    is deterministic and is run once"* and *"emits confidence 1.0 by
    construction."* Confidence 1.0 means R never escalates on low confidence — it
    escalates when its conditions say so, and at the 0.8 threshold it is never
    routed for uncertainty. Both facts are asserted here rather than assumed.
    """
    _, ytr, _, raw, _ = workload.train_only(seed)
    pred = metrics.rule_arm(raw)
    probs = pred.astype(float)                # 1.0 for escalate, 0.0 for not
    conf = metrics.confidence(probs)
    assert np.all(conf == 1.0), "arm R must emit confidence 1.0 by construction"
    assert set(np.unique(pred)) <= {0, 1}
    rr = metrics.routing_report(probs, ytr, workload.ROUTE_THRESHOLD)
    assert rr["escalation_rate"] == 0.0, (
        "at confidence 1.0 nothing is routed for uncertainty; R's escalations are "
        "its answer, not its confidence")
    return {
        "arm": "R", "seed": seed, "fit_seconds": 0.0,
        "deterministic": True, "nothing_fitted": True,
        "temperature_scaled": False,
        "confidence_is_1_by_construction": True,
        "rule_source": "metrics.rule_arm, verbatim from run05d/experiment.py",
        "arch_conditions": {
            "ARCH-030": "repair budget of three attempts; attempt 3 escalates -> attempt == 3",
            "ARCH-130": "gate escalation -> any of the four gates fails",
            "ARCH-040": "unresolved arbitration -> NO FIELD IN THE GENERATOR'S STATE (C5 M9)",
        },
        "train_answer_rate_in_sample": float(pred.mean()),
        "train_accuracy_in_sample": float((pred == ytr).mean()),
        "routing_at_0.8_in_sample": rr,
    }


# -------------------------------------------------------------------- L0 ----

def fit_l0(seed, outdir, model_dir, device, verify):
    """Laya zero-shot: build the pipeline and fit its §3 temperature. Not scored.

    §3: *"Temperature for L0, L1 and T is fitted on a 500-sample slice of Train
    only, drawn once with a fixed seed and identical for every arm."* The
    checkpoint's own calibration is set to identity first, so that the one fit
    §3 prescribes is the only one in force and "identical for every arm" is true
    of the whole scale and not just of the slice it was fitted on.
    """
    from rlaya import laya_backend as LB

    agent, info = LB.load_agent(model_dir, device)
    _, ytr, _, raw, _ = workload.train_only(seed)
    sl = workload.calibration_slice()
    states = [fixture.serialise(raw, i) for i in range(sl.start, sl.stop)]

    check = sens = None
    if verify:
        check = LB.verify_matches_system_one(agent, states)
        if not check["agrees"]:
            raise RuntimeError("batched path disagrees with laya.Agent.system_one: %r" % check)
        sens = LB.numeric_sensitivity(agent, states)

    t0 = time.perf_counter()
    lg = LB.logits(agent, states)
    infer_secs = time.perf_counter() - t0

    z = LB.score(lg)
    ycal = ytr[sl]
    temp = metrics.fit_temperature(z, ycal)

    np.savez_compressed(os.path.join(outdir, f"L0_calib_seed{seed}.npz"),
                        logits=lg, score=z, y=ycal)
    lens = [len(x) for x in states]
    return {
        "arm": "L0", "seed": seed,
        "agent": info,
        "calibration_slice": {"start": sl.start, "stop": sl.stop, "n": len(states),
                              "definition": "the first 500 rows of Train; see workload.calibration_slice"},
        "temperature_fitted": float(temp),
        "temperature_fit_on": "§3 slice, identity checkpoint temperature",
        "inference_seconds_for_500": infer_secs,
        "seconds_per_state": infer_secs / max(1, len(states)),
        "serialised_char_len": {"min": int(min(lens)), "max": int(max(lens)),
                                "mean": float(np.mean(lens))},
        "score_summary": {"min": float(z.min()), "max": float(z.max()),
                          "mean": float(z.mean()), "sd": float(z.std())},
        "system_one_agreement": check,
        "numeric_sensitivity": sens,
        "artefacts": [f"L0_calib_seed{seed}.npz"],
        "not_scored": "L0's metrics are produced at step 4 with every other arm.",
    }


# ------------------------------------------------------------------- main ----

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--model-dir", default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--skip-l0", action="store_true")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    rec = {
        "experiment": "R-LAYA-01", "step": "2-fixture-and-arms",
        "criteria_commit": "e12d153", "criteria_original": "7b85d29",
        "env": base_env(), "code_checksums": code_checksums(),
        "route_threshold": workload.ROUTE_THRESHOLD,
        "seeds": workload.SEEDS,
        "fixture_arch_provenance": fixture.ARCH_PROVENANCE,
        "arms": {"G": [], "R": [], "L0": []},
        "draw_fingerprint": {},
    }
    if not args.skip_l0:
        import laya
        import torch
        import transformers
        rec["env"].update({"torch": torch.__version__, "torch_cuda": torch.version.cuda,
                           "transformers": transformers.__version__, "laya": laya.__version__,
                           "torch_cuda_arch_list": torch.cuda.get_arch_list()
                           if torch.cuda.is_available() else None})

    # One serialised Train example, and the token-length distribution under the
    # real fixture, to be compared against step 1's provisional numbers.
    _, _, _, raw0, _ = workload.train_only(0)
    rec["train_example_seed0_item0"] = json.loads(fixture.serialise(raw0, 0))
    rec["train_example_seed0_item0_json"] = fixture.serialise(raw0, 0)

    # Step 1 timed a PROVISIONAL serialisation and said the estimate must be
    # re-checked if the real fixture moved the lengths. Rather than compare
    # summary statistics, compare the strings.
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "step1_feasibility"))
    import serialisation_provisional as PROV  # noqa: E402
    n_diff = sum(1 for i in range(len(raw0["attempt"]))
                 if PROV.serialise(raw0, i) != fixture.serialise(raw0, i))
    rec["provisional_vs_fixture_seed0_train"] = {
        "n_items": int(len(raw0["attempt"])),
        "n_differing_strings": n_diff,
        "identical": n_diff == 0,
        "meaning": ("if identical, step 1's wall-clock estimate stands unchanged, "
                    "because it was computed on exactly these strings"),
    }
    if not args.skip_l0:
        from rlaya import laya_backend as LB
        agent_tl, _ = LB.load_agent(args.model_dir, args.device)
        t0 = time.perf_counter()
        states_all = [fixture.serialise(raw0, i) for i in range(len(raw0["attempt"]))]
        items = LB.build_items(agent_tl, states_all)
        secs = time.perf_counter() - t0
        lens = np.array([len(it["ids"]) for it in items])
        rec["token_lengths_real_fixture_seed0_train"] = {
            "n": int(len(lens)), "min": int(lens.min()), "max": int(lens.max()),
            "mean": float(lens.mean()), "p50": float(np.percentile(lens, 50)),
            "p90": float(np.percentile(lens, 90)), "p99": float(np.percentile(lens, 99)),
            "seconds": secs, "items_per_second": len(lens) / secs,
            "step1_provisional": {"min": 146, "p50": 147.0, "mean": 146.752125,
                                  "p90": 147.0, "p99": 148.0, "max": 148},
        }
        del agent_tl, items

    for s in workload.SEEDS:
        rec["draw_fingerprint"][str(s)] = workload.draw_fingerprint(s)
        print("seed", s, "fingerprint", rec["draw_fingerprint"][str(s)]["X"][:16], flush=True)
        rec["arms"]["R"].append(fit_r(s))
        rec["arms"]["G"].append(fit_g(s, args.out_dir))
        print("  G, R done", flush=True)
        if not args.skip_l0:
            rec["arms"]["L0"].append(
                fit_l0(s, args.out_dir, args.model_dir, args.device, verify=(s == 0)))
            print("  L0 temperature", rec["arms"]["L0"][-1]["temperature_fitted"], flush=True)

    with open(os.path.join(args.out_dir, "step2_arms_gr_l0.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print(json.dumps({"env": rec["env"],
                      "example": rec["train_example_seed0_item0_json"],
                      "R": rec["arms"]["R"][0],
                      "G": {k: v for k, v in rec["arms"]["G"][0].items() if k != "params"},
                      "L0": rec["arms"]["L0"][0] if rec["arms"]["L0"] else None},
                     indent=2))


if __name__ == "__main__":
    main()
