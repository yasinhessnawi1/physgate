"""A choice taken in the UI goes through the same route and decision function as every decision.

The request carries the position with ``choose`` and with no other verb; the route hands both to
the queue's own decision function, so a choice is the line ``physgate queue resolve --choose``
writes, and it is refused where that refuses it: on an item whose kind offers no positions, and
for the domain's position on a view whose transcripts did not all hold their seal.
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

import pytest
from ui_rig import context_over, escalated_run, fake_ui, serving

from physgate import roles
from physgate.cli import main
from physgate.orchestrator import queue as queue_module
from physgate.orchestrator.queue import DECISIONS_NAME, read_queue
from physgate.ui.server import ACT_TOKEN_HEADER

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from arbitration_runs import driven, rig_of  # noqa: E402

ARB = "run-arb"
ESC = "run-esc"
FIXED = datetime(2026, 10, 30, 9, 30, 0, 654321, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
    monkeypatch.setattr(queue_module, "utc_now", lambda: FIXED)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("built")
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)
        arbitration = base / "arb" / ARB
        driven(rig_of(arbitration))
    return {
        "arb": arbitration,
        "esc": escalated_run(base, ESC, acts=True),
        "ui": fake_ui(base / "checkout"),
    }


def _copy(source: Path, root: Path) -> Path:
    target = root / source.name
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("worktrees"))
    return target


class Page:
    """Asks as the app's own page does, with its origin and the operator's token."""

    def __init__(self, port: int, token: str, run: str) -> None:
        self.port, self.token, self.run = port, token, run

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

    def view(self) -> dict[str, object]:
        status, body = self._request("GET", f"/api/runs/0/{self.run}/queue/items/0")
        assert status == 200, body
        found: dict[str, object] = json.loads(body)
        return found

    def decide(self, payload: dict[str, object]) -> tuple[int, bytes]:
        body = json.dumps(payload).encode()
        return self._request("POST", f"/api/runs/0/{self.run}/queue/decisions", body)


def _decision(view: dict[str, object], **fields: object) -> dict[str, object]:
    item = view["item"]
    trajectories = view["trajectories"]
    assert isinstance(item, dict) and isinstance(trajectories, list)
    return {
        "item_id": item["item_id"],
        "verb": "choose",
        "position": "domain",
        "note": "",
        "shown": {
            "item_sha256": view["item_sha256"],
            "trajectories": [t["status"] for t in trajectories],
        },
    } | fields


@pytest.fixture
def served(built: dict[str, Path], tmp_path: Path) -> Iterator[dict[str, tuple[Page, Path]]]:
    root = tmp_path / "ui-root"
    root.mkdir()
    arb, esc = _copy(built["arb"], root), _copy(built["esc"], root)
    context = replace(context_over(root, ui_root=built["ui"]), operator="yasin")
    with serving(context) as live:
        yield {
            "arb": (Page(live.port, live.token, ARB), arb),
            "esc": (Page(live.port, live.token, ESC), esc),
        }


@pytest.mark.parametrize(("position", "note"), [("domain", ""), ("sizing", "keep 24 V")])
def test_a_choice_in_the_ui_writes_exactly_what_the_command_writes(
    built: dict[str, Path],
    served: dict[str, tuple[Page, Path]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    position: str,
    note: str,
) -> None:
    page, run_dir = served["arb"]
    by_command = _copy(built["arb"], tmp_path / "command-root")
    view = read_queue(by_command)
    item_id = view.items[0].item_id
    noted = ["--note", note] if note else []
    try:
        code = main(
            ["queue", "resolve", item_id, "--run-dir", str(by_command), "--choose", position,
             *noted, "--sha256", view.digests[item_id], "--by", "yasin"]
        )  # fmt: skip
    except SystemExit as exc:
        code = int(exc.code or 0)
    printed = capsys.readouterr().out
    assert code == 0, printed
    status, answered = page.decide(_decision(page.view(), position=position, note=note))
    assert status == 201, answered
    assert answered.decode() == printed
    assert (run_dir / DECISIONS_NAME).read_bytes() == (by_command / DECISIONS_NAME).read_bytes()
    assert json.loads((run_dir / DECISIONS_NAME).read_bytes())["position"] == position


@pytest.mark.parametrize(
    ("fields", "says"),
    [({"position": None}, "a position is chosen with choose, and only with it"),
     ({"verb": "approve", "position": "domain"}, "a position is chosen with choose, and only"),
     ({"position": "builder"}, "'sizing', 'domain'")],
    ids=["choose without a position", "a position on approve", "outside the set"],
)  # fmt: skip
def test_a_choice_that_is_not_one_is_refused_with_400(
    served: dict[str, tuple[Page, Path]], fields: dict[str, object], says: str
) -> None:
    page, run_dir = served["arb"]
    status, body = page.decide(_decision(page.view(), **fields))
    assert status == 400, body
    assert b"not a decision" in body
    assert says in body.decode(), body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


def test_a_position_another_kind_of_item_offers_is_refused_with_409(
    served: dict[str, tuple[Page, Path]],
) -> None:
    page, run_dir = served["arb"]
    status, body = page.decide(_decision(page.view(), position="producer"))
    assert status == 409, body
    assert b"a position the item's kind does not offer: it offers sizing, domain" in body
    assert (run_dir / DECISIONS_NAME).read_bytes() == b""


def test_a_choice_on_an_item_of_another_kind_is_refused_with_409(
    served: dict[str, tuple[Page, Path]],
) -> None:
    page, run_dir = served["esc"]
    before = (run_dir / DECISIONS_NAME).read_bytes()
    status, body = page.decide(_decision(page.view(), position="sizing"))
    assert status == 409, body
    assert b"a choice is made only on an item whose kind offers positions" in body
    assert (run_dir / DECISIONS_NAME).read_bytes() == before


def test_choosing_the_domain_on_a_view_with_a_broken_seal_is_refused_with_409(
    served: dict[str, tuple[Page, Path]],
) -> None:
    page, run_dir = served["arb"]
    trajectories = page.view()["trajectories"]
    assert isinstance(trajectories, list)
    stream = run_dir / "sessions" / str(trajectories[0]["session_id"]) / "stdout.jsonl"
    stream.write_bytes(stream.read_bytes() + b"{}\n")
    view = page.view()
    shown = view["trajectories"]
    assert isinstance(shown, list)
    assert [t["status"] for t in shown].count("tampered") == 1
    status, body = page.decide(_decision(view))
    assert status == 409, body
    assert b"held its seal" in body
    status, body = page.decide(_decision(view, position="sizing"))
    assert status == 201, body
