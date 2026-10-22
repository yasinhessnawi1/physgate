"""The synthetic fixture R-LAW-01's tests share, and the scripted stand-in model.

Nothing here is an input of the experiment. Two tiny sets (a "practice" and a "fresh" one) are
built on the instrument's own test design (three electrical nodes), each loadable by the corpus
loader and gateable, with a parts sheet of their own; seven runs over them hold invented review
lines whose evidence is written here, and gate lines the real gate wrote over the fixture.

``python -I law_fixture.py standin <claude arguments>`` is the stand-in: it reads a packet on
standard input and answers in the CLI's JSON output, every answer a function of the packet's own
text and a hash, never a model. ``RLAW_STANDIN_STATE`` names a directory for its memory across
tries (an invalid first try for some packets, for the retry tests).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for _p in (HERE, REPO / "tests", REPO / "tests" / "unit" / "evaluation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import law_extract as X  # noqa: E402

SHEET = (
    "# A test parts sheet\n\n| row | quantity | value | unit | note |\n|---|---|---|---|---|\n"
    "| R1.01 | stall current | 1.5 to 2.6 | A | range over windings |\n"
    "| R8.01 | gyroscope ODR options | 12.5, 26, 52, 104 | Hz | list |\n"
)


def _corpus(root: Path, extra_artefact: bool = True) -> Path:
    import instrument_corpus as ic

    from physgate.evaluation.inject.corpus import manifest_for, write_manifest

    unit = {
        "id": "u1",
        "error_class": "unit",
        "expected_check": "units",
        "assigned_role": "electrical",
        "description": "the motor's stall current is written in volts",
        "edge": None,
        "clean": {"nodes": [ic.with_quantity(ic.MOTOR, "stall_current", 2.5, "A")]},
        "injected": {"nodes": [ic.with_quantity(ic.MOTOR, "stall_current", 2.5, "V")]},
    }
    equil = {
        "id": "e1",
        "error_class": "equilibrium",
        "expected_check": "equilibrium",
        "assigned_role": "electrical",
        "description": "the driver's limit is raised past its rating",
        "edge": None,
        "clean": {"nodes": [ic.with_quantity(ic.DRIVER, "current_limit", 3.0, "A")]},
        "injected": {"nodes": [ic.with_quantity(ic.DRIVER, "current_limit", 30.0, "A")]},
    }
    arts = (ic.MAGNITUDE_ARTEFACT, ic.PROPAGATION_ARTEFACT, unit, equil)
    ic.write_corpus(root, artefacts=arts if extra_artefact else arts[:2], base_nodes=ic.BASE_NODES)
    (root / "parts_sheet.md").write_text(SHEET)
    write_manifest(root, manifest_for(root, label=ic.LABEL, author_model=ic.AUTHOR))
    return root


# ---------------------------------------------------------------- the review lines

#: Per run label, per (artefact, side): the review script. ``("unavailable",)``, or
#: ("fail", [(item, section, result, evidence)], failing item), or ("pass",).
IMU = "electrical.imu"
LINES: dict[str, dict[tuple[str, str], tuple[Any, ...]]] = {
    "practice-0": {
        ("m1", "injected"): (
            "fail",
            [
                (
                    "ES-3",
                    "domain_standards",
                    "unmet",
                    "The imu sample_rate of 50000 Hz breaks ES-3.",
                ),
                ("ES-4", "domain_standards", "met", "fine"),
            ],
            None,
        ),
        ("p1", "injected"): (
            "fail",
            [
                (
                    "ES-1",
                    "domain_standards",
                    "unmet",
                    "The motor_left stall_current rose; driver not revisited.",
                )
            ],
            None,
        ),
        ("u1", "twin"): (
            "fail",
            [("EH-2", "reward_hacking", "confirmed", "Values look tuned.")],
            None,
        ),
        ("e1", "injected"): (
            "fail",
            [
                (
                    "ES-5",
                    "domain_standards",
                    "unmet",
                    "The driver current_limit of 30 A is too high.",
                )
            ],
            None,
        ),
    },
    "practice-1": {
        ("m1", "injected"): (
            "fail",
            [("ES-3", "domain_standards", "unmet", "imu sample_rate still out of range.")],
            None,
        ),
    },
    "practice-2": {
        ("u1", "injected"): (
            "fail",
            [("ES-2", "domain_standards", "unmet", "motor_left stall_current is in volts.")],
            None,
        ),
    },
    "a-fresh": {
        ("m1", "injected"): (
            "fail",
            [
                ("EA-1", "acceptance_criteria", "unmet", "The imu sample_rate is out of range."),
                (
                    "ES-3",
                    "domain_standards",
                    "unmet",
                    "electrical.imu sample_rate is 50000 Hz (ES-3).",
                ),
                ("EH-2", "reward_hacking", "confirmed", "No numbers here."),
            ],
            None,
        ),
        ("p1", "injected"): (
            "fail",
            [
                ("ES-1", "domain_standards", "unmet", "motor_left stall_current changed alone."),
                (
                    "EP-2",
                    "antipatterns",
                    "unmet",
                    "The motor_left stall_current edit skips the driver.",
                ),
            ],
            None,
        ),
        ("u1", "twin"): (
            "fail",
            [("ES-7", "domain_standards", "unmet", "The imu sample_rate lacks a source row.")],
            None,
        ),
        ("e1", "twin"): ("unavailable",),
    },
    "b-fresh": {
        ("m1", "injected"): (
            "fail",
            [("ES-3", "domain_standards", "unmet", "imu sample_rate too high for R8.01.")],
            None,
        ),
        ("e1", "injected"): (
            "fail",
            [("ES-5", "domain_standards", "met", "The driver current_limit is 30 A.")],
            "ES-5",
        ),
    },
    "repeat-K": {
        ("m1", "twin"): (
            "fail",
            [
                (
                    "ES-3",
                    "domain_standards",
                    "unmet",
                    "driver current_limit is fine but imu sample_rate is odd.",
                )
            ],
            None,
        ),
    },
    "round-1": {
        ("e1", "injected"): (
            "fail",
            [("ES-7", "domain_standards", "unmet", "imu sample_rate has no source.")],
            None,
        ),
        ("u1", "injected"): (
            "fail",
            [("ES-2", "domain_standards", "unmet", "motor_left stall_current unit is V.")],
            None,
        ),
    },
}


def _review(script: tuple[Any, ...]) -> dict[str, Any]:
    if script[0] == "unavailable":
        return {"kind": "review_unavailable", "cause": "scripted"}
    if script[0] == "pass":
        return {"kind": "review_ran", "result": {"verdict": "pass", "items": [], "criteria": []}}
    _, items, failing = script
    return {
        "kind": "review_ran",
        "result": {
            "verdict": "fail",
            "items": [
                {"item": i, "section": s, "result": r, "evidence": e} for i, s, r, e in items
            ],
            "failing_item": failing,
            "criteria": [{"criterion": "C1", "result": "unmet", "evidence": "restated"}],
            "spec_defects": [],
            "indicators": [],
            "finding": "a rejecting item",
            "subject": "the revision",
        },
    }


def gate_lines(set_root: Path, seed: int) -> dict[str, dict[str, Any]]:
    import law_regate as G

    return {r["subtask_id"]: r["result"] for r in G.gate_set(set_root, seed)}


def write_runs(
    root: Path, sets: dict[str, Path], gates: dict[str, dict[str, Any]]
) -> dict[str, Path]:
    from physgate.evaluation.inject.runner import control_id, review_id

    dirs = {}
    for pin in X.RUNS:
        d = root / pin.label
        (d / "controls").mkdir(parents=True)
        seed = X.SETS[pin.set].seed
        aids = ("e1", "m1", "p1", "u1")
        rows = [
            {"artefact": a, "review_id": review_id(seed, a), "control_id": control_id(seed, a)}
            for a in aids
        ]
        (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        script = LINES.get(pin.label, {})
        for side, path in (
            ("injected", d / "events.jsonl"),
            ("twin", d / "controls" / "events.jsonl"),
        ):
            out = []
            for r in rows:
                sid = r["review_id"] if side == "injected" else r["control_id"]
                out.append(
                    {"kind": "subtask_planned", "subtask_id": sid, "assigned_role": "electrical"}
                )
                out.append({"kind": "gate_ran", "subtask_id": sid, "result": gates[pin.set][sid]})
                if (r["artefact"], side) == ("m1", "injected") and pin.label == "a-fresh":
                    # an earlier review line of the same subtask: only the last one counts
                    out.append({"subtask_id": sid, **_review(("pass",))})
                s = script.get((r["artefact"], side), ("pass",))
                out.append({"subtask_id": sid, **_review(s)})
            path.write_text("".join(json.dumps(e) + "\n" for e in out))
        manifest = X.sha256_file(sets[pin.set] / "MANIFEST.json")
        run_id = pin.run_id or f"fixture-{pin.label}"
        (d / "instrument.json").write_text(
            json.dumps(
                {
                    "corpus_manifest_sha256": manifest,
                    "reviewer_kind": pin.kind,
                    "run_id": run_id,
                    "seed": seed,
                }
            )
        )
        dirs[pin.label] = d
    return dirs


def build(root: Path) -> dict[str, Any]:
    """Both sets, the seven runs, their digests and the pins that hold them."""
    sets = {
        "practice": _corpus(root / "sets" / "practice"),
        "fresh": _corpus(root / "sets" / "fresh"),
    }
    gates = {n: gate_lines(p, X.SETS[n].seed) for n, p in sets.items()}
    runs = write_runs(root / "runs", sets, gates)
    pins = X.Pins(
        sets={
            n: replace(
                X.SETS[n],
                path=str(sets[n].relative_to(root)),
                manifest=X.sha256_file(sets[n] / "MANIFEST.json"),
            )
            for n in sets
        },
        runs=X.RUNS,
        parts_sheet=X.sha256_bytes(SHEET.encode()),
        repo=root,
    )
    digests = {
        "runs": {label: X.run_digests(d) for label, d in runs.items()},
        "manifests": {n: p.manifest for n, p in pins.sets.items()},
    }
    return {"root": root, "sets": sets, "runs": runs, "pins": pins, "digests": digests}


def extract_fixture(
    fx: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, X.SetData]]:
    """The fixture's lines, read through the experiment's own refusals (rubric ids at REPO)."""
    pins = replace(fx["pins"], repo=fx["root"])
    sets = {n: X.load_set(pins, n) for n in pins.sets}
    runs = {p.label: X.load_run(pins, p, fx["runs"][p.label], fx["digests"]) for p in pins.runs}
    real = replace(pins, repo=REPO)
    lines, counts = X.extract(real, sets, runs)
    return lines, counts, sets


# ---------------------------------------------------------------- the stand-in model


def _h(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


def _findings(packet: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r"^### (F\d+)\n\n?(.*?)(?=^### F\d+|^## |\Z)", packet, re.M | re.S):
        out.append((m.group(1), m.group(2).strip()))
    return out


def _design(packet: str) -> list[dict[str, Any]]:
    m = re.search(r"## The design, all nodes\n\n(.*?)\n\n## The parts sheet", packet, re.S)
    return json.loads(m.group(1)) if m else []


def _numeric_pair(nodes: list[dict[str, Any]]) -> tuple[str, str, Any, str, str, Any, str] | None:
    for n in nodes:
        qs = [
            (q, v)
            for q, v in sorted((n.get("quantities") or {}).items())
            if isinstance(v.get("value"), int | float)
        ]
        for i, (qa, va) in enumerate(qs):
            for qb, vb in qs[i + 1 :]:
                if va["unit"] == vb["unit"] and va["value"] != vb["value"]:
                    hi, lo = (qa, va), (qb, vb)
                    if va["value"] < vb["value"]:
                        hi, lo = lo, hi
                    return (
                        n["id"],
                        hi[0],
                        hi[1]["value"],
                        hi[1]["unit"],
                        lo[0],
                        lo[1]["value"],
                        lo[1]["unit"],
                    )
    for n in nodes:
        for q, v in sorted((n.get("quantities") or {}).items()):
            if isinstance(v.get("value"), int | float) and v["value"] > 0:
                return (n["id"], q, v["value"], v["unit"], q, v["value"], v["unit"])
    return None


def _coder_form(
    fid: str, text: str, pid: str, model: str, nodes: list[dict[str, Any]]
) -> dict[str, Any]:
    h = _h(model, text) if _h(text, "agree") % 10 < 6 else _h(model, text, pid, fid)
    code = ("G", "L", "L-if-data", "D", "N")[h % 5]
    form: dict[str, Any] = {
        "id": fid,
        "defect": "a restatement",
        "code": code,
        "multiple_defects": False,
        "reason": "scripted",
    }
    pair = _numeric_pair(nodes)
    if code in ("G", "L") and pair is not None:
        node, qa, va, ua, qb, vb, ub = pair
        same = qa == qb
        form.update(
            {
                "gate_relation": "power_budget" if code == "G" else "none",
                "relation": "a * 2 <= b" if same else "a <= b",
                "law": "a bound",
                "kind": "law",
                "inputs": [
                    {"symbol": "a", "node": node, "quantity": qa, "value": va, "unit": ua},
                    {"symbol": "b", "node": node, "quantity": qb, "value": vb, "unit": ub},
                ],
                "tolerance": "inequality",
                "evaluation": "violated",
                "family": 4,
                "fallback_code": "N",
            }
        )
    elif code in ("G", "L"):
        form.update({"code": "N", "n_kind": "judgement"})
    elif code == "L-if-data":
        form.update(
            {
                "relation": "P == V**2 / R",
                "law": "Joule heating",
                "kind": "law",
                "inputs": [],
                "missing": [{"node": None, "quantity": "resistance"}],
                "family": 4,
            }
        )
    elif code == "D":
        form["d_kind"] = "table"
    else:
        form["n_kind"] = "judgement"
    return form


def standin(argv: list[str], packet: str) -> dict[str, Any] | list[dict[str, Any]]:
    model = argv[argv.index("--model") + 1]
    schema = argv[argv.index("--json-schema") + 1]
    pid = re.search(r"^# Packet (\S+)", packet, re.M)
    pid_s = pid.group(1) if pid else "?"
    state = os.environ.get("RLAW_STANDIN_STATE")
    if state and _h(pid_s, "flaky") % 4 == 0:
        mark = Path(state) / f"{hashlib.sha256(packet.encode()).hexdigest()[:16]}.seen"
        if not mark.exists():
            mark.write_text("1")
            return [
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "structured_output": {"findings": []},
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                    "modelUsage": {model: {}},
                }
            ]
    found = _findings(packet)
    if '"verdict"' in schema:
        out = []
        for fid, text in found:
            h = _h(model, text, "reality")
            verdict = ("true_flaw", "true_flaw", "true_flaw", "not_a_flaw", "undecidable")[h % 5]
            origin = (
                ("already_in_base", "introduced", "introduced", "both")[h // 5 % 4]
                if verdict == "true_flaw"
                else "n/a"
            )
            out.append({"id": fid, "verdict": verdict, "origin": origin, "reason": "scripted"})
    else:
        nodes = _design(packet)
        out = [_coder_form(fid, text, pid_s, model, nodes) for fid, text in found]
        if '"chosen"' in schema:
            for f in out:
                f["chosen"] = ("A", "B", "other")[_h(f["id"], pid_s) % 3]
    return [
        {"type": "system", "subtype": "init", "model": model},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": {"findings": out},
            "usage": {
                "input_tokens": len(packet) // 4,
                "output_tokens": 300 * max(len(found), 1),
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "modelUsage": {model: {"inputTokens": len(packet) // 4}},
        },
    ]


def write_standin(where: Path) -> Path:
    """An executable that runs the stand-in with this interpreter."""
    exe = where / "standin"
    exe.write_text(
        "#!/usr/bin/env bash\n"
        f'exec "{sys.executable}" -I "{HERE / "law_fixture.py"}" standin "$@"\n'
    )
    exe.chmod(0o755)
    return exe


def main(argv: list[str]) -> int:
    if argv[:1] == ["standin"]:
        res = standin(argv[1:], sys.stdin.read())
        print(json.dumps(res))
        return 0
    if argv[:1] == ["build"] and len(argv) == 2:
        fx = build(Path(argv[1]))
        print(json.dumps({"sets": {k: str(v) for k, v in fx["sets"].items()}}))
        return 0
    print("usage: law_fixture.py standin <args> | build <dir>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    tempfile.tempdir = None
    sys.exit(main(sys.argv[1:]))
