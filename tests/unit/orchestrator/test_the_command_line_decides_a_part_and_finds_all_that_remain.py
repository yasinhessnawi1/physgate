"""The command line decides a part, and chooses find on every part still open, as a person.

ARCH-122. ``physgate queue resolve`` takes a part's choice with the values it states
(``--declare name=value:unit``, once per value) and a made part's texts (``--text``), and goes
through the one decision function, bound to the digest the listing printed. ``physgate queue
parts --find-remaining`` writes one ``choose find`` line per open part, each bound to its own
item's digest and naming who decided: a run can be released without the interface, and nothing
is chosen by code that a person did not ask for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from parts_rig import BRACKET, IMU, MOTOR, decisions_bytes, item, listed

from physgate.cli import main
from physgate.orchestrator.queue import read_queue

IDS = ["run-1-parts-1", "run-1-parts-2", "run-1-parts-3"]


def _run(tmp_path: Path) -> Path:
    return listed(tmp_path / "run", item(MOTOR, 1, 3), item(IMU, 2, 3), item(BRACKET, 3, 3))


def _main(*args: str) -> Any:  # noqa: ANN401 - the exit code, however the command ended
    try:
        return main(list(args))
    except SystemExit as exc:
        return exc.code


def _resolve(run_dir: Path, item_id: str, *args: str) -> Any:  # noqa: ANN401
    digest = read_queue(run_dir).digests[item_id]
    return _main(
        "queue", "resolve", item_id, "--run-dir", str(run_dir), "--sha256", digest,
        "--by", "yasin", *args,
    )  # fmt: skip


def _lines(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in decisions_bytes(run_dir).splitlines()]


def test_have_is_decided_with_each_value_it_states(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    code = _resolve(
        run_dir, IDS[0], "--choose", "have",
        "--declare", "mass=0.4:kg", "--declare", "stall_current=2:A",
    )  # fmt: skip
    assert code == 0
    (line,) = _lines(run_dir)
    assert (line["decision"], line["position"], line["resolved_by"]) == (
        "choose have",
        "have",
        "yasin",
    )
    assert line["parts"] == {
        "declared": {
            "mass": {"value": 0.4, "unit": "kg"},
            "stall_current": {"value": 2, "unit": "A"},
        },
        "texts": [],
    }
    # A whole number is written as one: 2, never 2.0, which equals it in Python and is not it.
    assert b'"stall_current":{"value":2,"unit":"A"}' in decisions_bytes(run_dir)
    assert line["shown_sha256"] == read_queue(run_dir).digests[IDS[0]]


def test_a_unit_may_hold_what_separates_a_value_from_it(tmp_path: Path) -> None:
    # The value ends at the first colon; a unit holds none, so nothing after it is lost.
    run_dir = _run(tmp_path)
    code = _resolve(run_dir, IDS[0], "--choose", "have", "--declare", "torque_constant=0.05:N*m/A")
    assert code == 0
    (line,) = _lines(run_dir)
    assert line["parts"]["declared"] == {"torque_constant": {"value": 0.05, "unit": "N*m/A"}}


def test_make_is_decided_with_its_texts_and_a_note(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    code = _resolve(
        run_dir, IDS[1], "--choose", "make", "--text", "printed in PETG", "--text", "3 mm walls",
        "--note", "my own",
    )  # fmt: skip
    assert code == 0
    (line,) = _lines(run_dir)
    assert line["decision"] == "choose make: my own"
    assert line["parts"] == {"declared": {}, "texts": ["printed in PETG", "3 mm walls"]}


def test_find_is_decided_with_nothing_stated(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    assert _resolve(run_dir, IDS[2], "--choose", "find") == 0
    (line,) = _lines(run_dir)
    assert line["decision"] == "choose find" and "parts" not in line


@pytest.mark.parametrize(
    "args",
    [
        ("--choose", "have"),  # nothing stated
        ("--choose", "have", "--declare", "mass"),
        ("--choose", "have", "--declare", "mass=0.4"),  # a bare number
        ("--choose", "have", "--declare", "mass=0.4:"),
        ("--choose", "have", "--declare", "=0.4:kg"),
        ("--choose", "have", "--declare", "mass=heavy:kg"),
        ("--choose", "have", "--declare", "mass=nan:kg"),
        ("--choose", "have", "--declare", "mass=0.4:A"),  # another dimension
        ("--choose", "have", "--declare", "mass=0.4:kg", "--declare", "mass=0.5:kg"),
        ("--choose", "find", "--declare", "mass=0.4:kg"),
        ("--choose", "find", "--text", "mine"),
        ("--approve", "--declare", "mass=0.4:kg"),
        ("--approve",),
        ("--reject", "--note", "no"),
    ],
)
def test_what_the_function_refuses_the_command_refuses_and_writes_nothing(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    run_dir = _run(tmp_path)
    assert _resolve(run_dir, IDS[0], "--choose", "find") == 0, "the command decides no part"
    before = decisions_bytes(run_dir)
    assert _resolve(run_dir, IDS[1], *args) == 2
    assert decisions_bytes(run_dir) == before


def test_free_text_decides_no_part(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    assert _resolve(run_dir, IDS[1], "--choose", "find") == 0, "the command decides no part"
    args = ("queue", "resolve", IDS[0], "--run-dir", str(run_dir), "--by", "yasin")
    assert _main(*args, "--decision", "I have one") == 2
    assert len(_lines(run_dir)) == 1


# --- find for all that remain ----------------------------------------------------------------


def _find_remaining(run_dir: Path, *args: str) -> Any:  # noqa: ANN401
    return _main("queue", "parts", "--run-dir", str(run_dir), *args)


def test_find_remaining_chooses_find_on_every_open_part_each_on_its_own_view(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _run(tmp_path)
    assert _resolve(run_dir, IDS[1], "--choose", "have", "--declare", "mass=0.02:kg") == 0
    capsys.readouterr()
    assert _find_remaining(run_dir, "--find-remaining", "--by", "yasin") == 0
    printed = json.loads(capsys.readouterr().out)
    assert [one["item_id"] for one in printed["resolved"]] == [IDS[0], IDS[2]]
    have, first, third = _lines(run_dir)
    assert have["position"] == "have"  # what was decided stays as it was decided
    digests = read_queue(run_dir).digests
    for line, item_id in ((first, IDS[0]), (third, IDS[2])):
        assert (line["item_id"], line["decision"], line["position"]) == (
            item_id,
            "choose find",
            "find",
        )
        assert (line["resolved_by"], line["shown_sha256"]) == ("yasin", digests[item_id])
        assert "parts" not in line
    assert read_queue(run_dir).open_items() == []


def test_find_remaining_decides_no_item_of_another_kind(tmp_path: Path) -> None:
    from test_a_part_is_decided_by_a_typed_choice_checked_before_it_is_written import _arbitration

    run_dir = _run(tmp_path)
    other = _arbitration(run_dir)
    assert _find_remaining(run_dir, "--find-remaining", "--by", "yasin") == 0
    assert [one.item_id for one in read_queue(run_dir).open_items()] == [other]
    assert len(_lines(run_dir)) == 3


def test_with_no_part_open_find_remaining_writes_nothing(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    assert _find_remaining(run_dir, "--find-remaining", "--by", "yasin") == 0
    before = decisions_bytes(run_dir)
    assert _find_remaining(run_dir, "--find-remaining", "--by", "yasin") == 0
    assert decisions_bytes(run_dir) == before and len(_lines(run_dir)) == 3


@pytest.mark.parametrize("args", [("--by", "yasin"), ("--find-remaining",), ()])
def test_nothing_is_chosen_unless_a_person_asks_and_says_who(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    run_dir = _run(tmp_path)
    assert _find_remaining(run_dir, "--find-remaining", "--by", "yasin") == 0, "no such command"
    fresh = listed(tmp_path / "other", item(MOTOR, 1, 1))
    assert _find_remaining(fresh, *args) == 2
    assert decisions_bytes(fresh) == b""
