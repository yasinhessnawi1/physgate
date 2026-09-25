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
   not, because owners are assigned at decomposition, not by roles;
3. an existing interface node is not written at all;
4. every quantity is a value with a unit, a source and a writer — a bare number
   is refused here, with the schema's own message;
5. the node as a whole is valid.

The current owner and kind come from the journal, read without opening the
store. The ownership rules are a list, so a rule the architecture adds later is
one more entry rather than a new branch.

A proposal written by a shell command is refused: only the Write and Edit tools
carry the content, so only they can be checked before the file exists.
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
    "before the file exists. A shell command may read them but not write them."
)
UNCHECKABLE = (
    "This command could not be split into the commands it would run ({detail}), so whether it "
    "writes a node proposal cannot be checked, and it is refused."
)

#: Not one of the store's reasons: the store accepts this write, and the hook
#: is stricter on purpose (see ``_owner_does_not_change``).
OWNER_CHANGE = "owner_change"


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


#: Checked in order; the first to object refuses the proposal.
OWNERSHIP_RULES: tuple[OwnershipRule, ...] = (_owner_is_the_session, _owner_does_not_change)


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
    try:
        validate_node(proposal)
    except (DesignStateError, ValidationError) as exc:
        return "invalid", _first_problem(exc)
    return None


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


def _content_after(hook_input: InputView, target: str) -> str:
    tool_input = hook_input.tool_input or {}
    if hook_input.tool_name == "Write":
        return str(tool_input.get("content", ""))
    current = ""
    if os.path.exists(target):
        with open(target) as handle:
            current = handle.read()
    old, new = str(tool_input.get("old_string", "")), str(tool_input.get("new_string", ""))
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


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
    try:
        proposal = json.loads(_content_after(hook_input, target))
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
