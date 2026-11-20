"""The route table: every route the operator UI's server answers.

The command serves :func:`served`: the product's own tuple, :data:`ROUTES`, then the reads its
composition root registers beside it (:func:`register`), the routes over the evaluation's
records, which no module of this package may import. With nothing registered it is
:data:`ROUTES` alone. The dispatcher consults the table it is given and nothing else, and the
route sweeps walk the served table, so the list a test enumerates is exactly the list a request
can reach. Every route is a read but one: the decision on an approval-queue item, of the ``act``
kind, whose handler calls the queue's own decision function. A route of a kind with no policy in
the guard cannot even be declared.
"""

from __future__ import annotations

from collections.abc import Iterable

from physgate.ui import actions, library, readers, simulation
from physgate.ui.guard import require_registered
from physgate.ui.routes import Route, asset, engine_catalogue, index, runs

#: The path every route over one run starts with.
RUN = "/api/runs/{root:index}/{name:name}"

#: Every route the server answers. The enumeration test walks this tuple.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", "read", index),
    Route("GET", "/assets/{name:asset}", "read", asset),
    Route("GET", "/api/engines", "read", engine_catalogue),
    Route("GET", "/api/runs", "read", runs),
    Route("GET", "/api/prices", "read", readers.prices),
    Route("GET", "/api/library", "read", library.listing),
    Route("GET", "/api/library/files/{kind:library_file}/{role:role}", "read", library.document),
    Route("GET", "/api/library/staged", "read", library.staged),
    Route("GET", "/api/library/staged/{candidate:candidate}", "read", library.candidate),
    Route("GET", "/api/library/ratings", "read", library.ratings),
    Route("GET", f"{RUN}/config", "read", readers.config),
    Route("GET", f"{RUN}/events", "read", readers.events),
    Route("GET", f"{RUN}/ledger", "read", readers.ledger),
    Route("GET", f"{RUN}/gate-events", "read", readers.gate_events),
    Route("GET", f"{RUN}/graph", "read", readers.graph),
    Route("GET", f"{RUN}/trajectories/{{session:session}}", "read", readers.trajectory),
    Route(
        "GET",
        f"{RUN}/trajectories/decomposition/{{round:round}}",
        "read",
        readers.decomposition_round_stream,
    ),
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
    # The run's simulation records: what each attempt sealed, read from the event log alone.
    Route("GET", f"{RUN}/series", "read", simulation.listing),
    Route(
        "GET", f"{RUN}/series/{{subtask:subtask}}/{{attempt:attempt}}", "read", simulation.attempt
    ),
    Route(
        "GET",
        f"{RUN}/series/{{subtask:subtask}}/{{attempt:attempt}}/{{record:record}}",
        "read",
        simulation.record,
    ),
    # The one route that acts: a decision, through the approval queue's own function.
    Route("POST", f"{RUN}/queue/decisions", "act", actions.decide),
)


#: The read routes the command's composition root registered beside the product's own.
_registered: tuple[Route, ...] = ()


def _shape(route: Route) -> tuple[str, tuple[str, ...]]:
    """The paths a route answers, whatever its parameters are called: its method and segments."""
    parts = tuple(name if kind is None else f"{{{kind}}}" for name, kind in route.segments)
    return route.method, parts


def register(routes: Iterable[Route]) -> None:
    """Serve ``routes`` beside :data:`ROUTES`, after every route of the product's own.

    Called once, by the command's composition root, which wires the evaluation into the core:
    no module of this package imports the evaluation, so the routes over its records are handed
    in from outside. Only reads are taken, so the table still acts in exactly one place, and none
    whose paths the table or an earlier route of the set already answers. The same routes again
    are the same registration, since the root runs once per command and a test process runs it
    many times; any other second set is refused.

    Raises:
        UnregisteredKindError: a route's kind has no policy in the guard.
        ValueError: a route acts, answers a path already served, or the table already serves
            another registration.
    """
    global _registered  # noqa: PLW0603 - the one place the command's root sets them
    offered = tuple(routes)
    if offered == _registered:
        return
    if _registered:
        msg = "routes are registered once, by the command's composition root"
        raise ValueError(msg)
    shapes = {_shape(route) for route in ROUTES}
    for route in offered:
        require_registered(route.kind)
        if route.kind != "read":
            msg = f"only reads are registered beside the table: {route.pattern!r} is {route.kind}"
            raise ValueError(msg)
        if _shape(route) in shapes:
            msg = f"{route.method} {route.pattern!r} is already served"
            raise ValueError(msg)
        shapes.add(_shape(route))
    _registered = offered


def registered() -> tuple[Route, ...]:
    """The routes registered beside the product's own."""
    return _registered


def served() -> tuple[Route, ...]:
    """Every route the server answers: the product's own, then what was registered."""
    return (*ROUTES, *_registered)


def methods(routes: tuple[Route, ...]) -> frozenset[str]:
    """The methods the table names, plus HEAD wherever GET is: everything else is a 405."""
    named = {route.method for route in routes}
    return frozenset(named | ({"HEAD"} if "GET" in named else set()))
