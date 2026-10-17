"""What the evaluation requires of a run before its numbers may be reported.

A reportable run whose sessions run shell commands is refused where the OS layer
cannot run: its role sessions' shell would be bounded by the shell parser alone,
whose residual (values known only at run time, programs fed on standard input)
reaches the protected roots the measurement depends on. There is no override.
A run of reviewers alone runs no shell, and a run that is not reportable is the
product's to run as it likes; neither is held to this.

This is the evaluation's rule, not the product's: the command's composition root
registers it with the core, and removing the evaluation removes it.
"""

from __future__ import annotations

from physgate.orchestrator.requirements import RunFacts, RunRequirement
from physgate.oslayer.probe import Absent


def os_layer_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run with shell sessions where the OS layer is absent."""
    if not facts.config.reportable or not facts.shell_sessions:
        return None
    if isinstance(facts.os_layer, Absent):
        return (
            "a reportable run's role sessions run only inside the OS layer, and here it is "
            f"absent: {facts.os_layer.reason}"
        )
    return None


#: The requirements the evaluation holds every run to.
REQUIREMENTS: tuple[RunRequirement, ...] = (os_layer_for_reportable_runs,)
