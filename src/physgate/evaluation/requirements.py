"""What the evaluation requires of a run before its numbers may be reported.

A reportable run whose sessions run shell commands is refused where the OS layer
cannot run: its role sessions' shell would be bounded by the shell parser alone,
whose residual (values known only at run time, programs fed on standard input)
reaches the protected roots the measurement depends on. There is no override.
A run of reviewers alone runs no shell, and a run that is not reportable is the
product's to run as it likes; neither is held to this.

A reportable run also records a person's queue decisions and acts on none, so no measured
outcome is changed by a decision taken during it.

A reportable run never names the core's development allowance for running without the OS
layer (``os_layer_absent: allow``), whatever the layer where it runs: its record never carries
an allowance a measurement would have to explain.

A reportable run that asks for ``network: none`` is refused on the same ground: only
the OS layer refuses a shell remote hosts, so without it the record would say ``none`` while
the sessions stay online.

These are the evaluation's rules, not the product's: the command's composition root
registers them with the core, and removing the evaluation removes them.
"""

from __future__ import annotations

from physgate.orchestrator.requirements import RunFacts, RunRequirement
from physgate.orchestrator.run_config import network_enforced
from physgate.oslayer.policy import NETWORK_UNENFORCED
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


def no_os_layer_allowance_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run whose parameters allow role sessions without the OS layer.

    The allowance is the core's, for development. A reportable run is refused where the layer is
    absent in any case (:func:`os_layer_for_reportable_runs`); this refuses the allowance itself,
    present layer or not, so no reportable run's record names it.
    """
    if facts.config.reportable and facts.config.os_layer_absent == "allow":
        return (
            "a reportable run never allows role sessions without the OS layer: "
            "os_layer_absent: refuse"
        )
    return None


def network_none_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run that asks for ``network: none`` where nothing enforces it.

    Only the OS layer refuses a shell remote hosts. The core records such a run and goes on;
    a reportable run's sessions would be online while its record says ``none``.
    """
    if not facts.config.reportable or not facts.shell_sessions:
        return None
    if network_enforced(facts.config.network, facts.os_layer) is False:
        return f"a reportable run's {NETWORK_UNENFORCED}: the OS layer is absent"
    return None


def record_decisions_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run that would act on a person's queue decisions.

    A decision that acts changes what the run does next (a merge, a retry, a fix) by a person's
    hand, so a measured outcome would no longer be the harness's alone. A reportable run records
    decisions and acts on none (ARCH-133).
    """
    if facts.config.reportable and facts.config.queue_decisions != "record":
        return "a reportable run records queue decisions and acts on none: queue_decisions: record"
    return None


#: The requirements the evaluation holds every run to.
REQUIREMENTS: tuple[RunRequirement, ...] = (
    os_layer_for_reportable_runs,
    no_os_layer_allowance_for_reportable_runs,
    network_none_for_reportable_runs,
    record_decisions_for_reportable_runs,
)
