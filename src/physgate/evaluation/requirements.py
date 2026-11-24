"""What the evaluation requires of a run before its numbers may be reported.

A reportable run whose sessions run shell commands is refused where the OS layer
cannot run: its role sessions' shell would be bounded by the shell parser alone,
whose residual (values known only at run time, programs fed on standard input)
reaches the protected roots the measurement depends on. There is no override.
A run of reviewers alone runs no shell, and a run that is not reportable is the
product's to run as it likes; neither is held to this.

A reportable run also records a person's queue decisions and acts on none, so no measured
outcome is changed by a decision taken during it; and it reviews its plan, under
``design_review: observe`` (recorded, changing nothing the run does) unless its criteria name
another value as an experiment's arm.

A reportable run never names the core's development allowance for running without the OS
layer (``os_layer_absent: allow``), whatever the layer where it runs: its record never carries
an allowance a measurement would have to explain.

A reportable run that asks for ``network: none`` is refused on the same ground: only
the OS layer refuses a shell remote hosts, so without it the record would say ``none`` while
the sessions stay online.

An ablation run is held to every one of these (ARCH-140): it is measured like a reportable run,
with a component switched off, and each refusal names it as what it is.

No run that names anything under a role's root of a tier-set store (or that root, or the
store) starts while that store holds a pool, a version still being written, or a record of a
session's work out of a role's root: each holds or points at tasks that are or become
held-out and validation ones and carry no canary, which no session of the run withholds. This
holds for every run that names one, reportable or not, since a read of them spoils the tiers
whatever run made it. Nor does one that does not name, among the roots its sessions withhold,
that role's withheld root, which holds the sessions' streams and the pool, its work root,
where the blind check works with a copy of the held-out tasks, and the validation and
held-out tiers of every version under that role's root, older ones too. Nor does one whose
withheld roots are not spelt as the filesystem spells them, so every layer of the protection
is given the spelling on disk.

A reportable or ablation run that names held-out roots is on one version of a tier-set store,
found by its brief, and is refused unless that version is known, unchanged since the run
recorded it, not marked exposed by the store's register, has its held-out tier's blind check
recorded beside it (a held-out tier nobody checked is not scored, so nothing on its version is
measured), and its run directory lies beneath one of the run roots the register scans
(:func:`.tiers.exposure.version_refusal`). A version the run
only withholds, as every run on the role withholds every version, is not one it is on. Such a
run also withholds whole every run root of the stores it names, where the earlier runs on them
lie, and nothing else (:func:`.tiers.exposure.run_roots_refusal`), and reviews inside its own
run directory, so those roots hold its reviews too (:func:`.tiers.exposure.review_root_refusal`).

These are the evaluation's rules, not the product's: the command's composition root
registers them with the core, and removing the evaluation removes them.
"""

from __future__ import annotations

from physgate.evaluation.tiers.exposure import (
    review_root_refusal,
    run_roots_refusal,
    version_refusal,
)
from physgate.evaluation.tiers.store import (
    leftover_refusal,
    protected_tier_refusal,
    role_roots,
    spelling_refusal,
    withheld_refusal,
    work_refusal,
)
from physgate.orchestrator.requirements import RunFacts, RunRequirement
from physgate.orchestrator.run_config import RunConfig, network_enforced
from physgate.oslayer.policy import NETWORK_UNENFORCED
from physgate.oslayer.probe import Absent


def measured(config: RunConfig) -> str | None:
    """What kind of measured run ``config`` is, as a refusal names it; ``None`` for neither.

    The two kinds are held to the same rules, and a run is never both.
    """
    if config.reportable:
        return "a reportable run"
    return "an ablation run" if config.ablation else None


def os_layer_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable or ablation run with shell sessions where the OS layer is absent."""
    kind = measured(facts.config)
    if kind is None or not facts.shell_sessions:
        return None
    if isinstance(facts.os_layer, Absent):
        return (
            f"{kind}'s role sessions run only inside the OS layer, and here it is "
            f"absent: {facts.os_layer.reason}"
        )
    return None


def no_os_layer_allowance_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run whose parameters allow role sessions without the OS layer.

    The allowance is the core's, for development. A reportable run is refused where the layer is
    absent in any case (:func:`os_layer_for_reportable_runs`); this refuses the allowance itself,
    present layer or not, so no reportable run's record names it.
    """
    kind = measured(facts.config)
    if kind is not None and facts.config.os_layer_absent == "allow":
        return f"{kind} never allows role sessions without the OS layer: os_layer_absent: refuse"
    return None


def network_none_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run that asks for ``network: none`` where nothing enforces it.

    Only the OS layer refuses a shell remote hosts. The core records such a run and goes on;
    a reportable run's sessions would be online while its record says ``none``.
    """
    kind = measured(facts.config)
    if kind is None or not facts.shell_sessions:
        return None
    if network_enforced(facts.config.network, facts.os_layer) is False:
        return f"{kind}'s {NETWORK_UNENFORCED}: the OS layer is absent"
    return None


def record_decisions_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse a reportable run that would act on a person's queue decisions.

    A decision that acts changes what the run does next (a merge, a retry, a fix) by a person's
    hand, so a measured outcome would no longer be the harness's alone. A reportable run records
    decisions and acts on none (ARCH-133).
    """
    kind = measured(facts.config)
    if kind is not None and facts.config.queue_decisions != "record":
        return f"{kind} records queue decisions and acts on none: queue_decisions: record"
    return None


def nothing_left_in_a_named_tier_set_store(facts: RunFacts) -> str | None:
    """Refuse a run while a tier-set store it names holds a split's leftovers or work left.

    A store is named by a held-out root that lies in one of its roles' roots, is one, or is
    the store, judged on its resolved form (:func:`.tiers.store.role_roots`). Every role's root
    in it is looked at, by name only (:func:`.tiers.store.leftovers`): a pool, a version being
    written, a record of a session's work out of the root. A store that cannot be listed
    refuses too.
    """
    stores = sorted({store for store, _ in role_roots(facts.config.held_out)})
    for store in stores:
        refusal = leftover_refusal(store)
        if refusal is not None:
            reason, words = refusal
            return f"{words} ({reason})"
    return None


def every_named_store_s_withheld_root_is_withheld(facts: RunFacts) -> str | None:
    """Refuse a run that names a tier of a store but not that store's withheld root.

    The withheld root of a role (``<store>/<role>/withheld``) holds what sessions wrote: the
    authoring and blind-check streams, with every task they saw, and the pool. A run that
    names any tier of that role's versions withholds it too, among its held-out roots, so
    every layer of the protection refuses it to the run's sessions as it refuses the tier.
    """
    refusal = withheld_refusal(facts.config.held_out)
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def every_named_role_root_s_protected_tiers_are_withheld(facts: RunFacts) -> str | None:
    """Refuse a run that names a role's root of a store but not every protected tier in it.

    A run that names anything under ``<store>/<role>`` withholds the validation and held-out
    tiers of every version there, older ones too, among its held-out roots: one it does not is
    read by its sessions with no canary of the run's to show it, and that version is then
    measured as unseen when it is not (:func:`.tiers.store.protected_tier_refusal`).
    """
    refusal = protected_tier_refusal(facts.config.held_out)
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def every_named_role_root_s_work_root_is_withheld(facts: RunFacts) -> str | None:
    """Refuse a run that names a role's root of a store but not that role's work root.

    The blind check works under ``<store>/<role>/work`` with a copy of the held-out tasks and
    no canary; a run naming anything under the role's root withholds it
    (:func:`.tiers.store.work_refusal`). The work root is made with the role's root, so the
    run's sandbox denies a directory that is there when the run starts. A check is still run
    only when no run on the store is live: such a run's sentinel moves new work under a root
    it withholds into its session's own records.
    """
    refusal = work_refusal(facts.config.held_out)
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def a_named_store_s_roots_are_spelt_as_on_disk(facts: RunFacts) -> str | None:
    """Refuse a run naming a store whose held-out roots are not spelt as they are on disk.

    On a volume that ignores case, another case reaches the same files; that every layer of
    the protection refuses a root named so is not shown, so the spelling is held to the one on
    disk (:func:`.tiers.store.spelling_refusal`).
    """
    refusal = spelling_refusal(facts.config.held_out)
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def a_measured_run_withholds_every_run_root_whole(facts: RunFacts) -> str | None:
    """Refuse a measured run that does not withhold whole exactly its stores' run roots.

    An earlier run on the store lies under one of its run roots, its record holding every
    canary of the store, its plan written from its brief, its answer beside it: a later run's
    sessions are withheld each root whole, by rule, but for their own worktree, and nothing
    else is withheld so (:func:`.tiers.exposure.run_roots_refusal`). Its reviews (each packet with
    the brief and the answer, each reviewer's record, the key for labels) run strictly inside its
    own run directory, so the run roots withhold them whole too, from every later session: the
    review roots of its stores are inside the run roots, and no other place is withheld whole
    (:func:`.tiers.exposure.review_root_refusal`). At its start and at every run and resume: a
    root registered while the run was halted refuses it until it names it, and a run about to
    review is shown where. A run that is not measured is the product's, and is not held to it.
    """
    config = facts.config
    if measured(config) is None or not (config.held_out or config.withheld_whole):
        return None
    refusal = run_roots_refusal(config, facts.run_dir) or review_root_refusal(
        facts.run_dir, facts.review_root, reviewing=not facts.new_run
    )
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def a_measured_run_is_on_a_known_unexposed_version(facts: RunFacts) -> str | None:
    """Refuse a measured run with held-out roots unless it is on a version it may be measured on.

    At its start, at every run and at every resume: a run that exposed its version, or whose
    tier changed while it was halted, does not go on as measured. A run that is not measured is
    the product's, and is not held to it.
    """
    if measured(facts.config) is None or not facts.config.held_out:
        return None
    refusal = version_refusal(facts.config, facts.run_dir)
    if refusal is None:
        return None
    reason, words = refusal
    return f"{words} ({reason})"


def observed_design_review_for_reportable_runs(facts: RunFacts) -> str | None:
    """Refuse to start a reportable run that does not record its plan's review.

    A reportable run reviews its plan under ``observe``, where the verdict is measured without
    changing the run, unless its frozen criteria name another value as an arm (``on``, or
    ``repair:N``, which only a reportable run may name). The criteria are not something code can
    read, so the rule admits every value that reviews the plan and refuses the one that does not.
    Asked of a new run only: a reportable run recorded before the flag existed reads as ``off``,
    and it still resumes.
    """
    kind = measured(facts.config)
    if facts.new_run and kind is not None and facts.config.design_review == "off":
        return (
            f"{kind} records its plan's review: design_review: observe, or the arm its "
            "criteria name"
        )
    return None


#: The requirements the evaluation holds every run to.
REQUIREMENTS: tuple[RunRequirement, ...] = (
    os_layer_for_reportable_runs,
    no_os_layer_allowance_for_reportable_runs,
    network_none_for_reportable_runs,
    record_decisions_for_reportable_runs,
    nothing_left_in_a_named_tier_set_store,
    every_named_store_s_withheld_root_is_withheld,
    every_named_role_root_s_protected_tiers_are_withheld,
    every_named_role_root_s_work_root_is_withheld,
    a_named_store_s_roots_are_spelt_as_on_disk,
    a_measured_run_withholds_every_run_root_whole,
    a_measured_run_is_on_a_known_unexposed_version,
    observed_design_review_for_reportable_runs,
)
