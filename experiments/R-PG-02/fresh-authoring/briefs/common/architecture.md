# The architecture's decisions the corpus rests on (verbatim)

### ARCH-010 — Graph schema
**Decision.** JSON, one file per node, committed. Minimum node shape:

```json
{
  "id": "motor.left",
  "kind": "component | module | requirement | interface",
  "domain": "mechanical | electrical | control | firmware | cross",
  "owner_role": "electrical",
  "quantities": {
    "stall_current": {"value": 2.4, "unit": "A", "source": "datasheet", "written_by": "sizing"}
  },
  "requirements": ["REQ-014"],
  "constrains": ["power.budget", "control.loop_gain", "chassis.mount"],
  "model": "path/to/executable_model.py",
  "geometry_hash": "sha256:...",
  "updated": "2026-09-18T10:02:11Z"
}
```

**Depends on.** —
**Cadence.** on change
**Acceptance.** Every numeric quantity in the graph has a unit string. A node with a bare number fails schema validation.

### ARCH-080 — Mandatory checklist

| # | Check | Tool | Runs at | Returns | On failure |
|---|---|---|---|---|---|
| 1 | Unit consistency | `pint` | subtask | offending expression, both unit sides | **block** |
| 2 | Magnitude plausibility | bounds table in skill file | subtask | value, expected range, source of range | **block** |
| 3 | Static equilibrium and load path | closed form, CalculiX | module | reaction forces, unbalanced residual | **block** |
| 4 | Power balance | `sympy` + graph arithmetic | module, system | deficit in W, contributing nodes | **block** |
| 5 | Energy and mass conservation | `sympy` | module | imbalance, terms | **block** |
| 6 | Thermal budget | graph arithmetic | module, system | margin in K or W | warn at module, **block** at integration |
| 7 | Cross-domain propagation | graph traversal | system | list of unwritten constrained edges | **block** |

**Depends on.** ARCH-010, ARCH-004
**Cadence.** per subtask (1–2), per module (3–6), per run (4, 6, 7)
**Acceptance.** Each check has a unit test with a deliberately failing input and a deliberately passing input.

### ARCH-082 — Propagation check definition
**Decision.** For any node whose quantities changed, traverse `constrains`. For each target, if no quantity on that target was rewritten in the same commit and no explicit `no_change_justified` annotation exists, fail.
**Depends on.** ARCH-010, ARCH-080
**Cadence.** per run
**Acceptance.** Swapping a motor for one with different stall current, without touching current budget, loop gain or mount inertia, fails the check.

