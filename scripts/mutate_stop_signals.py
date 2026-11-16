# ruff: noqa: E501 - each mutant's text is the source's own line, kept whole to be found exactly
"""Mutants for the stop-signal guard and the resume's credential sweep, run against their rows.

Run from the repository's root: ``python -u scripts/mutate_stop_signals.py``. Each mutant
replaces one exact text in one source file (a text found other than once is an invalid
mutant), runs the rows with a fresh bytecode cache and a fresh basetemp, and restores the
file. A kill is a failing assertion only: an error, a collection failure or a timeout is
not. The unmutated tree is run first and last, and both must pass.

Not mutated: the handler's ``os._exit`` after its own signal (reached only if the signal is not
delivered), and ``_reaped``'s ``ChildProcessError`` branch (reached only when another wait
reaped the session between two of its lines).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROWS = (
    "tests/unit/orchestrator/test_a_run_stopped_or_killed_mid_session_leaves_no_credential_file.py",
)
TIMEOUT_S = 1200
S = "src/physgate/orchestrator/stop_signals.py"
C = "src/physgate/orchestrator/credentials.py"
D = "src/physgate/orchestrator/dispatch.py"
CLI = "src/physgate/orchestrator/cli.py"
R = "src/physgate/reviewers/claude.py"

#: (name, rule, file, old, new)
MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
    # a. A stop signal ends the run's sessions and removes their files, within a bound.
    (
        "track-no-login",
        "a",
        S,
        "    if login_dir is not None:\n        hold_login(login_dir)",
        "    if False:\n        hold_login(login_dir)",
    ),
    ("track-not-live", "a", S, "    _live.append(process)", "    pass"),
    ("spawn-untracked", "a", D, "    track(process, login_dir)\n", ""),
    (
        "no-tree",
        "a",
        S,
        "            trees.append(tree(process.pid))",
        "            trees.append([])",
    ),
    (
        "no-sigterm",
        "a",
        S,
        "            os.killpg(process.pid, signal.SIGTERM)",
        "            pass",
    ),
    (
        "full-grace-always",
        "a",
        S,
        "    while len(reaped) < len(live) and time.monotonic() < deadline:",
        "    while time.monotonic() < deadline:",
    ),
    (
        "no-tree-kill",
        "a",
        S,
        "                signal_if_same(proc, signal.SIGKILL)",
        "                pass",
    ),
    (
        "no-group-kill",
        "a",
        S,
        "                os.killpg(process.pid, signal.SIGKILL)",
        "                pass",
    ),
    ("reaped-always", "a", S, "    return done == pid", "    return True"),
    ("reaped-never", "a", S, "    return done == pid", "    return False"),
    (
        "no-first-removal",
        "a",
        S,
        "    remove_held_secrets()\n    ended = end_live_sessions()",
        "    ended = end_live_sessions()",
    ),
    (
        "no-second-removal",
        "a",
        S,
        "    ended = end_live_sessions()\n    remove_held_secrets()",
        "    ended = end_live_sessions()",
    ),
    ("handler-not-reset", "a", S, "    signal.signal(signum, signal.SIG_DFL)\n", ""),
    ("not-ended-by-signal", "a", S, "    os.kill(os.getpid(), signum)\n", ""),
    (
        "thread-check-inverted",
        "a",
        S,
        "if threading.current_thread() is not threading.main_thread():",
        "if threading.current_thread() is threading.main_thread():",
    ),
    (
        "ignored-overridden",
        "a",
        S,
        "        if handler == signal.SIG_IGN:\n            continue\n",
        "",
    ),
    ("not-put-back", "a", S, "            signal.signal(each, before)", "            pass"),
    (
        "drive-unguarded",
        "a",
        CLI,
        "    with on_stop_signals():\n        return _drive_run(",
        "    if True:\n        return _drive_run(",
    ),
    (
        "decompose-unguarded",
        "a",
        CLI,
        "    with on_stop_signals():\n        return _decompose_run(",
        "    if True:\n        return _decompose_run(",
    ),
    ("role-login-dropped", "a", D, '                login_dir=sdir / "config",\n', ""),
    ("review-login-dropped", "a", R, "                login_dir=config,\n", ""),
    # b. What this process wrote is held until its session's end removed it.
    (
        "login-not-held",
        "b",
        C,
        "    _hold(config_dir, (LOGIN_FILE,))\n    login = {",
        "    login = {",
    ),
    (
        "key-not-held",
        "b",
        C,
        "    _hold(state_dir, (KEY_FILE, KEY_HELPER))\n    _write_private(secret",
        "    _write_private(secret",
    ),
    (
        "debug-left",
        "b",
        C,
        "        if LOGIN_FILE in names:\n            with suppress(OSError, InvocationError):\n                remove_debug_logs(directory)",
        "        pass",
    ),
    (
        "one-stops-all",
        "b",
        C,
        "        with suppress(OSError, InvocationError):\n            _unlink_in(directory, tuple(sorted(names)))",
        "        _unlink_in(directory, tuple(sorted(names)))",
    ),
    (
        "ended-still-held",
        "b",
        C,
        "    _held.pop(state_dir, None)\n    _held.pop(config_dir, None)\n",
        "",
    ),
    # c. The next command removes the files of the sessions nothing runs as, first.
    ("no-early-sweep", "c", CLI, "    remove_left_credentials(args.run_dir.resolve())\n", ""),
    ("listing-wrong-flag", "c", S, 'if before == "--session-id")', 'if before != "--session-id")'),
    (
        "listing-failure-taken",
        "c",
        S,
        "    if done.returncode != 0 or str(os.getpid()) not in pids:",
        "    if done.returncode != 0 and str(os.getpid()) not in pids:",
    ),
    (
        "listing-ignored",
        "c",
        S,
        "        running = running_session_ids()",
        "        running: frozenset[str] = frozenset()",
    ),
    ("running-not-skipped", "c", S, "        if sdir.name in running:\n            continue\n", ""),
    (
        "link-refusal-escapes",
        "c",
        S,
        "        except (OSError, InvocationError):\n            continue",
        "        except OSError:\n            continue",
    ),
    ("not-reported", "c", S, "        removed.append(sdir.name)", "        pass"),
)


_FAILED = re.compile(r"^FAILED [^\s\[]+(?:\[[^\]]*\])? - (.*)$", re.M)


def run_rows(label: str) -> tuple[str, str]:
    """Run the rows once; say how they came out, with the tail of the output."""
    with tempfile.TemporaryDirectory(prefix=f"mut-{label}-") as scratch:
        # A wide terminal, so pytest's summary keeps each failure's reason on its line: without
        # it the reason is cut and no failure can be read as an assertion's.
        env = {
            **os.environ,
            "PYTHONPYCACHEPREFIX": str(Path(scratch) / "pycache"),
            "COLUMNS": "4000",
        }
        argv = [
            sys.executable,
            "-u",
            "-m",
            "pytest",
            "-q",
            "-rfE",
            "-p",
            "no:cacheprovider",
            "-n",
            "0",
            f"--basetemp={Path(scratch) / 'basetemp'}",
            *ROWS,
        ]
        try:
            done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
                argv, capture_output=True, text=True, timeout=TIMEOUT_S, env=env, check=False
            )
        except subprocess.TimeoutExpired:
            return "timeout", ""
    out = done.stdout + done.stderr
    tail = "\n".join(out.strip().splitlines()[-3:])
    if done.returncode == 0:
        return "pass", tail
    reasons = _FAILED.findall(out)
    asserted = [r for r in reasons if r.startswith(("assert", "AssertionError"))]
    if done.returncode == 1 and asserted and "\nERROR " not in out:
        return f"killed ({len(asserted)} of {len(reasons)} failing on an assertion)", tail
    return f"error (exit {done.returncode})", tail


def main() -> int:
    """Run the baselines and every mutant; say what each came to."""
    root = Path.cwd()
    head = subprocess.run(  # noqa: S603, S607 - git, fixed arguments
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    print(f"head {head}")
    first, tail = run_rows("baseline-first")
    print(f"baseline first: {first}\n{tail}")
    if first != "pass":
        return 1
    results: list[tuple[str, str, str]] = []
    for name, rule, file, old, new in MUTANTS:
        path = root / file
        original = path.read_text()
        if original.count(old) != 1:
            results.append((name, rule, f"invalid ({original.count(old)} matches)"))
            print(f"{rule} {name}: invalid")
            continue
        try:
            path.write_text(original.replace(old, new))
            outcome, tail = run_rows(name)
        finally:
            path.write_text(original)
        results.append((name, rule, outcome))
        print(f"{rule} {name}: {outcome}\n{tail}", flush=True)
    last, tail = run_rows("baseline-last")
    print(f"baseline last: {last}\n{tail}")
    print("\nSUMMARY")
    for name, rule, outcome in results:
        print(f"  rule {rule}  {name:28} {outcome}")
    killed = sum(o.startswith("killed") for _, _, o in results)
    print(f"killed {killed} of {len(results)}; baselines {first}/{last}")
    clean = subprocess.run(  # noqa: S603, S607 - git, fixed arguments
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    print(f"tree clean after: {not clean.strip()}")
    return 0 if last == "pass" and killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
