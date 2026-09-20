# R-OP-02 result: persona-core 1.2.1

**Verdict: unchanged. The baseline ships. Open Persona is still recorded as
tested and not adopted.**

**But 1.2.1 is materially better than 1.1.0, and one of R-OP-01's two most
serious findings is closed outright.** The version correction was worth making.

Amendment frozen at `de496de`, before any code for this rerun was copied or
written. Held constant and verified by SHA-256 in `metrics/provenance.json`:
`generator.py`, `harness.py`, `protocol.py` and `baseline_store.py`, all four
byte identical to R-OP-01. The venv metadata recorded the swap:
`persona-core==1.1.0` to `persona-core==1.2.1` (`cb4abf63`, 293 commits later).

Same machine, same day, same five seeds, same 1,230 operations per seed.

---

## Scoreboard

Acceptance is applied to the better of the two embedder arms, as the amendment
declared before the run. That is B-hash.

| Criterion | Baseline | B-hash (1.2.1) | Threshold | Verdict |
|---|---|---|---|---|
| C1 correctness | perfect | perfect | perfect for both | **pass** |
| C2 diff p95 | 0.287 ms | 216.2 ms | within 2x | **fail, 754x** |
| C3 traverse p95 | 40.4 ms | 248.5 ms | within 2x | **fail, 6.2x** |
| C4 crash recovery | consistent 5 of 5 | **consistent 5 of 5** | not an acceptance condition | **was 2 of 5 on 1.1.0** |
| C5c adapter lines | n/a | 87 | under 300 | **pass** |
| C6 mismatches | n/a | 11 open, 2 closed, 1 narrowed | none forces an ARCH-010 change | **pass** |

Two of the four acceptance conditions still fail, and they are the same two, for
the same structural reason: the `MemoryStore` protocol is unchanged in 1.2.1, so
there is still no changed-since read and still no read by node id.

---

## What 1.2.1 fixed

### C4 went from 2 of 5 to 5 of 5, and the store was never corrupt at all

R-OP-01 found that a versioned write was two untransacted upserts, so a SIGKILL
between them left a node with a dangling supersede link, zero heads, and
`BrokenVersionChainError` on every `history()` and `rollback()` from then on,
permanently, with no repair anywhere in the package. Three of five seeds hit it.

1.2.1 makes it one deduplicated upsert, links before heads. The code comment on
the change carries its own kill measurements: "two calls tore 4 of 8 kills, one
call tore 0 of 8".

Ten crash runs here, five per arm, every one consistent, zero acknowledged
writes lost. The stronger detail: **`repair` fired zero times in all ten runs.**
The audit logs contain only `write` and `rollback` actions. B calls
`TypedStore.repair` at open, as the amendment required, and it never had
anything to do, because the write path stopped tearing. The fix is at the cause,
not a mop afterwards.

### Rollback got 2.6x to 7x faster, because `history()` stopped scanning

`TypedStore.history` was a `get_all` over the whole store filtered in Python.
In 1.2.1 it is an indexed chain read through `get_by_logical_ids`. Rollback
calls it, so rollback moved with it:

| | 1.1.0 (st) | 1.2.1 (st) | 1.2.1 (hash) |
|---|---|---|---|
| rollback p50 | 454.9 ms | 175.9 ms | 63.4 ms |

### `HashEmbedder` removes the model from the write path

New in 1.2.1, and the right choice for a store that is never queried
semantically. Write p50 drops from 200.6 ms on 1.1.0 to 55.1 ms, a 3.6x
improvement, and the hundred second cold torch import disappears from the first
write.

---

## What 1.2.1 did not fix

### C2, diff latency

`diff(since)` after every write operation, 1,000 samples per seed.

| | p50 mean (sd) | p95 mean (sd) | p95 vs baseline |
|---|---|---|---|
| Baseline | 0.070 ms (0.014) | **0.287 ms (0.110)** | 1x |
| B-hash 1.2.1 | 71.5 ms (10.1) | **216.2 ms (53.6)** | **754x** |
| B-st 1.2.1 | 96.6 ms (6.8) | 369.3 ms (86.0) | 1,289x |
| B-st 1.1.0, for reference | 111.6 ms (17.9) | 332.9 ms (55.2) | 780x against its own baseline |

B-hash improves the absolute number by 35 per cent against 1.1.0. It is still
three orders of magnitude off, because nothing about the mechanism changed:
persona-core has no changed-since read, so every diff is still
`get_all(include_superseded=True)`, materialising and revalidating every version
of every node, while the baseline seeks to a byte offset and reads the tail.

### C3, traversal latency

`traverse_constrains` on the deepest node, 100 samples per seed.

| | p50 mean (sd) | p95 mean (sd) | p95 vs baseline |
|---|---|---|---|
| Baseline | 20.2 ms (5.8) | **40.4 ms (15.7)** | 1x |
| B-hash 1.2.1 | 104.7 ms (19.5) | **248.5 ms (41.5)** | **6.2x** |
| B-st 1.2.1 | 167.5 ms (24.1) | 630.9 ms (263.3) | 15.6x |
| B-st 1.1.0, for reference | 188.4 ms (51.6) | 444.7 ms (186.1) | 9.8x against its own baseline |

B-hash is the best traversal result any configuration has produced, 44 per cent
better than 1.1.0 in absolute terms, and it is still three times outside the 2x
threshold. `get_by_ids` arrived in 1.2.1 but keys on physical chunk ids, and a
graph node is a logical chain, so it does not give a keyed graph a read by node
id.

---

## C1. Correctness

Perfect for all three arms, totals over five seeds each: 750 cross role writes
rejected, 100 interface writes rejected, 250 unit less writes rejected, 3,900
legal writes accepted, 1,000 creates accepted, 150 rollbacks completed, zero
rejected writes mutated the graph, zero wrong rejection reasons.

Same caveat as R-OP-01, and 1.2.1 does not change it: `WriteSource` still has
three values keyed on where text came from, never on who wrote it, so all three
guards remain caller code in every implementation.

## C4. Crash recovery, in full

| | Baseline | B-hash | B-st |
|---|---|---|---|
| Consistent after SIGKILL | 5 of 5 | 5 of 5 | 5 of 5 |
| Acknowledged writes lost | 0 on every seed | 0 on every seed | 0 on every seed |
| Unacknowledged writes recovered | 0,0,1,0,1 | 1,1,1,1,1 | 0,0,1,1,0 |
| Open and recover | 124.3 ms (sd 58.5) | 2,824 ms (sd 936) | 2,668 ms (sd 1,551) |
| Verification pass | 53.4 ms (sd 24.4) | 1,126 ms (sd 535) | 791 ms (sd 324) |
| `repair` events fired | n/a | **0** | **0** |

Recovery is correct and about 22x slower than the baseline's ledger replay. That
is a cost, not a defect, and C4 is not an acceptance condition anyway.

## C5. Implementation cost

| | Lines |
|---|---|
| C5a implementation A | 182 |
| C5b implementation B | 195 |
| **C5c adapter and workaround subset** | **87** |
| Shared scaffolding | 802 |

C5c is unchanged at 87 lines and passes comfortably. B grew from 182 to 195,
which is 25 counted lines added and 12 removed; **14 of the 25 added are
docstring prose** recording the three amendment-permitted changes, so the real
code delta is 11 lines. By tag, unchanged: revision synthesis 30, traversal
synthesis 19, point read 18, diff synthesis 11, marshalling 5, rollback
translation 4.

Install footprint: persona-core's dependency list is byte identical in 1.2.1, so
it is still 20 direct dependencies and **137 distributions**, including torch and
sentence-transformers, even in the B-hash arm where no model is ever loaded.

## Out of scope numbers, for context

| | Baseline | B-hash | B-st | B-st on 1.1.0 |
|---|---|---|---|---|
| Write p50 | 0.73 ms | 55.1 ms | 140.2 ms | 200.6 ms |
| Write p95 | 3.06 ms | 153.5 ms | 507.8 ms | 510.4 ms |
| Rollback p50 | 0.79 ms | 63.4 ms | 175.9 ms | 454.9 ms |
| Wall clock, one seed | 3.73 s | 175.1 s | 461.9 s | 563.1 s |

## Deviations and disclosures

1. **The baseline drifted faster between the two experiments**, from 0.427 ms to
   0.287 ms at C2 p95 and 45.6 ms to 40.4 ms at C3 p95, on the same unchanged
   code. That inflates today's ratios against yesterday's. Measured against
   R-OP-01's own baseline instead, B-hash would be 506x on C2 and 5.5x on C3.
   Both still fail. This is why the amendment required A to be rerun.
2. **B-st ran second, after B-hash, in the same background job.** Its C3 p95 has
   the largest standard deviation in the experiment (263 ms on a 631 ms mean) and
   is worse than 1.1.0 in absolute terms, which is the one number here I would
   not defend as a clean measurement. It does not affect the verdict, because
   acceptance is applied to B-hash, which was declared the tie-break in advance
   and ran first.
3. Three edits were made to `openpersona_store.py`, all named in the amendment
   before the run: `current_view` for head selection, `repair` at open, and a
   selectable embedder. No other edit. Neither implementation was optimised for
   speed, and neither was touched after its first measured run of this
   experiment.
4. R-OP-01's results are not edited, moved or deleted. They stand as the 1.1.0
   record.

---

## The honest summary

1.2.1 is a better piece of software than 1.1.0 in the ways this experiment can
see. It closed the crash bug outright and proved it at the write path, it took
the full store scan out of `history` and `rollback`, and it shipped an embedder
that lets a keyed store stop paying for a model it never uses. Two of thirteen
C6 entries are closed and a third is narrowed, and the closed ones are real.

None of that changes the verdict, because none of it touches the two things WP4
needs and persona-core does not have: a way to ask what changed, and a way to
ask for one node by name. Those live in the `MemoryStore` protocol, which is the
one file in the store layer that 1.2.1 did not touch. Until a diff is a bounded
read rather than a full materialisation, the gap is three orders of magnitude,
and no amount of the surrounding machinery getting faster closes it.

The schema is still fine. The store is still the mismatch.
