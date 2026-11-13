# ruff: noqa: E501 - each mutant's text is the source's own line, kept whole to be found exactly
"""Mutants for the usage-limit fix: one per rule, each run against the rows that guard it.

Run from the repository's root: ``python -u scripts/mutate_usage_limit.py``. Each mutant
replaces one exact text in one source file (a text found other than once is an invalid
mutant), runs the rows with a fresh bytecode cache and a fresh basetemp, and restores the
file. A kill is a failing assertion only: an error, a collection failure or a timeout is
not. The unmutated tree is run first and last, and both must pass.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROWS = (
    "tests/unit/orchestrator/test_a_usage_limit_is_its_own_cause_and_the_run_waits_for_its_reset.py",
    "tests/unit/reviewers/test_a_review_that_met_the_usage_limit_names_it.py",
)
TIMEOUT_S = 1200
UL = "src/physgate/orchestrator/usage_limit.py"
LOOP = "src/physgate/orchestrator/loop.py"
EV = "src/physgate/orchestrator/events.py"
WAIT = "src/physgate/orchestrator/waiting.py"
CLI = "src/physgate/orchestrator/cli.py"
REV = "src/physgate/reviewers/claude.py"

#: (name, rule, file, old, new)
MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
    # 1. A usage limit is its own cause, read from the stream; the reset parsed in its zone.
    (
        "event-any-state",
        "1",
        UL,
        'info.get("status") == REJECTED',
        'info.get("status") != REJECTED',
    ),
    ("message-sign-dropped", "1", UL, 'event.get("error") == RATE_LIMIT', "False"),
    (
        "text-sign-dropped",
        "1",
        UL,
        "if not signed and _NAMES_THE_LIMIT.search(said) is None:",
        "if not signed:",
    ),
    ("never-the-limit", "1", UL, 'if end.cause == "api_error" else None', "if False else None"),
    (
        "reset-text-dropped",
        "1",
        UL,
        "UsageLimit(resets=resets.group(1) if resets else None)",
        "UsageLimit(resets=None)",
    ),
    ("pm-ignored", "1", UL, '(12 if found["half"].lower() == "pm" else 0)', "0"),
    ("no-same-day", "1", UL, "for days in (0, 1, 2):", "for days in (1, 2):"),
    ("zone-ignored", "1", UL, "local = after.astimezone(zone)", "local = after"),
    (
        "instant-not-recorded",
        "1",
        UL,
        'return limit.model_copy(update={"resets_at": utc_stamp(instant)})',
        "return limit",
    ),
    (
        "review-limit-not-named",
        "1",
        REV,
        "stop.usage_limit = usage_limit_of(text, result)",
        "stop.usage_limit = None",
    ),
    # 2. No retry is spent and nothing is forced into the queue.
    (
        "session-limit-retried",
        "2",
        LOOP,
        "if now.session is not None and now.session.usage_limit is not None:",
        "if False:",
    ),
    (
        "review-limit-retried",
        "2",
        LOOP,
        "                if exc.usage_limit is not None:\n",
        "                if False:\n",
    ),
    # 3. The run halts waiting; a resume before the instant refuses, after it goes on.
    (
        "no-refusal",
        "3",
        LOOP,
        "        if why is not None:\n            raise LimitNotResetError(",
        "        if False:\n            raise LimitNotResetError(",
    ),
    (
        "refusal-never",
        "3",
        UL,
        "    if now >= stamped(after):\n        return None",
        "    return None",
    ),
    ("word-overrides-read", "3", UL, "if not read and limit_reset:", "if limit_reset:"),
    (
        "no-default-wait",
        "3",
        UL,
        "UNREAD_RESET_WAIT = timedelta(hours=5)",
        "UNREAD_RESET_WAIT = timedelta(0)",
    ),
    (
        "limit-halt-not-resumable",
        "3",
        EV,
        '"os_layer_unavailable", "usage_limit"}',
        '"os_layer_unavailable"}',
    ),
    ("word-not-recorded", "3", LOOP, "limit_reset_by=limit_word,", "limit_reset_by=None,"),
    # 4. Other infrastructure errors are unchanged.
    (
        "api-error-read-as-limit",
        "4",
        UL,
        '\\busage limit reached\\b", re.I)',
        '\\busage limit reached\\b|API Error", re.I)',
    ),
    # 5. Replay: lines with no limit byte for byte; the limit on a line exactly when it is the cause.
    (
        "session-line-keeps-null",
        "5",
        EV,
        '        # Every other end is written byte for byte as before the limit was a cause.\n        data: dict[str, Any] = handler(self)\n        if self.usage_limit is None:\n            data.pop("usage_limit", None)',
        "        # Every other end is written byte for byte as before the limit was a cause.\n        data: dict[str, Any] = handler(self)",
    ),
    (
        "halt-line-keeps-null",
        "5",
        EV,
        '        # A halt of any other reason is written byte for byte as before the limit was a cause.\n        data: dict[str, Any] = handler(self)\n        if self.usage_limit is None:\n            data.pop("usage_limit", None)',
        "        # A halt of any other reason is written byte for byte as before the limit was a cause.\n        data: dict[str, Any] = handler(self)",
    ),
    (
        "resume-line-keeps-null",
        "5",
        EV,
        '        if self.limit_reset_by is None:\n            data.pop("limit_reset_by", None)',
        "        pass",
    ),
    (
        "halt-limit-unchecked",
        "5",
        EV,
        'if (self.reason == "usage_limit") != (self.usage_limit is not None):',
        "if False:",
    ),
    (
        "end-limit-unchecked",
        "5",
        EV,
        'if (self.cause == "usage_limit") != (self.usage_limit is not None):',
        "if False:",
    ),
    # 6. The command line's new step and exit status, and its refusal before anything is touched.
    (
        "printed-as-halted",
        "6",
        WAIT,
        'if kind == "halted" and halted is not None and halted.reason == "usage_limit":',
        "if False:",
    ),
    ("exit-as-halted", "6", WAIT, "EXIT_WAITING_FOR_LIMIT = 75", "EXIT_WAITING_FOR_LIMIT = 1"),
    (
        "cli-no-early-refusal",
        "6",
        CLI,
        "        if waiting is not None:\n            return _waiting(waiting)",
        "        pass",
    ),
    (
        "cli-word-ignored",
        "6",
        WAIT,
        "resume_refusal(halted.ts, halted.usage_limit, now, limit_reset=limit_reset)",
        "resume_refusal(halted.ts, halted.usage_limit, now, limit_reset=False)",
    ),
    # 7. The reset is the refusal event's instant; the limit's kind as given, a weekly one too.
    (
        "event-instant-dropped",
        "7",
        UL,
        '"resets_at": _instant(refusal.get("resetsAt")),',
        '"resets_at": None,',
    ),
    (
        "kind-dropped",
        "7",
        UL,
        '"limit_type": kind if isinstance(kind, str) and kind else None,',
        '"limit_type": None,',
    ),
    (
        "kind-known-only",
        "7",
        UL,
        '"limit_type": kind if isinstance(kind, str) and kind else None,',
        '"limit_type": kind if kind in ("five_hour", "seven_day") else None,',
    ),
    ("first-refusal", "7", UL, "refusal = refusals[-1]", "refusal = refusals[0]"),
    (
        "bool-epoch",
        "7",
        UL,
        "if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:",
        "if not isinstance(epoch, int) or epoch <= 0:",
    ),
    (
        "zero-epoch",
        "7",
        UL,
        "if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:",
        "if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 0:",
    ),
    (
        "loop-text-over-event",
        "7",
        LOOP,
        "if limit is None or limit.resets_at is not None:",
        "if limit is None:",
    ),
    (
        "detail-kind-dropped",
        "7",
        LOOP,
        'kind = f"a {limit.limit_type} limit, " if limit.limit_type else ""',
        'kind = ""',
    ),
    (
        "printed-kind-dropped",
        "7",
        WAIT,
        '"limit_type": limit.limit_type if limit is not None else None,',
        '"limit_type": None,',
    ),
    # 8. The windows' figures: on the limit, and at every session's end.
    ("windows-dropped", "8", UL, '"windows": _windows(refusal),', '"windows": (),'),
    (
        "bool-share",
        "8",
        UL,
        "if isinstance(used, bool) or not isinstance(used, int | float):",
        "if not isinstance(used, int | float):",
    ),
    (
        "share-range-unchecked",
        "8",
        UL,
        "used_fraction: Annotated[float, Field(ge=0, allow_inf_nan=False)]",
        "used_fraction: Annotated[float, Field()]",
    ),
    (
        "windows-first-event",
        "8",
        UL,
        "for event in reversed(_events(data)):",
        "for event in _events(data):",
    ),
    (
        "windows-empty-taken",
        "8",
        UL,
        "        if windows:\n            return windows\n    return ()",
        "        return windows\n    return ()",
    ),
    (
        "windows-not-recorded",
        "8",
        LOOP,
        "account_windows=report.account_windows,",
        "account_windows=(),",
    ),
    (
        "windows-line-kept",
        "8",
        EV,
        '        if not self.account_windows:\n            data.pop("account_windows", None)',
        "        pass",
    ),
)

#: A failure's line in pytest's summary: the test's id (a parameter's id may hold spaces, inside
#: its brackets), then its reason.
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
