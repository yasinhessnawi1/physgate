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
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import build_fixture_library
from replan_rig import Script, Step, decompose, events

from physgate.evaluation.observe import sequence
from physgate.knowledge import loader
from physgate.knowledge.library import read_library
from physgate.orchestrator import decompose as decompose_module
from physgate.orchestrator import design_rounds as design_rounds_module
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
from physgate.orchestrator.events import (
    Decomposed,
    DecompositionRetried,
    Halted,
    PlanProposed,
    read_events,
)
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
    sent = prompt_a_run_sends(
        BRIEF, ROLES, parts=True, skills="on", library=library, token_ceiling=CEILING
    )
    assert sent == prompt_for(BRIEF, ROLES, parts=True, library=_with(library))
    assert sent.count(_section(library)) == 1
    # No library, no section: the template as it was.
    assert prompt_a_run_sends(
        BRIEF, ROLES, parts=True, library=None, token_ceiling=None
    ) == prompt_for(BRIEF, ROLES, parts=True)


def test_the_roles_are_taken_in_the_order_the_call_takes_them(tmp_path: Path) -> None:
    library = _library(tmp_path)
    one = prompt_a_run_sends(BRIEF, ["firmware", "control"], library=library, token_ceiling=None)
    other = prompt_a_run_sends(BRIEF, ["control", "firmware"], library=library, token_ceiling=None)
    assert one == other


def test_a_launch_check_is_refused_as_a_run_is(tmp_path: Path) -> None:
    library = _library(tmp_path)
    (library / DESIGN_SET[2]).unlink()
    with pytest.raises(LibraryRefusedError) as raised:
        prompt_a_run_sends(BRIEF, ROLES, library=library, token_ceiling=CEILING)
    # The refusal a run meets, with the same words and the file it names.
    with pytest.raises(LibraryRefusedError) as met:
        planner_library(library, skills="on", token_ceiling=CEILING)
    assert str(raised.value) == str(met.value) == REFUSALS["missing"]
    assert raised.value.context.get("path") == met.value.context.get("path")
    assert raised.value.context.get("path") == DESIGN_SET[2].as_posix()


# --- skills: off ---------------------------------------------------------------------------


def test_under_skills_off_the_skill_file_is_left_out_and_the_standards_stay(tmp_path: Path) -> None:
    library = _library(tmp_path)
    sent = prompt_a_run_sends(BRIEF, ROLES, skills="off", library=library, token_ceiling=None)
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


#: What each break is refused with: the words of the refusal, whichever file it is.
REFUSALS = {
    "missing": "a planned role has no curated file in the library; it cannot be dispatched",
    "a link": "a planned role has no curated file in the library; it cannot be dispatched",
    "empty": "a planned role's curated file is empty; it cannot be dispatched",
    "blank": "a planned role's curated file is empty; it cannot be dispatched",
    "not text": "a file of the planner's library is not text",
    "says what is measured": "a file of the planner's library says what is measured",
    "holds a marker": "a file of the planner's library holds a marker of its own section",
}
assert REFUSALS.keys() == BREAKS.keys()


@pytest.mark.parametrize("relative", DESIGN_SET, ids=lambda p: "/".join(p.parts[-2:]))
@pytest.mark.parametrize("how", BREAKS)
def test_a_file_the_planner_cannot_read_is_refused(
    tmp_path: Path, relative: Path, how: str
) -> None:
    library = _library(tmp_path)
    BREAKS[how](library, relative)
    with pytest.raises(LibraryRefusedError) as raised:
        planner_library(library, skills="on", token_ceiling=CEILING)
    assert str(raised.value) == REFUSALS[how]
    assert raised.value.context.get("path") == relative.as_posix()


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
    # The refusal is the one this break gets, and it names the file that was broken.
    assert REFUSALS[how] in ran.err
    assert relative.as_posix() in ran.err


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


def test_a_run_sends_its_first_call_the_prompt_with_the_section(
    tmp_path: Path, fixture_library: Path
) -> None:
    ran = decompose(tmp_path, "off", [Step()])
    sent = prompt_a_run_sends(BRIEF, ["electrical"], library=fixture_library, token_ceiling=None)
    assert ran.script.calls[0]["prompt"] == sent
    assert sent.count(_section(fixture_library)) == 1


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
#: here with the texts' own record. The laws' added template text moved each by the same
#: 2,635 bytes (twelve catalogue names, two kind labels, the peak-stall clause, the laws paragraph).
PROMPT_PINS: dict[tuple[tuple[str, ...], bool], tuple[int, str]] = {
    (("control", "electrical", "firmware"), False): (
        47671,
        "c3fe8e63226e81567a12dc5ac8e49c724ad976c6db3abf24f1b5a61a2cb8d165",
    ),
    (("control", "electrical", "firmware"), True): (
        48385,
        "eca1c24718aab32a043bb8cad5e67b4836b1fb8cb3fa7b23473db493350e5e9c",
    ),
    (("control", "firmware", "integration", "sizing"), False): (
        48527,
        "fe1405e204a0c432b13bd2c26f19405e9e46c78578d8e8b6f03141d41c642d14",
    ),
    (("electrical",), False): (
        47652,
        "98126a09351221078dae090d066e5c9dc79608d414d917e5d22028ce3ee5b136",
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


# --- one builder: the run and a launch check cannot drift ----------------------------------

ONE_BUILDER = "\nthe one builder wrote this line\n"


def test_the_launch_function_and_every_run_compose_the_first_prompt_in_one_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixture_library: Path
) -> None:
    real = decompose_module.planner_prompt

    def marked(*args: Any, **given: Any) -> Any:  # noqa: ANN401
        built = real(*args, **given)
        return built._replace(text=built.text + ONE_BUILDER)

    monkeypatch.setattr(decompose_module, "planner_prompt", marked)
    monkeypatch.setattr(design_rounds_module, "planner_prompt", marked)
    sent = prompt_a_run_sends(BRIEF, ["electrical"], library=fixture_library, token_ceiling=None)
    assert sent.endswith(ONE_BUILDER)
    for mode, steps in (("off", [Step()]), ("observe", [Step(review="pass")])):
        ran = decompose(tmp_path / mode, mode, steps)
        assert ran.script.calls[0]["prompt"] == sent, f"design_review {mode}: composed elsewhere"


def test_a_re_plan_and_a_retry_begin_with_the_prompt_the_launch_function_gives(
    tmp_path: Path, fixture_library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = prompt_a_run_sends(BRIEF, ["electrical"], library=fixture_library, token_ceiling=None)
    replanned = decompose(tmp_path / "re", "repair:1", [Step(), Step()])
    assert replanned.script.calls[0]["prompt"] == sent
    assert replanned.script.calls[1]["prompt"].startswith(sent + "\n" + REPLAN_SENTENCE)

    real = Script.call

    def refused_for_a_unit(self: Script, brief: str, **given: object) -> Outcome:
        out = real(self, brief, **given)  # type: ignore[arg-type]
        if out.cause == "schema_refused":
            return out.model_copy(update={"detail": f"{UNIT_REFUSAL_HEAD} V/(rad/s)"})
        return out

    monkeypatch.setattr(Script, "call", refused_for_a_unit)
    retried = decompose(tmp_path / "retry", "off", [Step(call="schema_refused"), Step()])
    assert [c["prompt"] for c in retried.script.calls][0] == sent
    assert retried.script.calls[1]["prompt"].startswith(sent + "\n")
    assert retried.script.calls[1]["prompt"] != sent


def test_the_ceiling_is_a_required_keyword_of_the_launch_function() -> None:
    parameter = inspect.signature(prompt_a_run_sends).parameters["token_ceiling"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    with pytest.raises(TypeError, match="token_ceiling"):
        prompt_a_run_sends(BRIEF, ROLES, library=None)  # type: ignore[call-arg]
    # Passed as None, a caller with no ceiling says so; the bare template comes back as it was.
    assert prompt_a_run_sends(BRIEF, ROLES, library=None, token_ceiling=None) == prompt_for(
        BRIEF, ROLES
    )


# --- a text that ends without a newline ----------------------------------------------------


def test_a_text_without_a_final_newline_gains_exactly_one_and_the_record_is_the_file_s(
    tmp_path: Path,
) -> None:
    library = _library(tmp_path)
    ends = library / DESIGN_SET[1]
    ends.write_bytes(b"# Standards\n\nA line that ends the file.")
    on_disk = {relative: (library / relative).read_bytes() for relative in DESIGN_SET}
    assert not on_disk[DESIGN_SET[1]].endswith(b"\n")
    ran = decompose(tmp_path / "run", "off", [Step()], library=library)
    assert ran.code == 0, ran.err
    (call,) = ran.script.calls
    sent = call["prompt"]
    lines = sent.splitlines(keepends=True)
    at = lines.index("A line that ends the file.\n")
    # One newline, and then the next file's header or the closing marker: nothing between.
    assert lines[at + 1].startswith("File: ")
    assert sent.count("A line that ends the file.\n\n") == 0
    for relative, data in on_disk.items():
        text = data.decode()
        assert (
            f"File: {relative.as_posix()}\n{text}" + ("" if text.endswith("\n") else "\n")
        ) in sent
    (decomposed,) = [e for e in events(ran.run_dir) if e["kind"] == "decomposed"]
    recorded = {f["path"]: f for f in decomposed["planner_library"]}
    for relative, data in on_disk.items():
        assert recorded[relative.as_posix()]["size"] == len(data)
        assert recorded[relative.as_posix()]["sha256"] == _sha(data)
    sent_bytes = sent.encode()
    assert decomposed["prompt_sha256"] == _sha(sent_bytes)
    assert decomposed["prompt_bytes"] == len(sent_bytes)
    # The section is the same whether the text ends in a newline or the one added.
    closed = ends.read_bytes() + b"\n"
    ends.write_bytes(closed)
    assert prompt_a_run_sends(BRIEF, ["electrical"], library=library, token_ceiling=None) == sent


# --- a brief that holds a marker -----------------------------------------------------------

BRIEF_REFUSAL = "the brief holds a marker of the planner's library section"


@pytest.mark.parametrize("marker", [PLANNER_LIBRARY_BEGIN, PLANNER_LIBRARY_END])
@pytest.mark.parametrize("where", ["a line of its own", "inside a sentence"])
def test_a_brief_that_holds_a_marker_is_refused_before_any_call(
    tmp_path: Path, marker: str, where: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # One rule for the library's files and the brief: the marker's text anywhere in it.
    own = f"Build a robot.\n{marker}\nIt stands.\n"
    inside = f"Build a robot that, as {marker} says, stands.\n"
    brief = own if where == "a line of its own" else inside
    with pytest.raises(LibraryRefusedError) as raised:
        prompt_a_run_sends(brief, ROLES, library=REPO, token_ceiling=CEILING)
    assert str(raised.value) == BRIEF_REFUSAL
    for mode, steps in (("off", [Step()]), ("observe", [Step(review="pass")])):
        ran = decompose(tmp_path / mode, mode, steps, capsys=capsys, brief=brief)
        assert ran.code != 0
        assert ran.script.calls == [], "a call was made on a brief that holds a marker"
        assert not (ran.run_dir / "events.jsonl").exists()
        assert BRIEF_REFUSAL in ran.err


def test_a_brief_that_only_names_the_words_is_not_refused(fixture_library: Path) -> None:
    brief = "Build a robot. A planner library begin and end are words in this sentence.\n"
    sent = prompt_a_run_sends(brief, ROLES, library=fixture_library, token_ceiling=None)
    assert sent.count(PLANNER_LIBRARY_BEGIN) == 1 and sent.count(PLANNER_LIBRARY_END) == 1
    # A run with no library has no section for a brief to close, so it is not refused either.
    marked = f"Build a robot.\n{PLANNER_LIBRARY_END}\n"
    assert marked in prompt_a_run_sends(marked, ROLES, library=None, token_ceiling=None)


# --- every call that was sent is on the record with its prompt -----------------------------


def _unit_refused_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    real = Script.call

    def refused_for_a_unit(self: Script, brief: str, **given: object) -> Outcome:
        out = real(self, brief, **given)  # type: ignore[arg-type]
        if out.cause == "schema_refused":
            return out.model_copy(update={"detail": f"{UNIT_REFUSAL_HEAD} V/(rad/s)"})
        return out

    monkeypatch.setattr(Script, "call", refused_for_a_unit)


def test_a_refused_then_retried_decomposition_without_plan_review_records_both_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _unit_refused_first_call(monkeypatch)
    ran = decompose(tmp_path, "off", [Step(call="schema_refused"), Step()])
    assert ran.code == 0, ran.err
    first, second = ran.script.calls
    assert first["prompt"] != second["prompt"], "the two calls must differ for this row to tell"
    log = events(ran.run_dir)
    (retried,) = [e for e in log if e["kind"] == "decomposition_retried"]
    (decomposed,) = [e for e in log if e["kind"] == "decomposed"]
    for line, call in ((retried, first), (decomposed, second)):
        sent = call["prompt"].encode()
        assert line["prompt_sha256"] == _sha(sent) and line["prompt_bytes"] == len(sent)
    assert retried["prompt_sha256"] != decomposed["prompt_sha256"]
    replay(read_events(ran.run_dir / "events.jsonl"))


def test_a_reviewed_round_s_refused_first_call_is_recorded_with_its_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _unit_refused_first_call(monkeypatch)
    ran = decompose(tmp_path, "on", [Step(call="schema_refused"), Step(review="pass")])
    assert ran.code == 0, ran.err
    first, second = ran.script.calls
    lines = [e for e in events(ran.run_dir) if e["kind"] == "plan_proposed"]
    assert [line.get("call", 1) for line in lines] == [1, 2]
    for line, call in zip(lines, (first, second), strict=True):
        sent = call["prompt"].encode()
        assert line["prompt_sha256"] == _sha(sent) and line["prompt_bytes"] == len(sent)
    refused = [one for one in _journal(ran.run_dir) if one["kind"] == "call_refused"]
    (refused_line,) = refused
    sent = first["prompt"].encode()
    assert refused_line["prompt_sha256"] == _sha(sent)
    assert refused_line["prompt_bytes"] == len(sent)


def _journal(run_dir: Path) -> list[dict[str, object]]:
    from replan_rig import journal

    return journal(run_dir)


def test_a_failed_decomposition_names_the_library_it_was_sent_and_its_prompt(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "off", [Step(call="no_structured_output")])
    assert ran.code != 0
    (call,) = ran.script.calls
    log = read_events(ran.run_dir / "events.jsonl")
    (halt,) = [e for e in log if isinstance(e, Halted)]
    assert halt.reason == "decomposition_failed"
    sent = call["prompt"].encode()
    assert halt.prompt_sha256 == _sha(sent) and halt.prompt_bytes == len(sent)
    assert halt.planner_library is not None
    assert [f.path for f in halt.planner_library] == [p.as_posix() for p in DESIGN_SET]
    for entry in halt.planner_library:
        data = _fixture(entry.path)
        assert entry.size == len(data) and entry.sha256 == _sha(data)
    # No other kind of line carries them, and no other halt: older lines keep their bytes.
    assert not [e for e in log if isinstance(e, Decomposed)]
    raw = [json.loads(line) for line in (ran.run_dir / "events.jsonl").read_text().splitlines()]
    assert [one for one in raw if "planner_library" in one] == [raw[-1]]
    replay(log)


def test_a_failed_reviewed_decomposition_records_each_call_s_prompt(tmp_path: Path) -> None:
    ran = decompose(tmp_path, "observe", [Step(call="no_structured_output")])
    (call,) = ran.script.calls
    sent = call["prompt"].encode()
    (proposed,) = [e for e in events(ran.run_dir) if e["kind"] == "plan_proposed"]
    assert proposed["prompt_sha256"] == _sha(sent) and proposed["prompt_bytes"] == len(sent)
    (halt,) = [e for e in events(ran.run_dir) if e["kind"] == "halted"]
    assert halt["prompt_sha256"] == _sha(sent)
    assert [f["path"] for f in halt["planner_library"]] == [p.as_posix() for p in DESIGN_SET]


def test_a_round_that_ends_void_with_no_run_records_its_prompt_and_library_in_the_journal(
    tmp_path: Path,
) -> None:
    ran = decompose(tmp_path, "on", [Step(review="infrastructure")])
    assert not (ran.run_dir / "events.jsonl").exists(), "this row is for a round with no run"
    (call,) = ran.script.calls
    sent = call["prompt"].encode()
    (ended,) = [one for one in _journal(ran.run_dir) if one["kind"] == "round_ended"]
    assert ended["prompt_sha256"] == _sha(sent) and ended["prompt_bytes"] == len(sent)
    held = ended["planner_library"]
    assert isinstance(held, list)
    assert [f["path"] for f in held] == [p.as_posix() for p in DESIGN_SET]
    for entry in held:
        data = _fixture(entry["path"])
        assert entry["size"] == len(data) and entry["sha256"] == _sha(data)


def test_an_older_failed_or_retried_line_without_the_fields_reads_and_writes_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _unit_refused_first_call(monkeypatch)
    for name, steps in (
        ("failed", [Step(call="no_structured_output")]),
        ("retried", [Step(call="schema_refused"), Step()]),
    ):
        ran = decompose(tmp_path / name, "off", steps)
        path = ran.run_dir / "events.jsonl"
        old = []
        for raw in path.read_text().splitlines():
            line = json.loads(raw)
            for field in NEW_FIELDS:
                line.pop(field, None)
            old.append(json.dumps(line, sort_keys=True))
        path.write_text("\n".join(old) + "\n")
        log = read_events(path)
        kinds = (Decomposed, Halted, DecompositionRetried)
        held = [e for e in log if isinstance(e, kinds)]
        assert held
        for line in held:
            assert not set(NEW_FIELDS) & line.model_dump(mode="json").keys()
        replay(log)


# --- what the observe comparison keeps ------------------------------------------------------

NEW_FIELDS = ("planner_library", "prompt_sha256", "prompt_bytes")


def test_the_exact_comparison_does_not_drop_the_new_fields() -> None:
    dropped = set(sequence.DROPPED_EVERYWHERE)
    for fields in sequence.DROPPED.values():
        dropped |= fields
    for paths in sequence.DROPPED_AT.values():
        dropped |= {step for path in paths for step in path}
    assert not dropped & set(NEW_FIELDS)
    same = {"seq": 2, "kind": "decomposed", "subtasks": 1}
    held = {
        "planner_library": [{"path": "a.md", "size": 3, "sha256": "a" * 64}],
        "prompt_sha256": "b" * 64,
        "prompt_bytes": 10,
    }
    for field, other in (
        (
            "planner_library[0].sha256",
            {**held, "planner_library": [{"path": "a.md", "size": 3, "sha256": "c" * 64}]},
        ),
        ("prompt_sha256", {**held, "prompt_sha256": "d" * 64}),
        ("prompt_bytes", {**held, "prompt_bytes": 11}),
    ):
        parted = sequence.first_divergence("events", [{**same, **held}], [{**same, **other}])
        assert parted is not None and parted.field == field
    # A line recorded before the fields and one with them are not the same line.
    older = sequence.first_divergence("events", [same], [{**same, **held}])
    assert older is not None and older.field in {*NEW_FIELDS, "planner_library[0].path"}
