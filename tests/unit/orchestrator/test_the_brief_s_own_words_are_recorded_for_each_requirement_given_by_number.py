"""The brief's own words are recorded for each system requirement the plan gives by number.

Where the brief numbers its acceptance criteria, the plan gives a system requirement as one of
those numbers, and a number alone does not say what integration must show. So the run's opening
records, on the decomposition's line, the brief's own words for each requirement given by number,
taken from the brief the call was given: the criterion's numbered line and the lines that carry
it on, up to the next numbered line, heading or blank line, its whitespace joined. The field is
left out when there are none, so every earlier log, and every run without integration, keeps its
bytes. Words past a module specification's bound are refused before anything is written. The
record holds the brief by its digest alone, so replay holds the words to the requirement list,
never to the brief.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_every_pair_sharing_an_interface_is_enumerated_from_the_recorded_plan as pairs
from pydantic import ValidationError

from physgate import roles
from physgate.orchestrator.events import Decomposed
from physgate.orchestrator.exceptions import DecompositionError
from physgate.orchestrator.plan import SPEC_MAX_CHARS, CriterionWords, Plan, SystemRequirement
from physgate.reviewers.contract import criterion_words

BRIEF = (
    "Build a robot that stands.\n"
    "\n"
    "1. Not a criterion: it is above the heading.\n"
    "\n"
    "## Acceptance criteria\n"
    "\n"
    "1. It stands\n"
    "   upright,   on its feet.\n"
    "2) It walks 10 m.\n"
    "Then it stops.\n"
    "\n"
    "This paragraph is no part of criterion 2.\n"
    "3. It sits.\n"
    "## Notes\n"
    "4. Not a criterion: it is under another heading.\n"
)


@pytest.fixture(autouse=True)
def _sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


def requirements(*numbers: str) -> list[dict[str, Any]]:
    return [
        {"requirement": n, "contributing": [{"module": "drive", "criterion": "1"}]} for n in numbers
    ]


def decomposed_line(run_dir: Path) -> dict[str, Any]:
    (line,) = [one for one in pairs.lines(run_dir) if one["kind"] == "decomposed"]
    return line


def test_each_numbered_criterion_is_taken_in_the_briefs_own_words() -> None:
    assert criterion_words(BRIEF) == {
        "1": "It stands upright, on its feet.",
        "2": "It walks 10 m. Then it stops.",
        "3": "It sits.",
    }
    # A number given twice is the first; a brief that numbers none gives none.
    assert criterion_words("## Acceptance criteria\n\n1. One.\n1. Again.\n") == {"1": "One."}
    assert criterion_words("Build it.\n\n1. Not under a heading.\n") == {}


def test_the_run_records_the_words_for_each_requirement_given_by_number(tmp_path: Path) -> None:
    run_dir, _ = pairs.start(
        tmp_path, pairs.integrated(system_requirements=requirements("3", "1")), brief=BRIEF
    )
    line = decomposed_line(run_dir)
    assert line.get("brief_words") == [
        {"criterion": "3", "words": "It sits."},
        {"criterion": "1", "words": "It stands upright, on its feet."},
    ]


@pytest.mark.parametrize(
    "case", ["no requirement", "requirements in the brief's words", "no brief", "no integration"]
)
def test_the_field_is_left_out_when_there_are_none(tmp_path: Path, case: str) -> None:
    worded = "## Goals\n\nIt stands, and it walks.\n"
    plan, brief, run_roles = {
        "no requirement": (pairs.integrated(system_requirements=[]), BRIEF, pairs.BOTH),
        "requirements in the brief's words": (
            pairs.integrated(system_requirements=requirements("It stands, and it walks.")),
            worded,
            pairs.BOTH,
        ),
        "no brief": (pairs.integrated(), None, pairs.BOTH),
        "no integration": (
            Plan.model_validate_json(
                json.dumps({"modules": pairs.MODULES[1:], "interface_nodes": pairs.NODES[:1]})
            ),
            BRIEF,
            pairs.DOMAINS,
        ),
    }[case]
    run_dir, _ = pairs.start(tmp_path, plan, run_roles, brief=brief)
    assert "brief_words" not in decomposed_line(run_dir)
    assert "brief_words" not in (run_dir / "events.jsonl").read_text()


def test_words_past_a_specifications_bound_are_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    long = "## Acceptance criteria\n\n1. " + "x" * (SPEC_MAX_CHARS + 1) + "\n"
    # Refused by the bound's own check, with its own reason: not by the record's type later.
    with pytest.raises(Exception) as caught:  # noqa: B017, PT011 - the type is asserted below
        pairs.start(tmp_path, pairs.integrated(), brief=long)
    assert type(caught.value) is DecompositionError, repr(caught.value)
    assert "brief's words for a requirement are longer" in str(caught.value)
    assert caught.value.context["limit"] == str(SPEC_MAX_CHARS)
    assert not (tmp_path / "run" / "events.jsonl").exists()
    assert not (tmp_path / "run" / "run.json").exists()


def test_a_criterion_of_exactly_the_bound_is_recorded(tmp_path: Path) -> None:
    exact = "## Acceptance criteria\n\n1. " + "x" * SPEC_MAX_CHARS + "\n"

    def started() -> str:
        """Whether the run starts, or what was raised instead: asserted, never let through."""
        try:
            pairs.start(tmp_path, pairs.integrated(), brief=exact)
        except Exception as exc:  # noqa: BLE001 - what was raised is the answer
            return f"raised {type(exc).__name__}: {exc}"
        return "started"

    assert started() == "started"
    run_dir = tmp_path / "run"
    assert decomposed_line(run_dir).get("brief_words") == [
        {"criterion": "1", "words": "x" * SPEC_MAX_CHARS}
    ]


def line_with(words: list[dict[str, str]] | None, numbers: tuple[str, ...] = ("1", "2")) -> Any:  # noqa: ANN401
    fields: dict[str, Any] = {
        "seq": 1,
        "ts": "2026-10-27T00:00:00.000000Z",
        "run_id": "run-1",
        "gate_mode": "on",
        "session_id": "decomposition",
        "model": "claude-opus-5-5",
        "num_turns": 1,
        "subtasks": 2,
        "interface_nodes": ["iface.drive"],
        "spec_commit": "e" * 40,
        "head_revision": 1,
        "interface_consumers": [{"interface": "iface.drive", "consumers": ["fw"]}],
        "system_requirements": requirements(*numbers),
    }
    if words is not None:
        fields["brief_words"] = words
    return Decomposed.model_validate_json(json.dumps(fields))


@pytest.mark.parametrize(
    ("words", "why"),
    [
        ([], "only when there are some"),
        ([{"criterion": "3", "words": "It sits."}], "no system requirement"),
        (
            [{"criterion": "2", "words": "b"}, {"criterion": "1", "words": "a"}],
            "once, in the plan's order",
        ),
        (
            [{"criterion": "1", "words": "a"}, {"criterion": "1", "words": "a"}],
            "once, in the plan's order",
        ),
    ],
    ids=["none", "not a requirement", "out of order", "twice"],
)
def test_replay_holds_the_words_to_the_requirement_list(
    words: list[dict[str, str]], why: str
) -> None:
    with pytest.raises(ValidationError, match=why):
        line_with(words)


def test_a_line_with_words_and_no_requirements_is_refused() -> None:
    fields = json.loads(line_with([{"criterion": "1", "words": "a"}]).model_dump_json())
    fields.pop("system_requirements"), fields.pop("interface_consumers")
    with pytest.raises(ValidationError):
        Decomposed.model_validate_json(json.dumps(fields))


def test_a_line_with_the_words_reads_back_as_written() -> None:
    line = line_with([{"criterion": "2", "words": "b"}])
    assert line.brief_words == (CriterionWords(criterion="2", words="b"),)
    assert json.loads(line.model_dump_json())["brief_words"] == [{"criterion": "2", "words": "b"}]
    assert line_with(None).model_dump_json() == line_with(None).model_dump_json()
    assert "brief_words" not in json.loads(line_with(None).model_dump_json())
    assert line.system_requirements is not None
    assert isinstance(line.system_requirements[0], SystemRequirement)
