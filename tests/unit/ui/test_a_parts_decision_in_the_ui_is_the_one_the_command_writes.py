"""A part's decision taken in the UI is the body of the one decision route, and the command's line.

ARCH-122. A run that asks which parts a person has lists one item per component, and the person
chooses have, make or find on each. The request carries what a choice of have or make states of
the part (each value with its unit, and a made part's texts) as one more body field of the same
route: the same act token and operator, the same decision function under its lock, the same
201/400/403/409 answers. So a part decided here is the line ``physgate queue resolve --choose``
writes with ``--declare`` and ``--text``, byte for byte, and it is refused where that refuses it.
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import FIXTURE_ROLES, write_fixture
from ui_rig import context_over, fake_ui, serving

from physgate.cli import main
from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.decompose import start_run
from physgate.orchestrator.plan import PartsPlan
from physgate.orchestrator.queue import DECISIONS_NAME, read_queue
from physgate.ui.server import ACT_TOKEN_HEADER

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
import design_review_rig  # noqa: E402
from plan_hold_rig import PRESENT  # noqa: E402

RUN = design_review_rig.RUN_ID
FIXED = datetime(2026, 11, 15, 9, 30, 0, 654321, tzinfo=UTC)
#: Two parts of the stand-in plan: one whose values a person may state, one they may make.
COMPONENTS = (
    {
        "node": "control.motor_left",
        "domain": "electrical",
        "role": "control",
        "label": "Left drive motor",
        "own": ["mass", "stall_current"],
        "shared": [],
    },
    {
        "node": "control.bracket",
        "domain": "mechanical",
        "role": "control",
        "label": "Motor bracket",
        "own": ["mass"],
        "shared": [],
    },
)


@pytest.fixture(autouse=True)
def _pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(queue_module, "utc_now", lambda: FIXED)


def _asking_run(base: Path) -> Path:
    """A run started as ``decompose`` starts one that asks: its parts' items listed, open."""
    repo = design_review_rig.target_repo(base)
    library = base / "library"
    write_fixture(library, (*FIXTURE_ROLES, *design_review_rig.ROLES))
    run_dir = base / "runs" / RUN
    answer = json.loads(design_review_rig.plan().model_dump_json())
    plan = PartsPlan.model_validate_json(json.dumps({**answer, "components": list(COMPONENTS)}))
    start_run(
        design_review_rig.outcome(run_dir, plan),
        config=design_review_rig.config(
            repo, "off", parts_on_hand="on", queue_decisions="act", os_layer=PRESENT
        ),
        run_dir=run_dir,
        target_repo=repo,
        library=library,
        brief=design_review_rig.BRIEF,
    ).close()
    listed = [one.item_id for one in read_queue(run_dir).items]
    assert listed == [f"{RUN}-parts-1", f"{RUN}-parts-2"], listed
    return run_dir


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    return {"run": _asking_run(base), "ui": fake_ui(base / "checkout")}


def _copy(source: Path, root: Path) -> Path:
    target = root / source.name
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees"))
    return target


class Page:
    """Asks as the app's own page does, with its origin and the operator's token."""

    def __init__(self, port: int, token: str) -> None:
        self.port, self.token = port, token

    def _request(self, method: str, target: str, body: bytes = b"") -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"127.0.0.1:{self.port}")
        if method == "POST":
            connection.putheader("Origin", f"http://127.0.0.1:{self.port}")
            connection.putheader(ACT_TOKEN_HEADER, self.token)
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body if body else None)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def view(self, index: int = 0) -> dict[str, Any]:
        status, body = self._request("GET", f"/api/runs/0/{RUN}/queue/items/{index}")
        assert status == 200, body
        found: dict[str, Any] = json.loads(body)
        return found

    def decide(self, payload: dict[str, Any]) -> tuple[int, bytes]:
        return self.send(json.dumps(payload).encode())

    def send(self, body: bytes) -> tuple[int, bytes]:
        """The route asked with ``body`` as it stands: a JSON number no encoder writes."""
        return self._request("POST", f"/api/runs/0/{RUN}/queue/decisions", body)


def _decision(view: dict[str, Any], position: str, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    item, trajectories = view["item"], view["trajectories"]
    return {
        "item_id": item["item_id"],
        "verb": "choose",
        "position": position,
        "note": "",
        "shown": {
            "item_sha256": view["item_sha256"],
            "trajectories": [t["status"] for t in trajectories],
        },
    } | fields


def _body(declared: dict[str, tuple[Any, Any]], texts: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "declared": {name: {"value": v, "unit": u} for name, (v, u) in declared.items()},
        "texts": list(texts),
    }


@pytest.fixture
def served(built: dict[str, Path], tmp_path: Path) -> Iterator[tuple[Page, Path]]:
    root = tmp_path / "ui-root"
    root.mkdir()
    run_dir = _copy(built["run"], root)
    context = replace(context_over(root, ui_root=built["ui"]), operator="operator")
    with serving(context) as live:
        yield Page(live.port, live.token), run_dir


#: Each choice, the command's own flags for it, and the body the page sends for it.
CHOICES = [
    pytest.param(
        "have",
        ["--declare", "mass=0.0095:kg", "--declare", "stall_current=1.6:A"],
        _body({"mass": (0.0095, "kg"), "stall_current": (1.6, "A")}),
        id="have, two values",
    ),
    pytest.param(
        "make",
        ["--declare", "mass=0.012:kg", "--text", "printed in PETG, walls at least 2 mm"],
        _body({"mass": (0.012, "kg")}, ("printed in PETG, walls at least 2 mm",)),
        id="make, a value and a text",
    ),
    pytest.param(
        "make", ["--text", "fits the kit's M3 holes"], _body({}, ("fits the kit's M3 holes",)),
        id="make, a text alone",
    ),
    pytest.param("find", [], None, id="find, nothing stated"),
]  # fmt: skip


@pytest.mark.parametrize(("position", "flags", "parts"), CHOICES)
def test_a_part_decided_in_the_ui_writes_exactly_what_the_command_writes(
    built: dict[str, Path],
    served: tuple[Page, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    position: str,
    flags: list[str],
    parts: dict[str, Any] | None,
) -> None:
    page, run_dir = served
    by_command = _copy(built["run"], tmp_path / "command-root")
    view = read_queue(by_command)
    item_id = view.items[0].item_id
    try:
        code = main(
            ["queue", "resolve", item_id, "--run-dir", str(by_command), "--choose", position,
             *flags, "--sha256", view.digests[item_id], "--by", "operator"]
        )  # fmt: skip
    except SystemExit as exc:
        code = int(exc.code or 0)
    printed = capsys.readouterr().out
    assert code == 0, printed
    sent = _decision(page.view(), position) | ({} if parts is None else {"parts": parts})
    status, answered = page.decide(sent)
    assert status == 201, answered
    assert answered.decode() == printed
    written = (run_dir / DECISIONS_NAME).read_bytes()
    assert written == (by_command / DECISIONS_NAME).read_bytes()
    line = json.loads(written)
    assert line["position"] == position
    assert line.get("parts") == parts


def test_a_body_with_no_parts_field_is_the_decision_it_always_was(
    served: tuple[Page, Path],
) -> None:
    page, run_dir = served
    status, answered = page.decide(_decision(page.view(), "find"))
    assert status == 201, answered
    assert "parts" not in json.loads((run_dir / DECISIONS_NAME).read_bytes())


#: A body that is not one a decision can carry: refused before the queue is asked, with 400.
MALFORMED = [
    pytest.param({"declared": {"mass": 0.0095}, "texts": []}, "parts.declared.mass", id="bare"),
    pytest.param(_body({"mass": (0.0095, "")}), "parts.declared.mass.unit", id="blank unit"),
    pytest.param({"declared": {}}, "parts.texts", id="texts left out"),
    pytest.param(
        _body({"mass": (0.0095, "kg")}) | {"source": "datasheet"}, "parts.source", id="extra field"
    ),
    pytest.param(_body({"stall_current": (1.6, "kg")}), "'stall_current'", id="wrong dimension"),
    pytest.param(_body({"mass": (float("nan"), "kg")}), "finite", id="not a number"),
    pytest.param(_body({"mass": (10**400, "kg")}), "finite", id="an integer past a float"),
    pytest.param(_body({"mass": (2 * 10**308, "kg")}), "finite", id="309 digits, past a float"),
    pytest.param(_body({"mass": (-(10**309), "kg")}), "finite", id="310 digits, negative"),
]


@pytest.mark.parametrize(("parts", "says"), MALFORMED)
def test_a_body_that_is_not_a_part_s_values_is_refused_with_400_and_writes_nothing(
    served: tuple[Page, Path], parts: dict[str, Any], says: str
) -> None:
    page, run_dir = served
    status, body = page.decide(_decision(page.view(), "have", parts=parts))
    assert status == 400, body
    assert b"not a decision" in body
    assert says in body.decode(), body
    assert b"Extra inputs are not permitted" not in body or says == "parts.source", body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


@pytest.mark.parametrize("number", [b"1e999", b"-1e999"], ids=["1e999", "-1e999"])
def test_a_number_past_a_float_written_as_an_exponent_is_refused_with_400(
    served: tuple[Page, Path], number: bytes
) -> None:
    # No encoder writes it, so the body is sent as text: a reader that turns it into an infinity
    # and one that refuses the number both answer 400, and nothing is written or raised.
    page, run_dir = served
    held = "__the_number__"
    sent = json.dumps(_decision(page.view(), "have", parts=_body({"mass": (held, "kg")})))
    status, body = page.send(sent.replace(f'"{held}"', number.decode()).encode())
    assert status == 400, body
    assert b"not a decision" in body, body
    assert number not in body, body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


#: A body the route reads, on a decision the queue does not record with it: 409, as the command.
MISMATCHED = [
    pytest.param("find", _body({"mass": (0.0095, "kg")}), "choosing find states nothing", id="f"),
    pytest.param("have", None, "choosing have states at least one value", id="have, no body"),
    pytest.param(
        "have", _body({"mass": (0.0095, "kg")}, ("a text",)), "and no text", id="have, a text"
    ),
    pytest.param("make", _body({}), "choosing make states at least one value or one text", id="m"),
]


@pytest.mark.parametrize(("position", "parts", "says"), MISMATCHED)
def test_a_body_that_does_not_go_with_its_choice_is_refused_with_409_as_the_command_refuses_it(
    built: dict[str, Path],
    served: tuple[Page, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    position: str,
    parts: dict[str, Any] | None,
    says: str,
) -> None:
    page, run_dir = served
    sent = _decision(page.view(), position) | ({} if parts is None else {"parts": parts})
    status, body = page.decide(sent)
    assert status == 409, body
    assert says in body.decode(), body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""
    by_command = _copy(built["run"], tmp_path / "command-root")
    view = read_queue(by_command)
    item_id = view.items[0].item_id
    flags = [
        flag
        for name, stated in (parts or {"declared": {}})["declared"].items()
        for flag in ("--declare", f"{name}={stated['value']}:{stated['unit']}")
    ] + [flag for text in (parts or {}).get("texts", []) for flag in ("--text", text)]
    code = main(
        ["queue", "resolve", item_id, "--run-dir", str(by_command), "--choose", position,
         *flags, "--sha256", view.digests[item_id], "--by", "operator"]
    )  # fmt: skip
    assert code != 0
    assert says in capsys.readouterr().err
    assert (by_command / DECISIONS_NAME).read_bytes() == b""


def test_a_body_with_a_verb_that_is_no_choice_is_refused_with_409(
    served: tuple[Page, Path],
) -> None:
    page, run_dir = served
    approval = {"verb": "approve", "position": None, "parts": _body({"mass": (1, "kg")})}
    status, body = page.decide(_decision(page.view(), "have") | approval)
    assert status == 409, body
    assert b"only a choice of have or make states a part's values" in body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


def test_a_part_s_body_without_the_act_token_is_refused_with_403_and_writes_nothing(
    served: tuple[Page, Path],
) -> None:
    # A control: the token is checked before the body is read, before and after the body field.
    page, run_dir = served
    page.token = "not-the-token"
    status, body = page.decide(_decision(page.view(), "have", parts=_body({"mass": (1, "kg")})))
    assert status == 403, body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""
