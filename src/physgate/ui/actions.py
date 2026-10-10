"""The operator UI's one action: a person's decision on an approval-queue item.

The route is a thin call into the approval queue's own decision function, the same one
``physgate queue resolve`` calls, so a decision taken here is the same line, in the same file,
written under the same lock and the same checks. Nothing else is written, and the guard's
``act`` kind refuses any other write this handler might attempt.

What the request carries, and nothing more: the item, approve or reject, a note (required to
reject), and what the page showed of the item (its line's digest and each trajectory's seal
status), which the decision function checks again under its lock. Who decided is the operator
the server was started with, never a field of the request. The run directory is reached by the
walk from its root that no swap can redirect, and the decision function opens every file
beneath it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from physgate.orchestrator.common import NonEmptyStr, first_problem
from physgate.orchestrator.exceptions import QueueError
from physgate.orchestrator.queue import ShownItem, Verb, decision_text, record_decision
from physgate.ui.exceptions import UIError
from physgate.ui.readers import run_dir_of
from physgate.ui.routes import Context, Response, error_response, json_response, request_body

#: The longest note taken with a decision, in characters. The body's own cap is far larger.
MAX_NOTE = 4000


class DecisionRequest(BaseModel):
    """What a decision request carries."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    item_id: NonEmptyStr
    verb: Verb
    note: Annotated[str, Field(max_length=MAX_NOTE)]
    shown: ShownItem


def decide(context: Context, params: Mapping[str, str]) -> Response:
    """Record the operator's decision on an open item, exactly as ``queue resolve`` would.

    Answers 201 with what the command prints; 400 for a request that is not a decision (a
    rejection without a note among them); 409 for an item that is not open, a view that no
    longer matches, a lock held past its wait, or a queue that cannot be read.
    """
    operator = context.operator
    if operator is None:  # the server refuses an action before this; held here as well
        return error_response(403, "no operator was named when the server started")
    try:
        request = DecisionRequest.model_validate_json(request_body())
    except ValidationError as exc:
        return error_response(
            400, UIError("the request is not a decision", reason=first_problem(exc))
        )
    try:
        text = decision_text(request.verb, request.note)
    except QueueError as exc:  # a rejection without its reason: the request is not a decision
        return error_response(400, exc)
    run_dir = run_dir_of(context, params)
    try:
        with context.allowlist.opened_directory(run_dir) as fd:
            record = record_decision(
                run_dir,
                request.item_id,
                decision=text,
                resolved_by=operator,
                shown=request.shown,
                dir_fd=fd,
            )
    except QueueError as exc:
        return error_response(409, exc)
    return json_response({"resolved": record.model_dump()}, 201)
