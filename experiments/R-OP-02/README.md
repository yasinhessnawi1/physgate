# R-OP-02: R-OP-01 rerun against persona-core 1.2.1

R-OP-01 measured persona-core 1.1.0. The tree advanced 293 commits to 1.2.1 and
the store layer was much of what moved, so the experiment was rerun against the
version anyone would actually adopt.

Read in this order:

1. `../R-OP-01/CRITERIA.md`, the frozen criteria. Unchanged and still binding.
2. `AMENDMENT.md`, what may change for this rerun and why, frozen before any
   code was copied (commit `de496de`).
3. `RESULT.md`, pass or fail per criterion with both embedder arms.
4. `C6-v2.md`, the mismatch list as a delta: closed, narrowed, unchanged, new.
5. `metrics/provenance.json`, the SHA-256 proof that the workload, the harness
   and the baseline are byte identical to R-OP-01.

**Outcome: verdict unchanged, the baseline ships. 1.2.1 closed the crash bug
outright and took the full scan out of `history`, but the two criteria that
failed still fail, because the `MemoryStore` protocol did not change.**

## Reproducing

```bash
cd experiments/R-OP-02/src
../../../.venv/bin/python run.py --impl baseline          --seeds 1,2,3,4,5
../../../.venv/bin/python run.py --impl openpersona-hash  --seeds 1,2,3,4,5
../../../.venv/bin/python run.py --impl openpersona-st    --seeds 1,2,3,4,5
../../../.venv/bin/python loc.py
../../../.venv/bin/python aggregate.py
```
