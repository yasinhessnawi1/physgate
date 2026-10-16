"""Node proposals, applied and never trusted, and the canonical store the loop holds.

An agent does not write the graph. It proposes a node as one whole-node JSON file
under ``.physgate/proposals/``, named for the node's id, and the hook layer checks
the file as it is written. Here the orchestrator:

- reads proposals **from the attempt commit**, never the working tree, and only
  the ones the attempt added or changed, as regular files;
- takes the acting role from the subtask's own plan line, never from the proposal;
- refuses an owner change, which the store alone would accept from the current
  owner, because owners are assigned at decomposition and not by roles;
- refuses a kind change, for the same reason: a node's kind is fixed when it is
  created, and the relations the physics gate holds a node to follow from it (a
  module's declared mass is the sum of its parts), so rewriting the kind would
  let a node step out of a relation it failed;
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

from physgate.orchestrator.exceptions import StoreRefusalError
from physgate.orchestrator.git import (
    GitDir,
    changes_between,
    commit_all,
    git,
    init_repo,
    merge_base,
    verified_git_dir,
)
from physgate.orchestrator.merge import RunGit, write_scope_violations
from physgate.orchestrator.ports import ChangeCheck
from physgate.series.seal import SessionSeries
from physgate.state.divergence import divergence
from physgate.state.exceptions import DesignStateError
from physgate.state.schema import validate_node

# A node payload is typed as the store's frozen interface types it: a plain JSON
# object, given its structure by the node schema, which validates it here.
from physgate.state.store import (
    JOURNAL_NAME,
    JournalLine,
    Payload,
    Store,
    journal_records_after,
)

_PROPOSAL = re.compile(r"^\.physgate/proposals/(?P<id>[a-z][a-z0-9_]*(\.[a-z0-9_]+)+)\.json$")


class ProposalRefusedError(Exception):
    """A proposal cannot be applied; the message is the reason an agent reads."""

    def __init__(self, message: str, subject: str) -> None:
        """Say why, and name the offending path or node."""
        super().__init__(message)
        self.subject = subject


def _fixed(store_root: Path) -> dict[str, tuple[str, str]]:
    """Every node's owner and kind, fixed at creation, from the canonical journal, read-only."""
    return {
        line.node_id: (str(line.payload["owner_role"]), str(line.payload["kind"]))
        for line in journal_records_after(store_root, 0)
    }


def read_proposals(
    repo: Path, base: str, commit: str, store_root: Path, *, git_dir: GitDir | None = None
) -> list[Payload]:
    """The whole-node proposals ``commit`` added or changed since ``base``, validated.

    ``git_dir`` is the repository's verified git directory, if the caller has one.

    Raises:
        ProposalRefusedError: a proposal is not a regular file, not JSON, not a whole
            node, named for another node, or changes a node's owner or kind.
    """
    fixed = _fixed(store_root)
    found: list[Payload] = []
    for change in changes_between(repo, base, commit, git_dir=git_dir):
        named = _PROPOSAL.match(change.path)
        if named is None or change.status == "D":
            continue
        if change.new_mode != "100644":
            raise ProposalRefusedError(f"{change.path} is not a regular file", change.path)
        # Read through the clean object store: the bytes the commit holds, whatever the
        # repository's own settings say.
        raw = git(repo, "show", f"{commit}:{change.path}", objects_only=True, git_dir=git_dir)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise ProposalRefusedError(f"{change.path} is not JSON", change.path) from None
        if not isinstance(payload, dict) or payload.get("id") != named["id"]:
            raise ProposalRefusedError(
                f"{change.path} is not one whole node named for its file", change.path
            )
        try:
            validate_node(payload)
        except (DesignStateError, ValueError) as exc:
            raise ProposalRefusedError(
                f"{change.path} is not a valid node: {exc}", change.path
            ) from None
        owner, kind = fixed.get(named["id"], (None, None))
        if owner is not None and payload["owner_role"] != owner:
            raise ProposalRefusedError(
                f"{change.path} changes the owner of {named['id']} from {owner!r}; owners are "
                "assigned at decomposition",
                named["id"],
            )
        if kind is not None and payload["kind"] != kind:
            raise ProposalRefusedError(
                f"{change.path} changes the kind of {named['id']} from {kind!r} to "
                f"{payload['kind']!r}; a node's kind is fixed when it is created, like its owner",
                named["id"],
            )
        found.append(payload)
    return sorted(found, key=lambda p: str(p["id"]))


#: The modes a script may have in the commit: a regular file, or an executable one.
_SCRIPT_MODES = frozenset({"100644", "100755"})


def _series_refusal(
    repo: Path, commit: str, series: SessionSeries | None, pinned: GitDir
) -> tuple[str, str] | None:
    """Why the session's series records refuse the attempt, and about which, or ``None``.

    A record the collector refused is the attempt's to fix, as a malformed proposal is. A
    sealed record must name a script the attempt committed with exactly the bytes collected:
    the script's git blob at the attempt commit, read through the clean object store, must be
    the blob id sealed when the session ended.
    """
    if series is None:
        return None
    if series.refused:
        shown = "; ".join(f"{e.name}: {e.reason}" for e in series.refused[:5])
        more = len(series.refused) - 5
        reason = "the session left series records that were refused: " + shown
        if more > 0:
            reason += f"; and {more} more"
        return reason, ",".join(sorted(e.name for e in series.refused))[:500]
    for record in series.records:
        listing = git(
            repo, "ls-tree", "-z", commit, "--", record.script, objects_only=True, git_dir=pinned
        )
        entry = listing.split("\0", 1)[0]
        meta, _, listed = entry.partition("\t")
        found = meta.split()
        # A regular file or an executable, by exactly the path the record names: git lists a
        # link as a blob too, whose bytes are its target, so the type alone would let a link
        # stand in for a script.
        if (
            len(found) != 3
            or found[0] not in _SCRIPT_MODES
            or found[1] != "blob"
            or listed != record.script
            or found[2] != record.script_blob
        ):
            reason = (
                f"the record {record.record_id} names the script {record.script}, and the attempt "
                "did not commit that script with the bytes the record was collected with"
            )
            return reason, record.record_id
    return None


class GitChangeChecker:
    """The change check before the gate: write scope, then every proposal pre-checked."""

    def __init__(self, run: RunGit, store_root: Path, module_dirs: dict[str, str]) -> None:
        """Check attempts of ``run`` against the canonical store at ``store_root``."""
        self._run = run
        self._store_root = store_root
        self._module_dirs = module_dirs

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
    ) -> ChangeCheck:
        """Refuse an attempt out of scope, with a refused series record, or a refused proposal.

        The order: what the attempt committed outside its scope; then its session's series
        records (one the collector refused, or one whose script is not the one committed);
        then its node proposals, against the store's own guards.
        """
        repo = self._run.repo
        # Verified once; the base, the scope check and the proposals all read through it.
        pinned = verified_git_dir(repo, linked=False)
        base = merge_base(repo, self._run.run_branch, attempt_commit, git_dir=pinned)
        outside = write_scope_violations(
            repo, base, attempt_commit, self._module_dirs[subtask_id], git_dir=pinned
        )
        scratch = self._run.run_dir / "scratch" / f"{subtask_id}-{attempt_commit[:12]}"
        if outside:
            reason = "the attempt changed paths outside its module: " + "; ".join(outside)
            subject = ",".join(sorted(v.split(" (", 1)[0] for v in outside))
            return ChangeCheck(
                refused_by="write_scope", reason=reason, subject=subject, graph_root=str(scratch)
            )
        refusal = _series_refusal(repo, attempt_commit, series, pinned)
        if refusal is not None:
            reason, subject = refusal
            return ChangeCheck(
                refused_by="series", reason=reason, subject=subject, graph_root=str(scratch)
            )
        proposed: tuple[str, ...] = ()
        try:
            proposals = read_proposals(repo, base, attempt_commit, self._store_root, git_dir=pinned)
            proposed = tuple(str(p["id"]) for p in proposals)
            self._precheck(scratch, proposals, role)
        except ProposalRefusedError as exc:
            return ChangeCheck(
                refused_by="proposal",
                reason=str(exc),
                subject=exc.subject,
                graph_root=str(scratch),
                proposed=proposed,
            )
        return ChangeCheck(refused_by=None, reason=None, graph_root=str(scratch), proposed=proposed)

    def _precheck(self, scratch: Path, proposals: list[Payload], role: str) -> None:
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
                    raise ProposalRefusedError(msg, str(payload["id"]))
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

    @property
    def root(self) -> Path:
        """The canonical store's directory."""
        return self._root

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

    def proposals(self, subtask_id: str, attempt_commit: str) -> list[Payload]:
        """The attempt's validated proposals, read from its commit."""
        repo = self._run.repo
        pinned = verified_git_dir(repo, linked=False)
        base = merge_base(repo, self._run.run_branch, attempt_commit, git_dir=pinned)
        return read_proposals(repo, base, attempt_commit, self._root, git_dir=pinned)

    def write(self, payload: Payload, role: str) -> int:
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
