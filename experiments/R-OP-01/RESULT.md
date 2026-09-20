> **Added 2026-09-20, after the fact, changing no number below.** This is the
> **persona-core 1.1.0** record. The package has since moved to 1.2.1, which
> closed two of the thirteen C6 entries, including the crash bug in C4. See
> `../R-OP-02/RESULT.md` for the 1.2.1 measurement. The verdict is the same in
> both, for the same reason.

# R-OP-01 result

**Verdict: the baseline ships. Open Persona is recorded as tested and not
adopted.**

Criteria frozen at commit `14a2f12`, before any implementation code existed.
Both implementations and the full C6 list committed at `1d98b40`, before
implementation B produced a single number. Neither implementation was edited
after its first measured run.

Five seeds (1 to 5), 200 nodes, 1,230 operations per seed, no model in the loop.
Machine: Apple silicon, macOS 25.2, Python 3.12.6, persona-core 1.1.0,
chromadb 1.5.9, sentence-transformers 3.4.1, embedder BAAI/bge-small-en-v1.5.

---

## Scoreboard

| Criterion | Baseline (A) | Open Persona (B) | Threshold | Verdict |
|---|---|---|---|---|
| C1 correctness | perfect | perfect | perfect for both | **pass** |
| C2 diff p95 | 0.427 ms | 332.9 ms | B within 2x of A | **fail, 780x** |
| C3 traverse p95 | 45.6 ms | 444.7 ms | B within 2x of A | **fail, 9.8x** |
| C4 crash recovery | consistent 5 of 5 | consistent 2 of 5 | not in the acceptance rule | reported below |
| C5c adapter lines | n/a | 87 | under 300 | **pass** |
| C6 mismatches | n/a | 13 entries | none forces an ARCH-010 change | **pass** |

Acceptance required all four of: C1 perfect for both, C2 and C3 within 2x at
p95, C5c under 300 lines, C6 clean of ARCH-010 changes. Two of the four fail, so
the baseline ships.

---

## C1. Correctness

Counts are totals over the five seeds. Any miss is a hard failure; there were
none, for either implementation.

| Counter | Attempted | A rejected/accepted | B rejected/accepted |
|---|---|---|---|
| Cross role writes (must reject) | 750 | 750 rejected | 750 rejected |
| Interface writes after decomposition (must reject) | 100 | 100 rejected | 100 rejected |
| Unit less quantity writes (must reject) | 250 | 250 rejected | 250 rejected |
| Legal writes (must accept) | 3,900 | 3,900 accepted | 3,900 accepted |
| Node creates (must accept) | 1,000 | 1,000 accepted | 1,000 accepted |
| Rollbacks to a named earlier revision | 150 | 150 completed | 150 completed |
| Rejected writes that mutated the graph | | 0 | 0 |
| Rejections with the wrong reason | | 0 | 0 |

**Both pass.** Worth saying plainly: neither store earned this. All three guards
live in caller code in both implementations, because neither a JSON file nor
persona-core's write policy can express "only the owning role may write this
node" (C6 M5, M6, M7).

## C2. Diff latency

`diff(since)` after every write operation, 1,000 samples per seed per
implementation, 5,000 each in total. Mean and standard deviation of the per seed
percentile.

| | p50 mean (sd) | p95 mean (sd) |
|---|---|---|
| A baseline | 0.070 ms (0.014) | **0.427 ms (0.157)** |
| B openpersona | 111.6 ms (17.9) | **332.9 ms (55.2)** |
| ratio B/A | 1,586x | **780x** |

Per seed p95 for B: 417.1, 356.2, 314.4, 299.5, 277.3 ms.
Per seed p95 for A: 0.600, 0.515, 0.494, 0.297, 0.229 ms.

The gap is structural, not a tuning artefact. A diff in A is a seek to a known
byte offset in an append only file followed by a read of the tail. A diff in B is
`get_all(include_superseded=True)`, which materialises and revalidates every
version of every node, because persona-core offers no "what changed since" read
(C6 M8). The cost grows with the store for the life of the project, and the
stores are append only, so nothing ever shrinks it.

## C3. Traversal latency

`traverse_constrains` on the deepest node, every tenth write operation, 100
samples per seed. The deepest node is the same node for both implementations and
is fixed before the run.

| | p50 mean (sd) | p95 mean (sd) |
|---|---|---|
| A baseline | 17.8 ms (6.2) | **45.6 ms (18.1)** |
| B openpersona | 188.4 ms (51.6) | **444.7 ms (186.1)** |
| ratio B/A | 10.6x | **9.8x** |

Closure sizes reached, by seed: 169, 155, 147, 131, 106 nodes.

B batches its reads one breadth first level at a time through the transport's
logical id filter, which is the narrowest multi node read the package offers, and
it is still ten times slower than opening one small JSON file per hop.

## C4. Crash recovery

Not one of the four acceptance conditions, which is a gap in the pre-registration
rather than a gap in the store. Reported in full because it is the most serious
thing the experiment found.

| | A baseline | B openpersona |
|---|---|---|
| Consistent after SIGKILL | **5 of 5** | **2 of 5** |
| Acknowledged operations before the kill | 542 mean (sd 126) | 251 mean (sd 0) |
| Open and recover | 122.4 ms (sd 57.1) | 3,665 ms (sd 430), over the 2 seeds that completed |
| Verification pass | 39.9 ms (sd 10.2) | 15,302 ms (sd 4,592) |
| Acknowledged writes lost | 0, 0, 0, 0, 0 | 0, 0 on the 2 that completed |
| Unacknowledged writes recovered | 1, 1, 1 on three seeds | 0, 0 |

**A.** Every seed recovered. The one extra recovered write on three of the five
seeds is the expected case: the ledger line was fsynced and the process died
before it could write its acknowledgement. Nothing acknowledged was ever lost.

**B.** Three of the five seeds came back with a permanently broken version chain,
which is exactly hazard M13 as written in C6 before the run. `TypedStore.write`
persists a versioned update as two separate upserts with no transaction: first
the previous head with its `superseded_by` link set, then the new head. A kill
between them leaves the previous head pointing at a chunk that does not exist.

Reading the damaged stores afterwards (analysis of the same on disk artefacts,
no re-measurement):

| Seed | Node | Versions present | Heads | Dangling link |
|---|---|---|---|---|
| 1 | `firmware.node028` | [1] | 0 | `firmware.node028::v0002` |
| 2 | `firmware.node083` | [1] | 0 | `firmware.node083::v0002` |
| 3 | `firmware.node013` | [1, 2] | 0 | `firmware.node013::v0003` |

The node has zero heads, so `read_node` cannot find it; `history()` and
`rollback()` raise `BrokenVersionChainError` on it forever. persona-core has no
recovery routine and no repair path, so the node is lost to the graph and the
other 199 nodes carry on as if nothing happened. ARCH-002 requires that killing
an agent session mid task loses no project state. On this evidence, B does not
satisfy ARCH-002.

*Deviation:* the verifier aborted at its first `history()` call on those three
seeds, so open, recover and verify timings are unavailable for them. The two
timings quoted for B are from the two seeds that completed.

## C5. Implementation cost

Non blank, non comment Python lines. Docstrings counted, because they are
written.

| | Lines |
|---|---|
| **C5a** implementation A, `baseline_store.py` | **182** |
| **C5b** implementation B, `openpersona_store.py` | **182** |
| **C5c** adapter and workaround subset of B | **87** |
| Shared scaffolding, charged to neither | 795 |

C5c by tag: revision synthesis 30, traversal synthesis 19, point read 18, diff
synthesis 11, node marshalling 5, rollback revision translation 4.

C5c passes its threshold comfortably. The number is also the least interesting
result in this experiment: the two implementations came out the same length to
the line, so persona-core saved nothing. Roughly half of B is code that exists
only to bridge to it.

Install footprint, reported as context and not scored: persona-core declares 20
direct dependencies and pulled **137 distributions** into a clean virtual
environment, including torch, transformers, an Anthropic SDK and an OpenAI SDK.
The first `import sentence_transformers` in that environment cost about 102
seconds of wall clock, inside the first write of the first process.

## Out of scope numbers, reported as context

| | A baseline | B openpersona | ratio |
|---|---|---|---|
| Write p50 | 0.80 ms (sd 0.14) | 200.6 ms (sd 31.9) | 250x |
| Write p95 | 7.00 ms (sd 1.84) | 510.4 ms (sd 141.8) | 73x |
| Rollback p50 | 1.20 ms (sd 0.46) | 454.9 ms (sd 123.7) | 378x |
| Wall clock, one seed | 5.24 s (sd 1.13) | 563.1 s (sd 137.0) | 107x |

Write latency is not a scored criterion, as declared in the criteria before the
run. It is quoted because a design-state write at 200 ms sets the floor on how
fast the ARCH-030 control loop can turn.

## Deviations and disclosures

1. The C4 verifier aborted on the first broken chain for seeds 1, 2 and 3, so
   two of the four timings are missing for those seeds. The broken chain counts
   were established afterwards by reading the same store directories. Nothing was
   re-measured.
2. `aggregate.py` was edited after the runs to tolerate the missing fields, and
   `loc.py`'s list of shared files was extended to include `aggregate.py`.
   Neither file is an implementation, and C5a, C5b and C5c are unaffected.
3. Neither `baseline_store.py` nor `openpersona_store.py` was touched after its
   first measured run. What is reported is the first honest version of each.
4. The cold `import sentence_transformers` lands inside the first write of each B
   process. It is one sample in 1,230 and moves neither p50 nor p95.
5. The acceptance rule, as pre-registered, does not gate on C4. It is recorded
   here that it should have, and that fixing it after seeing the result would
   have been rewriting the criteria, so it was not fixed.

---

## Why the baseline wins, in one paragraph

The architecture asks for a keyed, diffable, role gated, crash safe graph.
persona-core is a semantic memory layer for conversational personas: its unit is
a text chunk with an embedding, its read primitives are "nearest to this
sentence" and "give me everything", its write policy axis is where the text came
from rather than who wrote it, and its durability model assumes a chat turn is
cheap to lose. Every one of those is a reasonable choice for what it was built
for, and every one of them is the wrong end of what ARCH-010 to ARCH-013 need.
Nothing in C6 forces a change to the ARCH-010 schema, which is worth stating
plainly: the schema is fine. The store is the mismatch.

---

# C6. Assumption mismatches

Written during implementation, before implementation B produced a single metric.
Each entry states what the architecture needs, what persona-core offers, what was
done about it, and whether closing the gap would require changing the ARCH-010
schema.

Code references are to `packages/core/src/persona/` in the Open Persona repo at
the commit installed for this experiment.

---

### M1. There is no structured slot for a node, so the node becomes an opaque blob

**Needs.** ARCH-010 nodes carry a nested `quantities` object and two lists,
`requirements` and `constrains`.

**Offers.** `PersonaChunk` has `text: str` and `metadata: dict[str, str]`. The
Chroma transport accepts JSON primitives in metadata only
(`chroma.py::_chunk_to_metadata`), so neither a nested object nor a list can go
there.

**Done.** The whole node is serialised into `text` as canonical JSON and parsed
back on every read.

**Consequence.** The store cannot filter, index or constrain on any node field.
Every write computes a 384 dimensional embedding of a JSON blob that nothing will
ever search semantically. The typed memory layer is, for this workload, a
key value store with an embedding tax.

**ARCH-010 change required.** No.

---

### M2. The MemoryStore protocol has no read by id

**Needs.** `read_node(id)`, and the same read on every hop of a `constrains`
traversal.

**Offers.** `query()` is semantic and needs an embedding plus a `top_k`.
`history()` and `get_all()` are full scans. The only id keyed read in the package,
`get_by_logical_ids`, is on the `Backend` transport, not on `MemoryStore`.

**Done.** The adapter holds its own reference to `ChromaBackend` and calls
`get_by_logical_ids`, then filters for the head version itself.

**Consequence.** Every point read goes past the typed store to the transport,
which is the layer where policy and audit do not run. A store whose public
contract cannot answer "give me node X" is not a graph store.

**ARCH-010 change required.** No.

---

### M3. There is no store wide revision, and `write()` returns nothing

**Needs.** A monotonic revision per mutation, handed back to the caller, so the
ledger (ARCH-012) and the divergence diff (ARCH-013) have something to anchor to.

**Offers.** Versions are per `logical_id`, not per store. `TypedStore.write`
returns `None` by CQS.

**Done.** A revision is defined as the ordinal position of a chunk in the
`(created_at, id)` total order over the store. After every write the adapter
re-reads the chain to discover what it just created.

**Consequence.** One extra read on every write. More seriously, the revision is a
derived artefact of timestamps that two processes cannot agree on. ARCH-005 puts
one agent per worktree today, so a single writer holds; the first time two
sessions write one store, this numbering is unsound.

**ARCH-010 change required.** No. It does bear on ARCH-012 and ARCH-013.

---

### M4. `rollback()` copies the target's metadata verbatim

**Offers.** `TypedStore.rollback` constructs the new head with
`metadata=dict(target.metadata)` (`base.py`). Any bookkeeping a caller keeps in
metadata travels back in time along with the payload.

**Done.** Avoided by keeping metadata empty and deriving the revision from
timestamps (M3). Recorded anyway, because a revision stamp in metadata is the
obvious first design and it fails silently: the rolled back head would carry the
old revision, and the diff would never report the rollback.

**ARCH-010 change required.** No.

---

### M5. The write policy axis is the wrong axis

**Needs.** ARCH-013: only the owning role may write a node, across five or more
roles, and a violation blocks.

**Offers.** `WriteSource` has exactly three values, system, user and
persona_self, and the policy table keys on that alone. The actor is carried in
`written_by`, a free text audit field the policy engine never reads.

**Done.** Role ownership is enforced in the adapter, above the store.

**Consequence.** Two of them. First, the store's policy engine contributes
nothing to the guard that matters here. Second, `SelfFactsStore` is FORCE_ONLY
for system writes, so every single write passes `force=True`; the force flag
stops meaning anything, and every audit row reads `source=system` with a forced
write. ARCH-003 says a deterministic constraint should move into a hook at the
boundary. The store boundary cannot host this hook, because the store does not
know who the actor is.

**ARCH-010 change required.** No, but it means persona-core cannot be the
enforcement point for ARCH-013.

---

### M6. Per node immutability (ARCH-011) has no counterpart

**Needs.** Interface nodes are writable by the orchestrator at decomposition and
by nobody afterwards.

**Offers.** The only immutability in the package is the identity store, which is
immutable wholesale and raises on `history()` and `rollback()`.

**Done.** Enforced in the adapter. Putting interface nodes in the identity store
was considered and rejected: it splits the graph across two collections, and
`traverse_constrains` crosses that boundary on almost every hop.

**ARCH-010 change required.** No.

---

### M7. Unit validation is not expressible in the store

**Needs.** ARCH-010 acceptance: a quantity with a bare number fails schema
validation.

**Offers.** `PersonaChunk` validates a content hash and tz aware datetimes.
There is no hook for a domain schema over the payload, because to the store the
payload is a string (M1).

**Done.** The adapter validates before writing.

**ARCH-010 change required.** No.

---

### M8. There is no "what changed since" read

**Needs.** ARCH-013 diffs the graph after every step.

**Offers.** Nothing narrower than `get_all`, which materialises and revalidates
every version of every node. `recent(limit)` looks narrower but calls the same
`get_all` internally and then keeps only current heads, so it cannot answer a
diff at all.

**Done.** `get_all(include_superseded=True)` on every diff, filtered against the
revision cursor.

**Consequence.** Diff is O(total versions), and because the stores are append only
and nothing prunes, that number only grows for the life of the project. This is
the single largest expected cost difference against the baseline, where a diff is
a seek into an append only file.

**ARCH-010 change required.** No.

---

### M9. `history()` is a full scan, and `rollback()` pays it twice

**Offers.** `TypedStore.history` calls `get_all` and filters in Python
(`base.py`). `TypedStore.rollback` then calls `history` again internally, after
the adapter has already called it to translate a revision into a version number.

**ARCH-010 change required.** No.

---

### M10. The tenancy unit is a persona, not a project

Every call takes a `persona_id`. A design project maps onto one persona id and
one store kind. Nothing breaks, but every collection name, log line and audit row
in the system calls a robot subsystem a persona.

**ARCH-010 change required.** No.

---

### M11. The four typed stores do not map to the four node kinds

ARCH-010 `kind` is component, module, requirement or interface. persona-core's
kinds are identity, self_facts, worldview and episodic, each with its own write
policy and its own retention machinery. Exactly one of them, self_facts, is
versioned, append only and willing to take arbitrary writes, so all four node
kinds land in it. The typing the package advertises is unused by this workload.

**ARCH-010 change required.** No.

---

### M12. An embedding model is a hard dependency of the write path

`ChromaBackend.upsert` calls `self.embedder.encode(...)` unconditionally and the
package ships no null embedder. Writing a design node therefore pulls torch,
transformers and sentence-transformers into the orchestrator process.

Measured during setup, before any metric was taken: installing persona-core into
a clean virtual environment pulled **137 distributions**, and the first
`import sentence_transformers` in that environment took **about 102 seconds** of
wall clock inside the first write.

ARCH-001 says the deterministic binding spends zero tokens on scheduling and
dispatch. It says nothing about a 137 package dependency on the state layer, but
the spirit of a deterministic, auditable orchestrator is not well served by one.

**ARCH-010 change required.** No.

---

### M13. A versioned write is two unsynchronised upserts

`TypedStore.write` writes the supersede link first and the new head second, as two
separate `upsert` calls with no transaction around them (`base.py`). A crash
between them leaves the previous head pointing `superseded_by` at a chunk that
does not exist, which is exactly what `validate_chain` invariant 4 forbids, so
`history()` on that node raises `BrokenVersionChainError` forever after.

The baseline has no equivalent window: the fsynced ledger line is the commit
point and the node file is a derived materialisation that recovery rebuilds.

Whether the crash test actually lands in that window is a matter of luck. The
window exists either way.

**ARCH-010 change required.** No.
