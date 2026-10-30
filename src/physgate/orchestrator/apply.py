"""Node proposals, applied and never trusted, and the canonical store the loop holds.

An agent does not write the graph. It proposes a node as one whole-node JSON file
under ``.physgate/proposals/``, named for the node's id, and the hook layer checks
the file as it is written. Here the orchestrator:

- reads proposals **from the attempt commit**, never the working tree, and only
  the ones the attempt added or changed, as regular files;
- takes the acting role from the subtask's own plan line, never from the proposal;
- holds every proposal to the hook's rules, in the hook's order, so one the hook
  refused that reached the commit by a route the hook does not see (where the OS
  layer is absent, a shell command can still reach the proposals directory) is
  refused here for the reason the hook gave;
- refuses an owner change, which the store alone would accept from the current
  owner, because owners are assigned at decomposition and not by roles;
- refuses a kind change, for the same reason: a node's kind is fixed when it is
  created, and the relations the physics gate holds a node to follow from it (a
  module's declared mass is the sum of its parts), so rewriting the kind would
  let a node step out of a relation it failed;
- refuses a node of the ``cross`` domain from any role but the one the role
  register names as owning the cross nodes, and a node of a domain from that role
  (ARCH-051); a new interface node from any attempt, since interface nodes are
  written from the plan; and any node from the role that owns completion, whose
  one write is its declaration. The owners of each duty are counted in the register
  on every read: with no owner of the cross nodes no cross node is written, with two
  no node but an interface is, and with two owners of completion no node at all.
  The store holds none of these rules, so recorded runs and corpora written straight
  into a store replay as they were;
- refuses a quantity name that shadows one a relation reads, as the hook did when
  the file was written: a name the catalogue lacks that is a misspelling of a
  relation's quantity (within two insertions or deletions of a long quantity, one
  edit of a short one) is that quantity stepping out of the relation without saying so.
  Every other uncatalogued name is written, and the gate records it as
  unchecked. The store does not refuse such names, so a corpus written straight
  into one is unaffected;
- pre-checks **all** of an attempt's proposals against the store's own guards on
  a scratch copy of the graph built from the canonical journal, so an attempt is
  applied whole or not at all, and a refusal is a rejected attempt carrying the
  store's own reason.

The canonical store is held by one handle across steps (opening it re-derives
every node file). The journal's newest records are read without opening it, so
the loop can look for a line it never intended before a single byte is written.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterable
from pathlib import Path

from physgate import roles
from physgate.gate.catalogue import shadowing_names
from physgate.hooks.graph import (
    COMPLETION_OWNER_NODE,
    CROSS_DOMAIN,
    CROSS_NODE,
    INTERFACE_CREATION,
    INTERFACE_KIND,
    KIND_CHANGE,
    OWNER_CHANGE,
    SHADOWED_QUANTITY,
)
from physgate.hooks.journal_view import heads
from physgate.orchestrator import dispute as rules
from physgate.orchestrator.declaration import (
    DECLARATION_PATH,
    LINE_ENDS,
    MAX_BYTES,
    NOT_UTF8,
    TOO_LONG,
    Declaration,
    DeclarationError,
    parse,
)
from physgate.orchestrator.dispute import DISPUTES_DIR, Dispute, DisputeError, disputer_problem
from physgate.orchestrator.events import SessionEnded, read_events
from physgate.orchestrator.exceptions import DutyUnownedError, RoleRegisterError, StoreRefusalError
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
from physgate.series.consistency import check_proposals
from physgate.series.reader import SealedEntry, attempt_records
from physgate.series.seal import FORMAT, MAX_FILE_BYTES, SealedRecord, SessionSeries
from physgate.state.divergence import Divergence, Duties, divergence
from physgate.state.exceptions import DesignStateError
from physgate.state.protocol import (
    REJECT_CROSS_ROLE,
    REJECT_INTERFACE_IMMUTABLE,
    REJECT_MISSING_UNIT,
)
from physgate.state.schema import quantities_are_valid, validate_node, validate_node_id

# A node payload is typed as the store's frozen interface types it: a plain JSON
# object, given its structure by the node schema, which validates it here.
from physgate.state.store import (
    JOURNAL_NAME,
    JournalLine,
    Payload,
    Store,
    journal_records_after,
)
from physgate.state.vocabulary import nearest_quantity_names

#: The hook's name for a proposal that is not a whole, valid node named for its file.
INVALID = "invalid"

_PROPOSAL = re.compile(r"^\.physgate/proposals/(?P<id>[a-z][a-z0-9_]*(\.[a-z0-9_]+)+)\.json$")


class ProposalRefusedError(Exception):
    """A proposal cannot be applied; the message is the reason an agent reads."""

    def __init__(self, message: str, subject: str, reason: str) -> None:
        """Say why, name the offending path or node, and name the reason.

        ``reason`` is the name the hook gives the same refusal when the proposal is
        written (``invalid``, ``kind_change``, ``cross_node``...), or the store's own
        reason for a refusal its guards make.
        """
        super().__init__(message)
        self.subject = subject
        self.reason = reason


def _fixed(store_root: Path) -> dict[str, tuple[str, str]]:
    """Every node's owner and kind, fixed at creation, from the canonical journal, read-only."""
    return {
        line.node_id: (str(line.payload["owner_role"]), str(line.payload["kind"]))
        for line in journal_records_after(store_root, 0)
    }


#: A node's owner and kind as the graph fixed them when it was created; ``None`` for a node
#: the proposal would create.
_Fixed = tuple[str, str] | None
#: A refusal's reason, and what it says after the proposal's path; ``None`` for no refusal.
_Refusal = tuple[str, str] | None


def _owner_is_the_attempt_s_role(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """The store's rule: a new node names the attempt's role as owner, an existing one is its."""
    owner = fixed[0] if fixed is not None else payload.get("owner_role")
    if owner == role:
        return None
    node_id = payload.get("id")
    if fixed is None:
        said = f"names {owner!r} as its owner, and a new node names the attempt's role, {role}"
    else:
        said = (
            f"would write {node_id}, which the {owner} role owns, in an attempt of the {role} role"
        )
    return REJECT_CROSS_ROLE, f"is refused ({REJECT_CROSS_ROLE}): it {said}"


def _owner_does_not_change(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """A role does not hand its node to another: owners are assigned at decomposition."""
    if fixed is None or payload.get("owner_role") == fixed[0]:
        return None
    return OWNER_CHANGE, (
        f"is refused ({OWNER_CHANGE}): it changes the owner of {payload.get('id')} from "
        f"{fixed[0]!r}; owners are assigned at decomposition"
    )


def _kind_does_not_change(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """A node keeps the kind it was created with: the relations the gate holds follow from it."""
    if fixed is None or payload.get("kind") == fixed[1]:
        return None
    return KIND_CHANGE, (
        f"is refused ({KIND_CHANGE}): it changes the kind of {payload.get('id')} from "
        f"{fixed[1]!r} to {payload.get('kind')!r}; a node's kind is fixed when it is created, "
        "like its owner"
    )


def _cross_nodes_are_their_owner_s_alone(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """A cross node is written by the owner of the cross nodes, and that owner writes no other.

    The owners are the roles the register names as owning the cross nodes, counted on every
    read. With no owner, no cross node is written; with two, no node is, since whose the
    cross nodes are cannot be told. Interface nodes are left to the rules that fix them.
    The rules before this one have made the node's owner the attempt's role and kept its
    kind.
    """
    if payload.get("kind") == INTERFACE_KIND:
        return None
    node_id, writer = payload.get("id"), payload.get("owner_role")
    cross = payload.get("domain") == CROSS_DOMAIN
    owners = roles.owners_of("cross_nodes")
    if len(owners) > 1:
        return CROSS_NODE, (
            f"is refused ({CROSS_NODE}): the role register names more than one owner of the "
            f"cross nodes ({','.join(owners)}), so whose they are cannot be told, and "
            f"{node_id} is not written while it does"
        )
    if not owners:
        if not cross:
            return None
        return CROSS_NODE, (
            f"is refused ({CROSS_NODE}): {node_id} is of the cross domain, and no registered "
            "role owns the cross nodes, so no attempt writes one"
        )
    (owner,) = owners
    if cross and writer != owner:
        return CROSS_NODE, (
            f"is refused ({CROSS_NODE}): {node_id} is of the cross domain, whose quantities tie "
            f"domains together; only the {owner} role writes them, and this node is the "
            f"{writer} role's"
        )
    if not cross and writer == owner:
        return CROSS_NODE, (
            f"is refused ({CROSS_NODE}): {node_id} is of the {payload.get('domain')} domain; "
            f"the {owner} role owns the cross nodes and writes no node of a domain"
        )
    return None


def _no_attempt_creates_an_interface(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """No attempt creates an interface node: interface nodes are written from the plan."""
    if fixed is not None or payload.get("kind") != INTERFACE_KIND:
        return None
    return INTERFACE_CREATION, (
        f"is refused ({INTERFACE_CREATION}): {payload.get('id')} would be a new interface node; "
        "interface nodes are written from the plan when the task is decomposed, never by an "
        "attempt"
    )


def _the_completion_owner_writes_no_node(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """The role that owns completion writes no node: its one write is the declaration.

    Found in the register by what it owns, counted on every read. With two owners no node
    is written, as with the cross nodes; with none, no role is held by this rule.
    """
    node_id, writer = payload.get("id"), payload.get("owner_role")
    owners = roles.owners_of("completion")
    if len(owners) > 1:
        return COMPLETION_OWNER_NODE, (
            f"is refused ({COMPLETION_OWNER_NODE}): the role register names more than one owner "
            f"of completion ({','.join(owners)}), so which role may write no node cannot be "
            f"told, and {node_id} is not written while it does"
        )
    if writer not in owners:
        return None
    return COMPLETION_OWNER_NODE, (
        f"is refused ({COMPLETION_OWNER_NODE}): the {writer} role owns the completion "
        f"declaration, which is its one write; it writes no node of the graph, and {node_id} "
        "would be one"
    )


def _an_interface_is_not_rewritten(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """The store's own rule: an interface node is fixed at decomposition."""
    if fixed is None or fixed[1] != INTERFACE_KIND:
        return None
    return REJECT_INTERFACE_IMMUTABLE, (
        f"is refused ({REJECT_INTERFACE_IMMUTABLE}): {payload.get('id')} is an interface node, "
        "fixed at decomposition"
    )


#: Checked in the order the hook checks a proposal as it is written, so a proposal with
#: two faults is refused here for the reason the hook gave the session: the store's
#: ownership, the owner and the kind kept, the cross nodes, no new interface, the owner of
#: completion, and an existing interface left alone.
_OWNERSHIP_RULES = (
    _owner_is_the_attempt_s_role,
    _owner_does_not_change,
    _kind_does_not_change,
    _cross_nodes_are_their_owner_s_alone,
    _no_attempt_creates_an_interface,
    _the_completion_owner_writes_no_node,
    _an_interface_is_not_rewritten,
)


def _ownership_refusal(payload: Payload, fixed: _Fixed, role: str) -> _Refusal:
    """The first ownership rule ``payload`` breaks in a ``role`` attempt, or ``None``."""
    for rule in _OWNERSHIP_RULES:
        refused = rule(payload, fixed, role)
        if refused is not None:
            return refused
    return None


def _content_refusal(payload: Payload, path: str) -> None:
    """Refuse a malformed quantity, then a shadowing name, then any other invalid field.

    The hook's order after ownership: a quantity that is not a value with a unit, a source
    and a writer; a name that shadows a relation's quantity; the node as a whole.

    Raises:
        ProposalRefusedError: the first of these ``payload`` breaks.
    """
    try:
        validate_node(payload)
        problem = None
    except (DesignStateError, ValueError) as exc:
        problem = f"{path} is not a valid node: {exc}"
    if problem is not None and not quantities_are_valid(payload):
        raise ProposalRefusedError(problem, path, REJECT_MISSING_UNIT)
    shadowed = shadowing_names(payload.get("quantities") or {})
    if shadowed:
        told = "; ".join(
            f"{name} shadows {relation} (nearest {', '.join(nearest_quantity_names(name))})"
            for name, relation in shadowed
        )
        raise ProposalRefusedError(
            f"{path} names a quantity the gate's catalogue does not know under a name a "
            f"relation reads ({told}); a quantity a relation reads is written under the "
            "catalogue's name, so that the relation applies to it",
            str(payload["id"]),
            SHADOWED_QUANTITY,
        )
    if problem is not None:
        raise ProposalRefusedError(problem, path, INVALID)


def read_proposals(
    repo: Path,
    base: str,
    commit: str,
    store_root: Path,
    *,
    role: str,
    git_dir: GitDir | None = None,
) -> list[Payload]:
    """The whole-node proposals ``commit`` added or changed since ``base``, validated.

    ``role`` is the role the plan gave the subtask whose attempt made ``commit``, never
    one a proposal names. ``git_dir`` is the repository's verified git directory, if the
    caller has one.

    Each proposal is held to the hook's rules, in the hook's order, so a proposal the
    hook refused, and that reached the commit by a route the hook does not see, is
    refused here for the same reason.

    Raises:
        ProposalRefusedError: a proposal is not a regular file, not JSON, not a whole
            node, named for another node, written for another role, changes a node's
            owner or kind, is a cross node not written by the owner of the cross nodes or
            a domain node written by it, creates an interface node, is written by the
            owner of completion, rewrites an interface node, or is not a valid node.
    """
    fixed = _fixed(store_root)
    found: list[Payload] = []
    for change in changes_between(repo, base, commit, git_dir=git_dir):
        named = _PROPOSAL.fullmatch(change.path)
        if named is None or change.status == "D":
            continue
        if change.new_mode != "100644":
            raise ProposalRefusedError(f"{change.path} is not a regular file", change.path, INVALID)
        # Read through the clean object store: the bytes the commit holds, whatever the
        # repository's own settings say.
        raw = git(repo, "show", f"{commit}:{change.path}", objects_only=True, git_dir=git_dir)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise ProposalRefusedError(f"{change.path} is not JSON", change.path, INVALID) from None
        if not isinstance(payload, dict) or payload.get("id") != named["id"]:
            raise ProposalRefusedError(
                f"{change.path} is not one whole node named for its file", change.path, INVALID
            )
        try:
            validate_node_id(payload["id"])
        except DesignStateError as exc:
            raise ProposalRefusedError(
                f"{change.path} is not a valid node: {exc}", change.path, INVALID
            ) from None
        refused = _ownership_refusal(payload, fixed.get(named["id"]), role)
        if refused is not None:
            reason, said = refused
            raise ProposalRefusedError(f"{change.path} {said}", named["id"], reason)
        _content_refusal(payload, change.path)
        found.append(payload)
    return sorted(found, key=lambda p: str(p["id"]))


#: The modes a script may have in the commit: a regular file, or an executable one.
_SCRIPT_MODES = frozenset({"100644", "100755"})


def _committed_records(repo: Path, base: str, commit: str, pinned: GitDir) -> list[str]:
    """Every path the attempt committed that holds a series record, read from the commit.

    A record leaves the worktree before the commit, so one in a commit was put where records
    do not go: a copy beside the module, or a record a process wrote after collection. A
    record is a JSON object carrying the format marker; a file named ``*.json`` (in any case)
    is read, through the clean object store, only when it is no larger than a record may be.
    Bytes that are not UTF-8 JSON are not a record, and are the write scope's to judge.
    """
    found: list[str] = []
    for change in changes_between(repo, base, commit, git_dir=pinned):
        if change.status == "D" or change.new_mode not in _SCRIPT_MODES:
            continue
        if not change.path.casefold().endswith(".json"):
            continue
        spec = f"{commit}:{change.path}"
        size = int(git(repo, "cat-file", "-s", spec, objects_only=True, git_dir=pinned))
        if size > MAX_FILE_BYTES:
            continue
        try:
            raw = git(repo, "cat-file", "blob", spec, objects_only=True, git_dir=pinned)
            parsed = json.loads(raw)
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
        if isinstance(parsed, dict) and parsed.get("format") == FORMAT:
            found.append(change.path)
    return found


def _committed_as(repo: Path, commit: str, path: str, blob: str, pinned: GitDir) -> bool:
    """Whether ``commit`` holds a regular file at exactly ``path`` with the blob ``blob``."""
    listing = git(repo, "ls-tree", "-z", commit, "--", path, objects_only=True, git_dir=pinned)
    entry = listing.split("\0", 1)[0]
    meta, _, listed = entry.partition("\t")
    found = meta.split()
    # A regular file or an executable, by exactly the path named: git lists a link as a blob
    # too, whose bytes are its target, so the type alone would let a link stand in for code.
    return (
        len(found) == 3
        and found[0] in _SCRIPT_MODES
        and found[1] == "blob"
        and listed == path
        and found[2] == blob
    )


def _series_refusal(
    repo: Path,
    commit: str,
    series: SessionSeries | None,
    pinned: GitDir,
    earlier: Iterable[SealedRecord] = (),
) -> tuple[str, str] | None:
    """Why the attempt's series records refuse it, and about which, or ``None``.

    A record the collector refused in the session that completed the attempt is the attempt's
    to fix, as a malformed proposal is. Every record the attempt sealed, in that session or in
    an earlier one that ended for infrastructure (``earlier``), must name code the attempt
    committed with exactly the bytes collected: the script, and every other file of code the
    producing process loaded, each at its path in the attempt commit, read through the clean
    object store, with the blob id sealed when its session ended.
    """
    if series is not None and series.refused:
        shown = "; ".join(f"{e.name}: {e.reason}" for e in series.refused[:5])
        more = len(series.refused) - 5
        reason = "the session left series records that were refused: " + shown
        if more > 0:
            reason += f"; and {more} more"
        return reason, ",".join(sorted(e.name for e in series.refused))[:500]
    records = {(r.record_id, r.sha256): r for r in (*(series.records if series else ()), *earlier)}
    held: dict[tuple[str, str], bool] = {}
    for key in sorted(records):
        record = records[key]
        if not _held(held, repo, commit, record.script, record.script_blob, pinned):
            reason = (
                f"the record {record.record_id} names the script {record.script}, and the attempt "
                "did not commit that script with the bytes the record was collected with"
            )
            return reason, record.record_id
        for code in record.loaded:
            if not _held(held, repo, commit, code.path, code.blob, pinned):
                reason = (
                    f"the record {record.record_id} names {code.path} as code its script loaded, "
                    "and the attempt did not commit that file with the bytes the record was "
                    "collected with; code the attempt does not commit cannot stand behind a curve"
                )
                return reason, record.record_id
    return None


def _held(
    held: dict[tuple[str, str], bool],
    repo: Path,
    commit: str,
    path: str,
    blob: str,
    pinned: GitDir,
) -> bool:
    """:func:`_committed_as`, asked of git once per path and blob."""
    if (path, blob) not in held:
        held[(path, blob)] = _committed_as(repo, commit, path, blob, pinned)
    return held[(path, blob)]


def _blob_id(data: bytes, length: int) -> str:
    """The id git gives ``data`` as a blob, in the object format whose ids are ``length`` long."""
    digest = hashlib.sha1 if length == 40 else hashlib.sha256  # noqa: S324 - git's own id
    return digest(b"blob %d\0" % len(data) + data).hexdigest()


def declares_completion(role: str) -> bool:
    """Whether ``role`` is the one role the register names as owning completion, asked now.

    Never while the register names none, or two: no attempt's declaration is then admitted.
    """
    try:
        return roles.owner_of("completion") == role
    except (DutyUnownedError, RoleRegisterError):
        return False


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

        The order: what the attempt committed outside its scope; then, for an attempt of the role
        that owns completion, its declaration, read from the commit; then its series records (one
        the collector refused, or one, from any session of the attempt, whose script or loaded
        code is not what was committed); then its node proposals, against the store's own
        guards; last, every quantity that names a record, against that record.
        """
        repo = self._run.repo
        # Verified once; the base, the scope check and the proposals all read through it.
        pinned = verified_git_dir(repo, linked=False)
        base = merge_base(repo, self._run.run_branch, attempt_commit, git_dir=pinned)
        declares = declares_completion(role)
        module_dir = self._module_dirs[subtask_id]
        disputes = disputer_problem(role) is None
        outside = write_scope_violations(
            repo,
            base,
            attempt_commit,
            module_dir,
            declares=declares,
            disputes=disputes,
            git_dir=pinned,
        )
        scratch = self._run.run_dir / "scratch" / f"{subtask_id}-{attempt_commit[:12]}"
        if outside:
            reason = "the attempt changed paths outside its module: " + "; ".join(outside)
            subject = ",".join(sorted(v.split(" (", 1)[0] for v in outside))
            return ChangeCheck(
                refused_by="write_scope", reason=reason, subject=subject, graph_root=str(scratch)
            )
        try:
            declared = self._declaration(attempt_commit, subtask_id, pinned) if declares else None
        except DeclarationError as exc:
            return ChangeCheck(
                refused_by="declaration",
                reason=f"{DECLARATION_PATH}: {exc}",
                subject=DECLARATION_PATH,
                graph_root=str(scratch),
            )
        try:
            disputed = self._disputes(base, attempt_commit, role, pinned) if disputes else ()
        except DisputeError as exc:
            path = str(exc.args[1])
            return ChangeCheck(
                refused_by="dispute",
                reason=f"{path}: {exc.args[0]}",
                subject=path,
                graph_root=str(scratch),
            )
        committed = _committed_records(repo, base, attempt_commit, pinned)
        if committed:
            reason = (
                f"a series record is committed at {', '.join(committed)}; records are written "
                "into .physgate/series/ by the script that ran, and collected from there before "
                "the commit, never committed"
            )
            return ChangeCheck(
                refused_by="series",
                reason=reason,
                subject=",".join(committed)[:500],
                graph_root=str(scratch),
            )
        sealed = self._attempt_records(subtask_id, attempt_commit)
        earlier = tuple(entry.record for entry in sealed)
        refusal = _series_refusal(repo, attempt_commit, series, pinned, earlier)
        if refusal is not None:
            reason, subject = refusal
            return ChangeCheck(
                refused_by="series", reason=reason, subject=subject, graph_root=str(scratch)
            )
        proposed: tuple[str, ...] = ()
        try:
            proposals = read_proposals(
                repo, base, attempt_commit, self._store_root, role=role, git_dir=pinned
            )
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
        # Last, once the store's own guards have passed: every proposed quantity that names a
        # simulation record is held to the record this attempt sealed.
        checks = check_proposals(proposals, sealed, self._run.run_dir)
        failed = [c for c in checks if c.outcome != "agrees"]
        if failed:
            reason = "; ".join(c.reason for c in failed[:3] if c.reason)
            if len(failed) > 3:
                reason += f"; and {len(failed) - 3} more"
            subject = ",".join(sorted({f"{c.node_id}.{c.quantity}" for c in failed}))
            return ChangeCheck(
                refused_by="series",
                reason=reason,
                subject=subject[:500],
                graph_root=str(scratch),
                proposed=proposed,
                series_checks=checks,
            )
        return ChangeCheck(
            refused_by=None,
            reason=None,
            graph_root=str(scratch),
            proposed=proposed,
            series_checks=checks,
            declaration=declared,
            disputes=disputed,
        )

    def _disputes(self, base: str, commit: str, role: str, pinned: GitDir) -> tuple[Dispute, ...]:
        """Every dispute ``commit`` added or changed since ``base``, read and parsed, sorted.

        Raises:
            DisputeError: one is not a dispute; its message, then its path.
        """
        repo = self._run.repo
        graph = {node_id: head[2] for node_id, head in heads(str(self._store_root)).items()}
        found: list[Dispute] = []
        for change in changes_between(repo, base, commit, git_dir=pinned):
            if change.status == "D" or not change.path.startswith(DISPUTES_DIR + "/"):
                continue
            listing = git(
                repo,
                "ls-tree",
                "-l",
                "-z",
                commit,
                "--",
                change.path,
                objects_only=True,
                git_dir=pinned,
            )
            _, _, blob, size = listing.partition("\t")[0].split()
            try:
                if int(size) > rules.MAX_BYTES:
                    raise DisputeError(rules.TOO_LONG.format(cap=rules.MAX_BYTES, size=size))
                try:
                    text = git(repo, "cat-file", "blob", blob, objects_only=True, git_dir=pinned)
                except UnicodeDecodeError:
                    raise DisputeError(rules.NOT_UTF8) from None
                data = text.encode()
                if _blob_id(data, len(blob)) != blob:
                    raise DisputeError(rules.LINE_ENDS)
                found.append(rules.parse(change.path, data, role, graph))
            except DisputeError as exc:
                raise DisputeError(str(exc), change.path) from None
        return tuple(sorted(found, key=lambda d: (d.position.node_id, d.position.name)))

    def declaration_at(self, commit: str, declaring: str) -> Declaration | None:
        """The completion declaration ``commit`` holds, read and parsed as :meth:`check` reads one.

        Raises:
            DeclarationError: what the commit holds there is not a declaration.
        """
        return self._declaration(commit, declaring, verified_git_dir(self._run.repo, linked=False))

    def _declaration(self, commit: str, declaring: str, pinned: GitDir) -> Declaration | None:
        """The declaration ``commit`` holds, read through the clean object store; ``None`` if none.

        Its bytes are held to the blob the commit names, so the digest is of the committed bytes.
        """
        repo = self._run.repo
        listing = git(
            repo,
            "ls-tree",
            "-l",
            "-z",
            commit,
            "--",
            DECLARATION_PATH,
            objects_only=True,
            git_dir=pinned,
        )
        if not listing:
            return None
        meta, _, path = listing.split("\0", 1)[0].partition("\t")
        found = meta.split()
        if len(found) != 4 or found[:2] != ["100644", "blob"] or path != DECLARATION_PATH:
            raise DeclarationError("the completion declaration is not a regular file")
        if int(found[3]) > MAX_BYTES:
            raise DeclarationError(TOO_LONG.format(cap=MAX_BYTES, size=found[3]))
        try:
            text = git(repo, "cat-file", "blob", found[2], objects_only=True, git_dir=pinned)
        except UnicodeDecodeError:
            raise DeclarationError(NOT_UTF8) from None
        data = text.encode()
        blob = (hashlib.sha1 if len(found[2]) == 40 else hashlib.sha256)(  # noqa: S324 - git's id
            b"blob %d\0" % len(data) + data
        )
        if blob.hexdigest() != found[2]:
            raise DeclarationError(LINE_ENDS)
        return parse(data, self._module_dirs, declaring)

    def _attempt_records(self, subtask_id: str, attempt_commit: str) -> tuple[SealedEntry, ...]:
        """The records the attempt that made ``attempt_commit`` sealed, read from the run's log.

        The attempt is the one whose session ended with this commit; a log that names no such
        session, or more than one attempt, gives no records, so a quantity naming one is
        refused as unsealed rather than read off another attempt's.
        """
        log = self._run.run_dir / "events.jsonl"
        if not log.exists():
            return ()
        events = read_events(log)
        attempts = {
            e.attempt
            for e in events
            if isinstance(e, SessionEnded)
            and e.subtask_id == subtask_id
            and e.attempt_commit == attempt_commit
        }
        if len(attempts) != 1:
            return ()
        return attempt_records(events, subtask_id, attempts.pop())

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
                    raise ProposalRefusedError(msg, str(payload["id"]), str(result.reason))
        finally:
            store.close()


def _duties() -> Duties:
    """Who owns each cross-cutting duty, as the role register answers now."""
    return Duties(
        cross_nodes=roles.owners_of("cross_nodes"), completion=roles.owners_of("completion")
    )


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

    def proposals(self, subtask_id: str, attempt_commit: str, role: str) -> list[Payload]:
        """The attempt's validated proposals, read from its commit under the plan's ``role``."""
        repo = self._run.repo
        pinned = verified_git_dir(repo, linked=False)
        base = merge_base(repo, self._run.run_branch, attempt_commit, git_dir=pinned)
        return read_proposals(repo, base, attempt_commit, self._root, role=role, git_dir=pinned)

    def write(self, payload: Payload, role: str) -> int:
        """Write one node; a refusal after a clean pre-check raises."""
        result = self._handle().write_node(payload, role)
        if not result.accepted or result.revision is None:
            msg = "the store refused a write the pre-check had accepted"
            raise StoreRefusalError(msg, node=str(payload.get("id")), reason=str(result.reason))
        return result.revision

    def divergences(self, since: int, acting_role: str) -> tuple[Divergence, ...]:
        """Every node changed after ``since`` by a role that does not own it, or against a duty.

        The duties' owners are asked of the role register now, as the hook and the apply
        step ask it.
        """
        store = self._handle()
        return tuple(divergence(store, store.diff(since), acting_role, _duties()))

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
