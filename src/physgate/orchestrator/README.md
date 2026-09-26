# `physgate.orchestrator` — the deterministic loop

This package decides what runs next and whether to merge, in Python. A model is
called once per run, at decomposition, and never to schedule, dispatch, merge or
reconcile (ARCH-001). Every awkward case, from a garbled session to a merge
conflict, is answered by code or by a person.

## What it owns

| | |
|---|---|
| `events.py` | The run-event log. It is the loop's only memory: one synced, append-only line per stage transition and per decision. Each line carries its sequence number, UTC timestamp, run id and gate mode. A line the replay would refuse is refused before it is written |
| `run_config.py` | Every input a run is reproduced from, written once before the first action: seed, model strings, bounds, gate mode, token ceiling. None has a default, and a resume under a different configuration is refused |
| `protocols.py` | The `Gate` and `Reviewer` Protocols the loop calls, in that order, and the result shapes they hand back. No implementation of either ships here. Also the refusal to run a reviewer on the implementer's model string (ARCH-060) |
| `accounting.py` | The token account, rebuilt from the event log: every token attributed to decomposition, a role session, a reviewer or routing, deduplicated by message id, and routing asserted zero |
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
