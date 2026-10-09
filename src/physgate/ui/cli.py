"""``physgate ui``: serve the operator UI on loopback, over the roots named and nothing else.

The roots are the only directories the server reads beneath. Each is a run
directory, or a directory whose direct children are run directories. The
held-out tier and any evaluation corpus that carries its answers are named the
way the hook layer takes them, explicit and absolute; the harness checkout's
own ``corpora`` is always refused; and a root that overlaps any of them refuses
the start. So does a missing or stale build of the app, and any address that is
not loopback.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from physgate.orchestrator.run_config import harness_root

#: The port the command listens on unless told otherwise.
DEFAULT_PORT = 8765

#: The address it binds unless told otherwise; only loopback is accepted.
DEFAULT_BIND = "127.0.0.1"


def _ui_root() -> Path | None:
    """The app's sources in the checkout this command runs from, or ``None`` with no checkout.

    Its own function so a test can name a fixture build.
    """
    root = harness_root()
    return None if root is None else root / "ui"


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register ``physgate ui`` on the top-level command."""
    p = subparsers.add_parser(
        "ui",
        help="serve the operator UI on loopback, read-only, over the roots named",
        description=__doc__,
    )
    p.add_argument(
        "--root",
        action="append",
        required=True,
        dest="roots",
        help="a run directory, or a directory of run directories; repeat for more",
    )
    p.add_argument("--held-out", action="append", default=[], help="an absolute path never read")
    p.add_argument(
        "--answer-key",
        action="append",
        default=[],
        help="an absolute path of a corpus carrying its answers, never read",
    )
    p.add_argument("--bind", default=DEFAULT_BIND, help="127.0.0.1 or ::1; nothing else")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.set_defaults(func=_serve)


def _fail(message: str, **context: str) -> int:
    print(json.dumps({"error": message, **context}, sort_keys=True), file=sys.stderr)
    return 2


def _serve(args: argparse.Namespace) -> int:
    from physgate.ui import assets
    from physgate.ui.exceptions import StartupRefusedError
    from physgate.ui.paths import Allowlist
    from physgate.ui.routes import Context
    from physgate.ui.server import make_server, require_loopback

    try:
        require_loopback(args.bind)
        allowlist = Allowlist.build(
            args.roots,
            held_out=args.held_out,
            answer_keys=args.answer_key,
            harness=harness_root(),
        )
        ui_root = _ui_root()
        if ui_root is None:
            msg = "the operator UI is served from a source checkout, and this is none"
            raise StartupRefusedError(msg)
        built = assets.load(ui_root)
        server = make_server(
            Context(allowlist=allowlist, assets=built), bind=args.bind, port=args.port
        )
    except StartupRefusedError as exc:
        return _fail(str(exc), **exc.context)
    except OSError as exc:
        return _fail("the server could not listen", reason=str(exc))
    host, port = str(args.bind), int(server.server_address[1])
    literal = f"[{host}]" if ":" in host else host
    print(
        json.dumps(
            {
                "url": f"http://{literal}:{port}/",
                "roots": [str(root.path) for root in allowlist.roots],
                "refused": list(allowlist.refused),
            },
            indent=1,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
