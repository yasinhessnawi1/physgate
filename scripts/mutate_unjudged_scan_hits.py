# ruff: noqa: E501 - each mutant's text is the source's own line, kept whole to be found exactly
"""Mutants for the unjudged-scan-hits fix: one or more per rule, each run against its rows.

Run from the repository's root: ``python -u scripts/mutate_unjudged_scan_hits.py`` for the
Python rules, or ``python -u scripts/mutate_unjudged_scan_hits.py ui`` for the queue words (it
needs the UI's dependencies installed). Each mutant replaces one exact text in one source file
(a text found other than once is an invalid mutant), runs the rows with a fresh bytecode cache
and a fresh basetemp, and restores the file. A kill is a failing assertion only: an error, a
collection failure or a timeout is not. The unmutated tree is run first and last, and both must
pass.

Rules: 1 the earlier unjudged attempts' hits go to the next review, which must answer them;
2 a dismissed hit no longer holds an approve, a confirmed or unjudged one still does; 3 the item
and the UI name each hit's attempt and the review that judged it; 4 what an approve never merges
past is unchanged; 5 a run recorded before reads, replays and is decided as it was; 6 a call
the hook layer refused for a protected path is named for what the call was; 7 the reviewer is
told of the earlier attempts it must judge; 8 only a confirmed or dismissed answer naming its
attempt judges an earlier hit, and replay holds a review line to the hits it was shown.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROWS = (
    "tests/unit/orchestrator/test_an_unreviewed_attempt_s_scan_hits_go_to_the_next_review.py",
    "tests/unit/orchestrator/test_a_run_recorded_before_judged_earlier_hits_replays_as_it_did.py",
    "tests/unit/reviewers/test_a_review_is_given_the_hits_no_earlier_review_judged.py",
    "tests/unit/orchestrator/test_a_refused_call_is_named_for_what_it_was.py",
    "tests/unit/orchestrator/test_a_later_item_merges_once_an_earlier_refused_attempt_s_hits_are_judged.py",
    "tests/unit/orchestrator/test_an_earlier_hit_is_judged_only_by_a_confirmed_or_dismissed_answer_naming_its_attempt.py",
    "tests/unit/orchestrator/test_a_review_judges_only_the_earlier_hits_its_packet_showed.py",
    "tests/unit/orchestrator/test_a_review_that_ends_on_the_usage_limit_leaves_the_earlier_hits_unjudged.py",
)
UI_ROWS = ("src/screens/queue/consequence.test.tsx",)
PROMPT_ROWS = (
    "tests/unit/reviewers/test_a_reviewer_is_told_of_the_earlier_attempts_it_must_judge.py",
)
TIMEOUT_S = 1200
LOOP = "src/physgate/orchestrator/loop.py"
DEC = "src/physgate/orchestrator/decisions.py"
REP = "src/physgate/orchestrator/replay.py"
EV = "src/physgate/orchestrator/events.py"
QUE = "src/physgate/orchestrator/queue.py"
PROT = "src/physgate/orchestrator/protocols.py"
SCAN = "src/physgate/reviewers/scan.py"
PKT = "src/physgate/reviewers/packet.py"
REV = "src/physgate/reviewers/claude.py"
VER = "src/physgate/reviewers/verdict.py"
CON = "src/physgate/reviewers/contract.py"
WORDS = "ui/src/words/queue.ts"
API = "ui/src/api/queue.ts"

#: (name, rule, file, old, new)
MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
    # 1. The next reviewed attempt is given the earlier unjudged attempts, and must answer them.
    ("no-earlier-given", "1", LOOP,
     "earlier = self._unjudged_earlier(subtask_id, attempt) if self._acts() else []",
     "earlier = []"),
    ("record-run-given-earlier", "1", LOOP,
     "earlier = self._unjudged_earlier(subtask_id, attempt) if self._acts() else []",
     "earlier = self._unjudged_earlier(subtask_id, attempt)"),
    ("earlier-includes-judged", "1", LOOP,
     "if earlier.number >= attempt or earlier.number in judged:",
     "if earlier.number >= attempt:"),
    ("unanswered-counts-judged", "1", SCAN,
     "if all(judges(hit, answers) for hit in hits) and all(",
     "if all("),
    ("packet-drops-earlier", "1", PKT,
     "earlier_parts = _write_parts(read, split_parts(earlier, EARLIER_PART)) if earlier else ()",
     "earlier_parts = ()"),
    ("earlier-not-required-reading", "1", PKT,
     "        *(read / part.name for part in earlier_parts),\n",
     ""),
    ("earlier-parts-unchecked", "1", PKT,
     "    _check_earlier(packet, artefact, read)\n",
     ""),
    ("earlier-seal-unheld", "1", PKT,
     "                data = read_sealed(Path(session.trajectory), expected)",
     "                data = Path(session.trajectory).read_bytes()"),
    ("verdict-ignores-earlier", "1", REV,
     "earlier = packet.earlier_indicators if isinstance(packet, Packet) else ()",
     "earlier = ()"),
    # 2. Dismissed no longer holds an approve; confirmed and unjudged still do.
    ("judged-ignores-earlier", "2", REP,
     "return {r.attempt for r in self.reviews} | {\n            n for r in self.reviews for n in r.judged_earlier\n        }",
     "return {r.attempt for r in self.reviews}"),
    ("scan-ignores-judged", "2", LOOP,
     "            if attempt.number in judged:\n                continue\n            found = self._hits_in(",
     "            found = self._hits_in("),
    ("confirmed-not-blocking", "2", DEC,
     "if why_not is None and indicators:",
     "if False:"),
    ("unjudged-not-blocking", "2", DEC,
     "    if why_not is None and hits:\n",
     "    if False:\n"),
    # 3. The item names each hit's attempt and the review that judged an earlier attempt.
    ("item-hits-unmarked", "3", LOOP,
     "hits.extend(hit.of_attempt(attempt.number) for hit in found)",
     "hits.extend(found)"),
    ("packet-hits-unmarked", "3", PKT,
     "hits.extend(hit.of_attempt(attempt) for hit in scan(stream))",
     "hits.extend(scan(stream))"),
    ("item-no-judged-earlier", "3", DEC,
     "judged_earlier=judged_earlier(sub) if source in SCANNED_SOURCES else (),",
     "judged_earlier=(),"),
    # 4. What an approve never merges past.
    ("automated-not-first", "4", DEC,
     "why_not: WhyRecordOnly | None = _automated_block(now)",
     "why_not: WhyRecordOnly | None = None"),
    ("seal-unheld-at-merge", "4", LOOP,
     "            if not self._sealed_hold(sessions):\n                return False",
     "            if False:\n                return False"),
    ("held-ignored", "4", DEC, "    if held:", "    if False:"),
    # 5. A run recorded before.
    ("review-line-keeps-empty", "5", EV,
     "        if not self.judged_earlier:\n            data.pop(\"judged_earlier\", None)\n        if not self.earlier_hits:",
     "        if not self.earlier_hits:"),
    ("review-line-keeps-no-hits", "5", EV,
     "        if not self.earlier_hits:\n            data.pop(\"earlier_hits\", None)\n",
     ""),
    ("hit-keeps-no-attempt", "5", SCAN,
     "        if self.attempt is None:\n            data.pop(\"attempt\", None)\n",
     ""),
    ("item-keeps-empty-judged", "5", QUE,
     "        if not self.judged_earlier:\n            data.pop(\"judged_earlier\", None)\n",
     ""),
    ("artefact-keeps-empty", "5", PROT,
     "        if not self.unjudged:\n            data.pop(\"unjudged\", None)\n",
     ""),
    ("packet-keeps-empty", "5", PKT,
     "        for empty in (\"earlier_parts\", \"earlier_nonces\", \"earlier_indicators\"):\n            if not data.get(empty):\n                data.pop(empty, None)\n",
     ""),
    ("replay-unchecked", "5", REP,
     "            self._judged_earlier(sub, now, event)\n",
     ""),
    ("replay-allows-judged", "5", REP,
     "earlier = {a.number for a in sub.attempts if a.number < now.number} - sub.judged()",
     "earlier = {a.number for a in sub.attempts if a.number < now.number}"),
    ("legacy-not-as-listed", "5", LOOP,
     "scan = _as_listed(found, item)",
     "scan = found"),
    # Replaces "any hit unmarked" for "every hit unmarked", an equivalent mutant: an item with
    # some hits marked and some not matches neither the scan marked nor the scan unmarked.
    ("legacy-marks-kept", "5", LOOP,
     '                    "attempt": None,\n',
     ""),
    # 6. A refused call is named for what it was.
    ("refused-read-is-write", "6", SCAN, '"Read": REFUSED_READ,', '"Read": REFUSED_WRITE,'),
    ("refused-shell-is-write", "6", SCAN, '"Bash": REFUSED_SHELL,', '"Bash": REFUSED_WRITE,'),
    ("refused-tool-unread", "6", SCAN,
     'calls[str(block.get("id"))] = str(block.get("name"))',
     "pass"),
    ("legacy-label-not-mapped", "6", LOOP,
     '"what": REFUSED_WRITE if hit.what in REFUSED_NAMES else hit.what,',
     '"what": hit.what,'),
    # 8. Only a confirmed or dismissed answer naming its attempt judges an earlier hit, and replay
    # holds a review line's judged attempts to the hits it was shown and its answers.
    ("noted-judges", "8", SCAN,
     "all(a.disposition in DECIDING and a.reason.strip() for a in found)",
     "all(a.reason.strip() for a in found)"),
    ("blank-reason-judges", "8", SCAN,
     "all(a.disposition in DECIDING and a.reason.strip() for a in found)",
     "all(a.disposition in DECIDING for a in found)"),
    ("answer-any-attempt", "8", SCAN,
     "[a for a in answers if a.attempt == hit.attempt and a.evidence == hit.evidence]",
     "[a for a in answers if a.evidence == hit.evidence]"),
    ("stray-answer-judges", "8", SCAN,
     "a.evidence in evidence for a in naming",
     "True for a in naming"),
    ("verdict-ignores-undecided", "8", VER,
     "if h.attempt is not None and not judges(h, answer.indicators)",
     "if h.attempt is not None and False"),
    ("schema-admits-noted", "8", CON,
     '                "disposition": {"enum": ["confirmed", "dismissed"]},\n',
     ""),
    ("schema-no-attempt", "8", CON,
     '                "attempt": {"const": hit.attempt},\n',
     ""),
    ("line-records-no-hits", "8", LOOP,
     "earlier_hits=shown,",
     "earlier_hits=(),"),
    ("replay-trusts-judged", "8", REP,
     "if tuple(named) != judged_attempts(event.earlier_hits, event.result.indicators):",
     "if False:"),
    ("one-word-dismissal-judges", "10", SCAN,
     "a.disposition in DECIDING and not is_bare(a.reason)",
     "a.disposition in DECIDING and a.reason.strip()"),
    ("dismissed-reason-unheld", "10", VER,
     '(f"the reason of the {r.kind} indicator", r.reason) for r in answer.indicators]',
     '(f"the reason of the {r.kind} indicator", r.reason) for r in answer.indicators\n'
     '        if r.disposition != "dismissed"]'),
    ("shown-without-scan", "9", LOOP,
     "            if indicator_scan_runs(artefact)\n            else ()\n",
     "            if True\n            else ()\n"),
)  # fmt: skip

UI_MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("words-no-attempt", "3", WORDS,
     "if (attempts.length === 0 || attempts.some((a) => a === null))",
     "if (true)"),
    ("words-no-judging-review", "3", WORDS,
     "  return c.judgedEarlier\n    .map(",
     "  return []\n    .map("),
    ("words-judged-only-on-merge", "3", WORDS,
     "approve: `Approve records only: ${why}.${judgedEarlierWords(c)}`,",
     "approve: `Approve records only: ${why}.`,"),
    ("parse-no-attempt", "3", API,
     'attemptOf(object(raw, "a scan hit").attempt),',
     "null,"),
    ("parse-judged-unchecked", "3", API,
     "if (attempt < 1 || judgedBy <= attempt)",
     "if (false)"),
)  # fmt: skip

#: Rule 7: the reviewer is told of the earlier parts and markers; no other prompt changes.
PROMPT_MUTANTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("earlier-parts-untold", "7", REV, "        f\"{earlier}\"\n", ""),
    ("earlier-markers-untold", "7", REV, "    if earlier_hits:\n", "    if False:\n"),
    ("earlier-markers-unmarked", "7", REV,
     'f"- {hit.kind}, evidence {hit.evidence}, attempt {hit.attempt}: {hit.what}\\n"',
     'f"- {hit.kind}, evidence {hit.evidence}: {hit.what}\\n"'),
    ("earlier-told-always", "7", REV, "    if earlier_hits:\n", "    if True:\n"),
    ("earlier-attempt-untold", "7", REV,
     '"indicator that names the same evidence and the same attempt, confirmed or dismissed with "',
     '"indicator that names the same evidence, confirmed or dismissed with "'),
)  # fmt: skip

#: A failing row's line; a parametrised row's id may hold spaces.
_FAILED = re.compile(r"^FAILED .+? - (.*)$", re.M)


def run_rows(label: str, rows: tuple[str, ...] = ROWS) -> tuple[str, str]:
    """Run the Python rows once; say how they came out, with the tail of the output."""
    with tempfile.TemporaryDirectory(prefix=f"mut-{label}-") as scratch:
        env = {**os.environ, "PYTHONPYCACHEPREFIX": str(Path(scratch) / "pycache")}
        argv = [
            sys.executable, "-u", "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider",
            "-p", "no:randomly", "-n", "0", f"--basetemp={Path(scratch) / 'basetemp'}", *rows,
        ]  # fmt: skip
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
    asserted = [r for r in reasons if r.startswith(("assert", "AssertionError", "Failed: DID NOT"))]
    if done.returncode == 1 and asserted and "\nERROR " not in out:
        return f"killed ({len(asserted)} of {len(reasons)} failing on an assertion)", tail
    return f"error (exit {done.returncode})", tail


def run_ui_rows(label: str) -> tuple[str, str]:
    """Run the UI rows once with vitest; an assertion failure is the only kill."""
    argv = ["pnpm", "exec", "vitest", "run", *UI_ROWS]
    try:
        done = subprocess.run(  # noqa: S603, S607 - pnpm, fixed arguments
            argv, cwd="ui", capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return "timeout", ""
    out = done.stdout + done.stderr
    tail = "\n".join(line for line in out.splitlines() if "Tests " in line)
    if done.returncode == 0:
        return "pass", tail
    asserted = out.count("AssertionError")
    if asserted and "Error: Transform failed" not in out and "SyntaxError" not in out:
        return f"killed ({asserted} assertion failures)", tail
    return f"error (exit {done.returncode})", tail


def main() -> int:
    """Run the baselines and every mutant; say what each came to."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "python"
    if mode == "ui":
        mutants, rows = UI_MUTANTS, run_ui_rows
    elif mode == "prompt":
        mutants, rows = PROMPT_MUTANTS, lambda label: run_rows(label, PROMPT_ROWS)
    else:
        mutants, rows = MUTANTS, run_rows
    root = Path.cwd()
    head = subprocess.run(  # noqa: S603, S607 - git, fixed arguments
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    print(f"head {head}")
    first, tail = rows("baseline-first")
    print(f"baseline first: {first}\n{tail}", flush=True)
    if first != "pass":
        return 1
    results: list[tuple[str, str, str]] = []
    for name, rule, file, old, new in mutants:
        path = root / file
        original = path.read_text()
        if original.count(old) != 1:
            results.append((name, rule, f"invalid ({original.count(old)} matches)"))
            print(f"{rule} {name}: invalid", flush=True)
            continue
        try:
            path.write_text(original.replace(old, new))
            outcome, tail = rows(name)
        finally:
            path.write_text(original)
        results.append((name, rule, outcome))
        print(f"{rule} {name}: {outcome}\n{tail}", flush=True)
    last, tail = rows("baseline-last")
    print(f"baseline last: {last}\n{tail}")
    print("\nSUMMARY")
    for name, rule, outcome in results:
        print(f"  rule {rule}  {name:30} {outcome}")
    killed = sum(o.startswith("killed") for _, _, o in results)
    print(f"killed {killed} of {len(results)}; baselines {first}/{last}")
    clean = subprocess.run(  # noqa: S603, S607 - git, fixed arguments
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    print(f"tree clean after: {not clean.strip()}")
    return 0 if last == "pass" and killed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
