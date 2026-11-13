"""The baseline: the raw coding agent the harness is measured against (ARCH-143).

The raw arm (:mod:`physgate.evaluation.per_role.arms.raw`) runs one session on one task; the
trial layer (:mod:`physgate.evaluation.per_role.assemble`) holds it equal to the harness arm
and turns what it left into a trial. This package runs that arm on every trial a named set of
harness runs made on a named tier version, and writes what the round was bound to: the tier
version, each tier's digest and the pin set, with counts only.
"""
