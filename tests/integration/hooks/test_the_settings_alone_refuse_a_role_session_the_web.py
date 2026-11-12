"""Through the real binary: with the tools hook off, the settings alone refuse a role its WebFetch.

A role or baseline session is offered WebSearch and WebFetch by the binary, and the tools hook
was the only layer that refused them: ``network: none`` binds a session's shell commands, not the
binary's own WebFetch tool, on the pinned 2.1.301. So the generated settings deny both web tools
to every profile, a rule that binds in ``bypassPermissions``. Here the tools hook is not wired at
all, the session is a role's, and its scripted WebFetch names a listener on this machine's
loopback: neither web tool is offered, the call is refused as disabled, no hook refuses anything,
and nothing connects to the listener.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fake_messages_api import Script, text, tool
from hook_session import run_session

from physgate.hooks.registry import REGISTRY

pytestmark = pytest.mark.integration


@contextmanager
def _listening() -> Iterator[tuple[str, list[bytes]]]:
    """A loopback listener that records every connection's first bytes; yields its URL."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    server.settimeout(0.2)
    seen: list[bytes] = []
    stop = threading.Event()

    def accept() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1)
                try:
                    seen.append(conn.recv(256))
                except OSError:
                    seen.append(b"")

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.getsockname()[1]}/page", seen
    finally:
        stop.set()
        thread.join(timeout=5)
        server.close()


def test_with_the_tools_hook_off_the_settings_refuse_a_role_session_s_web_fetch(
    tmp_path: Path,
) -> None:
    without_tools = {name: spec for name, spec in REGISTRY.items() if name != "tools"}
    assert "tools" in REGISTRY and "tools" not in without_tools
    with _listening() as (url, seen):
        run = run_session(
            tmp_path,
            Script(main=[tool("WebFetch", url=url, prompt="summarise"), text("end")]),
            registry=without_tools,
        )
    # Nothing reached the listener: without the deny rule the binary's WebFetch connected to it
    # (measured on 2.1.301, the URL upgraded to HTTPS). The settings took both web tools out of
    # the session: a tool denied by name is not offered, and a call to it is refused as disabled.
    assert seen == []
    offered = {name for r in run.api.requests if r.thread == "main" for name in r.offered_tools}
    assert offered and not {"WebFetch", "WebSearch"} & offered, offered
    told = run.told_after(1)
    assert "WebFetch is disabled for this session" in told, told
    # No hook decided: the tools hook is not wired, and no other hook refused the call.
    assert [e for e in run.hook_log if e.get("hook") == "tools"] == []
    assert [e for e in run.hook_log if e.get("decision") == "refuse"] == []
    # The layer that refused is the settings file the session was given.
    assert {"WebFetch", "WebSearch"} <= set(run.settings.get("permissions", {}).get("deny", ()))
