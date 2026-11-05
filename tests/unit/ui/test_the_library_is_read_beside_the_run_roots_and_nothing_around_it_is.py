"""The library is a slot of its own on the allowlist, and nothing beside it becomes readable.

The curated library is the checkout's ``knowledge`` folder. It sits next to what the server
must never serve: the evaluation corpora (which carry their answers), the private document
tier, the source tree, the experiments and the environment file. So the library is named on
the allowlist as one folder, held to start checks of its own, and every refusal that holds
beneath a run root holds inside it too.

One folder inside the library is withheld: ``reviewers``. Any local process can reach the
server, a builder's shell among them, and a builder that could fetch its reviewer's rubric
over loopback would no longer be judged blind. The withheld folder is refused the way the
held-out tier is, by the resolver and by the guard's read rule, and not by the start check,
since it lies inside the library by construction.

Each test plants one form against one rule, and where two rules could refuse the same path,
the test says which one it proves and builds the case so only that one can.
"""

from __future__ import annotations

import json
import os
import socketserver
from pathlib import Path

import pytest
from ui_rig import context_over, fake_ui, serving, write_run

from physgate.cli import main
from physgate.gate.bounds_table import KNOWLEDGE_DIR
from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE
from physgate.ui import cli as ui_cli
from physgate.ui.exceptions import PathRefusedError, StartupRefusedError
from physgate.ui.paths import Allowlist
from physgate.ui.routes import run_directories

#: Why the resolver refuses the reviewers' folder.
WITHHELD = "reviewers' folder"


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Path]:
    """A checkout with a library and what lies beside it, a run root, a held-out tier, a stray."""
    checkout = tmp_path / "checkout"
    library = checkout / "knowledge"
    (library / "control").mkdir(parents=True)
    (library / "control" / "standards.md").write_text("# Control standards\n")
    (library / "reviewers" / "control").mkdir(parents=True)
    (library / "reviewers" / "control" / "rubric.md").write_text("# rubric\n")
    (checkout / "corpora").mkdir()
    (checkout / "corpora" / "answers.json").write_text("{}\n")
    for folder, name in ((".docs", "notes.md"), ("src", "module.py"), ("experiments", "RESULT.md")):
        (checkout / folder).mkdir()
        (checkout / folder / name).write_text("not for the UI\n")
    runs = tmp_path / "runs"
    write_run(runs / "run-1", "run-1")
    held = tmp_path / "held"
    held.mkdir()
    (held / "scenario.json").write_text("{}\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "file.txt").write_text("outside every root\n")
    return {
        "checkout": checkout,
        "library": library,
        "runs": runs,
        "held": held,
        "outside": outside,
    }


def _allow(world: dict[str, Path], *, held_out: tuple[str, ...] | None = None) -> Allowlist:
    return Allowlist.build(
        [str(world["runs"])],
        held_out=[str(world["held"])] if held_out is None else list(held_out),
        answer_keys=[],
        harness=world["checkout"],
        library=str(world["library"]),
    )


def _refused(allow: Allowlist, path: Path, reason: str) -> None:
    """Refused by the resolver with ``reason``, and by the guard's read rule as well."""
    with pytest.raises(PathRefusedError, match=reason):
        allow.resolve(path)
    assert allow.readable(str(path)) is False, path


# -- the slot ---------------------------------------------------------------------------------


def test_the_library_is_its_own_slot_and_a_file_in_it_resolves(world: dict[str, Path]) -> None:
    allow = _allow(world)
    real = Path(os.path.realpath(world["library"]))
    assert allow.library is not None
    assert allow.library.path == real
    assert [root.path for root in allow.roots] == [Path(os.path.realpath(world["runs"]))]
    standards = world["library"] / "control" / "standards.md"
    assert allow.resolve(standards) == real / "control" / "standards.md"
    assert allow.readable(str(standards)) is True


def test_the_withheld_folder_is_the_library_s_reviewers_and_not_part_of_the_refused_set(
    world: dict[str, Path],
) -> None:
    allow = _allow(world)
    reviewers = str(Path(os.path.realpath(world["library"])) / "reviewers")
    assert allow.withheld == (reviewers,)
    assert reviewers not in allow.refused


def test_without_a_library_there_is_no_slot_and_nothing_is_withheld(
    world: dict[str, Path],
) -> None:
    allow = Allowlist.build(
        [str(world["runs"])], held_out=[], answer_keys=[], harness=world["checkout"]
    )
    assert allow.library is None
    assert allow.withheld == ()
    with pytest.raises(PathRefusedError, match="outside every root"):
        allow.resolve(world["library"] / "control" / "standards.md")


# -- the start checks -------------------------------------------------------------------------


def test_a_library_that_is_missing_or_not_a_directory_refuses_the_start(
    world: dict[str, Path], tmp_path: Path
) -> None:
    missing = tmp_path / "nowhere" / "knowledge"
    a_file = tmp_path / "file" / "knowledge"
    a_file.parent.mkdir()
    a_file.write_text("not a folder\n")
    for given in (str(missing), str(a_file)):
        with pytest.raises(StartupRefusedError, match="existing directory"):
            Allowlist.build(
                [str(world["runs"])], held_out=[], answer_keys=[], harness=None, library=given
            )
    with pytest.raises(StartupRefusedError, match="NUL"):
        Allowlist.build(
            [str(world["runs"])],
            held_out=[],
            answer_keys=[],
            harness=None,
            library=str(world["library"]) + "\x00",
        )


def test_a_library_that_is_a_link_into_a_corpus_refuses_the_start(tmp_path: Path) -> None:
    """Refused by the corpus component alone: no harness is named, so no refused path overlaps."""
    runs = tmp_path / "runs"
    runs.mkdir()
    inside = tmp_path / "other" / "corpora" / "knowledge"
    inside.mkdir(parents=True)
    link = tmp_path / "linked" / "knowledge"
    link.parent.mkdir()
    link.symlink_to(inside)
    with pytest.raises(StartupRefusedError, match="evaluation corpus"):
        Allowlist.build([str(runs)], held_out=[], answer_keys=[], harness=None, library=str(link))


def test_a_library_not_named_knowledge_refuses_the_start(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    other = tmp_path / "library"
    other.mkdir()
    with pytest.raises(StartupRefusedError, match="named knowledge"):
        Allowlist.build([str(runs)], held_out=[], answer_keys=[], harness=None, library=str(other))


def test_a_held_out_path_inside_the_library_refuses_the_start(world: dict[str, Path]) -> None:
    inside = world["library"] / "held"
    inside.mkdir()
    with pytest.raises(StartupRefusedError, match="library overlaps a path nothing may read"):
        _allow(world, held_out=(str(inside),))


def test_a_library_inside_a_held_out_path_refuses_the_start(world: dict[str, Path]) -> None:
    with pytest.raises(StartupRefusedError, match="library overlaps a path nothing may read"):
        _allow(world, held_out=(str(world["checkout"]),))


def test_a_library_holding_the_harness_s_corpora_refuses_the_start(world: dict[str, Path]) -> None:
    harness = world["library"] / "inner"
    harness.mkdir()
    with pytest.raises(StartupRefusedError, match="library overlaps a path nothing may read"):
        Allowlist.build(
            [str(world["runs"])],
            held_out=[],
            answer_keys=[],
            harness=harness,
            library=str(world["library"]),
        )


def test_a_library_inside_a_run_root_refuses_the_start(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    library = runs / "knowledge"
    library.mkdir(parents=True)
    with pytest.raises(StartupRefusedError, match="overlaps a run root"):
        Allowlist.build(
            [str(runs)], held_out=[], answer_keys=[], harness=None, library=str(library)
        )


def test_a_run_root_inside_the_library_refuses_the_start(world: dict[str, Path]) -> None:
    inner = world["library"] / "runs"
    inner.mkdir()
    with pytest.raises(StartupRefusedError, match="overlaps a run root"):
        Allowlist.build(
            [str(inner)], held_out=[], answer_keys=[], harness=None, library=str(world["library"])
        )


# -- what stays refused inside and around it ---------------------------------------------------


def test_a_corpus_folder_inside_the_library_is_refused(world: dict[str, Path]) -> None:
    """Refused by the corpus component alone.

    The path lies inside the library and reaches no refused path: the harness's own corpora
    is the checkout's, beside the library.
    """
    planted = world["library"] / "corpora" / "answers.json"
    planted.parent.mkdir()
    planted.write_text("{}\n")
    _refused(_allow(world), planted, "evaluation corpus")


def test_a_held_out_tier_named_later_into_the_library_is_refused_by_the_refused_set(
    world: dict[str, Path],
) -> None:
    """Refused by the request-time refused set alone: the path lies inside the library."""
    tier = world["held"].parent / "tier-named-later"
    allow = _allow(world, held_out=(str(tier),))
    standards = world["library"] / "control" / "standards.md"
    assert allow.readable(str(standards)), "readable before the link"
    tier.symlink_to(world["library"] / "control")
    _refused(allow, standards, "reaches a path nothing may read")


def test_the_harness_s_corpora_made_into_a_link_into_the_library_is_refused(
    world: dict[str, Path], tmp_path: Path
) -> None:
    """The harness's corpora is refused wherever it comes to point, here into the library."""
    harness = tmp_path / "harness"
    harness.mkdir()
    allow = Allowlist.build(
        [str(world["runs"])],
        held_out=[],
        answer_keys=[],
        harness=harness,
        library=str(world["library"]),
    )
    standards = world["library"] / "control" / "standards.md"
    assert allow.readable(str(standards)), "readable before the link"
    (harness / "corpora").symlink_to(world["library"] / "control")
    _refused(allow, standards, "reaches a path nothing may read")


def test_a_library_file_linked_to_the_corpora_or_the_held_out_tier_is_refused(
    world: dict[str, Path],
) -> None:
    allow = _allow(world)
    for name, target in (
        ("corpus.md", world["checkout"] / "corpora" / "answers.json"),
        ("held.md", world["held"] / "scenario.json"),
    ):
        link = world["library"] / "control" / name
        link.symlink_to(target)
        _refused(allow, link, "outside every root")


def test_links_to_the_private_tier_the_source_and_the_experiments_are_outside_every_root(
    world: dict[str, Path],
) -> None:
    allow = _allow(world)
    for name, target in (
        ("private.md", world["checkout"] / ".docs" / "notes.md"),
        ("source.md", world["checkout"] / "src" / "module.py"),
        ("experiment.md", world["checkout"] / "experiments" / "RESULT.md"),
    ):
        link = world["library"] / "control" / name
        link.symlink_to(target)
        _refused(allow, link, "outside every root")


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        LOGIN_FILE,
        KEY_FILE,
        KEY_HELPER,
        ".ENV",
        LOGIN_FILE.upper(),
        KEY_FILE.upper(),
        KEY_HELPER.title(),
    ],
)
def test_a_credential_or_environment_file_in_the_library_is_refused_in_any_case(
    world: dict[str, Path], name: str
) -> None:
    planted = world["library"] / "control" / name
    planted.write_text("not for the UI\n")
    _refused(_allow(world), planted, "credential or environment file")


def test_a_hard_link_in_the_library_is_refused_wherever_its_other_name_lies(
    world: dict[str, Path], tmp_path: Path
) -> None:
    credential = tmp_path / "state" / LOGIN_FILE
    credential.parent.mkdir()
    credential.write_text("{}\n")
    allow = _allow(world)
    for name, target in (
        ("corpus.md", world["checkout"] / "corpora" / "answers.json"),
        ("credential.md", credential),
        ("outside.md", world["outside"] / "file.txt"),
    ):
        linked = world["library"] / "control" / name
        os.link(target, linked)
        _refused(allow, linked, "more than one name")


# -- the withheld reviewers' folder ------------------------------------------------------------


def test_the_reviewers_folder_is_withheld_however_it_is_spelt(world: dict[str, Path]) -> None:
    allow = _allow(world)
    rubric = world["library"] / "reviewers" / "control" / "rubric.md"
    _refused(allow, rubric, WITHHELD)
    _refused(allow, world["library"] / "reviewers", WITHHELD)
    _refused(allow, world["library"] / "reviewers" / "staging" / "rubric" / "x.json", WITHHELD)
    _refused(allow, world["library"] / "Reviewers" / "control" / "rubric.md", WITHHELD)


def test_a_library_file_that_links_into_a_rubric_is_withheld(world: dict[str, Path]) -> None:
    link = world["library"] / "control" / "skill.md"
    link.symlink_to(world["library"] / "reviewers" / "control" / "rubric.md")
    _refused(_allow(world), link, WITHHELD)


# -- never a run root -------------------------------------------------------------------------


def test_no_folder_in_the_library_can_be_opened_for_a_write(world: dict[str, Path]) -> None:
    """The descriptor walk a decision writes through reaches run roots only."""
    allow = _allow(world)
    with pytest.raises(PathRefusedError, match="outside every root"):
        allow.open_directory(world["library"] / "control")
    with allow.opened_directory(world["runs"] / "run-1") as fd:
        assert fd >= 0


def test_the_library_is_never_scanned_for_runs(world: dict[str, Path]) -> None:
    write_run(world["library"] / "run-in-library", "run-in-library")
    with_library = run_directories(_allow(world))
    without = run_directories(
        Allowlist.build(
            [str(world["runs"])],
            held_out=[str(world["held"])],
            answer_keys=[],
            harness=world["checkout"],
        )
    )
    assert [(p, n) for p, n, _ in with_library] == [(0, "run-1")]
    assert with_library == without


def test_the_run_listing_is_byte_identical_with_and_without_a_library(
    world: dict[str, Path], tmp_path: Path
) -> None:
    ui = fake_ui(tmp_path / "app")
    bodies = []
    for library in (None, world["library"]):
        context = context_over(world["runs"], ui_root=ui, library=library)
        assert (context.allowlist.library is None) == (library is None)
        with serving(context) as live:
            status, _, body = live.request("GET", "/api/runs")
        assert status == 200
        bodies.append(body)
    assert bodies[0] == bodies[1]
    assert [run["name"] for run in json.loads(bodies[0])["runs"]] == ["run-1"]


# -- the command ------------------------------------------------------------------------------


def test_with_no_flag_the_library_is_the_checkout_s_own_knowledge_folder() -> None:
    """The folder the gate loads its bounds tables from and decomposition copies from."""
    assert ui_cli._default_library() == KNOWLEDGE_DIR
    assert KNOWLEDGE_DIR.is_dir()


def test_with_no_checkout_or_no_knowledge_folder_the_slot_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui_cli, "harness_root", lambda: None)
    assert ui_cli._default_library() is None
    bare = tmp_path / "checkout"
    bare.mkdir()
    monkeypatch.setattr(ui_cli, "harness_root", lambda: bare)
    assert ui_cli._default_library() is None
    (bare / "knowledge").mkdir()
    assert ui_cli._default_library() == bare / "knowledge"


@pytest.fixture
def command(world: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The command with the fixture build, stopping as an interrupt would once it would serve."""
    ui = fake_ui(tmp_path / "app")
    monkeypatch.setattr(ui_cli, "_ui_root", lambda: ui)

    def interrupted(self: socketserver.BaseServer, poll_interval: float = 0.5) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(socketserver.BaseServer, "serve_forever", interrupted)
    return ui


def test_an_explicit_library_that_fails_a_check_refuses_the_start(
    world: dict[str, Path], command: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "library"
    other.mkdir()
    argv = ["ui", "--root", str(world["runs"]), "--library", str(other), "--port", "0"]
    assert main(argv) == 2
    error = json.loads(capsys.readouterr().err)
    assert "named knowledge" in error["error"]


def test_the_start_announcement_names_the_library_it_reads(
    world: dict[str, Path], command: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["ui", "--root", str(world["runs"]), "--library", str(world["library"]), "--port", "0"]
    assert main(argv) == 0
    started = json.loads(capsys.readouterr().out)
    assert "library" in started, sorted(started)
    assert started["library"] == os.path.realpath(world["library"])
    reviewers = os.path.join(os.path.realpath(world["library"]), "reviewers")
    assert reviewers not in started["refused"], "withheld, not refused: it lies inside the library"


def test_with_no_library_the_announcement_says_so(
    world: dict[str, Path],
    command: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ui_cli, "_default_library", lambda: None)
    assert main(["ui", "--root", str(world["runs"]), "--port", "0"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert "library" in started
    assert started["library"] is None


def test_with_no_flag_the_command_reads_the_default_library(
    world: dict[str, Path],
    command: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ui_cli, "_default_library", lambda: world["library"])
    assert main(["ui", "--root", str(world["runs"]), "--port", "0"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert "library" in started, sorted(started)
    assert started["library"] == os.path.realpath(world["library"])
