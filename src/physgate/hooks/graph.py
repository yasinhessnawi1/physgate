"""How an agent's node reaches the graph: a proposal file, checked as it is written.

No agent tool writes the graph store. Its journal is the only authority, and a
line appended to it is replayed as genuine, so the store's whole directory is a
protected path. An agent proposes a node instead, by writing the whole node as
``.physgate/proposals/<node id>.json`` in its worktree with the Write or Edit
tool. The orchestrator applies proposals at merge, from the committed file,
under the role it recorded when it dispatched the subtask; the store's own
guards run then as a second line, with a role the session could not choose.

This hook is the first line, and it asks the store's questions in the store's
order, so a refused proposal is refused for the reason the store would give:

1. the identifier is a legal one, and the file is named after it;
2. the session's role may write the node: a new node must name the session's
   role as its owner, and an existing node must already be owned by it and keep
   that owner. The store would let the owner hand a node on; this hook does
   not, because owners are assigned at decomposition, not by roles. A node
   keeps its kind as it keeps its owner;
3. a node of the ``cross`` domain is written by the role that owns the cross
   nodes, and that role writes no node of a domain. These are the quantities
   that tie domains together, and ARCH-051 gives them one writer. Interface
   nodes are not held to this: they are of the cross domain and owned by the
   role that produces them;
4. no session creates an interface node. Interface nodes are written from the
   plan when the task is decomposed; a session that could create one could put
   a shared quantity on a node of its own that the rule before exempts;
5. an existing interface node is not written at all;
6. every quantity is a value with a unit, a source and a writer — a bare number
   is refused here, with the schema's own message;
7. no quantity's name shadows one a relation reads: a name the catalogue lacks
   that is a misspelling of a relation's quantity (``stall_currnt``,
   ``currentlimit``, ``supported_mas``: within two insertions or deletions of a
   quantity longer than five characters, underscores ignored; ``mess``, ``moss``,
   ``mask``: within one edit of a short one, ``mass``) is the way a writer steps
   out of the headroom relation, or the mass sum, without saying so. A different
   name (``idle_current``, ``motor_current_draw``, ``max``, ``dry_mass``) is not
   refused. Every other
   uncatalogued name is written, and the gate records it as unchecked. This rule
   is the hook's and the orchestrator's, not the store's: a corpus written
   straight into a store is unaffected;
8. the node as a whole is valid.

The current owner and kind come from the journal, read without opening the
store. The ownership rules (2 to 4) are a list, so a rule the architecture adds
later is one more entry rather than a new branch. Rules 3 and 4 are the hook's
and the orchestrator's, not the store's: recorded runs and corpora written
straight into a store replay as they were.

Only the Write and Edit tools carry a proposal's content, so only they can be
checked before the file exists. A command that names the proposals directory, or
a directory above it, is refused here unless it only reads. A command can reach
the directory without naming it, though: by a path it builds as it runs, or by
copying or moving a directory of its own into place. This hook cannot see those,
and the OS layer is what refuses them: it write-denies the proposals directory to
every shell command (``physgate.oslayer.policy``). Where the OS layer does not
run, they are the residual of this text check, as every path built at run time is.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from physgate.hooks.journal_view import heads
from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.shell import ShellSyntaxError, parse, unwrap
from physgate.hooks.shell_paths import _WRITE_REDIRECTS, _candidates, _expand, _only_reads

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from physgate.hooks.journal_view import Head
    from physgate.hooks.views import ConfigView, InputView

    #: A rule returns (reason, detail) for a proposal it refuses, or None.
    OwnershipRule = Callable[[dict[str, Any], Head | None, ConfigView], tuple[str, str] | None]

# The graph's schema and the store's reasons are imported inside the functions
# that need them: they load the validation library, and this module is on every
# hook's hot path while a proposal is written rarely.

#: Where proposals live, relative to the worktree. The orchestrator reads them from here.
PROPOSALS_DIR = os.path.join(".physgate", "proposals")

REFUSED = "This node proposal is refused ({reason}): {detail}"
NOT_JSON = "a proposal is one whole node as a JSON object"
MISNAMED = "a proposal file is named after the node it proposes: {name} holds {node_id}"
NOTEBOOK = "a proposal is a JSON file, not a notebook"
SHELL_WRITE = (
    "Node proposals are written with the Write or Edit tool, so that the node can be checked "
    "before the file exists. A shell command may read a proposal only with a recognised "
    "read-only program (cat, head, grep, ls and the like, or git diff/log/show); any other "
    "command that names a proposal path is refused, whether or not it would in fact only read."
)
UNLOCATED = (
    "This edit to a node proposal is refused: its old text occurs {found} times in the file "
    "as this hook reads it, so what the edit would leave cannot be checked. Give old text "
    "that occurs exactly once, character for character, or write the whole proposal with "
    "the Write tool."
)
UNCHECKABLE = (
    "This command could not be split into the commands it would run ({detail}), so whether it "
    "writes a node proposal cannot be checked, and it is refused."
)

#: Not one of the store's reasons: the store accepts this write, and the hook
#: is stricter on purpose (see ``_owner_does_not_change``).
OWNER_CHANGE = "owner_change"
#: Not one of the store's reasons either (see ``_kind_does_not_change``).
KIND_CHANGE = "kind_change"
#: Not one of the store's reasons: a quantity name that shadows one a relation reads.
SHADOWED_QUANTITY = "shadowed_quantity"
#: Not one of the store's reasons: a cross node by a role that does not own the cross
#: nodes, or a domain node by the role that does (see ``_cross_nodes_are_their_owners_alone``).
CROSS_NODE = "cross_node"
#: Not one of the store's reasons: a session creating an interface node.
INTERFACE_CREATION = "interface_creation"

#: The domain of the quantities that tie domains together (``state.schema.DomainKind``).
CROSS_DOMAIN = "cross"
#: The kind of node a plan fixes between modules (``state.schema.NodeKind``).
INTERFACE_KIND = "interface"


def _owner_is_the_session(
    proposal: dict[str, Any], current: Head | None, config: ConfigView
) -> tuple[str, str] | None:
    """The store's rule: a new node names the writer as owner; an existing one is owned by it."""
    owner = current[2].get("owner_role") if current is not None else proposal.get("owner_role")
    if owner == config.role:
        return None
    node_id = str(proposal.get("id"))
    if current is None:
        detail = f"a new node must name this session's role, {config.role}, as its owner"
    else:
        detail = (
            f"{node_id} is owned by the {owner} role, and this session is the {config.role} role"
        )
    from physgate.state.exceptions import CrossRoleWriteError
    from physgate.state.protocol import REJECT_CROSS_ROLE

    refusal = CrossRoleWriteError(detail, node_id=node_id, owner=str(owner), role=str(config.role))
    return REJECT_CROSS_ROLE, str(refusal)


def _owner_does_not_change(
    proposal: dict[str, Any], current: Head | None, config: ConfigView
) -> tuple[str, str] | None:
    """A role does not hand its node to another role.

    Stricter than the store, which lets the current owner name a new one. Owners
    are assigned when the orchestrator decomposes the task, not by the roles
    that own the nodes, so a proposal that changes an owner is refused here and
    the orchestrator refuses it again when it applies proposals.
    """
    if current is None:
        return None
    was, now = current[2].get("owner_role"), proposal.get("owner_role")
    if now == was:
        return None
    return OWNER_CHANGE, (
        f"{proposal.get('id')} is owned by the {was} role, and this proposal would make it the "
        f"{now} role's; owners are assigned when the task is decomposed, not by the roles"
    )


def _kind_does_not_change(
    proposal: dict[str, Any], current: Head | None, config: ConfigView
) -> tuple[str, str] | None:
    """A node keeps the kind it was created with, as it keeps its owner.

    The store accepts a kind change from the owner. The physics gate holds a node
    to relations that follow from its kind (a module's declared mass is the sum
    of its parts'), so a node rewritten under another kind would step out of a
    relation it failed. Refused here, and again when the orchestrator applies
    proposals.
    """
    if current is None:
        return None
    was, now = current[2].get("kind"), proposal.get("kind")
    if now == was:
        return None
    return KIND_CHANGE, (
        f"{proposal.get('id')} was created as a {was}, and this proposal would make it a "
        f"{now}; a node's kind is fixed when it is created, like its owner"
    )


def _cross_nodes_are_their_owners_alone(
    proposal: dict[str, Any], current: Head | None, config: ConfigView
) -> tuple[str, str] | None:
    """A cross node is written by the owner of the cross nodes, and that owner writes no other.

    The owner is the role the register names as owning the cross nodes, found by
    what it owns and never by its name. While the register names none, a cross node
    has no writer and every session is refused one. While it names two, whose the
    cross nodes are cannot be told, so no node but an interface is written: the
    check fails closed rather than pick one. Interface nodes are left to the rules
    that fix them. By the time this runs the node's owner is the session's role and
    its kind is the one it was created with, so a node's owner and the domain it
    would have decide.
    """
    if proposal.get("kind") == INTERFACE_KIND:
        return None
    from physgate.orchestrator.exceptions import DutyUnownedError, RoleRegisterError
    from physgate.roles import owner_of

    node_id, role = proposal.get("id"), proposal.get("owner_role")
    cross = proposal.get("domain") == CROSS_DOMAIN
    try:
        owner = owner_of("cross_nodes")
    except DutyUnownedError:
        if not cross:
            return None
        return CROSS_NODE, (
            f"{node_id} is of the cross domain, and no registered role owns the cross nodes, "
            "so no session writes one"
        )
    except RoleRegisterError as exc:
        return CROSS_NODE, (
            f"the role register names more than one owner of the cross nodes "
            f"({exc.context.get('owners')}), so whose they are cannot be told, and {node_id} "
            "is not written while it does"
        )
    if cross and role != owner:
        return CROSS_NODE, (
            f"{node_id} is of the cross domain, whose quantities tie domains together; only "
            f"the {owner} role writes them, and this node is the {role} role's"
        )
    if not cross and role == owner:
        return CROSS_NODE, (
            f"{node_id} is of the {proposal.get('domain')} domain; the {owner} role owns the "
            "cross nodes and writes no node of a domain"
        )
    return None


def _no_session_creates_an_interface(
    proposal: dict[str, Any], current: Head | None, config: ConfigView
) -> tuple[str, str] | None:
    """A session does not create an interface node, whatever its role.

    Interface nodes are written from the plan when the task is decomposed, and are
    fixed from then on. One a session created would be a node of its own that the
    cross rule exempts, on which it could write a quantity other domains depend on.
    An existing node turned into an interface is a kind change, refused before this.
    """
    if current is not None or proposal.get("kind") != INTERFACE_KIND:
        return None
    return INTERFACE_CREATION, (
        f"{proposal.get('id')} would be a new interface node; interface nodes are written "
        "from the plan when the task is decomposed, never by a session"
    )


#: Checked in order; the first to object refuses the proposal.
OWNERSHIP_RULES: tuple[OwnershipRule, ...] = (
    _owner_is_the_session,
    _owner_does_not_change,
    _kind_does_not_change,
    _cross_nodes_are_their_owners_alone,
    _no_session_creates_an_interface,
)


def _check(proposal: object, file_stem: str, config: ConfigView) -> tuple[str, str] | None:
    """(the store's reason, the detail) for a proposal that is refused, or None."""
    from pydantic import ValidationError

    from physgate.state.exceptions import (
        DesignStateError,
        InterfaceImmutableError,
        MissingUnitError,
    )
    from physgate.state.protocol import REJECT_INTERFACE_IMMUTABLE, REJECT_MISSING_UNIT
    from physgate.state.schema import quantities_are_valid, validate_node, validate_node_id

    if not isinstance(proposal, dict):
        return "invalid", NOT_JSON
    try:
        node_id = validate_node_id(proposal.get("id"))
    except DesignStateError as exc:
        return "invalid", str(exc)
    if node_id != file_stem:
        return "invalid", MISNAMED.format(name=f"{file_stem}.json", node_id=node_id)
    current = heads(config.store_root).get(node_id) if config.store_root else None
    for rule in OWNERSHIP_RULES:
        objection = rule(proposal, current, config)
        if objection is not None:
            return objection
    if current is not None and current[2].get("kind") == "interface":
        immutable = InterfaceImmutableError(
            f"{node_id} is an interface node, fixed at decomposition", node_id=node_id
        )
        return REJECT_INTERFACE_IMMUTABLE, str(immutable)
    if not quantities_are_valid(proposal):
        refusal = MissingUnitError(
            "every quantity is a value with a unit, a source and the role that wrote it; "
            + _quantity_problems(proposal),
            node_id=node_id,
        )
        return REJECT_MISSING_UNIT, str(refusal)
    shadowed = _shadowing_quantities(proposal)
    if shadowed:
        return SHADOWED_QUANTITY, shadowed
    try:
        validate_node(proposal)
    except (DesignStateError, ValidationError) as exc:
        return "invalid", _first_problem(exc)
    return None


def _shadowing_quantities(proposal: dict[str, Any]) -> str | None:
    """Why a proposal naming a quantity that shadows a relation's is refused, or None.

    The names are read from :mod:`physgate.state.vocabulary`, the catalogue's names spelled
    where a hook may load them: a hook never loads the gate.
    """
    from physgate.state.vocabulary import nearest_quantity_names, shadowing_quantity_names

    shadowed = shadowing_quantity_names(proposal.get("quantities") or {})
    if not shadowed:
        return None
    told = "; ".join(
        f"{name} shadows {relation} (nearest {', '.join(nearest_quantity_names(name))})"
        for name, relation in shadowed
    )
    return (
        f"{proposal.get('id')} names a quantity the gate's catalogue does not know under a "
        f"name a relation reads ({told}); a quantity a relation reads is written under the "
        "catalogue's name, so that the relation applies to it"
    )


def _quantity_problems(proposal: dict[str, Any]) -> str:
    """Which quantities are malformed, and how, in the schema's own words."""
    from pydantic import ValidationError

    from physgate.state.schema import Quantity

    problems = []
    for name, entry in (proposal.get("quantities") or {}).items():
        try:
            Quantity.model_validate(entry)
        except ValidationError as exc:
            problems.append(f"{name}: {_first_problem(exc)}")
    return "; ".join(problems) or "the quantities are not a mapping of quantities"


def _first_problem(exc: Exception) -> str:
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "the node"
        return f"{where}: {first['msg']}"
    return str(exc)


def _spellings(path: str, cwd: str) -> set[str]:
    target = os.path.normpath(path if os.path.isabs(path) else os.path.join(cwd, path))
    return {target, os.path.realpath(target)}


def _proposal_target(path: str, cwd: str, config: ConfigView) -> str | None:
    """The proposal file ``path`` names, if it is inside the proposals directory."""
    root = os.path.join(config.worktree, PROPOSALS_DIR).casefold()
    for spelling in _spellings(path, cwd):
        if spelling.casefold().startswith(root + "/"):
            return spelling
    return None


def _reaches_proposals(path: str, cwd: str, config: ConfigView) -> bool:
    """True if ``path`` is the proposals directory, anything in it, or a parent of it."""
    root = os.path.join(config.worktree, PROPOSALS_DIR).casefold()
    for spelling in _spellings(path, cwd):
        folded = spelling.casefold().rstrip("/")
        if folded == root or folded.startswith(root + "/") or root.startswith(folded + "/"):
            return True
    return False


def _content_after(hook_input: InputView, target: str) -> str | int:
    """What the Write or Edit would leave in the proposal, or how often an Edit's old text occurs.

    Claude Code finds an Edit's old text more loosely than an exact match (it takes curly
    quotes for straight ones, and reads line endings its own way), so an edit whose old
    text this reading does not find exactly once, or at least once under ``replace_all``,
    may still be made, and what it leaves cannot be checked here. Such an edit is answered
    with the count, and refused.
    """
    tool_input = hook_input.tool_input or {}
    if hook_input.tool_name == "Write":
        return str(tool_input.get("content", ""))
    current = ""
    if os.path.exists(target):
        with open(target) as handle:
            current = handle.read()
    old, new = str(tool_input.get("old_string", "")), str(tool_input.get("new_string", ""))
    if not old:
        # An empty old text creates a file that is not there, and locates nothing in one that is.
        return new if not current else 0
    found = current.count(old)
    if tool_input.get("replace_all"):
        return current.replace(old, new) if found else 0
    return current.replace(old, new, 1) if found == 1 else found


def _file_tool(hook_input: InputView, config: ConfigView) -> Decision:
    tool_input = hook_input.tool_input or {}
    key = "notebook_path" if hook_input.tool_name == "NotebookEdit" else "file_path"
    target = _proposal_target(str(tool_input.get(key, "")), hook_input.cwd, config)
    if target is None:
        return ALLOW
    if hook_input.tool_name == "NotebookEdit":
        return refuse(REFUSED.format(reason="invalid", detail=NOTEBOOK))
    stem, suffix = os.path.splitext(os.path.basename(target))
    if suffix != ".json":
        return refuse(REFUSED.format(reason="invalid", detail=NOT_JSON))
    after = _content_after(hook_input, target)
    if isinstance(after, int):
        return refuse(UNLOCATED.format(found=after))
    try:
        proposal = json.loads(after)
    except ValueError:
        return refuse(REFUSED.format(reason="invalid", detail=NOT_JSON))
    found = _check(proposal, stem, config)
    if found is None:
        return ALLOW
    return refuse(REFUSED.format(reason=found[0], detail=found[1]))


def _shell(hook_input: InputView, config: ConfigView) -> Decision:
    command = (hook_input.tool_input or {}).get("command")
    if not isinstance(command, str):
        return ALLOW  # the shell layer refuses a call without a command
    try:
        commands = parse(command)
    except ShellSyntaxError as exc:
        return refuse(UNCHECKABLE.format(detail=exc))
    cwd = hook_input.cwd if os.path.isabs(hook_input.cwd) else config.worktree
    for cmd in commands:
        argv = unwrap(cmd.argv)
        reads_only = bool(argv) and _only_reads(argv)
        words = [(r.target, "$" in r.target) for r in cmd.redirects if r.op in _WRITE_REDIRECTS]
        if not reads_only:
            words += [(w, n in cmd.dynamic) for n, w in enumerate(cmd.argv)]
        for word, dynamic in words:
            expanded = _expand(word, dynamic)
            if expanded is None:
                continue
            for candidate in _candidates(expanded, cwd):
                if _reaches_proposals(candidate, cwd, config) and not _is_the_worktree(
                    candidate, cwd, config
                ):
                    return refuse(SHELL_WRITE)
    return ALLOW


def _is_the_worktree(path: str, cwd: str, config: ConfigView) -> bool:
    # A parent of the proposals directory is refused (``rm -rf .physgate``), but
    # the worktree itself and anything above it is every command's home, and
    # naming it is not naming the proposals.
    worktree = os.path.normpath(config.worktree).casefold()
    return any(
        worktree == s.casefold().rstrip("/") or worktree.startswith(s.casefold().rstrip("/") + "/")
        for s in _spellings(path, cwd)
    )


def pre_tool_use(hook_input: InputView, config: ConfigView) -> Decision:
    """Check a proposal before it is written; refuse one written by any other route."""
    if hook_input.tool_name in ("Write", "Edit", "NotebookEdit"):
        return _file_tool(hook_input, config)
    if hook_input.tool_name == "Bash":
        return _shell(hook_input, config)
    return ALLOW


HOOK = HookSpec("graph", {"PreToolUse": pre_tool_use})
