"""Replays a seed's operations and acknowledges each one durably.

Run as a child process so the parent can SIGKILL it mid write. Every
acknowledgement is fsynced before the next operation starts, so on restart the
acknowledgement file is a lower bound on what the store must still hold.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import generator
from stores import open_store


def main() -> None:
    impl, seed, root, ack_path = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
    work = generator.build(seed)
    store = open_store(impl, root)
    ack = ack_path.open("a")

    def acknowledge(record: dict) -> None:
        ack.write(json.dumps(record, sort_keys=True) + "\n")
        ack.flush()
        os.fsync(ack.fileno())

    for op in work.ops:
        if op.kind == "rollback":
            revs = store.history(op.node_id)
            target = revs[op.to_ordinal - 1]
            store.rollback(op.node_id, target)
            acknowledge({"i": op.index, "kind": "rollback", "node_id": op.node_id,
                         "revision": store.head_revision(), "accepted": True})
            continue
        result = store.write_node(copy.deepcopy(op.payload), op.actor_role)
        acknowledge({"i": op.index, "kind": op.kind, "node_id": op.node_id,
                     "revision": result.revision, "accepted": result.accepted})

    store.close()
    ack.close()


if __name__ == "__main__":
    main()
