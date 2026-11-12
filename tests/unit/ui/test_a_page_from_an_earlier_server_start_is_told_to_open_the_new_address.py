"""A page from an earlier start of the server is told the server restarted, and what to open.

Every start of ``physgate ui --operator`` mints a new action token, and a run's scripts restart
the UI at each resume. A page opened before the restart still holds the earlier token, and its
decision is refused. The refusal says why in plain words: the server was restarted since the page
was opened, and the newest operator address in the run's ui.out is the one that decides.
"""

from __future__ import annotations

from pathlib import Path

from test_an_action_is_taken_only_from_this_server_s_page_and_only_through_the_queue import (
    Client,
    _context,
    _index_route,
    _recording_route,
    called,  # noqa: F401 - the fixture the routes record into
    run,  # noqa: F401 - the run fixture
)
from ui_rig import serving


def test_a_token_from_an_earlier_start_is_refused_with_how_to_decide(
    run: Path,  # noqa: F811
    called: list[bytes],  # noqa: F811
) -> None:
    routes = (_index_route(), _recording_route(called))
    with serving(_context(run), routes=routes) as first:
        earlier = first.token
    with serving(_context(run), routes=routes) as second:
        client = Client(second.port, earlier)
        status, _, body = client.act()
    assert status == 403
    said = body.decode()
    assert "restarted" in said, said
    assert "ui.out" in said, said
    assert called == []
