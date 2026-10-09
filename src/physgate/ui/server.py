"""The operator UI's HTTP server: the standard library's, on loopback, dispatching from the table.

The standard library's server is documented as not meant for production. Here it
listens on loopback only, refuses a request whose ``Host`` or ``Origin`` is not
that loopback address (so a page on another site cannot use DNS rebinding to
turn a browser tab into a reader), answers only the routes in the table, and
reads only through the allowlist. A web framework would bring default handlers
and fallthroughs to switch off, and a runtime dependency, for fewer than a dozen
routes that only read.

**Every method goes through the table.** The standard handler looks for a
``do_<METHOD>`` method and answers 501 when there is none; this one replaces that
step, so a method the table does not name is answered 405 with an ``Allow``
header, whatever the method is, and nothing else can answer it.

**Every response carries the same headers**, refusals included: a
Content-Security-Policy allowing nothing but this origin, no sniffing, no
framing, no referrer, no caching.

Each handler runs inside the guard's scope for its route's kind, so a read route
that tries to write, connect out or spawn is aborted before the operation, and
answered 500 with the reason.
"""

from __future__ import annotations

import socket
import sys
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from physgate.orchestrator.exceptions import OrchestratorError
from physgate.ui import guard
from physgate.ui.exceptions import GuardRefusedError, PathRefusedError, StartupRefusedError, UIError
from physgate.ui.routes import (
    ROUTES,
    Context,
    Response,
    Route,
    error_response,
    methods,
    split_target,
)

#: The only addresses the server binds. A host name is refused without a lookup.
LOOPBACK = ("127.0.0.1", "::1")

#: Sent on every response.
SECURITY_HEADERS: Mapping[str, str] = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def require_loopback(bind: str) -> str:
    """``bind`` if it is one of the loopback addresses; otherwise refuse.

    Raises:
        StartupRefusedError: anything else, an unspecified address and host names included.
    """
    if bind not in LOOPBACK:
        msg = "the operator UI binds to loopback only: 127.0.0.1 or ::1"
        raise StartupRefusedError(msg, bind=bind)
    return bind


def allowed_hosts(bind: str, port: int) -> frozenset[str]:
    """The ``Host`` values a request may carry: the bound address or ``localhost``, and the port."""
    literal = f"[{bind}]" if ":" in bind else bind
    return frozenset({f"{literal}:{port}", f"localhost:{port}"})


class Handler(BaseHTTPRequestHandler):
    """Answers one connection's request from the route table, and nothing else."""

    server_version = "physgate-ui"
    sys_version = ""
    protocol_version = "HTTP/1.0"
    context: ClassVar[Context]
    routes: ClassVar[tuple[Route, ...]]
    hosts: ClassVar[frozenset[str]]
    quiet: ClassVar[bool] = False

    def handle_one_request(self) -> None:
        """Read one request and dispatch it through the table, whatever its method.

        The standard version of this method answers 501 for a method with no
        ``do_`` handler; this one never looks for those.
        """
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = self.request_version = self.command = ""
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            self._dispatch()
            self.wfile.flush()
        except TimeoutError as exc:
            self.log_error("request timed out: %r", exc)
            self.close_connection = True

    def _dispatch(self) -> None:
        allowed = methods(self.routes)
        if self.command not in allowed:
            self._send(error_response(405, "this method is not served"), allow=allowed)
            return
        refusal = self._refuse_origin()
        if refusal is not None:
            self._send(error_response(403, refusal))
            return
        segments = split_target(self.path)
        if segments is None:
            self._send(error_response(400, "the request target is not a plain path"))
            return
        method = "GET" if self.command == "HEAD" else self.command
        served: set[str] = set()
        for route in self.routes:
            params = route.match(segments)
            if params is None:
                continue
            if route.method != method:
                served.add(route.method)
                continue
            self._send(self._run(route, params))
            return
        if served:
            self._send(
                error_response(405, "this method is not served on this path"),
                allow=methods(tuple(r for r in self.routes if r.method in served)),
            )
            return
        self._send(error_response(404, "no route serves this path"))

    def _run(self, route: Route, params: dict[str, str]) -> Response:
        try:
            with guard.scope(route.kind):
                return route.handler(self.context, params)
        except GuardRefusedError as exc:
            return error_response(500, exc)
        except PathRefusedError as exc:
            return error_response(403, exc)
        except (UIError, OrchestratorError) as exc:
            return error_response(422, exc)
        except Exception as exc:  # noqa: BLE001 - a handler's fault is answered, never a traceback
            self.log_error("handler failed: %s", type(exc).__name__)
            return error_response(500, f"the server failed to read this: {type(exc).__name__}")

    def _refuse_origin(self) -> str | None:
        """Why the request's ``Host`` or ``Origin`` is refused, or ``None``."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.hosts:
            return "the request does not name this server's loopback address as its host"
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1:
            return "the request carries more than one origin"
        if origins and origins[0].lower() not in {f"http://{h}" for h in self.hosts}:
            return "the request comes from another origin"
        return None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        """Answer a malformed request with the same JSON body and headers as every refusal."""
        phrase = message or HTTPStatus(code).phrase
        self._send(error_response(code, phrase))

    def _send(self, response: Response, allow: frozenset[str] | None = None) -> None:
        self.send_response(response.status)
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        if allow is not None:
            self.send_header("Allow", ", ".join(sorted(allow)))
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the base class's name
        """Log to standard error unless the server was made quiet (in tests)."""
        if not self.quiet:
            sys.stderr.write(f"{self.address_string()} {format % args}\n")


class _Server(ThreadingHTTPServer):
    daemon_threads = True


class _Server6(_Server):
    address_family = socket.AF_INET6


def make_server(
    context: Context,
    *,
    bind: str,
    port: int,
    routes: tuple[Route, ...] = ROUTES,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    """A server on ``bind``:``port`` answering ``routes``, with the guard installed.

    ``routes`` is for the tests that plant a route; the command always serves the table.

    Raises:
        StartupRefusedError: the address is not loopback.
    """
    require_loopback(bind)
    guard.install()
    server_class = _Server6 if ":" in bind else _Server
    server = server_class((bind, port), Handler)
    bound_port = int(server.server_address[1])
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "context": context,
            "routes": routes,
            "hosts": allowed_hosts(bind, bound_port),
            "quiet": quiet,
        },
    )
    server.RequestHandlerClass = handler
    return server
