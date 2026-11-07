"""The library's five read routes: what they answer, and everything they refuse.

The routes read the curated library slot and nothing else. Each answer here is checked against
the fixture library's known states (see ``ui_library_rig``), and each refusal against a plant:
a link or a hard link out to the corpora, the held-out tier, the private document tier, the
source tree, the experiments or a credential; a link inside the library; the reviewers' folder.
A refusal is a 403, a sentence (422) or an error in its own row of a listing, never a 500, and
never a byte of what it refused.

What promoting a candidate would do is held to promotion itself: the answer's "after" is the
digest of the bytes the write puts in a copy of the same library.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from ui_library_rig import (
    ANTIPATTERN_CANDIDATE,
    CONTROL_STANDARDS,
    REPLACING_CANDIDATE,
    RUBRIC_DRAFT,
    SKILL_CANDIDATE,
    STANDARDS_CANDIDATE,
    Library,
    build_library,
)
from ui_rig import RECORDER, Live, context_over, fake_ui, serving, snapshot, write_run

from physgate.gate.bounds_table import load_table
from physgate.gate.catalogue import STORE_CLASSES, catalogue_digest
from physgate.knowledge.promote import _apply, canaries
from physgate.knowledge.staging import Candidate
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.ui import assets, guard
from physgate.ui import library as library_routes
from physgate.ui.exceptions import PathRefusedError, UIError
from physgate.ui.library import CAP
from physgate.ui.paths import Allowlist
from physgate.ui.routes import Context

#: Written into every planted target; it must never appear in an answer. Built at run time.
MARKER = ("PLANTED-" + "TARGET-" + "MARKER").encode()

LISTING = "/api/library"
STAGED = "/api/library/staged"
RATINGS = "/api/library/ratings"


def _file(kind: str, role: str) -> str:
    return f"/api/library/files/{kind}/{role}"


def _candidate(candidate_id: str) -> str:
    return f"/api/library/staged/{candidate_id}"


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    """A checkout holding the fixture library, and every planted target beside it.

    Beside the library: the corpora, the private tier, the source tree, the experiments; then a
    run root with a credential in its run, a held-out tier and a folder outside every root.
    Each target carries the marker.
    """
    checkout = tmp_path / "checkout"
    library = build_library(checkout)
    for folder, name in (
        ("corpora", "answers.json"),
        (".docs", "notes.md"),
        ("src", "module.py"),
        ("experiments", "RESULT.md"),
    ):
        (checkout / folder).mkdir()
        (checkout / folder / name).write_bytes(MARKER + b"\n")
    runs = tmp_path / "runs"
    write_run(runs / "run-1", "run-1")
    (runs / "run-1" / LOGIN_FILE).write_bytes(MARKER + b"\n")
    held = tmp_path / "held"
    held.mkdir()
    (held / "scenario.json").write_bytes(MARKER + b"\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.txt").write_bytes(MARKER + b"\n")
    return {
        "checkout": checkout,
        "library": library,
        "lib": library.root,
        "runs": runs,
        "held": held,
        "outside": outside,
        "ui": fake_ui(tmp_path / "app"),
    }


def _context(world: dict[str, Any]) -> Context:
    allowlist = Allowlist.build(
        [str(world["runs"])],
        held_out=[str(world["held"])],
        answer_keys=[],
        harness=world["checkout"],
        library=str(world["lib"]),
    )
    return Context(allowlist=allowlist, assets=assets.load(world["ui"]))


def _ask(live: Live, target: str) -> tuple[int, Any]:
    status, _, body = live.request("GET", target)
    assert status != 500, (target, body[:300])
    assert MARKER not in body, target
    return status, json.loads(body)


def _ask_all(world: dict[str, Any], targets: list[str]) -> dict[str, tuple[int, Any]]:
    with serving(_context(world)) as live:
        return {target: _ask(live, target) for target in targets}


def _every_target() -> list[str]:
    files = [
        _file(kind, role)
        for kind in ("standards", "skill", "bounds")
        for role in ("control", "electrical", "cross", "sizing", "firmware")
    ]
    candidates = [
        _candidate(c)
        for c in (
            STANDARDS_CANDIDATE,
            SKILL_CANDIDATE,
            REPLACING_CANDIDATE,
            ANTIPATTERN_CANDIDATE,
            RUBRIC_DRAFT,
        )
    ]
    return [LISTING, STAGED, RATINGS, *files, *candidates]


def _row(listing: dict[str, Any], kind: str, role: str) -> dict[str, Any]:
    rows = [d for d in listing["documents"] if (d["kind"], d["role"]) == (kind, role)]
    assert len(rows) == 1, (kind, role, listing["documents"])
    row: dict[str, Any] = rows[0]
    return row


def _plant_link(path: Path, target: Path) -> None:
    path.unlink()
    path.symlink_to(target)


def _plant_hard_link(path: Path, target: Path) -> None:
    path.unlink()
    os.link(target, path)


# -- what the routes answer ------------------------------------------------------------------


def test_the_listing_names_each_file_its_state_and_the_promotion_that_wrote_it(
    world: dict[str, Any],
) -> None:
    """The state is chosen by bytes: the line that wrote a file carries the earlier time."""
    status, listing = _ask_all(world, [LISTING])[LISTING]
    assert status == 200
    standards = _row(listing, "standards", "control")
    assert standards["state"] == "matches"
    assert standards["promotion"]["promoted"] == "2026-10-21T15:07:08Z"
    assert standards["sha256"] == hashlib.sha256(CONTROL_STANDARDS).hexdigest()
    assert standards["size"] == len(CONTROL_STANDARDS)
    assert standards["path"] == "knowledge/control/standards.md"
    sizing = _row(listing, "standards", "sizing")
    assert (sizing["state"], sizing["promotion"]["promoted"]) == ("matches", "2026-10-16T13:29:06Z")
    assert _row(listing, "skill", "control")["state"] == "differs"
    assert _row(listing, "skill", "control")["promotion"] is None
    assert _row(listing, "standards", "electrical")["state"] == "no-digest"
    assert _row(listing, "standards", "cross")["state"] == "never-promoted"
    assert _row(listing, "bounds", "electrical")["state"] == "never-promoted"
    assert _row(listing, "bounds", "cross")["state"] == "never-promoted"
    roles = {d["role"] for d in listing["documents"]}
    assert roles == {"control", "cross", "electrical", "sizing"}, "laws holds no library file"
    assert listing["promotions"] == 10
    assert listing["staged"] == 4
    assert listing["library"] == os.path.realpath(world["lib"])
    [rubric] = listing["rubrics"]
    assert rubric["path"] == "knowledge/reviewers/control/rubric.md"
    assert rubric["role"] == "control"
    assert [line["promoted"] for line in rubric["promotions"]] == [
        "2026-10-08T12:00:00Z",
        "2026-10-09T12:00:00Z",
    ]


def test_one_file_is_served_with_its_text_and_every_line_naming_it_in_log_order(
    world: dict[str, Any],
) -> None:
    answers = _ask_all(
        world,
        [_file("standards", "control"), _file("skill", "control"), _file("bounds", "electrical")],
    )
    status, standards = answers[_file("standards", "control")]
    assert status == 200
    assert standards["text"] == CONTROL_STANDARDS.decode()
    assert [line["promoted"] for line in standards["promotions"]] == [
        "2026-10-22T05:58:48Z",
        "2026-10-21T15:07:08Z",
    ]
    assert standards["wrote"] == 1
    assert standards["state"] == "matches"
    status, skill = answers[_file("skill", "control")]
    assert (status, skill["wrote"], skill["state"]) == (200, None, "differs")
    status, bounds = answers[_file("bounds", "electrical")]
    assert (status, bounds["promotions"], bounds["state"]) == (200, [], "never-promoted")
    assert "sample_rate" in bounds["text"]


def test_a_missing_file_a_reserved_role_or_an_unknown_role_answers_404(
    world: dict[str, Any],
) -> None:
    answers = _ask_all(
        world,
        [
            _file("skill", "cross"),
            _file("standards", "reviewers"),
            _file("standards", "staging"),
            _file("standards", "nobody"),
            _candidate("no-such-candidate"),
        ],
    )
    assert {status for status, _ in answers.values()} == {404}


def test_the_staged_candidates_are_listed_without_their_content(world: dict[str, Any]) -> None:
    status, answer = _ask_all(world, [STAGED])[STAGED]
    assert status == 200
    rows = {row["candidate_id"]: row for row in answer["candidates"]}
    assert set(rows) == {
        STANDARDS_CANDIDATE,
        SKILL_CANDIDATE,
        REPLACING_CANDIDATE,
        ANTIPATTERN_CANDIDATE,
    }, "the rubric draft lies in the reviewers' tree and is never listed"
    assert all("content" not in row for row in rows.values())
    assert rows[STANDARDS_CANDIDATE]["destination"] == "knowledge/control/standards.md"
    assert rows[ANTIPATTERN_CANDIDATE]["destination"] == "knowledge/firmware/skill.md"
    assert rows[REPLACING_CANDIDATE]["replaces"] is True
    assert rows[SKILL_CANDIDATE]["role"] == "control"
    assert rows[SKILL_CANDIDATE]["written"] == "2026-11-01T10:00:00Z"
    assert len(rows[SKILL_CANDIDATE]["sha256"]) == 64


def _stage(lib: Path, kind: str, domain: str, candidate_id: str, content: str) -> None:
    record = Candidate.model_validate(
        {
            "kind": kind,
            "domain": domain,
            "content": content,
            "episode_id": "episode-9",
            "candidate_id": candidate_id,
            "written": "2026-11-02T10:00:00Z",
        }
    )
    path = lib / "staging" / kind / f"{candidate_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2) + "\n")


#: (candidate, effect): the fixture's own four, and three staged by the test.
EFFECTS = [
    (STANDARDS_CANDIDATE, "replaces whole"),
    ("cand-standards-creates", "creates"),
    ("cand-skill-creates", "creates"),
    (SKILL_CANDIDATE, "adds to"),
    (REPLACING_CANDIDATE, "replaces whole"),
    ("cand-antipattern-adds", "adds to"),
    (ANTIPATTERN_CANDIDATE, "creates"),
]


@pytest.mark.parametrize(("candidate_id", "effect"), EFFECTS, ids=[e[0] for e in EFFECTS])
def test_a_candidate_s_after_is_what_promotion_writes_in_a_copy_of_the_library(
    world: dict[str, Any], tmp_path: Path, candidate_id: str, effect: str
) -> None:
    lib = world["lib"]
    _stage(lib, "standards", "mechanical", "cand-standards-creates", "# Mechanical\n\nA rule.\n")
    _stage(lib, "skill", "electrical", "cand-skill-creates", "An electrical pattern.\n")
    _stage(lib, "antipattern", "control", "cand-antipattern-adds", "Never tune open loop.\n")
    status, answer = _ask_all(world, [_candidate(candidate_id)])[_candidate(candidate_id)]
    assert status == 200, answer
    assert answer["effect"] == effect
    assert answer["candidate"]["candidate_id"] == candidate_id
    destination = lib.parent / answer["destination"]
    if effect == "creates":
        assert answer["now"] is None
        assert not destination.exists()
    else:
        assert answer["now"]["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    copy = tmp_path / "copy" / "knowledge"
    shutil.copytree(lib, copy, symlinks=True)
    written = _apply(
        candidate_id,
        by="a person",
        staging_root=copy / "staging",
        knowledge_root=copy,
        promotions_path=copy / "promotions.jsonl",
        rubric_staging_root=copy / "reviewers" / "staging",
    )
    assert written == copy.parent / answer["destination"]
    data = written.read_bytes()
    assert answer["after"] == {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def test_the_changed_lines_are_a_unified_diff_of_the_file_now_and_after(
    world: dict[str, Any],
) -> None:
    target = _candidate(STANDARDS_CANDIDATE)
    status, answer = _ask_all(world, [target])[target]
    assert status == 200, answer
    lines = answer["lines"]
    assert lines[:2] == [
        "--- knowledge/control/standards.md",
        "+++ knowledge/control/standards.md",
    ]
    assert "-A loop is closed before it is tuned." in lines
    assert "+A new rule." in lines


def test_the_ratings_carry_every_value_with_its_unit_and_its_source(
    world: dict[str, Any],
) -> None:
    status, answer = _ask_all(world, [RATINGS])[RATINGS]
    assert status == 200
    tables = {table["domain"]: table for table in answer["tables"]}
    assert set(tables) == {"cross", "electrical"}
    [rate] = tables["electrical"]["ranges"]
    assert rate["quantity"] == "sample_rate"
    assert rate["kind"] == "frequency"
    assert rate["low"] == {"value": 0.78, "unit": "Hz"}
    assert rate["high"] == {"value": 32000, "unit": "Hz"}
    assert rate["retrieved"] == rate["confirmed"] == "2026-10-19"
    assert rate["source"] and rate["class"] and rate["note"]
    assert tables["electrical"]["path"] == "knowledge/electrical/bounds.toml"
    [envelope] = tables["cross"]["envelopes"]
    assert envelope["kind"] == "voltage"
    assert (envelope["low"], envelope["high"]) == (
        {"value": 0, "unit": "V"},
        {"value": 60, "unit": "V"},
    )
    assert tables["cross"]["ranges"] == []
    sent = answer["store_classes"]
    assert [s["name"] for s in sent] == [c.name for c in STORE_CLASSES]
    for store, served in zip(STORE_CLASSES, sent, strict=True):
        assert served["fastest_discharge"] == {"value": store.per_hour, "unit": "1/h"}
        assert served["source"] == store.source
    assert answer["catalogue_digest"] == catalogue_digest()


def test_with_no_library_every_library_route_answers_404(world: dict[str, Any]) -> None:
    context = context_over(world["runs"], ui_root=world["ui"])
    with serving(context) as live:
        for target in _every_target():
            status, body = _ask(live, target)
            assert status == 404, target
            assert body["error"] == "this server reads no library", target


# -- what never leaves the server ------------------------------------------------------------


def test_no_answer_carries_a_canary_or_a_byte_of_the_reviewers_folder(
    world: dict[str, Any],
) -> None:
    library: Library = world["library"]
    live_canaries = canaries(world["lib"] / "promotions.jsonl")
    assert len(live_canaries) == 2, "a sweep for no canary proves nothing"
    with serving(_context(world)) as live, RECORDER.recording():
        bodies = {}
        for target in _every_target():
            status, _, body = live.request("GET", target)
            assert status != 500, target
            bodies[target] = body
    for target, body in bodies.items():
        for canary in live_canaries:
            assert canary.encode() not in body, target
        assert b'"canary"' not in body, target
        assert library.reviewer_marker not in body, target
    assert json.loads(bodies[_candidate(RUBRIC_DRAFT)])["error"].startswith("no candidate")
    reviewers = os.path.realpath(world["lib"] / "reviewers")
    touched = [p for p in RECORDER.opened + RECORDER.listed if p.startswith(reviewers)]
    assert touched == [], touched


def test_a_file_linking_into_a_rubric_is_withheld(world: dict[str, Any]) -> None:
    _plant_link(
        world["lib"] / "control" / "standards.md",
        world["lib"] / "reviewers" / "control" / "rubric.md",
    )
    answers = _ask_all(world, [LISTING, _file("standards", "control")])
    status, body = answers[_file("standards", "control")]
    assert status == 403
    assert "reviewers' folder" in body["error"]
    assert "reviewers' folder" in _row(answers[LISTING][1], "standards", "control")["error"]


# -- the corpora, the held-out tier, credentials, hard links, the rest of the checkout --------


def _refused_everywhere(
    answers: dict[str, tuple[int, Any]], served: list[str], rows: list[tuple[str, str]]
) -> None:
    for target in served:
        assert answers[target][0] == 403, (target, answers[target])
    listing = answers.get(LISTING)
    for kind, role in rows:
        assert listing is not None
        row = _row(listing[1], kind, role)
        assert "error" in row and "sha256" not in row, row


def test_a_library_file_linked_to_the_corpora_is_refused_and_never_opened(
    world: dict[str, Any],
) -> None:
    target = world["checkout"] / "corpora" / "answers.json"
    _plant_link(world["lib"] / "control" / "standards.md", target)
    staged = world["lib"] / "staging" / "skill" / f"{SKILL_CANDIDATE}.json"
    _plant_link(staged, target)
    (world["lib"] / "corpora").mkdir()
    (world["lib"] / "corpora" / "standards.md").write_bytes(MARKER + b"\n")
    with RECORDER.recording():
        answers = _ask_all(
            world,
            [
                LISTING,
                STAGED,
                _file("standards", "control"),
                _file("standards", "corpora"),
                _candidate(SKILL_CANDIDATE),
            ],
        )
    _refused_everywhere(
        answers,
        [_file("standards", "control"), _file("standards", "corpora"), _candidate(SKILL_CANDIDATE)],
        [("standards", "control")],
    )
    assert "corpora" not in {d["role"] for d in answers[LISTING][1]["documents"]}
    [row] = [r for r in answers[STAGED][1]["candidates"] if r["name"] == staged.name]
    assert "error" in row
    real = os.path.realpath(target)
    assert [p for p in RECORDER.opened if os.path.realpath(p) == real] == []


def test_a_library_file_linked_to_the_held_out_tier_is_refused(world: dict[str, Any]) -> None:
    target = world["held"] / "scenario.json"
    _plant_link(world["lib"] / "control" / "standards.md", target)
    _plant_link(world["lib"] / "electrical" / "bounds.toml", target)
    answers = _ask_all(world, [LISTING, _file("standards", "control"), RATINGS])
    _refused_everywhere(
        answers,
        [_file("standards", "control"), RATINGS],
        [("standards", "control"), ("bounds", "electrical")],
    )


@pytest.mark.parametrize(
    "name", [".env", LOGIN_FILE, KEY_FILE, KEY_HELPER, ".ENV", LOGIN_FILE.upper(), KEY_FILE.upper()]
)
def test_credential_and_environment_files_in_the_library_are_never_listed_or_served(
    world: dict[str, Any], name: str
) -> None:
    planted = world["lib"] / "control" / name
    planted.write_bytes(MARKER + b"\n")
    _plant_link(world["lib"] / "control" / "skill.md", planted)
    answers = _ask_all(world, [*_every_target()])
    assert answers[_file("skill", "control")][0] == 403
    assert "credential" in answers[_file("skill", "control")][1]["error"]


def test_a_hard_link_in_the_library_is_refused_on_every_route_that_reads_it(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    _plant_hard_link(
        lib / "control" / "standards.md", world["checkout"] / "corpora" / "answers.json"
    )
    _plant_hard_link(
        lib / "staging" / "skill" / f"{SKILL_CANDIDATE}.json", world["outside"] / "file.txt"
    )
    _plant_hard_link(lib / "electrical" / "bounds.toml", world["runs"] / "run-1" / LOGIN_FILE)
    answers = _ask_all(
        world,
        [LISTING, STAGED, _file("standards", "control"), _candidate(SKILL_CANDIDATE), RATINGS],
    )
    _refused_everywhere(
        answers,
        [_file("standards", "control"), _candidate(SKILL_CANDIDATE), RATINGS],
        [("standards", "control"), ("bounds", "electrical")],
    )
    [row] = [r for r in answers[STAGED][1]["candidates"] if r["name"] == f"{SKILL_CANDIDATE}.json"]
    assert "more than one name" in row["error"]


@pytest.mark.parametrize(
    ("folder", "name"), [(".docs", "notes.md"), ("src", "module.py"), ("experiments", "RESULT.md")]
)
def test_the_private_tier_the_source_and_the_experiments_are_outside_every_root(
    world: dict[str, Any], folder: str, name: str
) -> None:
    _plant_link(world["lib"] / "control" / "standards.md", world["checkout"] / folder / name)
    status, body = _ask_all(world, [_file("standards", "control")])[_file("standards", "control")]
    assert status == 403
    assert "outside every root" in body["error"]


# -- links inside the library ----------------------------------------------------------------


def test_a_link_inside_the_library_is_refused_and_where_it_points_is_never_shown(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    _plant_link(lib / "control" / "skill.md", lib / "control" / "standards.md")
    answers = _ask_all(world, [LISTING, _file("skill", "control"), _candidate(SKILL_CANDIDATE)])
    status, body = answers[_file("skill", "control")]
    assert status == 403
    assert "link inside the library" in body["error"]
    assert "standards.md" not in json.dumps(body)
    assert "link inside the library" in _row(answers[LISTING][1], "skill", "control")["error"]
    # The candidate's destination is that link: what it would write to is refused too.
    assert answers[_candidate(SKILL_CANDIDATE)][0] == 403


def test_a_staged_candidate_that_is_a_link_inside_the_library_is_refused_as_promotion_refuses_it(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    staged = lib / "staging" / "skill" / f"{SKILL_CANDIDATE}.json"
    _plant_link(staged, lib / "staging" / "standards" / f"{STANDARDS_CANDIDATE}.json")
    answers = _ask_all(world, [STAGED, _candidate(SKILL_CANDIDATE)])
    status, body = answers[_candidate(SKILL_CANDIDATE)]
    assert status == 422
    assert "staged candidate is a link" in body["error"]
    [row] = [r for r in answers[STAGED][1]["candidates"] if r["name"] == staged.name]
    assert "link inside the library" in row["error"]


def test_a_folder_on_the_way_that_is_a_link_is_refused(world: dict[str, Any]) -> None:
    lib = world["lib"]
    elsewhere = lib / "elsewhere"
    (lib / "control").rename(elsewhere)
    (lib / "control").symlink_to(elsewhere)
    status, body = _ask_all(world, [_file("standards", "control")])[_file("standards", "control")]
    assert status == 403
    assert "link inside the library" in body["error"]


# -- refusals are sentences ------------------------------------------------------------------


def test_a_torn_promotion_log_line_is_one_refusal_naming_its_line(world: dict[str, Any]) -> None:
    with (world["lib"] / "promotions.jsonl").open("a") as log:
        log.write('{"kind": "standards", "destination": "knowl')
    answers = _ask_all(world, [LISTING, _file("standards", "control")])
    for target in (LISTING, _file("standards", "control")):
        status, body = answers[target]
        assert status == 422, target
        assert body["line"] == "11"
        assert "promotion log" in body["error"]


def test_a_candidate_that_is_not_one_is_its_own_row_and_a_refusal_alone(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    (lib / "staging" / "skill" / "not-a-candidate.json").write_text('{"kind": "skill"}\n')
    (lib / "staging" / "skill" / "bad name.json").write_text("{}\n")
    moved = lib / "staging" / "standards" / f"{SKILL_CANDIDATE}.json"
    (lib / "staging" / "skill" / f"{SKILL_CANDIDATE}.json").rename(moved)
    answers = _ask_all(
        world, [LISTING, STAGED, _candidate("not-a-candidate"), _candidate(SKILL_CANDIDATE)]
    )
    assert answers[LISTING][1]["staged"] == 3, "a candidate that is not one is not waiting"
    assert answers[STAGED][0] == 200, answers[STAGED]
    rows = {row["name"]: row for row in answers[STAGED][1]["candidates"]}
    assert "does not read as a candidate" in rows["not-a-candidate.json"]["error"]
    assert "not named as staging names a candidate" in rows["bad name.json"]["error"]
    assert "not the kind of the directory" in rows[f"{SKILL_CANDIDATE}.json"]["error"]
    assert rows[f"{STANDARDS_CANDIDATE}.json"]["candidate_id"] == STANDARDS_CANDIDATE
    assert answers[_candidate("not-a-candidate")][0] == 422
    assert answers[_candidate(SKILL_CANDIDATE)][0] == 422


def test_a_file_that_is_not_utf8_or_too_large_is_refused_with_a_sentence(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    (lib / "control" / "standards.md").write_bytes(b"\xff\xfe not text\n")
    (lib / "sizing" / "standards.md").write_bytes(b"x" * (CAP + 1))
    answers = _ask_all(
        world, [LISTING, _file("standards", "control"), _file("standards", "sizing")]
    )
    status, body = answers[_file("standards", "control")]
    assert status == 422, body
    assert "UTF-8" in body["error"]
    status, body = answers[_file("standards", "sizing")]
    assert status == 422, str(body)[:200]
    assert "larger than this page reads" in body["error"]
    assert "larger than" in _row(answers[LISTING][1], "standards", "sizing")["error"]
    assert _row(answers[LISTING][1], "standards", "control")["state"] == "differs"


def test_a_file_exactly_at_the_cap_is_read(world: dict[str, Any]) -> None:
    (world["lib"] / "sizing" / "standards.md").write_bytes(b"x" * CAP)
    status, body = _ask_all(world, [_file("standards", "sizing")])[_file("standards", "sizing")]
    assert status == 200, body
    assert body["size"] == CAP


def test_a_bounds_table_that_does_not_load_refuses_the_whole_tab(world: dict[str, Any]) -> None:
    (world["lib"] / "electrical" / "bounds.toml").write_text("[meta]\ndomain = 3\n")
    status, body = _ask_all(world, [RATINGS])[RATINGS]
    assert status == 422
    assert "bounds table" in body["error"]


# -- a swap between the judgement and the open ------------------------------------------------
#
# The swaps are made by the test inside the reader's own seams, so the reader is called
# directly: inside a served request the guard would refuse the test's own rename first.


def test_a_file_swapped_for_another_after_it_was_judged_is_refused(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = library_routes._open_file

    def swapped(path: str) -> int:
        if path.endswith("standards.md"):
            replacement = Path(path).with_name("replacement.md")
            replacement.write_bytes(b"other bytes\n")
            os.replace(replacement, path)
        return real_open(path)

    monkeypatch.setattr(library_routes, "_open_file", swapped)
    with pytest.raises(PathRefusedError, match="changed while it was read"):
        library_routes.document(_context(world), {"kind": "standards", "role": "control"})


def test_a_file_swapped_for_a_link_after_it_was_judged_is_refused(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = library_routes._open_file
    outside = world["outside"] / "file.txt"

    def swapped(path: str) -> int:
        if path.endswith("standards.md"):
            os.unlink(path)
            os.symlink(outside, path)
        return real_open(path)

    monkeypatch.setattr(library_routes, "_open_file", swapped)
    with pytest.raises(PathRefusedError, match="link inside the library"):
        library_routes.document(_context(world), {"kind": "standards", "role": "control"})


def test_a_bounds_table_changed_between_its_read_and_its_load_is_refused(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_load = load_table

    def changed(path: Path) -> Any:
        Path(path).write_text(Path(path).read_text() + "\n# changed\n")
        return real_load(path)

    monkeypatch.setattr(library_routes, "load_table", changed)
    with pytest.raises(UIError, match="changed while it was read") as refused:
        library_routes.ratings(_context(world), {})
    # A sentence (422), as the decision on the ratings states it, not a refusal of the path.
    assert not isinstance(refused.value, PathRefusedError)


# -- nothing is written ----------------------------------------------------------------------


def test_reading_every_route_writes_nothing_and_makes_no_folder(world: dict[str, Any]) -> None:
    """The antipattern's folder does not exist; describing its promotion must not make it."""
    lib = world["lib"]
    assert not (lib / "firmware").exists()
    before = snapshot(lib)
    with serving(_context(world)) as live, RECORDER.recording() as writes:
        for target in _every_target():
            assert live.request("GET", target)[0] != 500, target
    assert writes == [], writes
    assert snapshot(lib) == before
    assert not (lib / "firmware").exists()


def test_a_library_with_no_staging_folder_is_read_without_making_one(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    shutil.rmtree(lib / "staging")
    before = snapshot(lib)
    with RECORDER.recording() as writes:
        answers = _ask_all(world, [LISTING, STAGED, _candidate(STANDARDS_CANDIDATE)])
    assert answers[STAGED] == (200, {"candidates": []})
    assert answers[LISTING][1]["staged"] == 0
    assert answers[_candidate(STANDARDS_CANDIDATE)][0] == 404
    assert writes == []
    assert snapshot(lib) == before
    assert not (lib / "staging").exists()


def test_a_rubric_found_in_the_general_staging_folder_is_not_staged(world: dict[str, Any]) -> None:
    """Promotion looks for a rubric only in the reviewers' tree, so one here is never promoted."""
    lib = world["lib"]
    misplaced = lib / "staging" / "rubric" / "cand-rubric-misplaced.json"
    misplaced.parent.mkdir()
    record = json.loads((lib / "staging" / "skill" / f"{SKILL_CANDIDATE}.json").read_text())
    record.update(kind="rubric", candidate_id="cand-rubric-misplaced")
    misplaced.write_text(json.dumps(record))
    target = _candidate("cand-rubric-misplaced")
    status, body = _ask_all(world, [target])[target]
    assert status == 404, body
    assert body["error"].startswith("no candidate")


def test_two_tables_giving_one_kind_an_envelope_refuse_the_tab_as_the_gate_would(
    world: dict[str, Any],
) -> None:
    electrical = world["lib"] / "electrical" / "bounds.toml"
    cross = (world["lib"] / "cross" / "bounds.toml").read_text()
    envelope = cross[cross.index("[[envelope]]") :]
    electrical.write_text(electrical.read_text() + "\n" + envelope)
    status, body = _ask_all(world, [RATINGS])[RATINGS]
    assert status == 422, body
    assert "envelope" in body["error"]


# -- what the operating system refuses -------------------------------------------------------
#
# A folder or a file whose permission bits refuse the server is a refusal in words: a row's
# error, or a 403 when the library itself cannot be listed. The superuser ignores those bits,
# so these tests cannot hold there.

needs_permission_bits = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="the superuser ignores permission bits"
)


@pytest.fixture
def locked() -> Iterator[Callable[[Path, int], None]]:
    """Set a path's mode for the test, and give every path its mode back afterwards."""
    held: list[tuple[Path, int]] = []

    def lock(path: Path, mode: int) -> None:
        held.append((path, stat.S_IMODE(os.lstat(path).st_mode)))
        path.chmod(mode)

    yield lock
    for path, mode in reversed(held):
        path.chmod(mode)


@needs_permission_bits
def test_a_staged_folder_the_server_may_not_list_is_its_own_row_and_the_rest_stand(
    world: dict[str, Any], locked: Callable[[Path, int], None]
) -> None:
    locked(world["lib"] / "staging" / "skill", 0)
    answers = _ask_all(world, [LISTING, STAGED])
    assert answers[LISTING][0] == 200, answers[LISTING]
    assert answers[LISTING][1]["staged"] == 2, "the standards and the antipattern still wait"
    status, body = answers[STAGED]
    assert status == 200, body
    rows = {row["name"]: row for row in body["candidates"]}
    assert "not permitted" in rows["knowledge/staging/skill"]["error"]
    assert rows[f"{STANDARDS_CANDIDATE}.json"]["candidate_id"] == STANDARDS_CANDIDATE
    assert rows[f"{ANTIPATTERN_CANDIDATE}.json"]["candidate_id"] == ANTIPATTERN_CANDIDATE


@needs_permission_bits
def test_a_library_the_server_may_not_list_is_refused_in_words(
    world: dict[str, Any], locked: Callable[[Path, int], None]
) -> None:
    """Its files can still be read by name; what it holds cannot be listed."""
    locked(world["lib"], stat.S_IWUSR | stat.S_IXUSR)
    answers = _ask_all(world, [LISTING, RATINGS])
    for target in (LISTING, RATINGS):
        status, body = answers[target]
        assert status == 403, (target, body)
        assert "not permitted" in body["error"], target


@needs_permission_bits
def test_a_file_the_server_may_not_read_is_refused_as_such_and_never_as_a_swap(
    world: dict[str, Any], locked: Callable[[Path, int], None]
) -> None:
    locked(world["lib"] / "control" / "standards.md", 0)
    answers = _ask_all(world, [LISTING, _file("standards", "control")])
    status, body = answers[_file("standards", "control")]
    assert status == 403, body
    assert "not permitted" in body["error"]
    assert "changed" not in body["error"]
    row = _row(answers[LISTING][1], "standards", "control")
    assert "not permitted" in row["error"]
    assert _row(answers[LISTING][1], "skill", "control")["state"] == "differs"


# -- what a refusal says about where the library is -------------------------------------------


def _no_machine_path(world: dict[str, Any], answers: dict[str, tuple[int, Any]]) -> None:
    lib = world["lib"]
    spellings = {str(lib), os.path.realpath(lib), str(world["checkout"])}
    for target, (status, body) in answers.items():
        if status == 200:
            continue
        sent = json.dumps(body)
        for spelling in spellings:
            assert spelling not in sent, (target, sent)


def test_a_refusal_names_a_library_file_as_the_log_does_never_by_its_place_on_the_machine(
    world: dict[str, Any],
) -> None:
    lib = world["lib"]
    _plant_link(lib / "control" / "standards.md", world["checkout"] / ".docs" / "notes.md")
    (lib / "electrical" / "bounds.toml").write_text("[meta\n")
    staged = lib / "staging" / "skill" / f"{SKILL_CANDIDATE}.json"
    _plant_link(staged, lib / "staging" / "standards" / f"{STANDARDS_CANDIDATE}.json")
    answers = _ask_all(world, _every_target())
    _no_machine_path(world, answers)
    status, body = answers[_file("standards", "control")]
    assert (status, body["path"]) == (403, "knowledge/control/standards.md")
    status, body = answers[RATINGS]
    assert (status, body["path"]) == (422, "knowledge/electrical/bounds.toml")
    status, body = answers[_candidate(SKILL_CANDIDATE)]
    assert (status, body["path"]) == (422, f"knowledge/staging/skill/{SKILL_CANDIDATE}.json")


def test_two_tables_giving_one_kind_an_envelope_are_named_as_the_log_names_them(
    world: dict[str, Any],
) -> None:
    electrical = world["lib"] / "electrical" / "bounds.toml"
    cross = (world["lib"] / "cross" / "bounds.toml").read_text()
    electrical.write_text(electrical.read_text() + "\n" + cross[cross.index("[[envelope]]") :])
    answers = _ask_all(world, [RATINGS])
    _no_machine_path(world, answers)
    status, body = answers[RATINGS]
    assert status == 422, body
    assert body["tables"] == "knowledge/cross/bounds.toml, knowledge/electrical/bounds.toml"


# -- changed lines that differ only in how they end ------------------------------------------


def test_a_change_of_line_endings_alone_is_shown_as_changed_lines(world: dict[str, Any]) -> None:
    """Promoting LF text over a CRLF file rewrites every byte that ends a line."""
    lib = world["lib"]
    (lib / "mechanical").mkdir()
    (lib / "mechanical" / "standards.md").write_bytes(b"# M\r\nrule\r\n")
    _stage(lib, "standards", "mechanical", "cand-line-ends", "# M\nrule\n")
    status, answer = _ask_all(world, [_candidate("cand-line-ends")])[_candidate("cand-line-ends")]
    assert status == 200, answer
    assert answer["effect"] == "replaces whole"
    assert answer["now"]["size"] == 11
    assert answer["after"]["size"] == 9
    lines = answer["lines"]
    assert "-# M\u240d" in lines, lines
    assert "-rule\u240d" in lines, lines
    assert "+# M" in lines, lines
    assert "+rule" in lines, lines


def test_a_missing_last_newline_is_shown_as_a_changed_line(world: dict[str, Any]) -> None:
    lib = world["lib"]
    (lib / "mechanical").mkdir()
    (lib / "mechanical" / "standards.md").write_bytes(b"# M\nrule")
    _stage(lib, "standards", "mechanical", "cand-last-newline", "# M\nrule\n")
    target = _candidate("cand-last-newline")
    status, answer = _ask_all(world, [target])[target]
    assert status == 200, answer
    lines = answer["lines"]
    assert " # M" in lines, lines
    removed = lines.index("-rule")
    assert lines[removed + 1 : removed + 3] == ["\\ No newline at end of file", "+rule"], lines


# -- a log line nested deeper than the parser goes --------------------------------------------


def test_a_log_line_nested_too_deep_to_parse_is_a_refusal_naming_its_line(
    world: dict[str, Any],
) -> None:
    with (world["lib"] / "promotions.jsonl").open("a") as log:
        log.write("[" * 200_000 + "]" * 200_000 + "\n")
    status, body = _ask_all(world, [LISTING])[LISTING]
    assert status == 422, body
    assert body["line"] == "11"
    assert "promotion log" in body["error"]


# -- a folder swapped above a judged file -----------------------------------------------------


def test_a_folder_swapped_for_a_link_out_after_its_file_was_judged_is_a_refusal_never_a_500(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The open then names a file outside every root, and the request's guard refuses it.

    The swap is made inside the reader's own seam, with the guard set aside for the test's own
    rename only; the open itself runs under the guard, as in any request.
    """
    lib = world["lib"]
    outside = world["outside"] / "control"
    outside.mkdir()
    (outside / "standards.md").write_bytes(MARKER + b"\n")
    real_open = library_routes._open_file

    def swapped(path: str) -> int:
        if path.endswith(os.path.join("control", "standards.md")):
            token = guard._current.set(None)
            try:
                (lib / "control").rename(lib / "control-moved")
                (lib / "control").symlink_to(outside)
            finally:
                guard._current.reset(token)
        return real_open(path)

    monkeypatch.setattr(library_routes, "_open_file", swapped)
    status, body = _ask_all(world, [_file("standards", "control")])[_file("standards", "control")]
    assert status == 403, body
    assert "changed while it was read" in body["error"]
