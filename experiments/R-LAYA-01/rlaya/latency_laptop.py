"""C4 — latency on the laptop, which is what the criterion gates.

§6 C4: *"p50 per decision. **Gated on the laptop**, which is where the
orchestrator and its sessions actually run, and where the interface would be
called: p50 ≤ 500 ms."* One state per call, batch size 1, because that is how
`decide()` is called.

**Test-ID and Train, in the same session.** The Train figure is a reference, not
a substitute: latency is the criterion most exposed to the machine and least
dependent on the split, so if the gated number later looks wrong the same-session
Train figure says whether the machine was behaving. Agreement and the question
never arises; disagreement and the finding is about the machine rather than the
engine. Both come from states exported by `measure.py`, so no split is
constructed here.

**Device.** Whatever `laya.Agent` selects on this machine, recorded before
anything is timed. The other device is timed afterwards as context. The
selection is made by the library, not by which number is better — `--device` is
accepted only to force the *context* run and is refused for the gated one.

**Memory.** 8 GB, and ModernBERT-large is 421M parameters. Checkpoints are loaded
one at a time and peak RSS is recorded per seed. A seed that cannot be loaded is
a finding, not something to route around.

**Load.** The load average is recorded before and after every measurement, with
the process list, because a p50 gate on a busy machine is not a measurement of
the engine.

Usage:  python latency_laptop.py <out.json> --states DIR --checkpoints DIR
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rlaya import laya_backend as LB  # noqa: E402


def loadavg():
    try:
        return list(os.getloadavg())
    except OSError:
        return None


def top_processes(n=8):
    try:
        out = subprocess.run(["ps", "-Ao", "pcpu,comm", "-r"], capture_output=True,
                             text=True, timeout=20).stdout.splitlines()[:n + 1]
        return [l.strip() for l in out]
    except Exception as e:
        return [repr(e)]


def peak_rss_bytes():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    return int(r) if sys.platform == "darwin" else int(r) * 1024


def pct(ts):
    a = np.array(ts, dtype=float)
    return {"n": int(len(a)), "p50_ms": float(np.percentile(a, 50)),
            "p90_ms": float(np.percentile(a, 90)), "p99_ms": float(np.percentile(a, 99)),
            "mean_ms": float(a.mean()), "sd_ms": float(a.std()),
            "min_ms": float(a.min()), "max_ms": float(a.max())}


def machine():
    def sysctl(k):
        try:
            return subprocess.run(["sysctl", "-n", k], capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return None
    return {
        "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(),
        "model": sysctl("hw.model"), "cpu": sysctl("machdep.cpu.brand_string"),
        "ncpu": sysctl("hw.ncpu"), "nperflevels0": sysctl("hw.perflevel0.logicalcpu"),
        "nperflevels1": sysctl("hw.perflevel1.logicalcpu"),
        "memsize_bytes": sysctl("hw.memsize"),
        "os_version": subprocess.run(["sw_vers", "-productVersion"], capture_output=True,
                                     text=True).stdout.strip(),
        "os_build": subprocess.run(["sw_vers", "-buildVersion"], capture_output=True,
                                   text=True).stdout.strip(),
    }


def time_calls(agent, states, n):
    ts = []
    probs = []
    for st in states[:n]:
        t0 = time.perf_counter()
        r = agent.system_one(st, LB.QUESTION)
        ts.append((time.perf_counter() - t0) * 1000.0)
        probs.append(r["answers"][LB.QUESTION_ID]["noul"])
    return ts, probs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--states", required=True, help="dir with states_*.json from measure.py")
    ap.add_argument("--checkpoints", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--seeds", type=int, nargs="*", default=[0, 1, 2, 3, 4])
    ap.add_argument("--context-device", default=None,
                    help="second device to time as CONTEXT only; never the gated one")
    args = ap.parse_args()

    import torch
    rec = {
        "experiment": "R-LAYA-01", "step": "4-latency-laptop", "gates": "C4, arm L1",
        "threshold_p50_ms": 500.0, "n_per_split_per_seed": args.n,
        "warmup_discarded": args.warmup,
        "call_shape": "one state per call, batch size 1, as decide() is called",
        "machine": machine(),
        "torch": torch.__version__, "torch_threads": torch.get_num_threads(),
        "mps_available": bool(getattr(torch.backends, "mps", None)
                              and torch.backends.mps.is_available()),
        "load_at_start": loadavg(), "processes_at_start": top_processes(),
        "per_seed_test_id": {"L1": {}}, "per_seed_train": {"L1": {}},
        "peak_rss_bytes": {}, "device_selected": None, "load_samples": [],
        "server_agreement": {}, "context_device": {},
    }

    states_id = json.load(open(os.path.join(args.states, "states_test_id_seed0.json")))
    states_tr = json.load(open(os.path.join(args.states, "states_train_seed0.json")))
    server_p = json.load(open(os.path.join(args.states, "server_probs_test_id_seed0.json")))

    for s in args.seeds:
        ck = os.path.join(args.checkpoints, f"L1_seed{s}")
        rec["load_samples"].append({"seed": s, "before": loadavg()})
        try:
            # device=None: laya.Agent selects. Recorded before anything is timed.
            agent, info = LB.load_agent(ck, None)
        except Exception as e:
            rec["per_seed_test_id"]["L1"][str(s)] = {"error": repr(e)}
            rec["peak_rss_bytes"][str(s)] = peak_rss_bytes()
            continue
        if rec["device_selected"] is None:
            rec["device_selected"] = {"device": info["device"], "dtype": info["dtype"],
                                      "chosen_by": "laya.Agent, device=None",
                                      "dtype_laya_would_have_chosen":
                                          info["dtype_laya_would_have_chosen"],
                                      "dtype_forced_fp32": info["dtype_forced_fp32"]}
        time_calls(agent, states_id, args.warmup)                     # warm-up
        ts_id, p_id = time_calls(agent, states_id, args.n)
        ts_tr, _ = time_calls(agent, states_tr, args.n)
        rec["per_seed_test_id"]["L1"][str(s)] = pct(ts_id)
        rec["per_seed_train"]["L1"][str(s)] = pct(ts_tr)
        rec["peak_rss_bytes"][str(s)] = peak_rss_bytes()
        rec["load_samples"][-1]["after"] = loadavg()
        if str(s) in server_p:
            sp = np.array(server_p[str(s)][:len(p_id)], dtype=float)
            lp = np.array(p_id, dtype=float)
            rec["server_agreement"][str(s)] = {
                "n": int(len(lp)),
                "max_abs_difference": float(np.abs(sp - lp).max()),
                "mean_abs_difference": float(np.abs(sp - lp).mean()),
                "decisions_crossing_0.5": int(((sp >= 0.5) != (lp >= 0.5)).sum()),
                "note": "server fp32 cuda vs laptop fp32; system_one rounds to 4 dp",
            }
        if args.context_device and s == args.seeds[0]:
            try:
                a2, i2 = LB.load_agent(ck, args.context_device)
                time_calls(a2, states_id, args.warmup)
                t2, _ = time_calls(a2, states_id, args.n)
                rec["context_device"] = {"device": i2["device"], "dtype": i2["dtype"],
                                         "test_id": pct(t2),
                                         "note": "context only; never the gated number"}
                del a2
            except Exception as e:
                rec["context_device"] = {"error": repr(e)}
        del agent

    for split in ("test_id", "train"):
        allt = []
        for v in rec[f"per_seed_{split}"]["L1"].values():
            if "p50_ms" in v:
                allt.append(v)
        if allt:
            rec[f"pooled_{split}"] = {"L1": {
                "p50_ms_mean_over_seeds": float(np.mean([v["p50_ms"] for v in allt])),
                "p50_ms_max_over_seeds": float(np.max([v["p50_ms"] for v in allt])),
                "p90_ms_mean_over_seeds": float(np.mean([v["p90_ms"] for v in allt])),
                "p99_ms_mean_over_seeds": float(np.mean([v["p99_ms"] for v in allt])),
                "n_seeds": len(allt)}}
    rec["load_at_end"] = loadavg()
    rec["processes_at_end"] = top_processes()
    with open(args.out, "w") as f:
        json.dump(rec, f, indent=2)
    print(json.dumps({k: rec[k] for k in
                      ("machine", "device_selected", "load_at_start", "load_at_end",
                       "pooled_test_id", "pooled_train", "peak_rss_bytes",
                       "server_agreement", "context_device")
                      if k in rec}, indent=2))


if __name__ == "__main__":
    main()
