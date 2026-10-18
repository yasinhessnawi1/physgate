"""Why a present binary's write changed nothing: a diagnostic, not a measurement.

In the bypass corpus's sentinel-alone arm, fifteen binaries that resolve on the
session's path wrote nothing at any target and drew no record. The run's logs keep
no tool output, so the cause was not on record. This drives the same attempts, in
the same arm and placement, through the runner's own ``run_one``, and records one
coarse class per attempt from what the session was told back: the lines meant for
the program ran in the shell instead, the program needs a terminal, it has no Java
script engine, it refused an option, it needs a remote host or privilege, it timed
out, or it said nothing. Only the class, the exit code, the outcome's class and the
number of sentinel records are kept. The deciding line, the outcome's text and the
records' paths are not: each can quote the attempt's own arguments or a file name it
chose, and the attempt list is read by the instrument alone.

It reads the frozen attempt list only through the runner's loader, which checks the
list's checksum, and never prints an attempt's code.

Usage::

    RHK03_SCRATCH=<dir> uv run python tests/integration/hooks/no_op_diagnosis.py
        experiments/R-HK-01/attempts.jsonl <target_key> <out.jsonl> <binary> [<binary> ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import bypass_corpus_runner as runner
import hook_session

from physgate import bypass_corpus as bc

#: Checked in order; the first class whose pattern matches a line names the attempt.
CLASSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shell-parse-error", re.compile(r"parse error", re.I)),
    (
        "no-java-script-engine",
        re.compile(
            r"java runtime|unable to locate a java|script engine .* (can ?not|cannot) be found|"
            r"nashorn|java\.com",
            re.I,
        ),
    ),
    (
        "needs-remote-host",
        re.compile(
            r"could not resolve|connection (refused|closed)|host key|ssh: connect|lost connection",
            re.I,
        ),
    ),
    (
        "needs-terminal",
        re.compile(
            r"not a (tty|terminal)|output is not to a terminal|inappropriate ioctl|tcgetattr|"
            r"stdin is not|must be (run|connected)",
            re.I,
        ),
    ),
    (
        "needs-privilege",
        re.compile(r"you don't have permission|operation not permitted|must be root", re.I),
    ),
    (
        "option-refused",
        re.compile(r"illegal option|invalid option|unrecognized option|unknown option", re.I),
    ),
    # The program never read the lines meant for it (it read nothing from stdin, or
    # wanted a terminal), so the shell ran them as commands of its own.
    ("program-input-ran-in-the-shell", re.compile(r"^\(eval\):\d+: ")),
    ("needs-a-file-it-was-not-given", re.compile(r"failed to open|no such file", re.I)),
    ("timed-out", re.compile(r"timed out|timeout", re.I)),
)
EXIT = re.compile(r"exit code (\d+)", re.I)


def classify(told: str) -> dict[str, Any]:
    """One coarse class for what the session was told, with the line that decided it."""
    exit_code = EXIT.search(told)
    lines = [line.strip() for line in told.splitlines() if line.strip()]
    for name, pattern in CLASSES:
        for line in lines:
            if pattern.search(line):
                return {
                    "class": name,
                    "exit_code": int(exit_code.group(1)) if exit_code else None,
                }
    return {
        "class": "said-nothing" if not lines else "unclassified",
        "exit_code": int(exit_code.group(1)) if exit_code else None,
        "told_lines": len(lines),
    }


def diagnosis_line(
    attempt: dict[str, Any], key: str, record: dict[str, Any], told: str
) -> dict[str, Any]:
    """One attempt's line: classes and counts only, nothing of the texts they came from.

    An outcome's text quotes the paths reached, a sentinel record holds the paths
    put back, and the told text can quote the attempt's own arguments: each can
    carry a file name the attempt chose, so only the outcome's class, the number of
    records and the told text's class are kept.
    """
    return {
        "id": attempt["id"],
        "binary": attempt["binary"],
        "target_key": key,
        "present": record["present"],
        "outcome_class": str(record["outcome"]).split(":", 1)[0],
        "sentinel_records": len(record.get("sentinel_paths", [])),
        **classify(told),
    }


def main(argv: list[str]) -> int:
    """``<attempts.jsonl> <target_key> <out.jsonl> <binary>...``: diagnose those attempts."""
    if len(argv) < 4:
        print(main.__doc__, file=sys.stderr)
        return 2
    attempts_path, key, out_path, binaries = Path(argv[0]), argv[1], Path(argv[2]), set(argv[3:])
    arm = runner.RunnerArm.of("arm2-sentinel")
    captured: list[hook_session.SessionRun] = []
    # The runner calls the session function by its own module-level name, so that name
    # is stood in for; the function behind it is the session module's.
    real = hook_session.run_session

    def keep(*args: Any, **kwargs: Any) -> hook_session.SessionRun:  # noqa: ANN401
        run = real(*args, **kwargs)
        captured.append(run)
        return run

    vars(runner)["run_session"] = keep
    chosen = [
        a
        for a in bc.load_attempts(attempts_path)
        if a["binary"] in binaries and a.get("target_key") == key
    ]
    with out_path.open("w") as out:
        for attempt in chosen:
            captured.clear()
            record = runner.run_one(attempt, arm)
            told = captured[-1].told_after(1) if captured else ""
            line = diagnosis_line(attempt, key, record, told)
            out.write(json.dumps(line) + "\n")
            out.flush()
            print(f"{attempt['id']}: {line['class']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
