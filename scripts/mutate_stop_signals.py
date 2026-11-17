# ruff: noqa: E501 - each mutant's text is the source's own line, kept whole to be found exactly
"""Mutants for the stop-signal guard and the resume's credential sweep, run against their rows.

Run from the repository's root: ``python -u scripts/mutate_stop_signals.py``. Each mutant
replaces one exact text in one source file (a text found other than once is an invalid
mutant), runs the rows with a fresh bytecode cache and a fresh basetemp, and restores the
file. A kill is a failing assertion only: an error, a collection failure or a timeout is
not. The unmutated tree is run first and last, and both must pass.

Not mutated: the handler's ``os._exit`` after its own signal (reached only if the signal is not
delivered); ``_reaped``'s ``ChildProcessError`` branch and ``_running``'s unreadable table
(reached only when another wait reaped the session between two of its lines, or ``ps`` fails);
keeping a session unreaped through the grace, which only keeps its pid from being handed to
another group before the group's SIGKILL; a survivor counted on ``not reaped`` alone (no row has a
session unreaped whose group is empty: a session is its group's leader); the messaging keys'
directory check (unlinking a directory raises, an error and not a kill); and an unreadable run
record or owner file, which only finds no reviewer session. The wait after SIGKILL for each session and its group
is mutated against rows whose probe stands in for a process still dying.
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
P = "src/physgate/orchestrator/processes.py"

#: (name, rule, file, old, new)
MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
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
        "    while len(ended) < len(live) and time.monotonic() < deadline:",
        "    while time.monotonic() < deadline:",
    ),
    ("running-always", "a", S, "        return started_at(pid) is not None", "        return True"),
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
        "            os.killpg(process.pid, signal.SIGKILL)",
        "            pass",
    ),
    (
        "no-reap-wait",
        "a",
        S,
        "        while not reaped and time.monotonic() < gone:\n            time.sleep(_WAIT_S)\n            reaped = _reaped(process.pid)\n",
        "",
    ),
    (
        "no-group-wait",
        "a",
        S,
        "        while left and time.monotonic() < gone:\n            time.sleep(_WAIT_S)\n            left = _group_left(process.pid)\n",
        "",
    ),
    (
        "reap-unbounded",
        "a",
        S,
        "        while not reaped and time.monotonic() < gone:",
        "        while not reaped:",
    ),
    (
        "group-unbounded",
        "a",
        S,
        "        while left and time.monotonic() < gone:",
        "        while left:",
    ),
    (
        "survivor-not-counted",
        "d",
        S,
        "        if not reaped or left:\n            survivors.append(process.pid)",
        "        if False:\n            survivors.append(process.pid)",
    ),
    ("survivor-exit-dropped", "d", S, "    if alive:\n        os._exit(EXIT_SESSIONS_ALIVE)\n", ""),
    (
        "survivor-claims-removed",
        "d",
        S,
        "MAY_BE_WRITTEN_AGAIN if alive else REMOVED",
        "REMOVED",
    ),
    (
        "survivors-unnamed",
        "d",
        S,
        '    if alive:\n        said["survivors"] = list(ended.survivors)\n',
        "",
    ),
    (
        "gone-counts-tried",
        "d",
        S,
        '"sessions_gone": ended.tried - alive,',
        '"sessions_gone": ended.tried,',
    ),
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
        "    with driving(run_dir), on_stop_signals():\n        return _drive_run(",
        "    with driving(run_dir):\n        return _drive_run(",
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
        "            with suppress(OSError, InvocationError):\n                remove_debug_logs(directory)\n",
        "",
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
    (
        "no-early-sweep",
        "c",
        CLI,
        "    remove_left_credentials(run_dir, None if review_root is None else review_root_path(review_root))\n",
        "",
    ),
    (
        "listing-wrong-flag",
        "c",
        P,
        "if before in SESSION_ID_FLAGS)",
        "if before not in SESSION_ID_FLAGS)",
    ),
    (
        "listing-failure-taken",
        "c",
        P,
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
    (
        "running-not-skipped",
        "c",
        S,
        "        if session_id in running:\n            continue\n",
        "",
    ),
    (
        "link-refusal-escapes",
        "c",
        S,
        "        except (OSError, InvocationError):\n            continue",
        "        except OSError:\n            continue",
    ),
    ("not-reported", "c", S, "        removed.append(session_id)", "        pass"),
    (
        "sweep-unlocked",
        "e",
        S,
        "            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)",
        "            pass",
    ),
    ("drive-unlocked", "e", S, "            fcntl.flock(fd, fcntl.LOCK_SH)", "            pass"),
    (
        "lock-refusal-not-caught",
        "h",
        S,
        "        except OSError:\n            _say_unlocked()",
        "        except ZeroDivisionError:\n            _say_unlocked()",
    ),
    (
        "lock-refusal-not-said",
        "h",
        S,
        "            _say_unlocked()\n        yield",
        "            pass\n        yield",
    ),
    ("lock-refusal-said-every-time", "h", S, "    _said_unlocked = True\n", ""),
    (
        "sweep-refusal-not-caught",
        "h",
        S,
        "        except OSError:\n            return ()\n        return _sweep",
        "        except ZeroDivisionError:\n            return ()\n        return _sweep",
    ),
    (
        "key-pattern-unicode-digits",
        "i",
        C,
        'MESSAGING_KEY = re.compile(r"^[0-9]+\\.',
        'MESSAGING_KEY = re.compile(r"^\\d+\\.',
    ),
    (
        "key-unlink-error-stops-loop",
        "j",
        C,
        "                except OSError:\n                    left += 1",
        "                except OSError:\n                    left += 1\n                    break",
    ),
    (
        "key-unlink-error-not-raised",
        "j",
        C,
        "        if left:\n            msg =",
        "        if False:\n            msg =",
    ),
    (
        "failures-not-counted",
        "j",
        C,
        "            failed += 1\n        try:\n            remove_messaging_keys",
        "            pass\n        try:\n            remove_messaging_keys",
    ),
    ("stop-line-no-count", "j", S, '        said["removal_failures"] = failed', "        pass"),
    ("stop-line-says-removed", "j", S, "NOT_ALL_REMOVED if failed else REMOVED", "REMOVED"),
    (
        "cli-not-driving",
        "e",
        CLI,
        "    with driving(run_dir), on_stop_signals():",
        "    with on_stop_signals():",
    ),
    (
        "reviews-not-swept",
        "f",
        S,
        "        sessions += _review_sessions(run_dir, review_root)",
        "        pass",
    ),
    (
        "other-run-swept",
        "f",
        S,
        '            if json.loads(owner.read_text()).get("run_id") == run_id:',
        "            if True:",
    ),
    (
        "cli-no-review-root",
        "f",
        CLI,
        "remove_left_credentials(run_dir, None if review_root is None else review_root_path(review_root))",
        "remove_left_credentials(run_dir, None)",
    ),
    (
        "resume-not-listed",
        "f",
        P,
        'SESSION_ID_FLAGS = ("--session-id", "--resume")',
        'SESSION_ID_FLAGS = ("--session-id",)',
    ),
    (
        "keys-left-at-end",
        "g",
        C,
        "                remove_messaging_keys(config_dir)",
        "                pass",
    ),
    (
        "keys-left-at-stop",
        "g",
        C,
        "        try:\n            remove_messaging_keys(directory)\n        except (OSError, InvocationError):\n            failed += 1\n",
        "",
    ),
    (
        "key-pattern-loose",
        "g",
        C,
        'MESSAGING_KEY = re.compile(r"^[0-9]+\\.[0-9a-f]{64}\\.key',
        'MESSAGING_KEY = re.compile(r"^.*\\.key',
    ),
    ("no-tmp-keys", "g", C, r'\.key(?:\.tmp\.[0-9a-f]+)?$")', r'\.key$")'),
    (
        "keys-link-followed",
        "g",
        C,
        "os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)",
        "os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)",
    ),
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
