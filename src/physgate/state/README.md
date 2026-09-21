# `physgate.state` — the design-state graph and the task ledger

This package owns the durable record of what has been designed. It is the
promotion of the store that won the pre-registered comparison in
`experiments/R-OP-01/` and was re-measured in `experiments/R-OP-02/`: one JSON
file per graph node, an append-only journal beside them, and the guards that
decide what may be written.

Read `experiments/R-OP-01/RESULT.md` before changing anything here. The numbers
in it describe this design, and they are the reason the alternative was not
adopted.

## What it owns

| | |
|---|---|
| `store.py` | The store itself: JSON per node over an append-only journal, the three guards, recovery at open, and the staleness detector |
| `divergence.py` | The check that names a node changed during a step by a role that does not own it |
| `protocol.py` | The store interface, exactly as the comparison froze it: eight methods, and the closed set of rejection reasons the correctness score is counted in |
| `schema.py` | The node shape, the quantity, and the identifier rule. Every quantity carries a value, a unit, a source and the role that wrote it |
| `exceptions.py` | The domain exceptions. All of them carry a context mapping |
| `task_ledger.py` | One append-only line per dispatched subtask |

### One of them reads differently from the others

**The task ledger answers from a process-lifetime view, and that is a decision
rather than an oversight.** It holds every parsed line from its open and answers
from that list; it does not re-read the file and it has no staleness detector.
The ledger has one writer by architecture — the orchestrator — so there is no
second writer to disagree with, and a reader that wants current state opens its
own handle.

The graph store is the opposite and deliberately so: it re-reads its files, and
it refuses to answer when the journal has moved underneath it, because there a
second writer corrupts the record silently. The two files are not held to the
same rule because they do not have the same risk.

## The two append-only files, which are not the same file

They are easy to confuse and the confusion is expensive, so they have different
names.

**The journal** (`journal.jsonl`) belongs to the graph. It is the authority: a
mutation is durable once its journal line is synced, and the per-node JSON files
are a materialisation that recovery rebuilds from it. That ordering is what makes
a kill between the two harmless.

**The task ledger** (`ledger.jsonl`) belongs to the orchestrator. One line per
dispatched subtask. It knows nothing about nodes.

Both are append-only. Neither ever rewrites a line.

## A handle is a view as of open

**A store handle rebuilds its indexes when it opens and not afterwards.** One
process holds the store at a time. This is not a caution, it is a property the
code enforces: if the journal moves underneath a handle, that handle refuses to
answer rather than answering inconsistently.

The reason is worth knowing, because the failure it prevents is silent. A handle
whose indexes predate another writer's work answers some reads from the current
files and others from the stale indexes — measured, the change list said two
changes while the head revision said one — and, worse, it mints a revision number
the other writer has already used. Two handles opened on one directory both mint
revision one; the journal then holds two lines at that revision, a fresh open
reports the lower head, and one of the two nodes **never appears in any change
list again**. A node that never appears in a change list can never be named by
the divergence check, which is the whole mechanism for catching a role writing a
node it does not own.

So the handle refuses. There is no refresh method, deliberately: a refresh would
make the inconsistent window smaller rather than closing it, and it would not
help the write case at all, because two handles that both refresh still race. If
the orchestrator ever needs concurrent handles, that is a decision taken here,
not a convenience added at the call site.

## What it deliberately does not own

- **Committing anything to git.** The store writes files; the orchestrator
  commits them. The comparison declared this out of scope and it stays there.
- **Concurrency across worktrees.** Single writer, serialised by the
  orchestrator. See above for what the store does instead of pretending
  otherwise. Locking is a decision for the day a measurement shows contention.
- **Search over the graph.** The architecture does not ask for it, and the
  comparison is the record of why the store that offered it was not adopted.
- **Enforcing the guards before a write is attempted.** The store refuses a
  write and says why. Making that refusal reach an agent *before* it writes is
  the hook layer's job.
- **The propagation check.** Traversal of the `constrains` edges ships here; the
  check that fails when a constrained node was not rewritten belongs to the
  physics gate.
- **Anything to do with units beyond their presence.** That a quantity *has* a
  unit is checked here. That the units *balance* is the physics gate.
