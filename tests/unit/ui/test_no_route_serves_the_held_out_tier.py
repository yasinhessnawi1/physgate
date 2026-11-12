"""No route's answer carries the held-out tier: not a root, not a canary, not a root's digest.

A run that protects a held-out tier records its roots, the canary each held-out task carries and
each root's digest in ``run.json``. The UI keeps the tier out of every screen, and its server must
keep it out of every answer too: a canary a session can read from the loopback server may then
turn up in that session's stream, raising a false incident or telling it what to avoid, and a
root names where the tier lives.

The run here is made by the real loop with a tier of two roots, and escalated, so its queue holds
an item and every route over it has a record to serve. The config route is asked first and on its
own; then every GET route in the table is asked, and no answer may hold any of the tier's strings.
Every check first asserts the record it reads carries them, so a fixture that lost its tier would
fail rather than pass.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import pytest
from ui_library_rig import STANDARDS_CANDIDATE, build_library
from ui_rig import context_over, evaluation_rig, fake_ui, sealed_session, serving

from physgate.orchestrator.protocols import QuantityRef
from physgate.orchestrator.run_config import load_run_config
from physgate.state.store import journal_records_after
from physgate.ui import engines
from physgate.ui.routes import Route
from physgate.ui.table import ROUTES

#: The checkout itself, whose engine catalogue the sweep serves, so that route has a record too.
REPO = Path(__file__).resolve().parents[3]
RUN = "run-held"
PRICES = "2026-09-27"
#: The tier's fields in the record, each of which no answer may carry.
TIER_FIELDS = ("held_out", "held_out_canaries", "held_out_sha256")
#: One canary per held-out task: 32 hexadecimal characters, as the record's type requires.
CANARIES = ("5e1d7a0c9b3f42e8a6c1d0f7b2e94a37", "c0ffee5a7d2b4e19a8f63c0d1e2b7a95")
#: Routes this run has no record for: it made no later decomposition round.
NOT_RECORDED = {"/api/runs/{root:index}/{name:name}/trajectories/decomposition/{round:round}"}


def _digest(name: str) -> str:
    return hashlib.sha256(f"held-out root {name}".encode()).hexdigest()


@dataclass(frozen=True)
class World:
    #: The root the run lies under.
    runs: Path
    #: The held-out tier's roots, beside the root.
    roots: tuple[Path, ...]
    #: The fixture build.
    ui: Path
    #: The fixture library, so the library's routes have a record to serve too.
    library: Path


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    """One escalated run under a root, made with a held-out tier of two roots beside it."""
    # The trace route parses a time, and Python imports its parser on first use. Under a bytecode
    # cache outside the roots (a fresh ``PYTHONPYCACHEPREFIX``) that import is an open the guard
    # refuses, a 500 that says nothing of the tier; parsed once here, the sweep reads the answer.
    datetime.strptime("2026", "%Y")

    rig = evaluation_rig()
    base = tmp_path_factory.mktemp("held-world")
    tier = base / "tier"
    roots = tuple(tier / name for name in ("scenarios-7c1e", "answers-4b9d"))
    for root in roots:
        root.mkdir(parents=True)
        (root / "task.json").write_text("{}\n")
    cited = (
        QuantityRef(node_id="electrical.motor_driver", name="stall_current", value=3.4, unit="A"),
        QuantityRef(node_id="electrical.motor_driver", name="current_limit", value=2.5, unit="A"),
    )
    runs = base / "runs"
    rig.fake_run(
        runs,
        RUN,
        rig.target_repo(base / RUN),
        gate=rig.Gate(fail_on={1, 2, 3}, cited=cited),
        overrides={
            "held_out": tuple(str(r) for r in roots),
            "held_out_canaries": CANARIES,
            "held_out_sha256": tuple(_digest(r.name) for r in roots),
        },
    )
    return World(
        runs=runs,
        roots=roots,
        ui=fake_ui(base / "checkout"),
        library=build_library(base / "checkout").root,
    )


def _tier_strings(world: World) -> list[str]:
    """Every string that names the tier, each asserted present in the run's record."""
    record = (world.runs / RUN / "run.json").read_text()
    names = [*CANARIES, *(_digest(r.name) for r in world.roots)]
    for root in world.roots:
        names += [str(root), os.path.realpath(root)]
    for name in names:
        assert name in record, f"the fixture's record no longer carries {name!r}"
    # A root's own name says where the tier lives as plainly as its whole path.
    return [*names, *(r.name for r in world.roots)]


def _serve(world: World, *targets: str) -> list[tuple[str, int, bytes]]:
    held_out = tuple(str(r) for r in world.roots)
    answers = []
    context = context_over(world.runs, ui_root=world.ui, held_out=held_out, library=world.library)
    context = replace(context, engines=engines.load(REPO, context.allowlist))
    with serving(context) as live:
        for target in targets:
            status, _, body = live.request("GET", target)
            answers.append((target, status, body))
    return answers


def test_the_config_route_serves_no_root_canary_or_digest_of_the_tier(
    world: World,
) -> None:
    leaks = _tier_strings(world)
    ((_, status, body),) = _serve(world, f"/api/runs/0/{RUN}/config")
    assert status == 200, body[:300]
    text = body.decode()
    assert [s for s in leaks if s in text] == []
    served = json.loads(body)
    assert [f for f in TIER_FIELDS if f in served["config"]] == []


def test_the_config_route_still_serves_the_rest_of_the_record_and_its_manifest_id(
    world: World,
) -> None:
    """Only the tier is withheld: every other field is the record's, and the id is the record's."""
    recorded = load_run_config(world.runs / RUN / "run.json")
    ((_, status, body),) = _serve(world, f"/api/runs/0/{RUN}/config")
    assert status == 200, body[:300]
    served = json.loads(body)
    whole = recorded.model_dump(mode="json")
    assert all(whole[f] for f in TIER_FIELDS), "the record carries no tier to withhold"
    assert served["config"] == {k: v for k, v in whole.items() if k not in TIER_FIELDS}
    assert served["manifest_id"] == recorded.sha256()


def _valid(world: World) -> dict[str, str]:
    run_dir = world.runs / RUN
    return {
        "index": "0",
        "name": RUN,
        "asset": "app.js",
        "session": sealed_session(run_dir),
        "date": PRICES,
        "revision": "1",
        "round": "2",
        "node": journal_records_after(run_dir / "store", 0)[-1].node_id,
        "library_file": "standards",
        "role": "control",
        "candidate": STANDARDS_CANDIDATE,
    }


def _target(route: Route, valid: dict[str, str]) -> str:
    parts = [valid[kind] if kind else name for name, kind in route.segments]
    return "/" + "/".join(parts)


def test_no_get_route_serves_a_root_canary_or_digest_of_the_tier(
    world: World,
) -> None:
    leaks = _tier_strings(world)
    gets = [route for route in ROUTES if route.method == "GET"]
    assert len(gets) == len(ROUTES) - 1, "every route but the decision is a GET"
    valid = _valid(world)
    answers = _serve(world, *(_target(route, valid) for route in gets))
    statuses = {route.pattern: status for route, (_, status, _) in zip(gets, answers, strict=True)}
    # Every route answered with its record, so the sweep read what each route really serves.
    refused = {t: (s, b[:300]) for t, s, b in answers if s != 200}
    assert {p for p, s in statuses.items() if s != 200} == NOT_RECORDED, refused
    found = {
        target: [s for s in leaks if s in body.decode(errors="replace")]
        for target, _, body in answers
    }
    assert {t: f for t, f in found.items() if f} == {}
