"""The completion declaration: one file, one shape, and one parser for its three readers.

The role that owns completion declares which modules of the plan are complete in one file of its
worktree, ``.physgate/completion/declaration.json``, holding one JSON object with one key:
``{"complete": ["<subtask id>", ...]}``. Each entry names a module by the subtask that planned it,
as the run's record names modules; a module left out is not declared complete, and the entries
may come in any order. The evidence for each module stays in the role's own record, for its
reviewer: the file says what is declared, never why.

The file is held as node proposals are. It is written with the Write or Edit tool only, and three
readers hold it to the rules here:

- the hook, before the file exists: its shape (:func:`read_shape`), since a hook has no plan;
- the change check, from the commit it checks (:func:`parse`): every entry a module of the plan,
  and the digest of the bytes that commit holds;
- the loop, from the merged commit before every completion line, with the same parser, so that a
  declaration line rewritten on the record cannot carry a module the file does not name.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

#: Where the declaration lives in a worktree, as git names the path.
DECLARATION_PATH = ".physgate/completion/declaration.json"
#: The declaration's one key.
KEY = "complete"
#: The most bytes a declaration holds: far more than any plan's list of modules needs.
MAX_BYTES = 4096
TOO_LONG = "a completion declaration holds at most {cap} bytes, and this one holds {size}"
NOT_JSON = "a completion declaration is JSON, and this one is not"
NOT_UTF8 = "a completion declaration is UTF-8 text, and this one is not"
SHAPE = (
    'a completion declaration is one JSON object with one key, "complete", whose value is a '
    "list of subtask ids"
)
NOT_AN_ID = (
    "an entry of a completion declaration is not a subtask id (a lower-case letter, then "
    "lower-case letters, digits, '-' or '_', at most 64 characters)"
)
TWICE = "a completion declaration names a module twice"
LINE_ENDS = (
    "a completion declaration's lines end in a line feed alone, with no carriage return, so "
    "that the bytes the harness reads are the bytes written"
)
#: A subtask id as the harness mints one, and its bound.
_ID = re.compile(r"[a-z][a-z0-9_-]*")
_ID_MAX_LENGTH = 64


class DeclarationError(Exception):
    """A declaration that is not one; the message says why, in words a session can act on."""


class Declaration(BaseModel):
    """What a declaration names complete, in plan order, and the digest of its bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    modules: tuple[str, ...]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def read_shape(data: bytes) -> tuple[str, ...]:
    """The subtask ids a declaration names, held to its shape alone.

    Raises:
        DeclarationError: past the size cap, not JSON, not one object with the one key whose
            value is a list, an entry that is not a subtask id, or one named twice.
    """
    if len(data) > MAX_BYTES:
        raise DeclarationError(TOO_LONG.format(cap=MAX_BYTES, size=len(data)))
    if b"\r" in data:
        raise DeclarationError(LINE_ENDS)
    try:
        value = json.loads(data)
    except (ValueError, RecursionError):
        raise DeclarationError(NOT_JSON) from None
    if not isinstance(value, dict) or list(value) != [KEY] or not isinstance(value[KEY], list):
        raise DeclarationError(SHAPE)
    names: list[object] = value[KEY]
    for name in names:
        if not isinstance(name, str) or len(name) > _ID_MAX_LENGTH or not _ID.fullmatch(name):
            raise DeclarationError(NOT_AN_ID)
    if len(set(names)) != len(names):
        raise DeclarationError(TWICE)
    return tuple(str(name) for name in names)


def parse(data: bytes, planned: Mapping[str, str], declaring: str) -> Declaration:
    """What a declaration names complete, held to the plan, in plan order, with its digest.

    ``planned`` maps each planned subtask, in plan order, to its module directory; a module is
    named by the first subtask planned in its directory. ``declaring`` is the subtask whose
    attempt holds the declaration.

    Raises:
        DeclarationError: the shape is not a declaration's (:func:`read_shape`), or an entry is
            no subtask of the plan, is the declaring subtask, or is a later pass over a module an
            earlier subtask planned (as sizing's closing pass is).
    """
    names = read_shape(data)
    order = list(planned)
    first: dict[str, str] = {}
    for subtask, directory in planned.items():
        first.setdefault(directory, subtask)
    for name in names:
        if name not in planned:
            msg = f"the completion declaration names {name}, which is no subtask of the plan"
            raise DeclarationError(msg)
        if name == declaring:
            msg = f"the completion declaration names {name}, the declaring subtask, no module"
            raise DeclarationError(msg)
        module = first.get(planned.get(name, ""), "")
        if module != name:
            msg = (
                f"the completion declaration names {name}, a later pass over the module "
                f"{module} planned; name that module by {module}"
            )
            raise DeclarationError(msg)
    modules = tuple(sorted(names, key=order.index))
    return Declaration(modules=modules, sha256=hashlib.sha256(data).hexdigest())
