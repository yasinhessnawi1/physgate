"""Per-role evaluation: one design role's tasks, scored numerically, harness against raw agent.

A task is a brief, the quantities it gives, the numeric specifications its answer is held to,
and the scorer that holds it there; both arms are given the same text for it, its brief and its
quantities as the scorer reads them (:mod:`physgate.evaluation.tiers.issued`). The scorer is
deterministic and no language model judges anything. This package is evaluation-side
machinery: it imports the product core, and the core never imports it.
"""
