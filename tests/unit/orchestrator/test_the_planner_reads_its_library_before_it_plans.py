"""The planner reads its library before it plans: cross standards, design standards and skill.

The decomposition prompt gains one section between fixed markers, holding the three files of the
design role's always-loaded set in that set's order, each under a header line with its path and
with its bytes unchanged. Nothing else of the prompt moves. The first call, a re-plan and the one
retry send the same section. The set is read once before any call, by the reader role sessions'
library uses, and the call is refused before it is made where a file is missing, a link, empty,
over the ceiling, says what is measured, or holds a marker. Under ``skills: off`` the skill file
is left out. The digests go on the decomposition's record, and so does the prompt's own.

A run that has no library to copy from is sent the template as it was: no section.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from knowledge_fixture import build_fixture_library
from replan_rig import Step, decompose, events

from physgate.knowledge import loader
from physgate.knowledge.library import read_library
from physgate.orchestrator import decompose as decompose_module
from physgate.orchestrator.decompose import (
    PLANNER_LIBRARY_BEGIN,
    PLANNER_LIBRARY_END,
    REPLAN_SENTENCE,
    UNIT_REFUSAL_HEAD,
    Outcome,
    planner_library,
    prompt_a_run_sends,
    prompt_for,
    replan_prompt,
    retry_prompt,
)
from physgate.orchestrator.events import Decomposed, PlanProposed, read_events
from physgate.orchestrator.exceptions import LibraryRefusedError
from physgate.orchestrator.replay import replay

REPO = Path(__file__).resolve().parents[3]
BRIEF = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"
ROLES = ["control", "electrical", "firmware"]
DESIGN_SET = loader.always_loaded("design")
CEILING = 100_000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _section(root: Path, *, skills: bool = True) -> str:
    """What the prompt must hold, written here from the files and not from the code."""
    body = ""
    for relative in DESIGN_SET:
        if not skills and relative.name == "skill.md":
            continue
        text = (root / relative).read_text(encoding="utf-8")
        body += f"File: {relative.as_posix()}\n" + text + ("" if text.endswith("\n") else "\n")
    return f"<<<PLANNER LIBRARY BEGIN>>>\n{body}<<<PLANNER LIBRARY END>>>\n\n"


def _library(root: Path) -> Path:
    return build_fixture_library(root / "library")


def _with(library: Path) -> dict[Path, bytes]:
    files = planner_library(library, skills="on", token_ceiling=CEILING)
    assert files is not None
    return files


# --- the prompt, byte for byte --------------------------------------------------------------


@pytest.mark.parametrize("parts", [False, True], ids=["no parts", "parts"])
@pytest.mark.parametrize("roles", [["control"], ROLES, ["control", "integration", "sizing"]])
def test_the_prompt_holds_the_three_files_between_the_markers_and_nothing_else_moves(
    roles: list[str], parts: bool
) -> None:
    files = _with(REPO)
    prompt = prompt_for(BRIEF, roles, parts=parts, library=files)
    section = _section(REPO)
    assert prompt.count(PLANNER_LIBRARY_BEGIN) == 1 and prompt.count(PLANNER_LIBRARY_END) == 1
    assert prompt.count(section) == 1
    # Without the section it is the bare template, byte for byte.
    assert prompt.replace(section, "") == prompt_for(BRIEF, roles, parts=parts)
    # It sits last before the call's closing instruction and the brief.
    assert section + "Answer by calling StructuredOutput once.\n\nBrief:\n" in prompt
    # The three files in the role's order, each whole.
    at = [prompt.index(f"File: {relative.as_posix()}\n") for relative in DESIGN_SET]
    assert at == sorted(at)
    for relative in DESIGN_SET:
        assert (REPO / relative).read_text(encoding="utf-8") in prompt


def test_the_real_set_fits_the_ceiling_the_sessions_are_held_to() -> None:
    assert planner_library(REPO, skills="on", token_ceiling=40_960) is not None


def test_a_prompt_without_a_library_is_the_template_as_it_was() -> None:
    assert PLANNER_LIBRARY_BEGIN not in prompt_for(BRIEF, ROLES)
    assert planner_library(None, skills="on", token_ceiling=CEILING) is None


def test_a_re_plan_and_a_retry_carry_the_same_section(tmp_path: Path) -> None:
    files = _with(_library(tmp_path))
    section = _section(tmp_path / "library")
    from replan_rig import plan_of

    from physgate.orchestrator.decompose import ReplanFindings

    again = replan_prompt(BRIEF, ROLES, plan_of(1), ReplanFindings("found", False), library=files)
    assert again.count(section) == 1
    assert again.replace(section, "") == replan_prompt(
        BRIEF, ROLES, plan_of(1), ReplanFindings("found", False)
    )
    refused = Outcome(
        session_id="s",
        ok=False,
        cause="schema_refused",
        detail=f"{UNIT_REFUSAL_HEAD} V/(rad/s)",
        plan=None,
        usage=(),
        model=None,
        num_turns=0,
    )
    told = retry_prompt(BRIEF, ROLES, None, refused, library=files)
    assert told is not None and told.count(section) == 1
    # Given the first call's prompt, the retry is that prompt and the reason: one section.
    first = prompt_for(BRIEF, ROLES, library=files)
    held = retry_prompt(BRIEF, ROLES, first, refused, library=files)
    assert held is not None and held.count(section) == 1 and held.startswith(first)


# --- the one function a launch check calls -------------------------------------------------


def test_the_prompt_a_run_sends_is_the_first_call_s_prompt(tmp_path: Path) -> None:
    library = _library(tmp_path)
    sent = prompt_a_run_sends(BRIEF, ROLES, parts=True, skills="on", library=library)
    assert sent == prompt_for(BRIEF, ROLES, parts=True, library=_with(library))
    assert sent.count(_section(library)) == 1
    # No library, no section: the template as it was.
    assert prompt_a_run_sends(BRIEF, ROLES, parts=True, library=None) == prompt_for(
        BRIEF, ROLES, parts=True
    )


def test_the_roles_are_taken_in_the_order_the_call_takes_them(tmp_path: Path) -> None:
    library = _library(tmp_path)
    one = prompt_a_run_sends(BRIEF, ["firmware", "control"], library=library)
    assert one == prompt_a_run_sends(BRIEF, ["control", "firmware"], library=library)


def test_a_launch_check_is_refused_as_a_run_is(tmp_path: Path) -> None:
    library = _library(tmp_path)
    (library / DESIGN_SET[2]).unlink()
    with pytest.raises(LibraryRefusedError):
        prompt_a_run_sends(BRIEF, ROLES, library=library)


# --- skills: off ---------------------------------------------------------------------------


def test_under_skills_off_the_skill_file_is_left_out_and_the_standards_stay(tmp_path: Path) -> None:
    library = _library(tmp_path)
    sent = prompt_a_run_sends(BRIEF, ROLES, skills="off", library=library)
    assert sent.count(_section(library, skills=False)) == 1
    assert "File: knowledge/design/skill.md" not in sent
    assert (library / "knowledge/design/skill.md").read_text() not in sent
    assert "File: knowledge/design/standards.md" in sent
    assert "File: knowledge/cross/standards.md" in sent


def test_a_run_under_skills_off_sends_the_planner_no_skill_file(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "off", [Step()], config_update={"skills": "off"})
    assert ran.code == 0, ran.err
    (call,) = ran.script.calls
    assert "File: knowledge/design/skill.md" not in call["prompt"]
    assert "File: knowledge/design/standards.md" in call["prompt"]
    (decomposed,) = [e for e in events(ran.run_dir) if e["kind"] == "decomposed"]
    assert [f["path"] for f in decomposed["planner_library"]] == [
        "knowledge/cross/standards.md",
        "knowledge/design/standards.md",
    ]


# --- refused before the call is made -------------------------------------------------------


def _missing(library: Path, relative: Path) -> None:
    (library / relative).unlink()


def _linked(library: Path, relative: Path) -> None:
    target = library / "elsewhere.md"
    target.write_text("# Elsewhere\n\nSomething else.\n")
    (library / relative).unlink()
    (library / relative).symlink_to(target)


def _empty(library: Path, relative: Path) -> None:
    (library / relative).write_text("")


def _blank(library: Path, relative: Path) -> None:
    (library / relative).write_text(" \n\t\n")


def _unreadable(library: Path, relative: Path) -> None:
    (library / relative).write_bytes(b"# Standards\n\xff\xfe\n")


def _says_what_is_measured(library: Path, relative: Path) -> None:
    (library / relative).write_text("# Standards\n\nA planted fault is injected here.\n")


def _holds_a_marker(library: Path, relative: Path) -> None:
    (library / relative).write_text(f"# Standards\n\n{PLANNER_LIBRARY_END}\nmore\n")


BREAKS = {
    "missing": _missing,
    "a link": _linked,
    "empty": _empty,
    "blank": _blank,
    "not text": _unreadable,
    "says what is measured": _says_what_is_measured,
    "holds a marker": _holds_a_marker,
}


@pytest.mark.parametrize("relative", DESIGN_SET, ids=lambda p: "/".join(p.parts[-2:]))
@pytest.mark.parametrize("how", BREAKS)
def test_a_file_the_planner_cannot_read_is_refused(
    tmp_path: Path, relative: Path, how: str
) -> None:
    library = _library(tmp_path)
    BREAKS[how](library, relative)
    with pytest.raises(LibraryRefusedError) as raised:
        planner_library(library, skills="on", token_ceiling=CEILING)
    assert raised.value.context.get("path") == relative.as_posix() or how == "not text"


@pytest.mark.parametrize("relative", DESIGN_SET[1:], ids=lambda p: "/".join(p.parts[-2:]))
@pytest.mark.parametrize("how", BREAKS)
def test_a_library_with_a_design_file_that_cannot_be_read_is_refused_before_any_call(
    tmp_path: Path, relative: Path, how: str, capsys: pytest.CaptureFixture[str]
) -> None:
    library = _library(tmp_path)
    BREAKS[how](library, relative)
    ran = decompose(tmp_path / "run", "off", [Step()], library=library, capsys=capsys)
    assert ran.code != 0
    assert ran.script.calls == [], "a call was made on a library the planner cannot read"
    assert not (ran.run_dir / "events.jsonl").exists(), "a run was started"
    assert "design" in ran.err


def test_a_run_with_a_library_whose_design_skill_is_missing_is_refused_before_any_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = _library(tmp_path)
    (library / "knowledge/design/skill.md").unlink()
    for mode, steps in (("off", [Step()]), ("observe", [Step(review="pass")])):
        ran = decompose(tmp_path / mode, mode, steps, library=library, capsys=capsys)
        assert ran.code != 0
        assert ran.script.calls == []
        assert "knowledge/design/skill.md" in ran.err


def test_a_set_over_the_ceiling_is_refused_before_any_call(tmp_path: Path) -> None:
    library = _library(tmp_path)
    size = sum((library / p).stat().st_size for p in DESIGN_SET)
    with pytest.raises(LibraryRefusedError):
        planner_library(library, skills="on", token_ceiling=size - 1)
    assert planner_library(library, skills="on", token_ceiling=size) is not None
    ran = decompose(
        tmp_path / "run",
        "off",
        [Step()],
        library=library,
        config_update={"token_ceiling": size - 1},
    )
    assert ran.code != 0
    assert ran.script.calls == []


def test_the_reader_is_the_one_role_sessions_use(tmp_path: Path) -> None:
    library = _library(tmp_path)
    assert planner_library(library, skills="on", token_ceiling=CEILING) == read_library(
        library, ["design"]
    )


def test_a_run_sends_its_first_call_the_prompt_with_the_section(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "off", [Step()])
    assert ran.script.calls[0]["prompt"].count(PLANNER_LIBRARY_BEGIN) == 1


# --- a run: what every call is sent, and what the record holds ------------------------------


def test_every_call_of_a_run_is_sent_the_section_and_the_record_names_it(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "repair:1", [Step(review="fail"), Step(review="pass")])
    assert ran.code == 0, ran.err
    first, second = ran.script.calls
    block = first["prompt"][
        first["prompt"].index(PLANNER_LIBRARY_BEGIN) : first["prompt"].index(PLANNER_LIBRARY_END)
    ]
    assert block and block in second["prompt"], "a re-plan was sent another section"
    assert REPLAN_SENTENCE in second["prompt"] and REPLAN_SENTENCE not in first["prompt"]
    log = events(ran.run_dir)
    (decomposed,) = [e for e in log if e["kind"] == "decomposed"]
    files = decomposed["planner_library"]
    assert [f["path"] for f in files] == [p.as_posix() for p in DESIGN_SET]
    for entry in files:
        shown = f"File: {entry['path']}\n"
        assert shown in first["prompt"]
        data = _fixture(entry["path"])
        assert entry["size"] == len(data) and entry["sha256"] == _sha(data)
    # The prompt as sent: its digest and length, for the last call on the decomposition's line
    # and for each round on its own.
    for call, line in zip(
        (first, second), [e for e in log if e["kind"] == "plan_proposed"], strict=True
    ):
        sent = call["prompt"].encode()
        assert line["prompt_sha256"] == _sha(sent) and line["prompt_bytes"] == len(sent)
    sent = second["prompt"].encode()
    assert decomposed["prompt_sha256"] == _sha(sent) and decomposed["prompt_bytes"] == len(sent)
    replay(read_events(ran.run_dir / "events.jsonl"))


def _fixture(path: str) -> bytes:
    from knowledge_fixture import fixture_text

    return fixture_text(Path(path)).encode()


def test_a_run_that_does_not_review_its_plan_records_its_prompt_on_the_decomposition(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "off", [Step()])
    (decomposed,) = [e for e in events(ran.run_dir) if e["kind"] == "decomposed"]
    sent = ran.script.calls[0]["prompt"].encode()
    assert decomposed["prompt_sha256"] == _sha(sent)
    assert decomposed["prompt_bytes"] == len(sent)


def test_a_line_written_before_the_fields_existed_still_reads_and_replays(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "observe", [Step(review="pass")])
    path = ran.run_dir / "events.jsonl"
    old = []
    for raw in path.read_text().splitlines():
        line = json.loads(raw)
        if line["kind"] in ("decomposed", "plan_proposed"):
            for field in ("planner_library", "prompt_sha256", "prompt_bytes"):
                line.pop(field, None)
        old.append(json.dumps(line, sort_keys=True))
    path.write_text("\n".join(old) + "\n")
    log = read_events(path)
    assert [e for e in log if isinstance(e, Decomposed)][0].planner_library is None
    assert [e for e in log if isinstance(e, PlanProposed)][0].prompt_sha256 is None
    # Written again, such a line holds none of the fields: its bytes are what they were.
    for line in log:
        if isinstance(line, Decomposed | PlanProposed):
            dumped = line.model_dump(mode="json")
            assert not {"planner_library", "prompt_sha256", "prompt_bytes"} & dumped.keys()
    replay(log)


def test_the_module_names_the_markers_it_writes() -> None:
    assert decompose_module.PLANNER_LIBRARY_BEGIN == "<<<PLANNER LIBRARY BEGIN>>>"
    assert decompose_module.PLANNER_LIBRARY_END == "<<<PLANNER LIBRARY END>>>"


#: The prompt a run sends for this brief, taken over the real library as it is promoted: each
#: moves, by design, when a text of the design role's set is promoted again, and is then re-taken
#: here with the texts' own record.
PROMPT_PINS: dict[tuple[tuple[str, ...], bool], tuple[int, str]] = {
    (("control", "electrical", "firmware"), False): (
        45036,
        "0935759eb78268586670243c21750f86373c1398ea3227c1ce21062f12c0dd03",
    ),
    (("control", "electrical", "firmware"), True): (
        45750,
        "fcaaf98711b01a39d1855c916f803ba9c4660bf8b2715a3fadd93010c7a690b6",
    ),
    (("control", "firmware", "integration", "sizing"), False): (
        45892,
        "c304820660a2e2e969c4254d339f9412f8ba2eddeee98ad296bb4cec749770fa",
    ),
    (("electrical",), False): (
        45017,
        "a388197c4ef9c9d944f4197944db659336980ee34794b57ec989518db7d55a35",
    ),
}


@pytest.mark.parametrize(("roles", "parts"), list(PROMPT_PINS), ids=str)
def test_the_prompt_a_run_sends_over_the_real_library_is_the_one_pinned(
    roles: tuple[str, ...], parts: bool
) -> None:
    brief = "Build a robot.\n\n## Acceptance criteria\n\n1. It stands.\n"
    sent = prompt_a_run_sends(
        brief, roles, parts=parts, library=REPO, token_ceiling=40_960
    ).encode()
    assert (len(sent), _sha(sent)) == PROMPT_PINS[(roles, parts)]


def test_a_library_named_by_a_relative_path_is_read_all_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = _library(tmp_path)
    monkeypatch.chdir(library)
    assert planner_library(Path("."), skills="on", token_ceiling=CEILING) is not None
