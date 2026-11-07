"""The public ControlEval benchmark as tasks: fetched at one commit, checked byte for byte.

ControlEval (the ControlAgent paper, arXiv 2410.19811) publishes 500 control-design tasks,
ten categories of fifty, as JSON in a repository that carries no licence. So none of its
code runs here and none of its data is copied into this repository: the three categories
evaluated are fetched at run time, at one commit, into a cache outside the repository,
and each file is refused unless its SHA-256 is the one pinned below.

Each upstream record becomes one external task whose brief states the plant and exactly
the four requirements the benchmark's own prompt states: closed-loop stability, a minimum
phase margin, a settling-time window and a maximum steady-state error. Those four decide
the pass. The record's gain-margin and overshoot fields, which the benchmark's prompt
never states and its checker never reads, are kept as secondary specifications, reported
beside the pass and never part of it. The gain margin's unit is stated nowhere, so it is
reported under both readings, as a ratio and in decibels.

A category is evaluated whole or not at all: a ranking claim needs all fifty tasks.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from physgate.evaluation.per_role.answer import power_unit
from physgate.evaluation.per_role.exceptions import ControlEvalError
from physgate.evaluation.per_role.metrics import CONTROL_SCORER_VERSION
from physgate.evaluation.per_role.task import Task, parse_task, task_bytes

BENCHMARK = "controleval"
UPSTREAM = "https://raw.githubusercontent.com/ControlAgent/ControlAgent"
#: The commit every file is read at: the repository's head on 17.10.2026.
UPSTREAM_SHA = "7a4898eb57b4c76cf5bc69afd4546a4630927bdb"
#: The three categories evaluated, each a whole file of fifty, with its pinned digest.
CATEGORIES: dict[str, tuple[str, str]] = {
    "second_order_unstable": (
        "ControlEval/second_order_unstable_data.json",
        "826946d8d5fca7129add2485b0de66489ce5409997dae2dd575d494a5832c68c",
    ),
    "higher_order": (
        "ControlEval/higher_order_data.json",
        "458ca1c3eb7eb9639f1aa943fc18c5aa5b2bff6e6e8bd5a09a2bf871090b4a84",
    ),
    "first_order_w_delay": (
        "ControlEval/first_order_w_delay_data.json",
        "a3968fcdcaf6ac6ef4d3c6c95d2ccef25262633e5fb9cded08bce9ef41a783fd",
    ),
}
Category = Literal["second_order_unstable", "higher_order", "first_order_w_delay"]
CATEGORY_SIZE = 50
MAX_FILE_BYTES = 1024 * 1024
FETCH_TIMEOUT_S = 60.0
SCORER_VERSION = CONTROL_SCORER_VERSION


class _Record(BaseModel):
    """One upstream task, validated strictly before a number of it is used."""

    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)

    id: int = Field(ge=0)
    num: list[float | int] = Field(min_length=1, max_length=11)
    den: list[float | int] = Field(min_length=2, max_length=11)
    tau: float | None = Field(default=None, ge=0)
    gain_margin_min: float | int
    phase_margin_min: float | int
    settling_time_min: float | int
    settling_time_max: float | int
    overshoot_max: float | int
    steadystate_error_max: float | int
    metadata: str
    scenario: str


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch(category: Category, cache: Path, *, base_url: str = UPSTREAM) -> Path:
    """The category's file in ``cache``, fetched at the pinned commit if not there yet.

    A cached file is used only if its digest is the pinned one; a fetched file is written
    only if its digest is. Nothing else in this package touches the network. ``base_url``
    is for tests, which serve their own files.

    Raises:
        ControlEvalError: the file cannot be fetched, or is not the pinned bytes.
    """
    relative, pinned = CATEGORIES[category]
    target = cache / UPSTREAM_SHA / Path(relative).name
    if target.is_file() and not target.is_symlink():
        if _digest(target.read_bytes()) == pinned:
            return target
        msg = f"the cached {target.name} is not the pinned bytes"
        raise ControlEvalError(msg, path=str(target))
    url = f"{base_url}/{UPSTREAM_SHA}/{relative}"
    # curl, not the standard library: it reads the system's certificate store, which an
    # interpreter installed without its own certificates cannot (measured on this laptop).
    try:
        fetched = subprocess.run(
            ["curl", "-sfL", "--max-filesize", str(MAX_FILE_BYTES), url],
            capture_output=True,
            timeout=FETCH_TIMEOUT_S,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        msg = f"{url} could not be fetched: {exc}"
        raise ControlEvalError(msg, url=url) from exc
    raw = fetched.stdout
    if len(raw) > MAX_FILE_BYTES or _digest(raw) != pinned:
        msg = f"{url} is not the pinned bytes (sha256 {_digest(raw)})"
        raise ControlEvalError(msg, url=url)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".partial")
    temporary.write_bytes(raw)
    temporary.replace(target)
    return target


def _coefficients(prefix: str, values: list[float | int]) -> list[dict[str, Any]]:
    degree = len(values) - 1
    return [
        {"name": f"{prefix}_{i}", "value": v, "unit": power_unit(degree - i)}
        for i, v in enumerate(values)
    ]


def _polynomial_text(values: list[float | int]) -> str:
    degree = len(values) - 1
    terms = []
    for i, v in enumerate(values):
        power = degree - i
        variable = "" if power == 0 else ("s" if power == 1 else f"s^{power}")
        terms.append(f"{v!r}{'*' if variable else ''}{variable}")
    return " + ".join(terms)


BRIEF = """\
Design a controller for the plant below.

Plant (continuous time, s in 1/s):
  G(s) = ({num}) / ({den}){delay}

The loop is unity negative feedback: the controller C(s) acts on the error between a
unit step reference and the plant output.

Requirements, all of which must hold for the closed loop:
  1. the closed loop is asymptotically stable;
  2. phase margin >= {pm!r} deg;
  3. 2 % settling time of the unit step response between {ts_min!r} s and {ts_max!r} s;
  4. steady-state error of the unit step response <= {ess!r}.

Answer: write the controller to the file `answer.json` in the directory you work in, as
  {{"form": "lti_tf", "gain": {{"value": K, "unit": "1"}},
    "num": [...], "den": [...]}}
with C(s) = K * N(s) / D(s), the coefficients of N and D highest power first, each written
as {{"value": number, "unit": u}} where u is "s**k" for the coefficient of s^k ("s" for
k = 1, "1" for k = 0). The controller must be proper (N no higher in degree than D), of
order at most 10.
"""


def _brief(record: _Record) -> str:
    delay = "" if not record.tau else f" * exp(-{record.tau!r}*s)"
    return BRIEF.format(
        num=_polynomial_text(record.num),
        den=_polynomial_text(record.den),
        delay=delay,
        pm=record.phase_margin_min,
        ts_min=record.settling_time_min,
        ts_max=record.settling_time_max,
        ess=record.steadystate_error_max,
    )


def _spec(name: str, metric: str, op: str, bound: Any, counts: str = "headline") -> dict[str, Any]:
    return {
        "name": name,
        "metric": metric,
        "op": op,
        "bound": bound,
        "counts": counts,
        "composes": ["as_posed" if counts == "headline" else "recorded_not_posed"],
    }


def task_for(category: Category, index: int, record: _Record, sha256: str) -> Task:
    """One upstream record as an external task."""
    inputs = _coefficients("plant_num", record.num) + _coefficients("plant_den", record.den)
    if record.tau:
        inputs.append({"name": "plant_delay", "value": record.tau, "unit": "s"})
    specs = [
        _spec("stable", "max_real_pole", "<", {"value": 0, "unit": "1/s"}),
        _spec("margin", "phase_margin", ">=", {"value": record.phase_margin_min, "unit": "deg"}),
        _spec(
            "settling",
            "settling_time",
            "in",
            [
                {"value": record.settling_time_min, "unit": "s"},
                {"value": record.settling_time_max, "unit": "s"},
            ],
        ),
        _spec(
            "accuracy",
            "steady_state_error",
            "<=",
            {"value": record.steadystate_error_max, "unit": "1"},
        ),
        _spec(
            "gain_margin_as_ratio",
            "gain_margin_ratio",
            ">=",
            {"value": record.gain_margin_min, "unit": "1"},
            "secondary",
        ),
        _spec(
            "gain_margin_as_db",
            "gain_margin_db",
            ">=",
            {"value": record.gain_margin_min, "unit": "dB"},
            "secondary",
        ),
        _spec(
            "overshoot",
            "overshoot",
            "<=",
            {"value": record.overshoot_max, "unit": "percent"},
            "secondary",
        ),
    ]
    task_id = f"{BENCHMARK}.{category}.{record.id:03d}"
    task = {
        "id": task_id,
        "role": "control",
        "tier": "external",
        "source": {
            "kind": "external",
            "benchmark": BENCHMARK,
            "file": CATEGORIES[category][0],
            "index": index,
            "upstream_sha": UPSTREAM_SHA,
            "upstream_sha256": sha256,
        },
        "brief": _brief(record),
        "inputs": inputs,
        "answer": {"path": "answer.json", "form": "lti_tf"},
        "specs": specs,
        "scorer": {"id": "control", "version": SCORER_VERSION},
    }
    return parse_task(json.dumps(task).encode(), where=task_id)


def category_tasks(category: Category, path: Path, *, pinned: str | None = None) -> list[Task]:
    """Every task of ``category`` from its fetched file, refused unless it is whole.

    ``pinned`` replaces the pinned digest, for tests that build their own file.

    Raises:
        ControlEvalError: the file is not the pinned bytes, not fifty records with ids
            0 to 49 in order, or a record does not validate.
    """
    raw = path.read_bytes()
    sha256 = _digest(raw)
    if sha256 != (pinned or CATEGORIES[category][1]):
        msg = f"{path.name} is not the pinned bytes"
        raise ControlEvalError(msg, path=str(path))
    try:
        rows = json.loads(raw)
        records = [_Record.model_validate(row) for row in rows]
    except (ValueError, ValidationError, TypeError) as exc:
        msg = f"{path.name} holds a record that is not a ControlEval task: {exc}"
        raise ControlEvalError(msg, path=str(path)) from exc
    if [r.id for r in records] != list(range(CATEGORY_SIZE)):
        msg = f"{path.name} is not one whole category of {CATEGORY_SIZE} tasks in order"
        raise ControlEvalError(msg, path=str(path))
    return [task_for(category, i, r, sha256) for i, r in enumerate(records)]


def write_task(task: Task, directory: Path) -> Path:
    """``task`` written as ``directory/<id>/task.json``, canonically; its directory."""
    root = directory / task.id
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.json").write_bytes(task_bytes(task))
    return root
