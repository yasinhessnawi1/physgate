"""The operator UI's routes, as data: one table the server dispatches from and a test enumerates.

Every route is a record: a method, a path pattern, the kind of route it is, and
its handler. The server consults this table and nothing else, so the list a test
walks is exactly the list a request can reach; there is no default handler and
no fallthrough. A method no route names is answered 405, a path no route matches
404.

**The kind decides what a handler may do while it runs** (see ``guard``). Every
route here is ``read``. A later route that acts, for example one recording a
decision through the approval queue's own function, is added as a new kind with
its own policy; the table, the dispatcher and the read routes stay as they are.

**A request never carries a filesystem path.** Path parameters are typed by a
pattern each, checked after one round of percent-decoding, segment by segment,
so an encoded separator, a doubly encoded dot, a NUL or a ``..`` is simply a
segment that matches no pattern. Runs are addressed by the position of the root
they were found in and their directory's name; the server builds the path itself
and holds it to the allowlist before any reader opens it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.run_config import load_run_config
from physgate.ui.assets import Assets
from physgate.ui.exceptions import PathRefusedError, UIError
from physgate.ui.guard import RouteKind, require_registered
from physgate.ui.paths import Allowlist

#: The patterns a path parameter may take. Each excludes a separator, a NUL and a
#: leading dot, so no parameter can name a parent directory or a hidden file.
PARAMETERS: Mapping[str, re.Pattern[str]] = {
    "index": re.compile(r"^(0|[1-9][0-9]{0,3})$"),
    "name": re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$"),
    "asset": re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,255}$"),
}

#: The run's configuration file, whose presence makes a directory a run directory.
RUN_CONFIG = "run.json"

Method = Literal["GET"]


@dataclass(frozen=True)
class Response:
    """What a handler answers: a status, a body and its media type."""

    status: int
    body: bytes
    content_type: str


@dataclass(frozen=True)
class Context:
    """What every handler is given: the allowlist and the built app. Nothing writable."""

    allowlist: Allowlist
    assets: Assets


Handler = Callable[[Context, Mapping[str, str]], Response]


@dataclass(frozen=True)
class Route:
    """One route: method, pattern (``/api/runs/{root:index}``), kind, handler."""

    method: Method
    pattern: str
    kind: RouteKind
    handler: Handler
    segments: tuple[tuple[str, str | None], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Parse the pattern and refuse a kind with no policy.

        Raises:
            UnregisteredKindError: the kind has no registered policy.
            ValueError: the pattern does not start at the root or names an unknown type.
        """
        require_registered(self.kind)
        if not self.pattern.startswith("/"):
            msg = f"a route pattern starts at the root: {self.pattern!r}"
            raise ValueError(msg)
        parsed: list[tuple[str, str | None]] = []
        for part in self.pattern.split("/")[1:]:
            if part.startswith("{") and part.endswith("}"):
                name, _, kind = part[1:-1].partition(":")
                if kind not in PARAMETERS:
                    msg = f"unknown parameter type in {self.pattern!r}: {kind!r}"
                    raise ValueError(msg)
                parsed.append((name, kind))
            else:
                parsed.append((part, None))
        object.__setattr__(self, "segments", tuple(parsed))

    def match(self, segments: tuple[str, ...]) -> dict[str, str] | None:
        """The parameters if the decoded ``segments`` match this route, else ``None``."""
        if len(segments) != len(self.segments):
            return None
        params: dict[str, str] = {}
        for value, (name, kind) in zip(segments, self.segments, strict=True):
            if kind is None:
                if value != name:
                    return None
            elif PARAMETERS[kind].fullmatch(value) is None:
                return None
            else:
                params[name] = value
        return params


def split_target(target: str) -> tuple[str, ...] | None:
    """The request target's path as decoded segments, or ``None`` if it is not a plain path.

    The query is dropped. Each segment is percent-decoded once, after splitting, so
    an encoded separator stays inside its segment and fails every pattern.
    """
    path = target.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/") or path.startswith("//"):
        return None
    try:
        return tuple(unquote(part, errors="strict") for part in path.split("/")[1:])
    except UnicodeDecodeError:
        return None


def json_response(payload: object, status: int = 200) -> Response:
    """A JSON body, keys sorted, so the same records give the same bytes."""
    body = json.dumps(payload, sort_keys=True, indent=1).encode() + b"\n"
    return Response(status=status, body=body, content_type="application/json; charset=utf-8")


def error_response(status: int, error: UIError | OrchestratorError | str) -> Response:
    """The error body every refusal uses: the message and its context, never a traceback."""
    if isinstance(error, str):
        return json_response({"error": error}, status)
    return json_response({"error": str(error), **error.context}, status)


# -- the handlers ------------------------------------------------------------------


def index(context: Context, params: Mapping[str, str]) -> Response:
    """The app's page."""
    return Response(200, context.assets.index, "text/html; charset=utf-8")


def asset(context: Context, params: Mapping[str, str]) -> Response:
    """One file of the built app, from the set loaded at start; never from disk here."""
    found = context.assets.files.get(params["name"])
    if found is None:
        return error_response(404, "no such file in the built app")
    body, content_type = found
    return Response(200, body, content_type)


def run_directories(allowlist: Allowlist) -> list[tuple[int, str, Path]]:
    """Every run directory the roots hold: a root that is one, or a root's direct child that is.

    Each is (root position, directory name, real path), in a stable order. A child
    the allowlist refuses (a link out of its root, a corpus) is left out.
    """
    found: list[tuple[int, str, Path]] = []
    for position, root in enumerate(allowlist.roots):
        if (root.path / RUN_CONFIG).is_file():
            found.append((position, root.path.name, root.path))
            continue
        with os.scandir(root.path) as entries:
            names = sorted(entry.name for entry in entries if entry.is_dir())
        for name in names:
            if PARAMETERS["name"].fullmatch(name) is None:
                continue
            try:
                real = allowlist.resolve(root.path / name)
            except PathRefusedError:
                continue
            if (real / RUN_CONFIG).is_file():
                found.append((position, name, real))
    return found


def runs(context: Context, params: Mapping[str, str]) -> Response:
    """The runs the roots hold, each with its run id and manifest id, or why it is unreadable."""
    listed: list[dict[str, object]] = []
    for position, name, run_dir in run_directories(context.allowlist):
        entry: dict[str, object] = {"root": position, "name": name}
        try:
            config = load_run_config(context.allowlist.resolve(run_dir / RUN_CONFIG))
        except (OrchestratorError, UIError) as exc:
            entry |= {"error": str(exc)}
        else:
            entry |= {
                "run_id": config.run_id,
                "manifest_id": config.sha256(),
                "gate_mode": config.gate_mode,
            }
        listed.append(entry)
    return json_response({"runs": listed})


#: Every route the server answers. The enumeration test walks this tuple.
ROUTES: tuple[Route, ...] = (
    Route("GET", "/", "read", index),
    Route("GET", "/assets/{name:asset}", "read", asset),
    Route("GET", "/api/runs", "read", runs),
)


def methods(routes: tuple[Route, ...]) -> frozenset[str]:
    """The methods the table names, plus HEAD wherever GET is: everything else is a 405."""
    named = {route.method for route in routes}
    return frozenset(named | ({"HEAD"} if "GET" in named else set()))
