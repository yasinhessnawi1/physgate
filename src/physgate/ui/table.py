"""The route table: every route the operator UI's server answers, in one tuple.

The dispatcher consults this tuple and nothing else, and the route sweep walks it, so the
list a test enumerates is exactly the list a request can reach. Every route is a read. A
later route that acts is added here with its own kind, which must have a policy in the guard
or the route cannot even be declared.
"""

from __future__ import annotations

from physgate.ui import readers
from physgate.ui.routes import Route, asset, index, runs

#: The path every route over one run starts with.
RUN = "/api/runs/{root:index}/{name:name}"

#: Every route the server answers. The enumeration test walks this tuple.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", "read", index),
    Route("GET", "/assets/{name:asset}", "read", asset),
    Route("GET", "/api/runs", "read", runs),
    Route("GET", "/api/prices", "read", readers.prices),
    Route("GET", f"{RUN}/config", "read", readers.config),
    Route("GET", f"{RUN}/events", "read", readers.events),
    Route("GET", f"{RUN}/ledger", "read", readers.ledger),
    Route("GET", f"{RUN}/gate-events", "read", readers.gate_events),
    Route("GET", f"{RUN}/graph", "read", readers.graph),
    Route("GET", f"{RUN}/trajectories/{{session:session}}", "read", readers.trajectory),
    Route("GET", f"{RUN}/cost/{{date:date}}", "read", readers.cost),
)


def methods(routes: tuple[Route, ...]) -> frozenset[str]:
    """The methods the table names, plus HEAD wherever GET is: everything else is a 405."""
    named = {route.method for route in routes}
    return frozenset(named | ({"HEAD"} if "GET" in named else set()))
