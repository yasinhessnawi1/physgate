"""Step 4 — the measurement. The test splits are constructed here, once.

R4 and standards I-5: *"No arm is fitted, tuned, temperature-scaled or
early-stopped on any test split. The out-of-distribution sets are read once, at
measurement."* This module is the only place in the experiment that calls
`workload.splits(..., allow_test=True)`, and it takes everything it needs from
that one construction per seed. Nothing here fits anything.

**R5 after this runs: report, do not repair.** Every model scored here was
fitted at step 2 or step 3 and is loaded from disk.

--------------------------------------------------------------------------
Which model scores which split
--------------------------------------------------------------------------
CRITERIA §5: *"Test-OOD-B (unseen domain, with the retrained arm for OOD-B as
R-TM-01 defined it)"*. `run_b.py` is explicit: a second model fitted on Train
with the firmware domain dropped scores `test_id_nofw` and `ood_b`; the main
model scores `test_id` and `ood_a`.

| arm | test_id, ood_a | test_id_nofw, ood_b |
|---|---|---|
| L0 | zero-shot | zero-shot — no retrain exists or can |
| L1 | `L1_seed{s}` | `L1nofw_seed{s}` |
| T | `T_main_seed{s}` | `T_nofw_seed{s}` |
| G | `G_main_seed{s}` | `G_nofw_seed{s}` |
| R | the rule | the rule — deterministic, nothing to retrain |

--------------------------------------------------------------------------
C2's Test-ID baseline, and the one thing the criteria leave open
--------------------------------------------------------------------------
C2 asks for a drop *"below the Test-ID mean"* without saying which Test-ID when
the OOD-B arm is a different model. `score_d.py`, which is where C2 comes from,
answers it:

    per_a = [r["TM"]["test_id"]["mean_conf"]      - r["TM"]["ood_a"]["mean_conf"] ...]
    per_b = [r["TM"]["test_id_nofw"]["mean_conf"] - r["TM"]["ood_b"]["mean_conf"] ...]

OOD-A is compared against Test-ID; **OOD-B is compared against Test-ID-nofw** —
each out-of-distribution set against the in-distribution reference of the model
that scored it. Comparing a no-fw model's OOD-B confidence to a *different*
model's Test-ID confidence would confound the retrain with the distribution
shift, which is the one thing the retrain exists to separate.

That convention is what is gated. **Both are computed and both are reported**, so
a reader who prefers the literal reading can apply it. See the deviation note in
`RESULT.md`.

--------------------------------------------------------------------------
Temperature
--------------------------------------------------------------------------
Three passes, per the D2 and D4 rulings:

* **raw** — identity temperature, no scaling from any source. This is C1's "raw".
* **s3** — the §3 fit on the first 500 rows of *the split the model was fitted
  on*: `Train[0:500]` for a main model, `Train-nofw[0:500]` for a no-fw one.
  That is what `run_b.py` does and it is the only way a no-fw model can have a
  temperature at all. G and R are not scaled (§3).
* **shipped** — **non-gating context**, L0 and L1 only: the constant
  `laya.Agent` actually resolves for this question, which is **1.983399510383606**
  and not the value the fine-tuned config advertises. The resolution is
  `laya/agent.py:304` `t_scale = self.temperature_by_options.get(temp_bucket(qt, k),
  self.temperature[qt])` with `laya/common.py:209-211` mapping a two-option
  `noul` question to the key `"noul:2"`, which the inherited dict contains. See
  C5 M12.

Usage:  python measure.py <out_dir> --step2 DIR --step3 DIR --zero-shot DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle  # noqa: S403 - loads only this experiment's own step-2 artefacts,
              # written by rlaya/fit_arms.py and rlaya/fit_arm_t.py on this machine.
import platform
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import fixture, metrics, workload  # noqa: E402
from rlaya import laya_backend as LB  # noqa: E402

TEST_SPLITS = ("test_id", "test_id_nofw", "ood_a", "ood_b")
MAIN_SPLITS = ("test_id", "ood_a")
NOFW_SPLITS = ("test_id_nofw", "ood_b")

# The constant laya.Agent resolves for a two-option noul question, verified in
# the library rather than taken from the config. C5 M12.
SHIPPED_TEMPERATURE = 1.983399510383606
SHIPPED_TEMPERATURE_SOURCE = (
    "laya/agent.py:304  t_scale = self.temperature_by_options.get("
    "temp_bucket(qt, k), self.temperature[qt]);  laya/common.py:209-211  "
    "temp_bucket(noul, 2) -> 'noul:2', a key present in the inherited dict. "
    "The fine-tuned config's own cfg['temperature'][2] is NOT reachable.")

# C1 / C2 / C3 thresholds, frozen in CRITERIA §6. Constants, never compared to.
C1_RAW, C1_SCALED = 0.10, 0.06
C2_CONF_DROP, C2_ESC_RISE = 0.15, 0.20
C3_SELECTIVE = 0.95


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def tm_probs(class_sums, T):
    """VERBATIM from run05d/experiment.py:tm_probs."""
    v = np.clip(class_sums[:, 1], -T, T).astype(float)
    return np.clip(0.5 * (1.0 + v / T), 0.0, 1.0)


def tm_score(class_sums, T):
    """VERBATIM from run_b.py's ``z`` lambda."""
    return np.clip(class_sums[:, 1], -T, T) / T


def scored(probs, y):
    """Everything C1, C2 and C3 need from one (probs, y) pair."""
    out = metrics.score_all(np.asarray(probs, dtype=float), np.asarray(y),
                            workload.ROUTE_THRESHOLD)
    out["reliability"] = metrics.reliability(np.asarray(probs, dtype=float),
                                             np.asarray(y), metrics.N_BINS)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--step2", required=True)
    ap.add_argument("--step3", required=True)
    ap.add_argument("--zero-shot", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--latency-n", type=int, default=200)
    ap.add_argument("--export-n", type=int, default=250,
                    help="states exported for the laptop's C4 measurement")
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    import laya
    import sklearn
    import torch
    import transformers
    step2 = json.load(open(os.path.join(args.step2, "step2_arms_gr_l0.json")))
    step2t = json.load(open(os.path.join(args.step2, "step2_arm_t.json")))
    step3 = json.load(open(os.path.join(args.step3, "step3_l1_main.json")))
    step3n = json.load(open(os.path.join(args.step3, "step3_l1_nofw.json")))
    T_HP = step2t["fits"][0]["hp"]

    rec = {
        "experiment": "R-LAYA-01", "step": "4-measurement",
        "criteria_commit": "e12d153", "criteria_original": "7b85d29",
        "route_threshold": workload.ROUTE_THRESHOLD,
        "ece_bins": metrics.N_BINS,
        "gated_ece": "ece_conf_half, 10 equal-width bins over [0.5, 1.0]",
        "shipped_temperature": SHIPPED_TEMPERATURE,
        "shipped_temperature_source": SHIPPED_TEMPERATURE_SOURCE,
        "env": {
            "python": platform.python_version(), "platform": platform.platform(),
            "node": subprocess.run(["hostname"], capture_output=True,
                                   text=True).stdout.strip(),
            "torch": torch.__version__, "transformers": transformers.__version__,
            "laya": laya.__version__, "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "seeds": workload.SEEDS, "per_seed": [], "examples": {}, "latency": {},
    }

    # R6 — "frozen weights at a recorded version". Every checkpoint this run
    # scores is hashed and sized before it is loaded, so the result names the
    # bytes it measured rather than a directory that happened to be there.
    rec["checkpoints"] = {}
    for name, ck in ([("zero_shot", args.zero_shot)]
                     + [(f"L1_seed{s}", os.path.join(args.step3, f"L1_seed{s}"))
                        for s in workload.SEEDS]
                     + [(f"L1nofw_seed{s}", os.path.join(args.step3, f"L1nofw_seed{s}"))
                        for s in workload.SEEDS]):
        w = os.path.join(ck, "model.safetensors")
        rec["checkpoints"][name] = {
            "dir": os.path.abspath(ck), "weights": w,
            "exists": os.path.exists(w),
            "size_bytes": os.path.getsize(w) if os.path.exists(w) else None,
            "sha256": sha256_file(w) if os.path.exists(w) else None}
        print("  hashed", name, rec["checkpoints"][name]["sha256"], flush=True)
    missing = [k for k, v in rec["checkpoints"].items() if not v["exists"]]
    if missing:
        raise SystemExit("checkpoints missing, refusing to measure: %s" % missing)

    # Agents are loaded once and reused across seeds where the model does not
    # change (L0), and per seed where it does (L1).
    l0_agent, l0_info = LB.load_agent(args.zero_shot, args.device)
    rec["l0_agent"] = l0_info

    for s in workload.SEEDS:
        t0 = time.perf_counter()
        # ---------------- the one construction of the test splits -----------
        d = workload.splits(s, allow_test=True)
        data = {k: {"X": d[k][0], "y": d[k][1], "raw": d[k][3]} for k in
                ("test_id", "test_id_nofw", "ood_a", "ood_b")}
        seed_rec = {"seed": s, "n": {k: int(len(v["y"])) for k, v in data.items()},
                    "arms": {}}

        if s == 0:
            for k in ("test_id", "ood_a", "ood_b"):
                seed_rec_ex = fixture.serialise(data[k]["raw"], 0)
                rec["examples"][k] = {"seed": 0, "index": 0, "json": seed_rec_ex,
                                      "parsed": json.loads(seed_rec_ex)}

        states = {k: [fixture.serialise(v["raw"], i) for i in range(len(v["y"]))]
                  for k, v in data.items()}

        # Export the splits so arm T, which needs a Python 3.11 environment,
        # scores THESE arrays rather than constructing the splits a second time.
        # One construction, in this process, per R4.
        np.savez_compressed(
            os.path.join(args.out_dir, f"splits_seed{s}.npz"),
            **{f"X_{k}": data[k]["X"] for k in TEST_SPLITS},
            **{f"y_{k}": data[k]["y"] for k in TEST_SPLITS})

        # ------------------------------- L0 and L1 --------------------------
        l1_agents = {}
        for tag, ck_dir in (("main", os.path.join(args.step3, f"L1_seed{s}")),
                            ("nofw", os.path.join(args.step3, f"L1nofw_seed{s}"))):
            l1_agents[tag] = LB.load_agent(ck_dir, args.device)

        t_s3 = {r["seed"]: r["temperature_s3_fitted"] for r in step3["runs"]}
        t_s3n = {r["seed"]: r["temperature_s3_fitted"] for r in step3n["runs"]}
        l0_temp = {r["seed"]: r["temperature_fitted"] for r in step2["arms"]["L0"]}

        for arm in ("L0", "L1"):
            seed_rec["arms"][arm] = {}
            for split in TEST_SPLITS:
                if arm == "L0":
                    agent = l0_agent
                    temp = l0_temp[s]
                else:
                    tag = "main" if split in MAIN_SPLITS else "nofw"
                    agent = l1_agents[tag][0]
                    temp = t_s3[s] if tag == "main" else t_s3n[s]
                lg = LB.logits(agent, states[split])
                z = LB.score(lg)
                p_raw = LB.probs_raw(lg)
                p_s3 = metrics.apply_temperature(temp, z)
                p_ship = metrics.apply_temperature(SHIPPED_TEMPERATURE, z)
                y = data[split]["y"]
                seed_rec["arms"][arm][split] = {
                    "raw": scored(p_raw, y), "s3": scored(p_s3, y),
                    "shipped": scored(p_ship, y),
                    "temperature_s3": float(temp),
                    "temperature_shipped": SHIPPED_TEMPERATURE,
                    "model": ("zero-shot" if arm == "L0" else
                              ("L1_seed%d" % s if split in MAIN_SPLITS
                               else "L1nofw_seed%d" % s)),
                }
                np.savez_compressed(
                    os.path.join(args.out_dir, f"probs_{arm}_{split}_seed{s}.npz"),
                    logits=lg, score=z, p_raw=p_raw, p_s3=p_s3, p_shipped=p_ship, y=y)
            print(f"  seed {s} {arm} done", flush=True)

        # Exported for the laptop's C4 run, so the laptop constructs no split.
        # The probabilities go with them so the two machines can be compared on
        # identical states — the cross-machine half of C5 M10.
        #
        # **Per seed, not seed 0 only.** Checkpoint ``L1_seed{s}`` is fitted on
        # seed s's Train and scored here on seed s's Test-ID. Timing it on seed
        # 0's states would compare the laptop's probabilities for one seed's
        # states against the server's for another's, and the agreement check
        # would then report a difference that is a mismatch of inputs rather than
        # of machines. Each seed's states travel with that seed's probabilities.
        srv = os.path.join(args.out_dir, "server_probs_test_id.json")
        prev = json.load(open(srv)) if os.path.exists(srv) else {}
        prev[str(s)] = [float(x) for x in
                        np.load(os.path.join(args.out_dir,
                                             f"probs_L1_test_id_seed{s}.npz"))["p_raw"]
                        [:args.export_n]]
        with open(srv, "w") as f:
            json.dump(prev, f)
        with open(os.path.join(args.out_dir, f"states_test_id_seed{s}.json"), "w") as f:
            json.dump(states["test_id"][:args.export_n], f)
        _, _, _, raw_tr, _ = workload.train_only(s)
        train_states = [fixture.serialise(raw_tr, i) for i in range(args.export_n)]
        with open(os.path.join(args.out_dir, f"states_train_seed{s}.json"), "w") as f:
            json.dump(train_states, f)
        # The raw generator fields of Test-ID, so arm R's latency can be timed on
        # the laptop as context without the laptop constructing a split.
        np.savez_compressed(
            os.path.join(args.out_dir, f"raw_test_id_seed{s}.npz"),
            **{k: np.asarray(v) for k, v in data["test_id"]["raw"].items()})

        # The batched scoring path checked against Laya's public one on the very
        # states the criteria are scored on, not only on Train as at step 2. Eight
        # calls; the tolerance is system_one's own four decimals.
        if s == 0:
            rec["system_one_agreement_L1_seed0_test_id"] = LB.verify_matches_system_one(
                l1_agents["main"][0], states["test_id"], n=8)

        # ------------------------------------ G -----------------------------
        seed_rec["arms"]["G"] = {}
        for split in TEST_SPLITS:
            tag = "main" if split in MAIN_SPLITS else "nofw"
            with open(os.path.join(args.step2, f"G_{tag}_seed{s}.pkl"), "rb") as f:
                m = pickle.load(f)
            p = m.predict_proba(data[split]["X"])[:, 1]
            y = data[split]["y"]
            seed_rec["arms"]["G"][split] = {
                "raw": scored(p, y),
                "temperature_scaled": False,
                "note": "CRITERIA §3: G is not temperature-scaled; native probabilities.",
                "model": f"G_{tag}_seed{s}"}
            np.savez_compressed(
                os.path.join(args.out_dir, f"probs_G_{split}_seed{s}.npz"),
                p_raw=p, y=y)

        # ------------------------------------ R -----------------------------
        seed_rec["arms"]["R"] = {}
        for split in TEST_SPLITS:
            pred = metrics.rule_arm(data[split]["raw"])
            p = pred.astype(float)
            y = data[split]["y"]
            seed_rec["arms"]["R"][split] = {
                "raw": scored(p, y), "temperature_scaled": False,
                "confidence_is_1_by_construction": True,
                "model": "deterministic rule (ARCH-030/ARCH-040); nothing to retrain"}
            np.savez_compressed(
                os.path.join(args.out_dir, f"probs_R_{split}_seed{s}.npz"),
                p_raw=p, y=y)

        # ------------------------------------ T -----------------------------
        # Scored in this process only if tmu is importable; otherwise arm T is
        # scored by measure_arm_t.py in its own Python 3.11 environment and the
        # results are merged. Either way the split construction above is the one
        # and only construction in THIS process.
        seed_rec["arms"]["T"] = {"deferred_to": "measure_arm_t.py (Python 3.11 env)"}

        seed_rec["seconds"] = time.perf_counter() - t0
        rec["per_seed"].append(seed_rec)
        with open(os.path.join(args.out_dir, "step4_raw.json"), "w") as f:
            json.dump(rec, f, indent=2)
        print(f"seed {s} done in {seed_rec['seconds']:.1f}s", flush=True)

        # ----------------------------- server latency -----------------------
        # L1 on **every** seed, because §6 says every number is the mean over
        # seeds and the server figure should be read the same way the gated one
        # is. L0, G and R once, at seed 0: L0 is one model for all five seeds by
        # construction, and G and R are refitted per seed but their per-decision
        # cost does not depend on the seed. Train is timed in the same session as
        # Test-ID, for the same reason the laptop does it.
        rec.setdefault("latency_per_seed", {})[str(s)] = {
            "L1_test_id": pct(time_agent(l1_agents["main"][0],
                                         states["test_id"], args.latency_n)),
            "L1_train": pct(time_agent(l1_agents["main"][0],
                                       train_states, min(args.latency_n,
                                                         len(train_states)))),
            "load_at_measurement": os.getloadavg(),
        }
        if s == 0:
            rec["latency"] = latency_block(
                {"L0": l0_agent, "L1": l1_agents["main"][0]},
                states, data, args.step2, s, args.latency_n)
        with open(os.path.join(args.out_dir, "step4_raw.json"), "w") as f:
            json.dump(rec, f, indent=2)

        del l1_agents

    # The server's own mean over seeds, so its figure is read the same way the
    # gated one is. Reported, never gated (CRITERIA §6 C4).
    for which in ("L1_test_id", "L1_train"):
        vals = [v[which] for v in rec.get("latency_per_seed", {}).values()]
        if vals:
            rec.setdefault("latency_pooled_server", {})[which] = {
                "p50_ms_mean_over_seeds": float(np.mean([v["p50_ms"] for v in vals])),
                "p50_ms_max_over_seeds": float(np.max([v["p50_ms"] for v in vals])),
                "p90_ms_mean_over_seeds": float(np.mean([v["p90_ms"] for v in vals])),
                "p99_ms_mean_over_seeds": float(np.mean([v["p99_ms"] for v in vals])),
                "n_seeds": len(vals)}
    with open(os.path.join(args.out_dir, "step4_raw.json"), "w") as f:
        json.dump(rec, f, indent=2)
    print("measurement written")


def time_agent(agent, states, n):
    """Milliseconds per decision through Laya's public one-state-per-call path."""
    ts = []
    for st in states[:n]:
        t0 = time.perf_counter()
        agent.system_one(st, LB.QUESTION)
        ts.append((time.perf_counter() - t0) * 1000.0)
    return ts


def latency_block(agents, states, data, step2_dir, seed, n):
    """p50/p90/p99 per decision, one state per call, as the interface calls it."""
    import torch
    out = {"n_per_arm": n, "note": "one decision per call, batch size 1"}
    for name, agent in agents.items():
        out[name] = pct(time_agent(agent, states["test_id"], n))
    # G and R, per decision
    with open(os.path.join(step2_dir, f"G_main_seed{seed}.pkl"), "rb") as f:
        g = pickle.load(f)
    X = data["test_id"]["X"]
    ts = []
    for i in range(n):
        t0 = time.perf_counter()
        g.predict_proba(X[i:i + 1])
        ts.append((time.perf_counter() - t0) * 1000.0)
    out["G"] = pct(ts)
    raw = data["test_id"]["raw"]
    ts = []
    for i in range(n):
        one = {k: v[i:i + 1] for k, v in raw.items()}
        t0 = time.perf_counter()
        metrics.rule_arm(one)
        ts.append((time.perf_counter() - t0) * 1000.0)
    out["R"] = pct(ts)
    out["torch_threads"] = torch.get_num_threads()
    return out


def pct(ts):
    a = np.array(ts, dtype=float)
    return {"n": int(len(a)), "p50_ms": float(np.percentile(a, 50)),
            "p90_ms": float(np.percentile(a, 90)), "p99_ms": float(np.percentile(a, 99)),
            "mean_ms": float(a.mean()), "min_ms": float(a.min()), "max_ms": float(a.max())}


if __name__ == "__main__":
    main()
