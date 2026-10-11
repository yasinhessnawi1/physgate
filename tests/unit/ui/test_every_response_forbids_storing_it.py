"""Every answer the server gives says it must not be stored, the operator's page included.

The operator's page is opened at an address whose fragment carries the action token. A
browser that kept the page in its disk cache would keep that address with it, where another
process of the same user could read the token and act. So every response, the page, every
route, every method and every refusal, carries ``Cache-Control: no-store``, and this test holds
the server to that for a read-only server and for an operator's.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from ui_rig import METHODS, context_over, escalated_run, fake_ui, real_runs, sealed_session, serving

from physgate.state.store import journal_records_after
from physgate.ui.routes import Context
from physgate.ui.table import ROUTES

RUN = "run-esc"


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Real runs, one of them escalated, and a stamped build; built once for the module."""
    base = tmp_path_factory.mktemp("world")
    root = real_runs(base)
    escalated_run(base)
    ui = fake_ui(base / "checkout")
    return {"root": root, "ui": ui}


def _targets(world: dict[str, Path]) -> list[str]:
    """The page, every route filled with the escalated run's real values, and three misses."""
    run = world["root"] / RUN
    valid = {
        "index": "0",
        "name": RUN,
        "asset": "app.js",
        "session": sealed_session(run),
        "date": "2026-09-27",
        "revision": "1",
        "node": journal_records_after(run / "store", 0)[-1].node_id,
    }
    targets = ["/", "/no/such/route", "/api/runs/0/..%2f/ledger", "/?query=1"]
    for route in ROUTES:
        parts = [valid[kind] if kind else name for name, kind in route.segments]
        targets.append("/" + "/".join(parts))
    return list(dict.fromkeys(targets))


def _contexts(world: dict[str, Path]) -> list[Context]:
    plain = context_over(world["root"], ui_root=world["ui"])
    return [plain, replace(plain, operator="Ada Lovelace")]


def test_every_method_on_every_route_answers_no_store(world: dict[str, Path]) -> None:
    targets = _targets(world)
    assert len(targets) > len(ROUTES), "the sweep must reach every route"
    seen = 0
    for context in _contexts(world):
        with serving(context) as live:
            for target in targets:
                for method in METHODS:
                    status, headers, _ = live.request(method, target)
                    assert headers.get("cache-control") == "no-store", (
                        f"{method} {target} answered {status} without no-store: {headers}"
                    )
                    seen += 1
    assert seen == 2 * len(targets) * len(METHODS)


def test_a_refused_host_or_origin_is_answered_no_store_too(world: dict[str, Path]) -> None:
    for context in _contexts(world):
        with serving(context) as live:
            for host, headers in (
                ("evil.example", {}),
                (None, {"Origin": "http://evil.example"}),
            ):
                status, answered, _ = live.request("GET", "/", host=host, headers=headers)
                assert status == 403
                assert answered.get("cache-control") == "no-store"
