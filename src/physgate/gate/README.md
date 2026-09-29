# `physgate.gate` — the physics gate

Deterministic checks that refuse physically wrong work before any reviewer sees
it (ARCH-004, ARCH-080, ARCH-031). No model is called anywhere in this package,
and a syntax-tree test holds that: no provider, network or process, no code
loaded by name, and sympy only in its one typed wrapper. The directory is
protected from every session the harness spawns, and it travels into the
read-only installation the sessions run from (ARCH-081).

## The modules

| | |
|---|---|
| `runner.py` | `PhysicsGate`: runs the registered checks at an attempt's scopes (`check`) or at system scope on the whole design (`check_integration`), stamps every record with the check, the scope, whether its failure blocks and the gate mode, and folds the records into a verdict. Refuses any mode but `on` and `observe`, and gives no verdict if no check ran |
| `registry.py` | The checks the gate runs, in the architecture's order, and `CADENCE`: ARCH-080's "runs at" and "on failure" columns, plus the scopes the gate adds beyond them (`TIGHTENED`: units, magnitude, equilibrium and conservation also over the whole graph at integration). A check not registered does not run; a check never decides whether its own failure blocks |
| `graph.py` | The design-state graph read from the journal alone, never by opening a store: every node validated again at every revision, which nodes an attempt wrote, which nodes it could have changed (those, and every node their edges name before the attempt and after it, so a removed edge counts), the modules of those, and the change history the integration call hands it, refused if it does not name every revision above its baseline exactly once |
| `catalogue.py` | The vocabulary: each quantity name's kind (its canonical unit, radian power, factor shape, whether it is an absolute temperature, its sign), what makes a node a declared source of power and the rating that bounds it (`SOURCES`), and the relations the checks evaluate over `constrains` edges. Every entry names its source. A result carries the digest of the catalogue that judged it |
| `units.py` | pint's arithmetic, exact in fractions, plus the rules pint cannot see: the radian's power, a torque's force-times-length shape, offset temperatures only as absolutes, and the kind algebra (no frequency plus angular velocity, no torque plus energy, no two absolute temperatures added) |
| `relations.py` | The catalogue's relations instantiated over the graph, shared by the unit check and the check that judges each relation |
| `symbolic.py` | The one module that imports sympy: a balance built as an expression and evaluated exactly with one substitution pass |
| `tolerances.py` | What an equality between separately declared numbers may miss: half a unit in each term's third significant figure. Inequalities get no allowance |
| `bounds_table.py`, `bounds/` | The sourced bounds table, one TOML file per domain; a range without its source, date, note or class does not load, and the gate is not built |
| `equilibrium.py` | The equilibrium solver boundary (a Protocol), the closed form for statically determinate mounts, and what an indeterminate mount gets (`INDETERMINATE_MOUNTS`) |
| `check_units.py` … `check_thermal.py` | Checks 1 to 6: units, magnitude, equilibrium, power, conservation, thermal |
| `check_propagation.py` | Check 7, at the integration call: every node whose quantities changed above the given design (created, or a value that is physically different) owes a change to every node its `constrains` edges name, before or after the change, in the same change set or a later one; or that node's owner says why not in `no_change_justified`, which is recorded as unchecked, never passed. A change set is one merged attempt, from the history the loop recorded. It fails naming each unwritten edge; an edge into an interface node or into no node, and a graph with no history, are recorded as unchecked |
| `context.py`, `result.py`, `exceptions.py` | What a check is handed, what it reports, and the gate's own errors |

## What it deliberately does not own

- **The value of `reviewer_had_passed`.** The records carry that field, present
  and empty: the gate runs before any reviewer. The catch-accounting reader fills
  it when it derives the per-check events from the run's log.
- **What a change set is.** The loop derives it from its own log and hands it to
  the integration call; the gate only checks that it describes the journal.
- **The bounds table's curation.** The ranges here are the ones the fixtures
  need, each sourced and dated; widening or narrowing one is a curation event.
- **A finite-element solver.** The Protocol exists; the closed form is what runs.
- **Writing anything.** The gate reads the graph and returns records. Warnings
  live in the records, not in the graph.
