"""Mutation driver for the review-window change. Run with `python -u` from a checkout.

argv[1]: the JSON file of mutants {name, file, old, new, tests: [paths]}; argv[2]: output JSONL.
Each mutant (and a baseline first and last) runs in a fresh `git archive HEAD` copy, with the
copy's src first on PYTHONPATH (where physgate imports from is printed and asserted), the
checkout's .venv linked in, a fresh PYTHONPYCACHEPREFIX and --basetemp, no cache provider,
serial, 1200 s timeout. A kill is at least one test failing on an assertion: a JUnit <failure>
whose message starts with AssertionError, "assert " or "Failed: DID NOT RAISE". An error, a
collection failure, another exception or a timeout is never a kill.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

WORKTREE = Path.cwd()
TIMEOUT = 1200


def run_one(mutant: dict[str, Any], index: int) -> dict[str, Any]:
    name = str(mutant["name"])
    # Outside any path holding a word a rule of the harness reads (the review root's word
    # check refuses "physgate" in the path), and outside the clone: a fresh directory in /tmp.
    copy = Path(tempfile.mkdtemp(prefix=f"ctx-{index:02d}-", dir="/tmp"))
    # The tests' own files outside the copy too: a destination inside the checkout is refused for
    # that alone (provisioning's "in or around the harness checkout").
    basetemp = Path(tempfile.mkdtemp(prefix=f"ctx-bt-{index:02d}-", dir="/tmp"))
    archive = subprocess.run(
        ["git", "archive", "HEAD"], cwd=WORKTREE, capture_output=True, check=True
    )
    subprocess.run(["tar", "-x", "-C", str(copy)], input=archive.stdout, check=True)
    (copy / ".venv").symlink_to(WORKTREE / ".venv")
    if mutant.get("file"):
        target = copy / str(mutant["file"])
        text = target.read_text()
        old, new = str(mutant["old"]), str(mutant["new"])
        assert text.count(old) == 1, (name, text.count(old))
        target.write_text(text.replace(old, new))
    env = {
        **os.environ,
        "PYTHONPATH": str(copy / "src"),
        "PYTHONPYCACHEPREFIX": str(copy / ".pyc"),
        "UV_PROJECT_ENVIRONMENT": str(WORKTREE / ".venv"),
    }
    env.pop("PHYSGATE_TEST_ROOT", None)
    python = str(WORKTREE / ".venv" / "bin" / "python")
    where = subprocess.run(
        [python, "-c", "import physgate; print(physgate.__file__)"],
        cwd=copy,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert where.startswith(str(copy)), (where, copy)
    junit = copy / "junit.xml"
    argv = [
        python,
        "-u",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-n",
        "0",
        f"--basetemp={basetemp / 'bt'}",
        f"--junitxml={junit}",
        *[str(t) for t in mutant["tests"]],
    ]
    try:
        done = subprocess.run(
            argv, cwd=copy, env=env, capture_output=True, text=True, timeout=TIMEOUT, check=False
        )
        code: int | str = done.returncode
        tail = done.stdout.strip().splitlines()[-1:] if done.stdout else []
    except subprocess.TimeoutExpired:
        code, tail = "timeout", []
    asserted, other, errors, tests = [], [], 0, 0
    if junit.exists():
        root = ET.parse(junit).getroot()
        for case in root.iter("testcase"):
            tests += 1
            for failure in case.findall("failure"):
                message = failure.get("message") or ""
                first = message.strip()
                if (
                    first.startswith("AssertionError")
                    or first.startswith("assert ")
                    or first.startswith("Failed: DID NOT RAISE")
                ):
                    asserted.append(f"{case.get('name')}: {first[:90]}")
                else:
                    other.append(f"{case.get('name')}: {first[:90]}")
            errors += len(case.findall("error"))
    result = {
        "name": name,
        "imports_from": where,
        "exit": code,
        "tests": tests,
        "assertion_failures": len(asserted),
        "other_failures": len(other),
        "errors": errors,
        "killed": bool(asserted) and code != "timeout",
        "first": (asserted or other or [""])[0],
        "failing": (asserted + other) if name.startswith("baseline") else [],
        "tail": tail,
    }
    shutil.rmtree(copy, ignore_errors=True)
    shutil.rmtree(basetemp, ignore_errors=True)
    return result


def main() -> None:
    mutants = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    every = sorted({t for m in mutants for t in m["tests"]})
    baseline = {"name": "baseline", "tests": every}
    rows = [baseline, *mutants, {**baseline, "name": "baseline-last"}]
    with out.open("w") as handle:
        for index, mutant in enumerate(rows):
            result = run_one(mutant, index)
            handle.write(json.dumps(result) + "\n")
            handle.flush()
            print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
