"""A read-only view of the graph journal, for hooks that must never write the store.

A hook may not open a store. Constructing one runs recovery, which rewrites node
files that disagree with the journal and moves unknown files aside, so opening
one is writing, and the store has one writer. What a hook needs from the graph —
who owns a node, what kind it is, what its file should hold — it reads here: the
journal is opened for reading and nothing else, and no store object is ever made.

A final line without its terminator is a write still in progress and is not
read. A complete line that is not a record is skipped: a journal holding one is
refused by the store itself when it next opens, so nothing it says is served.
"""

from __future__ import annotations

import json
import os
from typing import Any

JOURNAL_NAME = "journal.jsonl"

#: (revision, version, payload) of a node's newest journal record.
Head = tuple[int, int, dict[str, Any]]


def heads(root: str) -> dict[str, Head]:
    """The newest record the journal under ``root`` holds for each node."""
    try:
        fd = os.open(os.path.join(root, JOURNAL_NAME), os.O_RDONLY)
    except FileNotFoundError:
        return {}
    try:
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
    finally:
        os.close(fd)
    found: dict[str, Head] = {}
    for line in b"".join(chunks).split(b"\n")[:-1]:
        try:
            record = json.loads(line)
            node_id, rev = record["node_id"], int(record["rev"])
            version, payload = int(record["version"]), record["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if (
            isinstance(node_id, str)
            and isinstance(payload, dict)
            and (node_id not in found or rev > found[node_id][0])
        ):
            found[node_id] = (rev, version, payload)
    return found
