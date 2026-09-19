# R-OP-01 pre-registration

**Status:** frozen before any implementation code was written.
**Written:** 2026-09-20
**Rule:** nothing in this file may change after the first metric is produced. If
a measurement turns out to be impossible as specified, that fact is recorded in
RESULT.md as a deviation, with its reason, and the criterion is scored as failed
rather than rewritten.

---

## 1. Question

Does Open Persona's typed memory layer serve as the design-state graph store for
the WP4 architecture better than a purpose-built schema file plus JSONL ledger?

The store under test is the one required by `.docs/02-architecture-specification.md`,
decisions ARCH-010 (graph schema), ARCH-011 (interface nodes immutable after
decomposition), ARCH-012 (append only task ledger), ARCH-013 (divergence
detection: a node written by a role that does not own it is a blocking failure,
caught within one step).

## 2. Node shape under test (ARCH-010, verbatim fields)

```
id, kind, domain, owner_role,
quantities: {name: {value, unit, source, written_by}},
requirements: [str], constrains: [str],
model: str | null, geometry_hash: str, updated: iso8601
```

## 3. Interface both implementations satisfy

```python
class DesignStateStore(Protocol):
    def write_node(self, node: dict, actor_role: str) -> WriteResult: ...
    def read_node(self, node_id: str) -> dict: ...
    def diff(self, since: Revision) -> list[NodeChange]: ...
    def traverse_constrains(self, node_id: str) -> list[str]: ...
    def history(self, node_id: str) -> list[Revision]: ...
    def rollback(self, node_id: str, to: Revision) -> None: ...
```

`Revision` is an opaque monotonically increasing integer minted by the store, one
per accepted mutation. `WriteResult` is frozen and carries `accepted: bool`,
`revision: Revision | None`, `reason: str | None`. A rejected write mints no
revision and leaves no trace in the graph.

`traverse_constrains` returns the transitive closure of the `constrains` edges
reachable from the node, excluding the start node, in breadth first order, with
cycles tolerated and visited once.

`history` returns every revision of the node, oldest first.

`rollback` is append only: it adds a new head whose payload equals the payload at
the named revision. It never deletes.

## 4. The two implementations

**A. baseline.** One JSON file per node on disk inside a git repository, plus an
append only JSONL ledger. Written from scratch for this experiment. Budget: one
day of work.

**B. openpersona.** The real `persona-core` package (installed from
`/Users/yasinhessnawi/dev/Open-Persona/packages/core`, not vendored and not
reimplemented) behind the same Protocol.

B's backing configuration is fixed here, before measurement, so that no store can
be shopped for after seeing numbers:

- `persona.stores.self_facts.SelfFactsStore`, the versioned append only typed
  store whose semantics are closest to "facts that are true of this artefact".
- `persona.stores.chroma.ChromaBackend` with a persistent path, the package's
  local transport.
- `persona.stores.embedder.SentenceTransformerEmbedder` with the project
  embedder `BAAI/bge-small-en-v1.5`, the real one, not a stub.
- `persona.audit.JSONLAuditLogger`, the package default.
- One design project maps to one `persona_id`.

## 5. Rules of fair play

- **R1 Durable state only.** Every fact either implementation needs after a
  process restart lives in that implementation's own durable store: for A the
  JSON files and the JSONL ledger, for B the persona-core stores. B may not keep
  a side ledger, a side index file, or any other durable record outside
  persona-core. That would answer a different question.
- **R2 Reads come off the durable record.** `diff`, `read_node`,
  `traverse_constrains` and `history` must read the durable store. Neither
  implementation may answer them out of a write log accumulated in this process's
  memory. The architecture runs agent sessions as separate processes in separate
  worktrees (ARCH-005) and the orchestrator diffs what they committed, so an in
  process content cache would be a false green. Location indexes (byte offsets
  into a file, a highest seen revision counter) may be kept in memory and must be
  rebuildable at open from durable state alone.
- **R3 First honest version.** Neither implementation is optimised after its
  numbers are seen. If an implementation is edited after a measurement run, every
  seed is rerun for both implementations and the reason for the edit is recorded
  in RESULT.md.
- **R4 Narrowest available read.** B uses the narrowest read that the public
  persona-core API offers for each operation. The call chosen for each operation
  is recorded in C6, including the ones where the narrowest available read is
  still a full scan.
- **R5 Equal guards.** The three correctness guards (role ownership, interface
  immutability, unit presence) are implemented in both, with the same semantics
  and the same rejection points.
- **R6 Same workload.** For a given seed both implementations receive an
  identical operation sequence from one generator.

## 6. Workload, generated by a seeded script, no model in the loop

Per seed:

- 200 nodes across the domains mechanical, electrical, control, firmware, cross.
- 50 of the 200 are `kind == "interface"`, created by the orchestrator role at
  decomposition.
- 1,000 write operations after creation, of which:
  - 15 per cent (150) are cross role writes, a role writing a node it does not
    own, which MUST be rejected;
  - 5 per cent (50) carry at least one quantity whose value is a bare number with
    no unit string, which MUST be rejected;
  - 20 of the writes target an interface node after decomposition, which MUST be
    rejected;
  - at least 10 per cent (100) target a node with three or more `constrains`
    edges;
  - the remainder are legal writes by the owning role, which MUST be accepted.
  The categories are assigned so the mandated counts are exact; a single
  operation carries at most one injected fault.
- 30 rollback operations to a named earlier revision of a node that has at least
  two revisions.
- One simulated crash, see C4.

The generator is seeded and deterministic: the same seed produces the same node
set and the same operation sequence, byte for byte, on every run and for both
implementations. Seeds: 1, 2, 3, 4, 5.

## 7. Measurements

Reported as mean and standard deviation across the five seeds.

### C1 Correctness, reported as counts

Per seed, four counters: cross role writes attempted and rejected, interface
writes attempted and rejected, unit less writes attempted and rejected, legal
writes attempted and accepted. A rejected write must also leave the graph
unchanged, verified by reading the node back and comparing to its payload before
the attempt.

**Any miss is a hard failure for that implementation.** A miss is: any mandated
rejection that was accepted, any legal write that was rejected, or any rejected
write that mutated the graph.

### C2 Diff latency

`diff(since)` is called once after every accepted write and after every rejected
write, with `since` set to the revision cursor held before that operation. 1,000
samples per seed per implementation. Wall clock, `time.perf_counter`, p50 and p95
in milliseconds. Correctness of the diff is asserted on every call: the returned
change set must equal the operations accepted since the cursor.

### C3 Traversal latency

`traverse_constrains` is called on the deepest node after every tenth operation.
100 samples per seed per implementation. The deepest node is the node with the
largest transitive `constrains` closure, ties broken by lexicographic id; it is
computed once from the generated graph before the run and is the same node for
both implementations. Wall clock, p50 and p95 in milliseconds.

### C4 Crash recovery

A child process opens the store, replays the seed's operation sequence, and
appends one fsynced acknowledgement line per operation the store returned from.
The parent kills the child with SIGKILL at a seeded delay inside the write phase.
A fresh process then opens the store and runs its recovery routine.

Consistent means all four of:
1. the store opens without raising;
2. every acknowledged write is readable at the revision it was acknowledged at,
   or a later one, and no acknowledged write is lost;
3. no node holds a payload that was never written: each node's current payload
   equals one of the payloads the generator produced for it;
4. every version chain is intact: versions 1..k with no gaps, no duplicate
   version numbers, exactly one head.

Reported: `consistent` boolean, `open_and_recover_ms` (process start to recovery
routine complete), `verify_ms` (the four checks), and the number of writes lost
after the last acknowledgement, which is expected and not a failure.

### C5 Implementation cost

Lines of code, counted with a script committed in the run directory, over Python
source, excluding blank lines and lines whose stripped content begins with `#`.
Docstring lines are counted, because they are written.

Three numbers:
- **C5a** implementation A, its own module only.
- **C5b** implementation B, its own module only.
- **C5c** the adapter and workaround subset of B: lines inside regions marked
  `# ADAPTER:<tag>` ... `# /ADAPTER`, where a region qualifies only if it exists
  because persona-core's model differs from the ARCH-010 model. Marshalling a
  node dict into a chunk and back, flattening list and nested fields into the
  metadata shape the transport accepts, synthesising a revision counter the
  package does not provide, and synthesising `diff` and `traverse_constrains`
  from the reads the package does offer, all qualify. The three correctness
  guards do NOT qualify, because implementation A needs them too; counting them
  would inflate C5c with work that is not attributable to persona-core.

Shared code, meaning the protocol module, the generator, the harness, the runner
and the counting script, is reported separately and charged to neither.

The install footprint of B is also reported: direct dependencies pulled in and
total installed distributions. It is context, not a scored criterion.

### C6 Assumption mismatches

A written list. One entry per place where the persona memory model had to be
worked around. Each entry states: what the architecture needs, what persona-core
offers, what was done about it, and whether resolving it would require changing
the ARCH-010 schema. Written during implementation, not after seeing the numbers.

## 8. Acceptance

Open Persona enters the architecture as the store only if all four hold:

1. C1 is perfect for both implementations.
2. C2 p95 and C3 p95 for B are each within 2x of A, comparing the mean across
   seeds of the per seed p95.
3. C5c is under 300 lines.
4. C6 lists no mismatch that requires changing the ARCH-010 schema.

Otherwise the baseline ships, and Open Persona is recorded as tested and not
adopted, with C6 as the reason.

## 9. Out of scope, declared here so it cannot be claimed later

- Write latency is recorded and reported as context. It is not a scored
  criterion, because the criteria list above does not name it.
- Git commit cadence is out of scope for both implementations. Both are measured
  as the in process store with its own durable files; committing those files is
  the orchestrator's job in both designs and would be identical work.
- Concurrency across worktrees is not measured. Single writer per run.
- Semantic search over the graph is not measured. The architecture does not ask
  for it.
