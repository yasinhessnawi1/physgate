"""Which recorded reasons make a trial's answer not to be trusted, so the trial is run once more.

A trial whose own records exclude it (:class:`.per_role.assemble.ExcludedTrial`) is decided by
the field of its reason alone, the text before the first ``:``, before any person or agent reads
a score: nothing else is read for it, not an outcome (an excluded record has none), not a score,
not an answer.

- **untrusted:** an instrument's fault, not a leak. The trial is run once more (the harness arm
  into a fresh run directory with the same seed; the raw arm as a new round of its one entry),
  the first draw kept and named, never counted. A second such exclusion is kept as the trial's
  record, and the cell it feeds has no verdict.
- **exposure:** a held-out canary found, a held-out read recorded, or a raw record that cannot
  say no canary showed. Never run again: the experiment stops on it, by the register and the
  launch script.
- **unknown:** a field nobody enumerated. Never run again.

This module imports nothing of either arm's round, so both may call it.
"""

from __future__ import annotations

from typing import Literal

Arm = Literal["harness", "raw"]
RerunCause = Literal["untrusted", "exposure", "unknown"]

#: The harness arm's reasons for an instrument's fault: a log empty or cut off, a run that did
#: not end, a canary the run did not look for (no way to tell, which the register does not count
#: an exposure), a leftover's or a session's stream never scanned, a stream the log names gone,
#: and a score whose verdict is not a bool.
HARNESS_UNTRUSTED: frozenset[str] = frozenset(
    {"events", "run", "held_out_canaries", "leftover_read", "session", "stream", "score"}
)
#: The raw arm's: a watch that failed or stalled or an end it does not take, an end check that
#: refused the session, a stream written after its result, and a score whose verdict is not a bool.
RAW_UNTRUSTED: frozenset[str] = frozenset({"end", "sentinel_after_stop", "stream", "score"})
#: Either arm's exposures: the task's canary found by a fresh scan, a held-out read the run
#: recorded, and a raw record that says a canary showed or cannot say none did.
EXPOSURES: frozenset[str] = frozenset({"canary", "incident", "held_out_seen"})


def reason_field(reason: str) -> str:
    """The field an exclusion's reason names: its text before the first ``:``."""
    return reason.split(":", 1)[0].strip()


def rerun_cause(reason: str, arm: Arm) -> RerunCause:
    """Whether an excluded trial of ``arm`` is run once more, by its reason's field alone."""
    named = reason_field(reason)
    if named in EXPOSURES:
        return "exposure"
    untrusted = HARNESS_UNTRUSTED if arm == "harness" else RAW_UNTRUSTED
    return "untrusted" if named in untrusted else "unknown"
