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
| `runner.py` | `PhysicsGate`: runs the registered checks at an attempt's scopes (`check`) or at system scope on the whole design (`check_integration`), stamps every record with the check, the scope, whether its failure blocks and the gate mode, and folds the records into a verdict. A law blocks only where the laws check blocks and the law table it was built with has the law out of probation; a probation law's failure is a warning. Refuses any mode but `on` and `observe`, and gives no verdict if no check ran |
| `registry.py` | The checks the gate runs, in the architecture's order, and `CADENCE`: ARCH-080's "runs at" and "on failure" columns, plus the scopes the gate adds beyond them (`TIGHTENED`: units, magnitude, equilibrium and conservation also over the whole graph at integration). A check not registered does not run; a check never decides whether its own failure blocks |
| `graph.py` | The design-state graph read from the journal alone, never by opening a store: every node validated again at every revision, which nodes an attempt wrote, which nodes it could have changed (those, and every node their edges name before the attempt and after it, so a removed edge counts), the modules of those, and the change history the integration call hands it, refused if it does not name every revision above its baseline exactly once |
| `catalogue.py` | The vocabulary: each quantity name's kind (its canonical unit, radian power, factor shape, whether it is an absolute temperature, its sign), the closed list of suffixes that give an uncatalogued name a kind and nothing else (`SUFFIXES`), what makes a node a declared source of power and the rating that bounds it (`SOURCES`), the store classes whose fastest sourced continuous discharge bounds any store's rating (`STORE_CLASSES`), and the relations the checks evaluate over `constrains` edges, each with the check that judges it. Every entry names its source. A result carries the digest of the catalogue that judged it |
| `units.py` | pint's arithmetic, exact in fractions, plus the rules pint cannot see: the radian's power, a torque's force-times-length shape, offset temperatures only as absolutes, and the kind algebra (no frequency plus angular velocity, no torque plus energy, no two absolute temperatures added) |
| `relations.py` | The catalogue's relations instantiated over the graph, shared by the unit check and the check that judges each relation |
| `symbolic.py` | The one module that imports sympy: a balance built as an expression and evaluated exactly with one substitution pass |
| `tolerances.py` | What an equality between separately declared numbers may miss: half a unit in each term's third significant figure. A product or quotient of declared numbers carries the rounding of every factor, propagated exactly to the worst case, `|t| * ((1 + e)**P / (1 - e)**N - 1)`, which is the same rule for one plain term. Inequalities get no allowance |
| `bounds_table.py` | Loads the sourced bounds table from the tracked `knowledge/<domain>/bounds.toml` files, one per domain directory: ranges, each for one named quantity in its domain, and envelopes (`knowledge/cross/`), each for a whole kind of quantity in every domain, applied to the size of a value after the writer's own domain's range; a range or envelope without its source, date, note or class does not load, and the gate is not built. The table itself is curated content, not part of this package — protected under `knowledge/` the same way this directory is, and moved there so it sits beside the standards and skill files it is curated alongside |
| `laws.py` | Loads the law table from the tracked `knowledge/laws/laws.toml`: closed-form laws as data, each read only by exact catalogue names and bound to the graph by one of three patterns (a node, a node and its edge's target, a subject and its members). A row is refused, naming it, unless it is sourced from a text, approved with the promotion line that recorded it, one comparison of two sums of monomials read by a syntax-tree allowlist (never evaluated), one dimension and one kind, new against the relations the checks already form, and, at `block`, cleared by an audit over at least 10 evaluated clean instances from at least 2 designs with nothing unexplained. Each law's worked examples are run when it loads, through the evaluator the check uses. Also the evaluator (exact in fractions, the allowance by tolerance class) and the patterns, which form an instance wherever a law's anchor is and say why one cannot be judged. A table that does not load stops the gate from being built; the catalogue digest names the table by content |
| `equilibrium.py` | The equilibrium solver boundary (a Protocol), the closed form for statically determinate mounts, and what an indeterminate mount gets (`INDETERMINATE_MOUNTS`) |
| `check_equilibrium_loads.py` | Check 3's two balances no mount reads: a torque unit's reaction moment against its peak torque (the unit as a whole, or the gearbox alone where a ratio is declared), and a carrier's supported mass against the weighted parts that name it (the whole, or an equal share among sibling carriers, with or without its own mass); refused only when every reading misses, passed only when every reading balances, unchecked otherwise |
| `check_units.py` … `check_thermal.py` | Checks 1 to 6: units, magnitude, equilibrium, power, conservation, thermal. Power also judges a motor's stall current against its supply's peak current limit, and a store's discharge rating against what it stores |
| `check_propagation.py` | Check 7, at the integration call: every node whose quantities changed above the given design (created, or a value that is physically different) owes a change to every node its `constrains` edges name, before or after the change, in the same change set or a later one; or that node's owner says why not in `no_change_justified`, which is recorded as unchecked, never passed. A change set is one merged attempt, from the history the loop recorded. It fails naming each unwritten edge; an edge into an interface node or into no node, and a graph with no history, are recorded as unchecked |
| `check_laws.py` | Check 8, the closed-form laws, at module and system scope: every law of the table the gate was built with, wherever its pattern binds, each input measured against its kind and the law evaluated exactly. A failure names the law, its source, the instance over nodes, every input with its own source and writer, both sides, the residual, the allowance and the table's digest; an instance it cannot judge (an input missing, an excusing name present, an edge into an interface node or no node, a subject no member names, a refused unit, a division by zero) is recorded unchecked, never passed. Each law's count is reported on its own. It never decides whether a failure blocks: the runner reads that from the table |
| `context.py`, `result.py`, `exceptions.py` | What a check is handed, what it reports, and the gate's own errors |

## What it deliberately does not own

- **The value of `reviewer_had_passed`.** The records carry that field, present
  and empty: the gate runs before any reviewer. The catch-accounting reader fills
  it when it derives the per-check events from the run's log.
- **What a change set is.** The loop derives it from its own log and hands it to
  the integration call; the gate only checks that it describes the journal.
- **The bounds table's curation.** The ranges are the ones the fixtures need,
  each sourced and dated, and live under `knowledge/<domain>/bounds.toml`, not
  in this directory; widening or narrowing one is a curation event, promoted
  the same way any other curated content is.
- **The law table's curation.** Each law is promoted into `knowledge/laws/laws.toml` by a
  person, as bounds and standards are; this package only loads and refuses.
- **A finite-element solver.** The Protocol exists; the closed form is what runs.
- **Writing anything.** The gate reads the graph and returns records. Warnings
  live in the records, not in the graph.
