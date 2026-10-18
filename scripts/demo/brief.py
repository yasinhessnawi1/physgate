"""Print the example brief: a two-wheeled self-balancing robot's balance loop and main loop.

The control module's specification is the reviewable balance-loop design task the paired-review
runs were built around (``control_fixture_spec.md`` beside the real-run drivers, held to its
digest before use); the firmware module's is that run's labelled stand-in, which asks for one
node written as given. Both are embedded verbatim, control first, with the one interface node,
exactly as the paired-review driver builds its brief; only the opening paragraph names what
this is. The decomposition model reads this brief and plans the two modules from it.

    python scripts/demo/brief.py > brief.md
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration" / "orchestrator"))

import real_paired_reviewers as paired  # noqa: E402

PREAMBLE = (
    "EXAMPLE BRIEF: the balance loop and the firmware main loop of a two-wheeled self-balancing "
    "robot, the Pololu Balboa 32U4 in the configuration its own balancing example is tuned for. "
    "This is an example design run of the harness, not an experiment. Control's specification "
    "is a reviewable design task; firmware's is a labelled stand-in that asks for one node "
    "written as given."
)


def brief() -> str:
    """The paired-review driver's brief, with this run's own opening paragraph."""
    text = paired.brief(paired.use_fixture())
    head, _, rest = text.partition("\n\n")
    if not head.startswith("BRIEF for"):
        msg = "the paired-review driver's brief no longer opens as expected"
        raise SystemExit(msg)
    return f"{PREAMBLE}\n\n{rest}"


if __name__ == "__main__":
    sys.stdout.write(brief())
