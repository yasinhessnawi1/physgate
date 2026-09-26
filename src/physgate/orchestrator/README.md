# `physgate.orchestrator` — the deterministic loop

This package decides what runs next and whether to merge, in Python. A model is
called once per run, at decomposition, and never to schedule, dispatch, merge or
reconcile (ARCH-001). Every awkward case, from a garbled session to a merge
conflict, is answered by code or by a person.

## What it owns

| | |
|---|---|
| `dispatch.py` | One attempt in a fresh Claude Code session: the binary's version checked against the run's, the session's own directory outside the worktree, settings from the hook layer's installer run from the read-only installation, the key through a helper, the wall clock, and afterwards only the orchestrator's own records: the stream it captured (key redacted), the hook layer's reading records, the hook log's node-file halts and journal appends |
| `processes.py` | Stopping a session so nothing it started is left running: the process tree collected by parent pid before the stop, SIGTERM, then SIGKILL for whatever is still alive and still the same process by start time |
| `install.py` | The copied, read-only installation the hooks run from, and the facts each run records about it and about the state directory's filesystem |
| `decompose.py` | The run's one model call (ARCH-001): one Claude Code invocation, no tools but the structured answer, one turn, so one request. The answer is untrusted input, validated here; success with no plan fails the run. Subtask ids are minted from the seed; specifications go onto the run branch, interface nodes into the store, and the store is committed |
| `invocation.py` | The one module that names the Claude Code binary: the pinned version, the isolated argv and an environment built from nothing |
| `cli.py` | `physgate decompose` (the configuration from explicit inputs, the one call, the run started) and `physgate queue list/resolve`. `physgate run` and `physgate resume` (the real ports wired, the gate and reviewers from the registrations, routing tokens asserted zero at the end); the run directory belongs on a local disk where one exists |
| `record.py` | A run's durable record (configuration, event log, ledger, queue), so a run can be started without the ports a loop needs |
| `loop.py` | The eight stages (ARCH-030), one subtask at a time: fresh session, reading, change check, gate, review only if the gate result allows it, merge or templated rejection, diff. Refuses to start in a gate mode that needs a gate when none is registered; under gate mode `off` the stage is skipped on the record, never passed. Resume restarts an interrupted attempt at its checkpoint with a fresh session |
| `replay.py` | `RunState`: the run's position, rebuilt from the event log, refusing a line that cannot come next at write time and at replay alike. The task ledger is projected from it, and the merge precondition reads that ledger back from disk (ARCH-001) |
| `apply.py` | Node proposals applied, never trusted: read from the attempt commit, only those the attempt changed, the role from the plan, an owner change refused, all of them pre-checked on a scratch copy of the graph so an attempt is applied whole or not at all. Also the canonical store the loop holds, whose journal is read without opening it |
| `merge.py` | A run's git layout, the recorded unforced removal of a done subtask's worktree, (its own branch, an integration worktree, one branch and worktree per subtask kept across attempts), the orchestrator's templated attempt commit, the write-scope check (ARCH-005) that runs before the gate, and the merge: `--no-ff` of exactly the checked commit, idempotent, a conflict aborted and raised |
| `git.py` | The git plumbing, with the user's and system's configuration off and repository hooks disabled |
| `ports.py` | The narrow Protocols the loop is handed for what it does not decide: the session, the change check, the merge, the graph diff |
| `events.py` | The run-event log. It is the loop's only memory: one synced, append-only line per stage transition and per decision. Each line carries its sequence number, UTC timestamp, run id and gate mode. A line the replay would refuse is refused before it is written |
| `run_config.py` | Every input a run is reproduced from, written once before the first action: seed, model strings, bounds, gate mode, token ceiling. None has a default, and a resume under a different configuration is refused |
| `protocols.py` | The `Gate` and `Reviewer` Protocols the loop calls, in that order, and the result shapes they hand back. No implementation of either ships here. Also the refusal to run a reviewer on the implementer's model string (ARCH-060) |
| `accounting.py` | The token account, rebuilt from the event log: every token attributed to decomposition, a role session, a reviewer or routing, deduplicated by message id, and routing asserted zero |
| `budget.py` | The repair budget of three (ARCH-030), and the classifier that keeps infrastructure failures (API error, wall clock, turn limit, no result, unexpected exit) out of it. The binary's result is read by `is_error` and `terminal_reason`, never `subtype` |
| `repair.py` | Repair instructions as fixed templates filled from the finding: attempt 1 the finding, attempt 2 plus the failing check and its number with unit, attempt 3 none (it escalates) |
| `queue.py` | The approval queue: one append-only file, items carrying ARCH-130's five things, a person's decision as its own line |
| `common.py` | The small shapes the records share: the gate mode, the full-model-string rule |
| `exceptions.py` | The domain exceptions. All of them carry a context mapping |

## What it deliberately does not own

- **Any gate check or any reviewer.** The loop calls a gate and a reviewer
  through Protocols, and ships no implementation that passes work.
- **The graph store and the task ledger.** Those are `physgate.state`'s. The
  ledger is written here, as a projection of the run-event log, because its
  line shape is fixed by the architecture and cannot hold a stage or a cause.
- **The hooks.** Sessions run under `physgate.hooks`; this package generates
  their settings and spawns them, and never edits what the hooks enforce.

## The run-event log and the task ledger

The ledger holds one line per change of a subtask's state, with the fields
ARCH-012 names. The event log holds everything else the loop needs to resume:
stages, causes, timestamps. Resuming reads the event log and nothing held in
memory.
