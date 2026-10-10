"""The route table: every route the operator UI's server answers, in one tuple.

The dispatcher consults this tuple and nothing else, and the route sweep walks it, so the
list a test enumerates is exactly the list a request can reach. Every route is a read but
one: the decision on an approval-queue item, of the ``act`` kind, whose handler calls the
queue's own decision function. A route of a kind with no policy in the guard cannot even be
declared.
"""

from __future__ import annotations

from physgate.ui import actions, readers
from physgate.ui.routes import Route, asset, index, operator, runs

#: The path every route over one run starts with.
RUN = "/api/runs/{root:index}/{name:name}"

#: Every route the server answers. The enumeration test walks this tuple.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", "read", index),
    Route("GET", "/assets/{name:asset}", "read", asset),
    Route("GET", "/api/runs", "read", runs),
    Route("GET", "/api/prices", "read", readers.prices),
    Route("GET", "/api/operator", "read", operator),
    Route("GET", f"{RUN}/config", "read", readers.config),
    Route("GET", f"{RUN}/events", "read", readers.events),
    Route("GET", f"{RUN}/ledger", "read", readers.ledger),
    Route("GET", f"{RUN}/gate-events", "read", readers.gate_events),
    Route("GET", f"{RUN}/graph", "read", readers.graph),
    Route("GET", f"{RUN}/trajectories/{{session:session}}", "read", readers.trajectory),
    Route("GET", f"{RUN}/cost/{{date:date}}", "read", readers.cost),
    Route("GET", f"{RUN}/trace", "read", readers.trace),
    Route("GET", f"{RUN}/decisions", "read", readers.decisions),
    Route("GET", f"{RUN}/status", "read", readers.status),
    Route("GET", f"{RUN}/tokens", "read", readers.tokens),
    Route("GET", f"{RUN}/gate-checks", "read", readers.gate_checks),
    Route("GET", f"{RUN}/graph/at/{{revision:revision}}", "read", readers.graph_at_revision),
    Route("GET", f"{RUN}/graph/history/{{node:node}}", "read", readers.history),
    Route("GET", f"{RUN}/graph/diff/{{from:revision}}/{{to:revision}}", "read", readers.diff),
    Route("GET", f"{RUN}/queue", "read", readers.queue),
    Route("GET", f"{RUN}/queue/items/{{position:index}}", "read", readers.queue_item),
    # The one route that acts: a decision, through the approval queue's own function.
    Route("POST", f"{RUN}/queue/decisions", "act", actions.decide),
)


def methods(routes: tuple[Route, ...]) -> frozenset[str]:
    """The methods the table names, plus HEAD wherever GET is: everything else is a 405."""
    named = {route.method for route in routes}
    return frozenset(named | ({"HEAD"} if "GET" in named else set()))
