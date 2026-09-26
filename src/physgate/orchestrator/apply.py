"""Node proposals, applied and never trusted, and the canonical store the loop holds.

An agent does not write the graph. It proposes a node as one whole-node JSON file
under ``.physgate/proposals/``, named for the node's id, and the hook layer checks
the file as it is written. Here the orchestrator:

- reads proposals **from the attempt commit**, never the working tree, and only
  the ones the attempt added or changed, as regular files;
- takes the acting role from the subtask's own plan line, never from the proposal;
- refuses an owner change, which the store alone would accept from the current
  owner, because owners are assigned at decomposition and not by roles;
- pre-checks **all** of an attempt's proposals against the store's own guards on
  a scratch copy of the graph built from the canonical journal, so an attempt is
  applied whole or not at all, and a refusal is a rejected attempt carrying the
  store's own reason.

The canonical store is held by one handle across steps (opening it re-derives
every node file). The journal's newest records are read without opening it, so
the loop can look for a line it never intended before a single byte is written.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from physgate.orchestrator.exceptions import StoreRefusalError
from physgate.orchestrator.git import changes_between, commit_all, git, init_repo, merge_base
from physgate.orchestrator.merge import RunGit, write_scope_violations
from physgate.orchestrator.ports import ChangeCheck
from physgate.state.divergence import divergence
from physgate.state.exceptions import DesignStateError
from physgate.state.schema import validate_node
from physgate.state.store import JOURNAL_NAME, JournalLine, Store, journal_records_after

_PROPOSAL = re.compile(r"^\.physgate/proposals/(?P<id>[a-z][a-z0-9_]*(\.[a-z0-9_]+)+)\.json$")


class ProposalRefusedError(Exception):
    """A proposal cannot be applied; the message is the reason an agent reads."""


def _owners(store_root: Path) -> dict[str, str]:
    """The current owner of every node, from the canonical journal, read-only."""
    return {
        line.node_id: str(line.payload["owner_role"])
        for line in journal_records_after(store_root, 0)
    }


def read_proposals(repo: Path, base: str, commit: str, store_root: Path) -> list[dict[str, Any]]:
    """The whole-node proposals ``commit`` added or changed since ``base``, validated.

    Raises:
        ProposalRefusedError: a proposal is not a regular file, not JSON, not a whole
            node, named for another node, or changes a node's owner.
    """
    owners = _owners(store_root)
    found: list[dict[str, Any]] = []
    for change in changes_between(repo, base, commit):
        named = _PROPOSAL.match(change.path)
        if named is None or change.status == "D":
            continue
        if change.new_mode != "100644":
            raise ProposalRefusedError(f"{change.path} is not a regular file")
        raw = git(repo, "show", f"{commit}:{change.path}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise ProposalRefusedError(f"{change.path} is not JSON") from None
        if not isinstance(payload, dict) or payload.get("id") != named["id"]:
            raise ProposalRefusedError(f"{change.path} is not one whole node named for its file")
        try:
            validate_node(payload)
        except (DesignStateError, ValueError) as exc:
            raise ProposalRefusedError(f"{change.path} is not a valid node: {exc}") from None
        owner = owners.get(named["id"])
        if owner is not None and payload["owner_role"] != owner:
            raise ProposalRefusedError(
                f"{change.path} changes the owner of {named['id']} from {owner!r}; owners are "
                "assigned at decomposition"
            )
        found.append(payload)
    return sorted(found, key=lambda p: str(p["id"]))


class GitChangeChecker:
    """The change check before the gate: write scope, then every proposal pre-checked."""

    def __init__(self, run: RunGit, store_root: Path, module_dirs: dict[str, str]) -> None:
        """Check attempts of ``run`` against the canonical store at ``store_root``."""
        self._run = run
        self._store_root = store_root
        self._module_dirs = module_dirs

    def check(self, subtask_id: str, attempt_commit: str, role: str) -> ChangeCheck:
        """Refuse an attempt out of scope or with a proposal the store would refuse."""
        repo = self._run.repo
        base = merge_base(repo, self._run.run_branch, attempt_commit)
        outside = write_scope_violations(repo, base, attempt_commit, self._module_dirs[subtask_id])
        scratch = self._run.run_dir / "scratch" / f"{subtask_id}-{attempt_commit[:12]}"
        if outside:
            reason = "the attempt changed paths outside its module: " + "; ".join(outside)
            return ChangeCheck(refused_by="write_scope", reason=reason, graph_root=str(scratch))
        try:
            proposals = read_proposals(repo, base, attempt_commit, self._store_root)
            self._precheck(scratch, proposals, role)
        except ProposalRefusedError as exc:
            return ChangeCheck(refused_by="proposal", reason=str(exc), graph_root=str(scratch))
        return ChangeCheck(refused_by=None, reason=None, graph_root=str(scratch))

    def _precheck(self, scratch: Path, proposals: list[dict[str, Any]], role: str) -> None:
        """Apply every proposal to a scratch copy of the graph; refuse on the first refusal."""
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        journal = self._store_root / JOURNAL_NAME
        if journal.exists():
            whole = journal.read_bytes()
            (scratch / JOURNAL_NAME).write_bytes(whole[: whole.rfind(b"\n") + 1])
        store = Store(scratch)
        try:
            for payload in proposals:
                result = store.write_node(payload, role)
                if not result.accepted:
                    msg = f"the store refused the proposal for {payload['id']}: {result.reason}"
                    raise ProposalRefusedError(msg)
        finally:
            store.close()


class StoreKeeper:
    """The loop's graph port over the canonical store and the run's repository."""

    def __init__(self, run: RunGit, store_root: Path) -> None:
        """Keep the store at ``store_root``; it is opened on first use, not here."""
        self._run = run
        self._root = store_root
        self._store: Store | None = None

    def _handle(self) -> Store:
        if self._store is None:
            self._store = Store(self._root)
        return self._store

    def records_after(self, revision: int) -> list[JournalLine]:
        """Every canonical journal record after ``revision``; never opens the store."""
        return journal_records_after(self._root, revision)

    def hold(self) -> None:
        """Open the handle now, so an append made after this makes it stale."""
        self._handle()

    def commit(self, message: str) -> None:
        """Commit the store's journal and node files in the store's own repository."""
        init_repo(self._root)
        commit_all(self._root, message)

    def proposals(self, subtask_id: str, attempt_commit: str) -> list[dict[str, Any]]:
        """The attempt's validated proposals, read from its commit."""
        repo = self._run.repo
        base = merge_base(repo, self._run.run_branch, attempt_commit)
        return read_proposals(repo, base, attempt_commit, self._root)

    def write(self, payload: dict[str, Any], role: str) -> int:
        """Write one node; a refusal after a clean pre-check raises."""
        result = self._handle().write_node(payload, role)
        if not result.accepted or result.revision is None:
            msg = "the store refused a write the pre-check had accepted"
            raise StoreRefusalError(msg, node=str(payload.get("id")), reason=str(result.reason))
        return result.revision

    def divergences(self, since: int, acting_role: str) -> tuple[str, ...]:
        """Every node changed after ``since`` by a role that does not own it."""
        store = self._handle()
        return tuple(str(d) for d in divergence(store, store.diff(since), acting_role))

    def reopen(self) -> tuple[int, tuple[str, ...]]:
        """Reopen the store so recovery repairs node files from the journal."""
        if self._store is not None:
            self._store.close()
        self._store = Store(self._root)
        return self._store.repaired_node_files, self._store.quarantined_node_files

    def close(self) -> None:
        """Release the store handle."""
        if self._store is not None:
            self._store.close()
            self._store = None
