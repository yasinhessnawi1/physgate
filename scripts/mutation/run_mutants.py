"""Mutation driver: each mutant's change applied to a fresh copy of HEAD, its named rows run.

Run with ``python -u scripts/mutation/run_mutants.py <list.json> [name ...]`` from a clean
checkout's root; names after the list run only those mutants, between the list's baselines.
The list is a JSON array of ``{name, file, old, new, tests: [paths]}``; a mutant whose
name starts with ``baseline`` (``baseline_first``, ``baseline_last``) applies no change,
and the list starts and ends with one, each named once. ``MUT_VENV`` names the
environment whose Python runs the rows (default ``.venv``; ``.venv-evaluation`` for
``tests/scoring``). Optional keys: ``paths``, more of HEAD to copy that is not a row (a rig's
sources, a helper module beside the rows); ``args``, more pytest arguments (``-m`` to select
integration rows); ``tool_environment: true``, the rows run against a fresh tool environment
made from the one ``MUT_TOOL_ENVIRONMENT`` names, every part of it linked except its
simulator rig, which is copied and given the copy's ``toolenv/avrsim`` sources and launcher,
mutated or not; ``PHYSGATE_TOOL_ENVIRONMENT`` names it.

Each run gets a fresh ``git archive`` copy of HEAD holding what the named rows need (``src``,
``scripts``, ``pyproject.toml``, the files directly under ``tests/`` and the rows), under a
work directory spelt as the filesystem spells it; the copy's ``src`` first on ``PYTHONPATH``,
proved by where ``physgate`` imports from; a fresh ``PYTHONPYCACHEPREFIX`` and ``--basetemp``;
no cache provider; serial; a 1200 s timeout. A kill is at least one row failing on an
assertion (a JUnit failure from ``AssertionError``, a plain ``assert`` or ``pytest.raises``'
``Failed``); an error, a collection failure, a refusal or a timeout is never a kill, and
neither is a row failing only where it asserts that a program it ran exited 0 (the mutant
crashed the program). A change whose ``old`` text does not occur exactly once is refused (an
invalid mutant, to be replaced).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

TIMEOUT_S = 1200
#: The failing line of a row that asserts a program it ran exited 0: a crash, never a kill.
CRASHED = re.compile(r"^>\s+assert \w+\.returncode == 0\b", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def _tool_environment(tree: Path, work: Path) -> Path:
    """A fresh tool environment: the named one's parts linked, its rig copied from ``tree``."""
    source = Path(os.environ["MUT_TOOL_ENVIRONMENT"])
    env = work / "env"
    env.mkdir()
    for part in source.iterdir():
        if part.name != "avrsim":
            (env / part.name).symlink_to(part)
    rig = env / "avrsim"
    shutil.copytree(source / "avrsim", rig, symlinks=True)
    shutil.rmtree(rig / "src")
    shutil.copytree(tree / "toolenv" / "avrsim" / "src", rig / "src")
    shutil.copy2(tree / "toolenv" / "avrsim" / "bin" / "avrsim", rig / "bin" / "avrsim")
    return env


def _verdicts(junit: Path) -> tuple[list[str], list[str], int]:
    failing: list[str] = []
    errors: list[str] = []
    total = 0
    if not junit.exists():
        return failing, errors, total
    for case in ET.parse(junit).iter("testcase"):
        total += 1
        failure = case.find("failure")
        error = case.find("error")
        message = "" if failure is None else failure.get("message") or ""
        text = "" if failure is None else failure.text or ""
        if failure is not None and CRASHED.search(text):
            errors.append(f"{case.get('name') or '?'} (the program crashed)")
        elif failure is not None and (
            message.startswith(("AssertionError", "Failed", "assert ")) or "AssertionError" in text
        ):
            failing.append(case.get("name") or "?")
        elif failure is not None or error is not None:
            errors.append(case.get("name") or "?")
    return failing, errors, total


def _run(m: dict[str, Any], python: Path, helpers: list[str]) -> tuple[str, list[str]]:
    work = Path(os.path.realpath(tempfile.mkdtemp(prefix="mut-")))
    try:
        tree = work / "tree"
        tree.mkdir()
        paths = [*helpers, *m.get("paths", []), *m["tests"]]
        archive = subprocess.run(
            ["git", "archive", "HEAD", "src", "scripts", "pyproject.toml", *paths],
            capture_output=True,
            check=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(tree)], input=archive, check=True)
        if not m["name"].startswith("baseline"):
            target = tree / m["file"]
            text = target.read_text()
            count = text.count(m["old"])
            if count != 1:
                print(f"[mut] {m['name']}: REFUSED, the text occurs {count} times")
                return "refused", []
            target.write_text(text.replace(m["old"], m["new"]))
        env = {
            **os.environ,
            "PYTHONPATH": str(tree / "src"),
            "PYTHONPYCACHEPREFIX": str(work / "pycache"),
        }
        if m.get("tool_environment"):
            if not os.environ.get("MUT_TOOL_ENVIRONMENT"):
                print(f"[mut] {m['name']}: REFUSED, no MUT_TOOL_ENVIRONMENT named")
                return "refused", []
            env["PHYSGATE_TOOL_ENVIRONMENT"] = str(_tool_environment(tree, work))
        where = subprocess.run(
            [str(python), "-c", "import physgate; print(physgate.__file__)"],
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if not where.startswith(str(tree)):
            print(f"[mut] {m['name']}: REFUSED, physgate imports from {where}")
            return "refused", []
        junit = work / "junit.xml"
        cmd = [
            str(python),
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-n",
            "0",
            f"--basetemp={work / 'basetemp'}",
            f"--junitxml={junit}",
            *m.get("args", []),
            *m["tests"],
        ]
        try:
            run = subprocess.run(
                cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            print(f"[mut] {m['name']}: TIMEOUT (not a kill)")
            return "timeout", []
        failing, errors, total = _verdicts(junit)
        out = run.stdout.strip()
        tail = out.splitlines()[-1] if out else run.stderr[-200:]
        if m["name"].startswith("baseline"):
            clean = run.returncode == 0 and total > 0 and not failing and not errors
            verdict = "green" if clean else "NOT GREEN"
        elif failing:
            verdict = "killed"
        else:
            verdict = "survived" if run.returncode == 0 else "not a kill (errors only)"
        print(f"[mut] {m['name']}: {verdict} | rc {run.returncode} | {tail}")
        for name in failing[:4]:
            print(f"[mut]     red at {name}")
        for name in errors[:4]:
            print(f"[mut]     error (not counted) at {name}")
        return verdict, failing
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str]) -> int:
    """Run every mutant of the list named in ``argv[1]`` and print each verdict and a tally."""
    if _git("status", "--porcelain").strip():
        print("[mut] the worktree is not clean; mutants run on a commit")
        return 2
    python = Path.cwd() / os.environ.get("MUT_VENV", ".venv") / "bin" / "python"
    mutants: list[dict[str, Any]] = json.loads(Path(argv[1]).read_text())
    if len(argv) > 2:
        unknown = set(argv[2:]) - {m["name"] for m in mutants}
        if unknown:
            print(f"[mut] not in the list: {sorted(unknown)}")
            return 2
        mutants = [m for m in mutants if m["name"].startswith("baseline") or m["name"] in argv[2:]]
    helpers = [line for line in _git("ls-files", "tests").splitlines() if line.count("/") == 1]
    print(f"[mut] HEAD {_git('rev-parse', 'HEAD').strip()}, {len(mutants)} runs")
    tally: dict[str, int] = {}
    for i, m in enumerate(mutants):
        verdict, _ = _run(m, python, helpers)
        tally[verdict] = tally.get(verdict, 0) + 1
        if i == 0 and m["name"].startswith("baseline") and verdict != "green":
            print("[mut] the first baseline is not green; no mutant is run against it")
            return 1
    print("[mut] tally:", json.dumps(tally, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
