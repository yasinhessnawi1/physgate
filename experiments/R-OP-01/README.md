# R-OP-01: is Open Persona's typed memory the WP4 design-state store?

Pre-registered comparison of two implementations of the same `DesignStateStore`
Protocol, measured on one seeded synthetic workload with no model in the loop.

Read in this order:

1. `CRITERIA.md`, frozen and committed before any implementation code existed
   (commit `14a2f12`).
2. `C6.md`, the assumption mismatch list, written during implementation and
   committed before implementation B produced a single number (commit `1d98b40`).
3. `RESULT.md`, pass or fail per criterion with the numbers.
4. `metrics/`, per seed JSON plus `summary.json` and the line count.

## Layout

```
src/protocol.py            the shared interface, charged to neither
src/generator.py           the seeded workload, charged to neither
src/harness.py             replays a workload and scores C1, C2, C3
src/baseline_store.py      implementation A
src/openpersona_store.py   implementation B, adapter regions marked
src/crash_child.py         the process that gets SIGKILLed (C4)
src/crash_verify.py        opens the store afterwards and scores C4
src/run.py                 driver
src/loc.py                 C5 line counting
src/aggregate.py           mean and standard deviation across seeds
```

## Reproducing

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e ../Open-Persona/packages/core
cd experiments/R-OP-01/src
../../../.venv/bin/python run.py --impl baseline     --seeds 1,2,3,4,5
../../../.venv/bin/python run.py --impl openpersona  --seeds 1,2,3,4,5
../../../.venv/bin/python loc.py
../../../.venv/bin/python aggregate.py
```

Seeds are 1 to 5. The generator is deterministic: same seed, same 200 nodes,
same 1,230 operations, for both implementations.
