"""The physics gate: deterministic checks that refuse physically wrong work before review.

Every check here is a tool, never a model: unit arithmetic, a sourced bounds
table, closed-form mechanics and symbolic balances over the design-state graph
(ARCH-004, ARCH-080). The gate runs before any reviewer, so work it refuses is
never reviewed (ARCH-031). This directory is protected from every agent session
the harness spawns (ARCH-081): an agent that could edit the gate would have a
cheaper path to passing than satisfying it.
"""
