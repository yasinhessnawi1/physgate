"""A dispute: a role's typed position on a value the owner of the cross nodes wrote, held as data.

A role that disagrees with a quantity of a ``cross`` node (ARCH-051 gives those one writer) does
not write the node. It writes its position as one file of its worktree,
``.physgate/disputes/<node id>.<quantity>.json``, holding one JSON object with three keys, each
once: ``{"value": <number>, "unit": "<unit>", "reason": "<why>"}``. The path names the node and
the quantity, so an attempt holds one dispute per quantity. A file left in place is the next
attempt's dispute too; deleting it withdraws it. A dispute is data: the change check reads it
from the attempt's commit and the run's log records it, and the merge and the reviewer's packet
leave the directory out, so no later worktree and no reviewer holds another role's reason.

It is held as node proposals are: written with the Write or Edit tool only, and read by two
readers with :func:`parse`, the hook before the file exists and the change check from the commit
it checks. Both ask the role register and the graph's journal, now:

- who: every role but the owners of the cross nodes and of completion, found by what they own;
  the first wrote the value, and the second writes no design;
- what: a quantity that an existing ``cross`` node holds, that node not an interface. An
  interface is fixed at decomposition, and any other node is its own role's to change.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.protocols import QuantityRef

#: Where disputes live in a worktree, as git names the path.
DISPUTES_DIR = ".physgate/disputes"
_PATH = re.compile(
    r"\.physgate/disputes/(?P<node>[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\.(?P<quantity>[a-z][a-z0-9_]*)\.json"
)
_QUANTITY_MAX = 64
#: The bounds of a dispute's file, unit and reason.
MAX_BYTES = 2048
UNIT_MAX = 32
REASON_MAX = 500
#: A control character, or half a surrogate pair: JSON escapes one as ASCII, and no line holds it.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")
KEYS = ("reason", "unit", "value")

NAMED = (
    f"a dispute is one file in {DISPUTES_DIR} named <node id>.<quantity>.json, for a node id of "
    "the graph and a quantity name of lower-case letters, digits and '_' (at most 64 characters)"
)
TOO_LONG = "a dispute holds at most {cap} bytes, and this one holds {size}"
NOT_UTF8 = "a dispute is UTF-8 text, and this one is not"
LINE_ENDS = "a dispute's lines end in a line feed alone, with no carriage return"
NOT_JSON = "a dispute is JSON, and this one is not"
SHAPE = (
    'a dispute is one JSON object with three keys, each named once: "value" (a number), "unit" '
    'and "reason" (text)'
)
VALUE = "a dispute's value is a finite number, neither quoted nor true or false"
_PLAIN = "with no control character and no half of a surrogate pair"
UNIT = f"a dispute's unit is text of 1 to {UNIT_MAX} characters {_PLAIN}"
REASON = f"a dispute's reason is text of 1 to {REASON_MAX} characters {_PLAIN}"
UNRECORDABLE = "the run's record cannot hold this dispute as written"


class DisputeError(Exception):
    """A dispute that is not one; the message says why, in words a session can act on."""


class Dispute(BaseModel):
    """The position a dispute takes on one quantity, and its reason as written."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    position: QuantityRef
    reason: NonEmptyStr


def disputer_problem(role: str) -> str | None:
    """Why a session of ``role`` may not dispute, or ``None``: found by duty, never by name."""
    from physgate.roles import owners_of

    if role in owners_of("cross_nodes"):
        return f"the {role} role writes the cross nodes' values, so it disputes none of them"
    if role in owners_of("completion"):
        return f"the {role} role owns completion and writes no design, so it disputes none"
    return None


def parse(path: str, data: bytes, role: str, nodes: Mapping[str, Mapping[str, object]]) -> Dispute:
    """The dispute ``data`` holds at ``path`` (as git names it), held to every rule here.

    ``nodes`` is the graph's newest payload of each node, from its journal.

    Raises:
        DisputeError: a path that names no node and quantity; a role that may not dispute; a
            node that is not an existing cross node other than an interface, or that does not
            hold the quantity; or a body that is not a dispute's.
    """
    found = _PATH.fullmatch(path)
    if found is None or len(found["quantity"]) > _QUANTITY_MAX:
        raise DisputeError(NAMED)
    node_id, quantity = found["node"], found["quantity"]
    why = disputer_problem(role)
    if why is not None:
        raise DisputeError(why)
    node = nodes.get(node_id)
    if node is None or node.get("domain") != "cross" or node.get("kind") == "interface":
        msg = (
            f"{node_id} is no cross node of the graph, or is an interface; a dispute is of a "
            "value the owner of the cross nodes wrote"
        )
        raise DisputeError(msg)
    held = node.get("quantities")
    if not isinstance(held, dict) or quantity not in held:
        raise DisputeError(f"the cross node {node_id} holds no quantity {quantity}")
    value, unit, reason = _body(data)
    try:
        position = QuantityRef(node_id=node_id, name=quantity, value=value, unit=unit)
        return Dispute(position=position, reason=reason)
    except ValidationError as exc:
        # Behind the rules above, never a crash: what the models refuse is refused here too.
        field = str(exc.errors()[0]["loc"][0])
        raise DisputeError(
            {"value": VALUE, "unit": UNIT, "reason": REASON}.get(field, SHAPE)
        ) from None


def _body(data: bytes) -> tuple[float | int, str, str]:
    """A dispute's value, unit and reason, held to its shape."""
    if len(data) > MAX_BYTES:
        raise DisputeError(TOO_LONG.format(cap=MAX_BYTES, size=len(data)))
    if b"\r" in data:
        raise DisputeError(LINE_ENDS)
    try:
        body = json.loads(data.decode("utf-8"), object_pairs_hook=_once, parse_constant=_no)
    except UnicodeDecodeError:
        raise DisputeError(NOT_UTF8) from None
    except (ValueError, RecursionError):
        raise DisputeError(NOT_JSON) from None
    if not isinstance(body, dict) or sorted(body) != list(KEYS):
        raise DisputeError(SHAPE)
    value, unit, reason = body["value"], body["unit"], body["reason"]
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise DisputeError(VALUE)
    if not isinstance(unit, str) or not 0 < len(unit) <= UNIT_MAX or _CONTROL.search(unit):
        raise DisputeError(UNIT)
    if not isinstance(reason, str) or not 0 < len(reason) <= REASON_MAX or _CONTROL.search(reason):
        raise DisputeError(REASON)
    return value, unit, reason


def _once(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """A JSON object whose keys are each named once: JSON alone would keep the last of two."""
    if len({key for key, _ in pairs}) != len(pairs):
        raise DisputeError(SHAPE)
    return dict(pairs)


def _no(constant: str) -> None:
    """``NaN`` and ``Infinity`` are no JSON numbers, though Python's reader takes them."""
    raise ValueError(constant)
