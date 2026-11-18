"""The server answers its own table and what the command's composition root registers beside it.

The Evidence screen's routes read evaluation records, and no module of the UI package may import
the evaluation (the pinned list may only shrink). So the routes are registered the way the
evaluation's run requirements are: from the command's entry point, the one module that wires the
evaluation into the core. The table takes only reads that do not overlap its own routes, and only
once; with nothing registered the server answers exactly the product's table.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest
from ui_rig import fake_ui

import physgate
from physgate.cli import compose, main
from physgate.evaluation import evidence
from physgate.evaluation.gaps import published
from physgate.evaluation.observe import compare
from physgate.orchestrator import catches as catch_count
from physgate.ui import cli as ui_cli
from physgate.ui import server as ui_server
from physgate.ui import table
from physgate.ui.exceptions import UnregisteredKindError
from physgate.ui.routes import Context, Response, Route, json_response
from physgate.ui.table import ROUTES, served

SRC = Path(physgate.__file__).parent

#: The routes the Evidence screen reads, as this slice registers them.
EVIDENCE_PATTERNS = {
    "/api/evidence/runs",
    "/api/evidence/spend/{root:index}/{name:name}/{date:date}",
    "/api/evidence/compare/{a_root:index}/{a_name:name}/{b_root:index}/{b_name:name}",
    "/api/evidence/catches",
    "/api/evidence/gaps",
}
#: The Evidence screen's routes over the comparison's own census, built here from the comparison
#: itself, so the root's registration equals them only if it hands in that census.
EVIDENCE_ROUTES = evidence.routes(
    evidence.Census(
        drift=compare.DRIFT,
        reported=compare.REPORTED,
        compare=compare.compare,
        catches=catch_count.catches,
        trend=evidence.TrendCensus(
            roles=published.ROLES,
            name=published.published_name,
            parse=published.read_published,
            refused=published.GapsError,
        ),
    )
)


def _answer(context: Context, params: Mapping[str, str]) -> Response:
    return json_response({})


@pytest.fixture
def nothing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The table as a core with no evaluation has it; restored after the test."""
    monkeypatch.setattr(table, "_registered", ())


@pytest.mark.usefixtures("nothing_registered")
def test_with_nothing_registered_the_server_answers_exactly_the_product_s_table() -> None:
    assert served() == ROUTES
    assert table.registered() == ()


@pytest.mark.usefixtures("nothing_registered")
def test_a_registered_read_is_served_after_every_route_of_the_product() -> None:
    extra = Route("GET", "/api/extra", "read", _answer)
    table.register((extra,))
    assert served() == (*ROUTES, extra)
    assert table.registered() == (extra,)


@pytest.mark.usefixtures("nothing_registered")
def test_the_table_refuses_to_register_a_route_that_acts() -> None:
    acting = Route("POST", "/api/extra", "act", _answer)
    with pytest.raises(ValueError, match="only reads are registered"):
        table.register((acting,))
    assert served() == ROUTES
    assert [route.kind for route in served()].count("act") == 1


@pytest.mark.usefixtures("nothing_registered")
def test_the_table_refuses_to_register_a_route_of_a_kind_the_guard_has_no_policy_for() -> None:
    forged = Route("GET", "/api/extra", "read", _answer)
    # A route cannot be declared with such a kind; one changed after it was declared is refused
    # at registration too, before any request reaches it.
    object.__setattr__(forged, "kind", "steer")
    with pytest.raises((UnregisteredKindError, ValueError)) as refused:
        table.register((forged,))
    # Refused by the guard's own register of policies, not only as something other than a read.
    assert isinstance(refused.value, UnregisteredKindError), refused.value
    assert "no policy" in str(refused.value)
    assert served() == ROUTES


@pytest.mark.usefixtures("nothing_registered")
@pytest.mark.parametrize(
    "pattern",
    [
        "/api/runs",
        # The product's run configuration route, under other parameter names: the same paths.
        "/api/runs/{r:index}/{n:name}/config",
    ],
)
def test_the_table_refuses_to_register_a_pattern_it_already_serves(pattern: str) -> None:
    with pytest.raises(ValueError, match="already served"):
        table.register((Route("GET", pattern, "read", _answer),))
    assert served() == ROUTES


@pytest.mark.usefixtures("nothing_registered")
def test_the_table_refuses_a_registration_that_names_one_pattern_twice() -> None:
    twice = (
        Route("GET", "/api/extra/{a:index}", "read", _answer),
        Route("GET", "/api/extra/{b:index}", "read", _answer),
    )
    with pytest.raises(ValueError, match="already served"):
        table.register(twice)
    assert served() == ROUTES


@pytest.mark.usefixtures("nothing_registered")
def test_the_table_takes_one_registration_and_the_same_again_changes_nothing() -> None:
    first = (Route("GET", "/api/extra", "read", _answer),)
    table.register(first)
    # The command's entry point runs once per command, and a test process runs it many times:
    # the same routes again are the same registration.
    try:
        table.register(first)
    except ValueError as exc:
        pytest.fail(f"the same routes again were refused: {exc}")
    with pytest.raises(ValueError, match="registered once"):
        table.register((Route("GET", "/api/other", "read", _answer),))
    assert served() == (*ROUTES, *first)


@pytest.mark.usefixtures("nothing_registered")
def test_the_composition_root_registers_exactly_the_evidence_routes() -> None:
    compose()
    assert table.registered() == EVIDENCE_ROUTES
    assert served() == (*ROUTES, *EVIDENCE_ROUTES)
    assert {route.pattern for route in EVIDENCE_ROUTES} == EVIDENCE_PATTERNS
    assert {(route.method, route.kind) for route in EVIDENCE_ROUTES} == {("GET", "read")}
    assert all(route.pattern.startswith("/api/evidence/") for route in EVIDENCE_ROUTES)


@pytest.mark.usefixtures("nothing_registered")
def test_the_routes_class_runs_by_the_comparison_s_own_lists_and_function() -> None:
    compose()
    handlers = {route.handler for route in table.registered()}
    assert handlers, "the root registered nothing"
    for handler in handlers:
        census = getattr(handler, "census", None)
        assert isinstance(census, evidence.Census), handler
        # The comparison's own objects, not copies of them: the two cannot drift apart.
        assert census.drift is compare.DRIFT
        assert census.reported is compare.REPORTED
        assert census.compare is compare.compare
        # The catch count is the command line's own function, handed in the same way.
        assert census.catches is catch_count.catches
        # The published gap trend's own name and parser, handed in the same way.
        assert census.trend.parse is published.read_published
        assert census.trend.name is published.published_name
        assert census.trend.roles is published.ROLES
        assert census.trend.refused is published.GapsError


def test_the_evidence_module_imports_nothing_of_the_comparison() -> None:
    tree = ast.parse(Path(str(evidence.__file__)).read_text())
    imported = [
        alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert [name for name in imported if "compare" in name] == []
    assert [name for name in imported if "catches" in name] == []
    assert [name for name in imported if "gaps" in name] == []


@pytest.mark.usefixtures("nothing_registered")
def test_the_command_registers_them_before_it_reads_its_arguments() -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert table.registered(), "the command registered nothing"
    assert table.registered() == EVIDENCE_ROUTES


@pytest.mark.usefixtures("nothing_registered")
def test_the_ui_command_serves_the_served_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runs"
    root.mkdir()
    ui = fake_ui(tmp_path / "checkout")
    monkeypatch.setattr(ui_cli, "_ui_root", lambda: ui)
    handed: list[tuple[Route, ...]] = []

    def recorded(context: Context, **kwargs: object) -> object:
        routes = kwargs.get("routes")
        assert isinstance(routes, tuple)
        handed.append(routes)
        msg = "stopped before listening"
        raise OSError(msg)

    monkeypatch.setattr(ui_server, "make_server", recorded)
    assert main(["ui", "--root", str(root), "--port", "0"]) == 2
    assert handed == [(*ROUTES, *EVIDENCE_ROUTES)]


def _calls_register(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "table"
        for node in ast.walk(tree)
    )


def test_only_the_composition_root_registers_routes_and_no_ui_module_names_the_evidence() -> None:
    registering = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if _calls_register(ast.parse(path.read_text()))
    )
    assert registering == ["cli.py"]
    naming = [
        str(path.relative_to(SRC))
        for path in (SRC / "ui").rglob("*.py")
        if "physgate.evaluation.evidence" in path.read_text()
        or "from physgate.evaluation import evidence" in path.read_text()
    ]
    assert naming == []
