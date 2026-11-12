"""A run's write account rebuilt from its held records as they are now, for rows that forge them.

A row that cuts a run's log to stand for a kill, copies a run directory, or rewrites a held
record's line to reach a later check plays a same-user forger. The write account would halt the
next resume first, on ``run_records_changed``: the account names what the orchestrators wrote,
and these rows change it behind them. The stated limit names the forger who writes the account
too, and the later checks are what stands then; so such rows rebuild the account before each
open (:func:`forged_account_before_each_open`), and their checks are reached as before. The
account's own rows never do.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from loop_fakes import Rig

from physgate.state.write_account import ACCOUNT_NAME

#: The records the account names, as the dispatcher's held records list them.
NAMED = ("events.jsonl", "ledger.jsonl", "queue.jsonl")


def reaccount(run_dir: Path) -> None:
    """Rewrite the run's account, in place, to name every complete line its records hold now."""
    lines: list[bytes] = []
    for name in NAMED:
        path = run_dir / name
        if not path.is_file():
            continue
        st = os.stat(path)
        at = 0
        for line in path.read_bytes().splitlines(keepends=True):
            if not line.endswith(b"\n"):
                break
            digest = hashlib.sha256(line).hexdigest()
            intent = {
                "record": name,
                "identity": [st.st_dev, st.st_ino],
                "offset": at,
                "length": len(line),
                "sha256": digest,
            }
            done = {"completed": name, "offset": at, "sha256": digest}
            lines += [json.dumps(x, separators=(",", ":")).encode() + b"\n" for x in (intent, done)]
            at += len(line)
    account = run_dir / ACCOUNT_NAME
    if account.exists() or lines:
        with account.open("wb") as out:
            out.write(b"".join(lines))


@pytest.fixture(autouse=True)
def forged_account_before_each_open(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every rig opened in the importing module finds the account rebuilt first."""
    real = Rig.open

    def opened(self: Rig) -> object:
        reaccount(self.run_dir)
        return real(self)

    monkeypatch.setattr(Rig, "open", opened)
    yield
