"""The harness checkout as one test process measures it: once, and the same for every test.

The orchestrator records the checkout it runs from (its commit, and a digest of anything not
committed) when a run starts, and refuses to resume a run under a different one. Measured live,
that made the suite depend on the checkout holding still while it ran: an edit saved, or an
untracked file created, while the tests ran turned every test that starts and resumes a run red,
or every test whose configuration was measured at import, minutes before.
"""

from __future__ import annotations

from functools import cache

from physgate.orchestrator.cli import _harness_root
from physgate.orchestrator.run_config import HarnessState, harness_state


@cache
def measured_harness() -> HarnessState:
    """The checkout this suite runs from, measured at the first call in this process."""
    return harness_state(_harness_root())
