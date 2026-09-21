"""Replay a seed against the promoted store, acknowledging every operation durably.

Run as a child process so a parent can kill it mid-write. Each acknowledgement is
synced before the next operation begins, so after a kill the acknowledgement file
is a lower bound on what the store must still hold: anything acknowledged was
durable before the process died, and losing it is a failure.

Both append-only files are exercised. The graph's journal takes the node writes;
the task ledger takes one line per operation, so a kill lands in whichever of the
two the process happened to be inside.

This is not a copy of the experiment's crash child, and it is not presented as
one: it drives a different store and writes a second file the experiment did not
have. What it reproduces is the experiment's *procedure* — replay, acknowledge
durably, die, and be judged against what was acknowledged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import generator
from pydantic import BaseModel, ConfigDict

from physgate.state.store import Store
from physgate.state.task_ledger import TaskLedger, TaskLine


class Acknowledgement(BaseModel):
    """One operation the child completed and made durable before continuing.

    This crosses a process boundary — the child writes it, a parent that killed
    the child reads it — so it is a validated shape rather than a loose mapping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    index: int
    kind: str
    node_id: str
    revision: int | None
    accepted: bool
    ledger_lines: int


def main() -> None:
    """Replay ``seed`` into ``root``, acknowledging into ``ack_path``."""
    seed = int(sys.argv[1])
    root = Path(sys.argv[2])
    ack_path = Path(sys.argv[3])

    work = generator.build(seed)
    store = Store(root)
    ledger = TaskLedger(root / "ledger.jsonl")
    ack = ack_path.open("a")

    def acknowledge(record: Acknowledgement) -> None:
        ack.write(record.model_dump_json() + "\n")
        ack.flush()
        os.fsync(ack.fileno())

    for op in work.ops:
        if op.kind == "rollback":
            revisions = store.history(op.node_id)
            store.rollback(op.node_id, revisions[op.to_ordinal - 1])
            ledger.append(
                TaskLine(
                    id=f"op-{op.index:05d}",
                    spec_path=f"seed{seed}",
                    assigned_role="rollback",
                    attempt_count=1,
                )
            )
            acknowledge(
                Acknowledgement(
                    index=op.index,
                    kind="rollback",
                    node_id=op.node_id,
                    revision=store.head_revision(),
                    accepted=True,
                    ledger_lines=len(ledger),
                )
            )
            continue

        assert op.payload is not None
        result = store.write_node(dict(op.payload), op.actor_role)
        ledger.append(
            TaskLine(
                id=f"op-{op.index:05d}",
                spec_path=f"seed{seed}",
                assigned_role=op.actor_role,
                attempt_count=1,
                gate_result="pass" if result.accepted else "fail",
            )
        )
        acknowledge(
            Acknowledgement(
                index=op.index,
                kind=op.kind,
                node_id=op.node_id,
                revision=result.revision,
                accepted=result.accepted,
                ledger_lines=len(ledger),
            )
        )

    ledger.close()
    store.close()
    ack.close()


if __name__ == "__main__":
    main()
