# R-OP-02: R-OP-01 rerun against persona-core 1.2.1

**Status:** frozen before any code for this rerun was written or copied.
**Written:** 2026-09-20
**Amends:** `../R-OP-01/CRITERIA.md`, which stays frozen and stays published.

---

## 1. Why this rerun exists

R-OP-01 measured persona-core **1.1.0**, the version present in the working tree
at commit `90cafe8b` when it ran. The tree has since advanced to **1.2.1**
(`cb4abf63`), **293 commits** later, and the store layer is a large part of what
moved: `stores/versioning.py` +319 lines, `stores/base.py` +214,
`stores/embedder.py` +109, `stores/chroma.py` +50, `stores/backend.py` +41.

Measuring a version nobody would adopt answers a question nobody asked. The
rerun is therefore correct on the merits.

It is not a do-over. R-OP-01's numbers stay in the repository, labelled as
1.1.0, and are not edited, moved or deleted. R-OP-02 is additive. If 1.2.1 is
still slow, this document's own acceptance rule will say so in the same words.

## 2. What is held constant

Byte identical to R-OP-01, verified by SHA-256 before the run and recorded in
`metrics/provenance.json`:

- `generator.py`, the seeded workload. Same 200 nodes, same 1,230 operations,
  same seeds 1 to 5.
- `harness.py`, the scoring.
- `baseline_store.py`, implementation A. Not one line changes.
- `protocol.py`, the shared interface.

Unchanged from `CRITERIA.md`: the node shape (S2), the Protocol (S3), the rules
of fair play (S5), the workload (S6), the six measurements (S7), and the
acceptance rule (S8), including the 2x thresholds and the 300 line adapter
budget.

## 3. What changes, and nothing else does

**A1. The package version.** B is built on persona-core 1.2.1 at `cb4abf63`.

**A2. B must use any narrower read 1.2.1 offers.** This is not new licence, it
is rule R4 of the original criteria applied to a new surface. The survey was
done before writing this document, so the answer is on the record:

| New in 1.2.1 | Does it narrow a Protocol operation? |
|---|---|
| `Backend.get_by_ids` | No. It keys on physical chunk ids; a graph node is a logical chain. `get_by_logical_ids` remains the narrowest keyed read. |
| `versioning.current_view` | Yes, for head selection. B will use it instead of filtering `superseded_by` by hand. |
| `TypedStore.chain_ids` | No. It maps doc ids to chain ids, which B already holds. |
| `MemoryStore` protocol | Unchanged. Still no read by id and still no changed-since read, so `diff` and `read_node` are synthesised as before. |

**A3. B's open runs the recovery routine, because 1.2.1 is the first version to
have one.** `TypedStore.diagnose()` and `TypedStore.repair()` did not exist in
1.1.0. C4 in the original criteria says the fresh process "opens the store and
runs its recovery routine", which B could not do. It can now, so it will, at
open, exactly as A's open runs `recover()`. Both then pay their recovery cost on
every open and the comparison stays symmetric.

**A4. Two embedder arms.** `HashEmbedder` is new in 1.2.1: a deterministic,
model free embedder shipped by the package. A design-state graph is never
queried semantically, so it is the right choice for this workload, but the
original criteria pinned `SentenceTransformerEmbedder`. Both are run:

- **B-st**, `SentenceTransformerEmbedder` with `BAAI/bge-small-en-v1.5`, exactly
  as R-OP-01 pinned it. This holds the configuration constant so the version
  effect is isolated.
- **B-hash**, `HashEmbedder`. The best configuration the package now offers for
  this workload.

Both are reported in full, per seed. **The acceptance rule is applied to
whichever arm scores better**, because the question is whether the package can
enter the architecture, not whether a particular knob was set well. Declaring
this before the run is what stops it being a choice made after seeing numbers.

**A5. Implementation A is rerun on the same machine on the same day**, with
unchanged code, so the 2x ratios are not comparing a number taken today against
one taken yesterday under a different load. Both of A's runs are reported.

## 4. What may not change

- No optimisation of either implementation for speed, on either side. The only
  edits permitted to `openpersona_store.py` are the ones A2 and A3 name.
  Every edit is listed in `RESULT.md`.
- C5 is recounted from scratch on the new adapter, with the same counting script
  and the same `# ADAPTER:` marking rule. If the adapter got shorter, that is a
  result; if it got longer, that is also a result.
- C6 is rewritten as a delta against R-OP-01's thirteen entries: closed,
  unchanged, or new. An entry is only marked closed with the code reference in
  1.2.1 that closes it.
- R3 stands: what is reported is the first honest version of each, and no
  implementation is edited after its first measured run of this experiment.

## 5. What would change the verdict

R-OP-01 failed on C2 and C3, both by more than an order of magnitude, and both
for structural reasons: persona-core has no changed-since read, so every diff is
a full materialisation of every version, and no read by id on its store
protocol. A2's survey says neither of those changed in 1.2.1. The honest
expectation, written down before the run so it cannot be adjusted afterwards, is
that **C2 and C3 still fail, and C4 now passes**, because the torn write that
broke three of five seeds was fixed in 1.2.1 and a repair path was added.

If that expectation turns out wrong in either direction, the numbers decide, not
this paragraph.
