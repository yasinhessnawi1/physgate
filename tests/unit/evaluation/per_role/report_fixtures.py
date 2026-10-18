"""A registered design and every trial record it asks for, as a test can break them."""

from __future__ import annotations

import copy
from typing import Any

#: Small enough that the golden table renders in a moment; the registered runs use 10,000.
DRAWS = 2000


def design(**changes: Any) -> dict[str, Any]:
    """Two control suites and their gap, a published benchmark's category, two firmware suites."""
    base: dict[str, Any] = {
        "experiment": "a fixture experiment",
        "seed": 7,
        "draws": DRAWS,
        "suites": [
            {
                "name": "control_visible",
                "label": "Control, own tasks, visible",
                "role": "control",
                "tier": "visible",
                "tasks": ["control.a", "control.b", "control.c"],
                "arms": ["harness", "observe", "raw"],
                "trials": 2,
            },
            {
                "name": "control_held_out",
                "label": "Control, own tasks, held out",
                "role": "control",
                "tier": "held_out",
                "tasks": ["control.d", "control.e", "control.f"],
                "arms": ["harness", "observe", "raw"],
                "trials": 2,
            },
            {
                "name": "benchmark_category",
                "label": "A published benchmark's category",
                "role": "control",
                "tier": "external",
                "tasks": ["bench.0", "bench.1", "bench.2", "bench.3"],
                "arms": ["harness", "raw"],
                "trials": 2,
            },
            {
                "name": "firmware_visible",
                "label": "Firmware, own tasks, visible",
                "role": "firmware",
                "tier": "visible",
                "tasks": ["firmware.a", "firmware.b"],
                "arms": ["harness", "observe", "raw"],
                "trials": 2,
            },
            {
                "name": "firmware_held_out",
                "label": "Firmware, own tasks, held out",
                "role": "firmware",
                "tier": "held_out",
                "tasks": ["firmware.c", "firmware.d"],
                "arms": ["harness", "observe", "raw"],
                "trials": 2,
            },
        ],
        "published": [
            {
                "suite": "benchmark_category",
                "system": "A published agent",
                "figure": "96.8 % of 50 tasks × 5 trials",
                "source": "a paper, Table 2",
                "record": {
                    "split": "the whole category, as ours",
                    "protocol": "five trials, its own checker in the loop",
                    "scorer": "its own checker",
                    "differences": [
                        "its checker reads no gain margin",
                        "another model",
                    ],
                },
                "warning": "its tasks are public",
            }
        ],
    }
    base.update(copy.deepcopy(changes))
    return base


#: Which (task index, trial) pairs pass, per arm: an arm's pattern over a suite's tasks.
_PASS = {
    "harness": lambda i, t: (i + t) % 3 != 2,
    "observe": lambda i, t: (i + 2 * t) % 3 == 0,
    "raw": lambda i, t: i == 0 and t == 0,
}


def _cost(arm: str, i: int, t: int) -> dict[str, Any]:
    tokens = {"harness": 900_000, "observe": 850_000, "raw": 400_000}[arm] + 1000 * i + 10 * t
    usd = {"harness": "4.10", "observe": "3.95", "raw": "1.20"}[arm]
    return {
        "tokens": tokens,
        "usd": usd,
        "basis": "list_price_estimate",
        "lower_bound": arm == "raw" and i == 1 and t == 1,
    }


def trials(spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Every trial the design registers, once each, in its order."""
    spec = design() if spec is None else spec
    records = []
    for suite in spec["suites"]:
        for i, task in enumerate(suite["tasks"]):
            for arm in suite["arms"]:
                for t in range(suite["trials"]):
                    # The held-out tier is harder for the arms that saw the visible one.
                    harder = suite["tier"] == "held_out" and arm != "raw" and i == t == 0
                    passed = _PASS[arm](i, t) and not harder
                    record: dict[str, Any] = {
                        "suite": suite["name"],
                        "task": task,
                        "arm": arm,
                        "trial": t,
                        "outcome": "pass" if passed else "fail",
                        "cost": _cost(arm, i, t),
                        "wall_clock_s": 600.0 + 60.0 * i + 7.0 * t
                        if arm == "raw"
                        else 1800.0 + 120.0 * i + 11.0 * t,
                    }
                    if arm != "raw":
                        record["gate"] = {
                            "checks_run": 7 + i,
                            "artefacts_caught": int(i == 1),
                            "caught_after_reviewer_passed": int(i == 1 and arm == "observe"),
                        }
                        record["review"] = {
                            "reviews": 2,
                            "failed": int(t == 1),
                            "blocked": int(i == 2 and t == 0),
                        }
                    if suite["role"] == "control":
                        record["control"] = {"no_gain_crossover": i == 2 and arm == "raw"}
                        if suite["tier"] == "external":
                            record["control"].update(
                                full_view_ratio=passed and i != 1,
                                full_view_db=passed,
                            )
                    else:
                        if not passed and arm == "harness" and i == 1:
                            record["outcome"] = "flaky"
                        if arm == "raw" and i == 1 and t == 1:
                            record["outcome"] = "unscored"
                        record["firmware"] = {
                            "executions": 1 if record["outcome"] == "unscored" else 3,
                            "sandbox_failed": int(arm == "raw" and t == 1),
                            "limit_hits": int(arm == "observe" and i == 0 and not passed),
                            "infrastructure_ends": 2 if record["outcome"] == "unscored" else 0,
                        }
                    records.append(record)
    return records
