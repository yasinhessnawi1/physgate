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

**A route that acts cannot be reached from another page.** Before any route whose kind
is not ``read`` runs, the server refuses, in order:

1. a request with no ``Origin``, or one that is not this server's own (a page on another
   site sends its own origin, or ``null``);
2. a ``Sec-Fetch-Site`` other than ``same-origin``, when the browser sends one;
3. a request without this server start's action token in its header. The token is made
   when the server starts, kept only in memory, and put in the app's own page; another
   site's page cannot read that page, and a request carrying a custom header from another
   origin needs a preflight, which this server answers 405;
4. any body that is not ``application/json``: the three content types a plain form or a
   simple request can send are among those refused;
5. a body without its length, sent in chunks, or longer than 16 KiB;
6. any action at all when the server was started without naming an operator.

No response carries a cross-origin header. Every connection's socket has a timeout, so a
request that stops sending is dropped rather than waited on.
"""

from __future__ import annotations

import hmac
import secrets
import socket
import sys
from collections.abc import Mapping
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from physgate.evaluation.observe.exceptions import ObserveError
from physgate.gate.exceptions import GateError
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.state.exceptions import DesignStateError
from physgate.ui import guard
from physgate.ui.exceptions import (
    GuardRefusedError,
    NotFoundError,
    PathRefusedError,
    StartupRefusedError,
    UIError,
)
from physgate.ui.routes import Context, Response, Route, carrying, error_response, split_target
from physgate.ui.table import ROUTES, methods

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


#: The header an action request carries the server's token in.
ACT_TOKEN_HEADER = "X-Physgate-Act-Token"

#: The largest action body read, in bytes. A decision is a few hundred.
MAX_ACT_BODY = 16 * 1024

#: How long a connection's socket waits for the client, in seconds, before it is dropped.
REQUEST_TIMEOUT_S = 10.0

#: The longest operator name taken at start.
MAX_OPERATOR = 64


def require_operator(name: str | None) -> str | None:
    """``name`` as the operator decisions are recorded under, or ``None`` if none was named.

    Raises:
        StartupRefusedError: a name that is empty, longer than ``MAX_OPERATOR``, or holds a
            character that does not print.
    """
    if name is None:
        return None
    if not name.strip() or len(name) > MAX_OPERATOR or not name.isprintable():
        msg = f"the operator is a printable name of at most {MAX_OPERATOR} characters"
        raise StartupRefusedError(msg, operator=repr(name))
    return name


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
    timeout = REQUEST_TIMEOUT_S
    context: ClassVar[Context]
    routes: ClassVar[tuple[Route, ...]]
    hosts: ClassVar[frozenset[str]]
    act_token: ClassVar[str]
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
            if route.kind == "read":
                self._send(self._run(route, params))
                return
            refused = self._refuse_action()
            if refused is not None:
                self._send(error_response(*refused))
                return
            body = self._read_body()
            if isinstance(body, Response):
                self._send(body)
                return
            with carrying(body):
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
            with guard.scope(route.kind, readable=self.context.allowlist.readable):
                return route.handler(self.context, params)
        except GuardRefusedError as exc:
            return error_response(500, exc)
        except PathRefusedError as exc:
            return error_response(403, exc)
        except NotFoundError as exc:
            return error_response(404, exc)
        except (UIError, OrchestratorError, DesignStateError, ObserveError, GateError) as exc:
            # A record the package's own reader refuses: shown as a refusal with its reason.
            return error_response(422, exc)
        except Exception as exc:  # noqa: BLE001 - a handler's fault is answered, never a traceback
            self.log_error("handler failed: %s", type(exc).__name__)
            return error_response(500, f"the server failed to read this: {type(exc).__name__}")

    def _own_origins(self) -> frozenset[str]:
        return frozenset(f"http://{host}" for host in self.hosts)

    def _refuse_action(self) -> tuple[int, str] | None:
        """Why an action request is refused before its body is read, or ``None``."""
        origins = self.headers.get_all("Origin") or []
        if len(origins) != 1 or origins[0].lower() not in self._own_origins():
            return 403, "an action is taken only from this server's own page"
        sites = self.headers.get_all("Sec-Fetch-Site") or []
        if sites and sites != ["same-origin"]:
            return 403, "an action is taken only from this server's own page"
        tokens = self.headers.get_all(ACT_TOKEN_HEADER) or []
        if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode(), self.act_token.encode()):
            return 403, "an action carries the token this server put in its own page"
        media = (self.headers.get_all("Content-Type") or [""])[0].split(";")
        charset = [p.strip().lower() for p in media[1:]]
        if media[0].strip().lower() != "application/json" or charset not in ([], ["charset=utf-8"]):
            return 415, "an action's body is JSON, sent as application/json"
        if self.context.operator is None:
            return 403, "no operator was named when the server started, so nothing can act"
        return None

    def _read_body(self) -> bytes | Response:
        """The action's body, read to its stated length, or the refusal of it."""
        if self.headers.get_all("Transfer-Encoding"):
            return error_response(411, "an action's body states its length; it is never chunked")
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isdigit():
            return error_response(411, "an action's body states its length, once")
        length = int(lengths[0])
        if length > MAX_ACT_BODY:
            return error_response(413, f"an action's body is at most {MAX_ACT_BODY} bytes")
        body = self.rfile.read(length)
        if len(body) != length:
            return error_response(400, "the body ended before its stated length")
        return body

    def _refuse_origin(self) -> str | None:
        """Why the request's ``Host`` or ``Origin`` is refused, or ``None``."""
        hosts = self.headers.get_all("Host") or []
        if len(hosts) != 1 or hosts[0].lower() not in self.hosts:
            return "the request does not name this server's loopback address as its host"
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1:
            return "the request carries more than one origin"
        if origins and origins[0].lower() not in self._own_origins():
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
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> ThreadingHTTPServer:
    """A server on ``bind``:``port`` answering ``routes``, with the guard installed.

    ``routes`` is for the tests that plant a route, and ``timeout_s`` for the test that
    crosses it; the command always serves the table with the default. A new action token is
    made for every server and put in its page.

    Raises:
        StartupRefusedError: the address is not loopback, the operator's name is refused, or
            the page has nowhere to carry the token.
    """
    require_loopback(bind)
    require_operator(context.operator)
    token = secrets.token_urlsafe(32)
    context = replace(context, assets=context.assets.with_act_token(token))
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
            "act_token": token,
            "timeout": timeout_s,
            "quiet": quiet,
        },
    )
    server.RequestHandlerClass = handler
    return server
