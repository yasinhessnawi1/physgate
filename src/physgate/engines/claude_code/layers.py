"""Which of the system's layers hold around a Claude Code session, and on what evidence.

What the hook layer wires is the same for a role session and a reviewer session: every
pre-execution and after-call event, through a wrapper that turns every outcome it cannot
read into a refusal. What differs is the tools each profile is offered, whether a verdict
is held to a schema, and whether shell commands run at all.

**The hooks are recorded as held only on a version a measurement showed them hold on.**
``HOOK_EVIDENCE`` names that measurement per version: an experiment under ``experiments/``,
with the runtime version and the enforcement code it ran on. A pinned version it does not
name is recorded as unmeasured. R-HK-02 measured 2.1.272 on earlier enforcement code and
found one held-out read; the parser was fixed after it, and that fix was measured on 2.1.301
only, so 2.1.272 is recorded as unmeasured rather than as held.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from physgate.engines.base import LayersHeld, Profile
from physgate.oslayer.probe import Absent, Present

#: The measurement that showed the pre-execution hooks hold, per runtime version: zero
#: reach over the attempt corpus with the first layer on.
HOOK_EVIDENCE: Mapping[str, str] = {
    "2.1.301": (
        "R-HK-03: zero byte reach and zero held-out leaks over all 755 attempts with the "
        "first layer on, OS layer off and on (Claude Code 2.1.301, macOS, enforcement code "
        "at 1c5e988)"
    ),
}

#: Gaps a measurement found in what holds, per runtime version, each with its source.
RESIDUALS: Mapping[str, tuple[str, ...]] = {
    "2.1.301": (
        "R-HK-03: the sentinel alone, with the shell-path parser off, did not put back the "
        "graph store's node files (22 reaches)",
        "R-HK-03: the parser lets three held-out reads through (latex, latexmk, pdflatex); "
        "their zero leaks rest on those binaries being absent",
    ),
}

ClosedToolList = Literal["harness", "hook", "both", "absent"]
OsLayerHeld = Literal["harness_sandbox", "outside_sandbox", "absent"]
VerdictSchema = Literal["native", "provided_tool", "absent"]

#: Why a reviewer session has no OS layer: it is offered no tool that runs a command.
REVIEWER_HAS_NO_SHELL = "the reviewer profile is offered no tool that runs a shell command"


def layers_held(profile: Profile, *, version: str, os_layer: Present | Absent) -> LayersHeld:
    """The layers held around ``profile``'s sessions on Claude Code ``version``.

    ``os_layer`` is the OS layer's state where the sessions run, as measured for that
    version: a role session's shell commands run inside the runtime's own sandbox where it
    is present. A reviewer runs no shell command, so none is sandboxed.
    """
    evidence = HOOK_EVIDENCE.get(version)
    if profile == "role":
        # Offered every tool; the hooks refuse any tool not on the role's list.
        tools: ClosedToolList = "hook"
        sandbox: OsLayerHeld = "harness_sandbox" if isinstance(os_layer, Present) else "absent"
        reason = os_layer.reason if isinstance(os_layer, Absent) else None
        verdict: VerdictSchema = "absent"
    else:
        # Offered the read tool and the verdict tool alone, and held to them by the hooks.
        tools, sandbox, reason, verdict = "both", "absent", REVIEWER_HAS_NO_SHELL, "native"
    return LayersHeld(
        pre_exec_hooks="held" if evidence is not None else "unmeasured",
        route="native",
        hook_failure="closed",
        residuals=RESIDUALS.get(version, ()),
        closed_tool_list=tools,
        sentinel="per_call",
        os_layer=sandbox,
        os_layer_reason=reason,
        mandatory_reading="held",
        verdict_schema=verdict,
        cost_basis="runtime_total",
        bypass_evidence=evidence,
    )
