"""``physgate drawing make`` writes its three files into ``--out`` and nowhere else.

Each file is written under a temporary name of its own in ``--out`` and then renamed over its
final name, so a file already there is replaced and never written through. A final name that is
a symbolic link, or is there and is not a regular file, and an ``--out`` that is a link or is
not a directory, are refused before the kernel is asked: exit 2, one sentence, nothing written.
What cannot be done ends the same way, never in a traceback: a kernel's answer that is not JSON,
an answer with no geometry hash, a module directory that cannot be made.

The kernel here is a stand-in: a tool environment whose interpreter prints the committed
projection of the chassis plate (or what a row needs it to print), so no row needs the kernel.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from drawing_helpers import FIXTURE, module_with_step, projection_said, stand_in_tree

from physgate.build.drawings.check import EXIT_PASSES, EXIT_REFUSED
from physgate.cli import main

WRITTEN = ("plate.svg", "plate.drawing.json", "plate.projection.json")
VICTIM = b"a file outside --out, which make must never write\n"


def _part(root: Path) -> Path:
    return module_with_step(root, b"ISO-10303-21; the plate", b"ISO-10303-21; the plate")


def _make(root: Path, out: Path, said: str | None = None) -> int:
    tree = stand_in_tree(root, projection_said() if said is None else said)
    part = _part(root)
    return main(["drawing", "make", str(part), "--out", str(out), "--tool-environment", str(tree)])


def _refusal(capsys: pytest.CaptureFixture[str]) -> str:
    """The refusal's sentence: JSON on the error stream, one line, no traceback."""
    out, err = capsys.readouterr()
    assert "Traceback" not in err and "Traceback" not in out
    error = json.loads(err)["error"]
    assert isinstance(error, str) and error and "\n" not in error
    return error


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# --- what make writes -------------------------------------------------------------------------


def test_make_writes_the_three_files_and_nothing_else_into_out(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "drawings"
    assert _make(tmp_path, out) == EXIT_PASSES
    assert _names(out) == sorted(WRITTEN)
    assert (out / "plate.svg").read_bytes() == (FIXTURE / "plate.svg").read_bytes()
    capsys.readouterr()


def test_make_replaces_the_files_a_drawing_made_before_left_and_leaves_nothing_else(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "drawings"
    out.mkdir()
    for name in WRITTEN:
        (out / name).write_text("an older drawing\n", encoding="utf-8")
    assert _make(tmp_path, out) == EXIT_PASSES
    assert _names(out) == sorted(WRITTEN)
    assert (out / "plate.svg").read_bytes() == (FIXTURE / "plate.svg").read_bytes()
    assert (out / "plate.projection.json").read_bytes() == (
        FIXTURE / "plate.projection.json"
    ).read_bytes()
    capsys.readouterr()


# --- links and what is not a file -------------------------------------------------------------


@pytest.mark.parametrize("name", WRITTEN)
def test_make_refuses_a_link_in_out_named_as_one_of_its_files_and_writes_nothing_through_it(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, name: str
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_bytes(VICTIM)
    out = tmp_path / "drawings"
    out.mkdir()
    (out / name).symlink_to(victim)
    assert _make(tmp_path, out) == EXIT_REFUSED
    error = _refusal(capsys)
    assert name in error and "link" in error
    assert victim.read_bytes() == VICTIM
    assert (out / name).is_symlink() and (out / name).resolve() == victim.resolve()
    assert _names(out) == [name]


def test_make_refuses_a_directory_where_one_of_its_files_goes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "drawings"
    (out / "plate.svg").mkdir(parents=True)
    assert _make(tmp_path, out) == EXIT_REFUSED
    assert "plate.svg" in _refusal(capsys)
    assert _names(out) == ["plate.svg"] and not any((out / "plate.svg").iterdir())


def test_make_refuses_an_out_that_is_a_link(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = tmp_path / "drawings"
    out.symlink_to(elsewhere, target_is_directory=True)
    assert _make(tmp_path, out) == EXIT_REFUSED
    assert "link" in _refusal(capsys)
    assert _names(elsewhere) == []


def test_make_refuses_an_out_that_is_a_file(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "drawings"
    out.write_bytes(VICTIM)
    assert _make(tmp_path, out) == EXIT_REFUSED
    assert "not a directory" in _refusal(capsys)
    assert out.read_bytes() == VICTIM


# --- what cannot be done ends in a sentence ---------------------------------------------------


def test_make_refuses_a_projection_the_kernel_did_not_print_as_json(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "drawings"
    assert _make(tmp_path, out, said="PROJECTION {not json") == EXIT_REFUSED
    assert "not JSON" in _refusal(capsys)
    assert not out.exists()


def test_example_part_refuses_a_kernel_answer_without_a_geometry_hash(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tree = stand_in_tree(tmp_path, "EXAMPLE-PART {}")
    argv = ["drawing", "example-part", str(tmp_path / "module"), "--tool-environment", str(tree)]
    assert main(argv) == EXIT_REFUSED
    assert "geometry hash" in _refusal(capsys)


def test_example_part_refuses_a_module_directory_that_cannot_be_made(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tree = stand_in_tree(tmp_path, 'EXAMPLE-PART {"geometry_hash": "sha256:' + "0" * 64 + '"}')
    a_file = tmp_path / "a-file"
    a_file.write_bytes(VICTIM)
    module = a_file / "module"
    argv = ["drawing", "example-part", str(module), "--tool-environment", str(tree)]
    assert main(argv) == EXIT_REFUSED
    assert "cannot be made" in _refusal(capsys)
    assert a_file.read_bytes() == VICTIM
