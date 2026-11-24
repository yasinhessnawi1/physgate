"""``physgate drawing`` says what it leaves out, its check only reads, and make refuses early.

The help of each action says the drawing is shown, not measured, and names what is not in it.
``check`` prints a verdict per line (or the same as data), writes nothing, and refuses a record
it cannot read. ``make`` refuses a STEP file that is not the one the part's record names before
any kernel is asked, and refuses without a provisioned tool environment; ``example-part``
refuses a length outside its range. None of these rows needs the kernel.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from drawing_helpers import PLATE_HASH, Copy

from physgate.build.drawings.check import EXIT_PASSES, EXIT_REFUSED, EXIT_STALE
from physgate.build.drawings.kernel import ENVIRONMENT_VARIABLE
from physgate.cli import main

OTHER_HASH = "sha256:" + "0" * 64
LEFT_OUT = ("AP242", "ISO 286", "geometric tolerances", "assembly manual", "a PDF")


def _help(capsys: pytest.CaptureFixture[str], action: str) -> str:
    with pytest.raises(SystemExit):
        main(["drawing", action, "--help"])
    return " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("action", ["make", "check"])
def test_the_help_says_shown_not_measured_and_names_what_is_left_out(
    capsys: pytest.CaptureFixture[str], action: str
) -> None:
    said = _help(capsys, action)
    assert "shown, not measured" in said
    for left in LEFT_OUT:
        assert left in said, left
    assert "nothing here claims the drawing is fit to manufacture from" in said
    assert "never patched" in said


def test_check_prints_a_verdict_per_line_and_says_stale_plainly(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = Copy(tmp_path / "d")
    assert main(["drawing", "check", str(copy.drawing), str(copy.part)]) == EXIT_PASSES
    said = capsys.readouterr().out.splitlines()
    rows = [line for line in said if line.split(" ")[0] in {"part", "file", "views", "title"}]
    rows += [line for line in said if line.startswith("dimensions ")]
    assert len(rows) == 5 and all("PASSES" in row for row in rows)

    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    assert main(["drawing", "check", str(copy.drawing), str(copy.part)]) == EXIT_STALE
    out = capsys.readouterr().out
    part = next(line for line in out.splitlines() if line.startswith("part "))
    assert "STALE" in part and PLATE_HASH in part and OTHER_HASH in part
    assert "the drawing is STALE" in out


def test_check_gives_the_same_verdicts_as_data(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = Copy(tmp_path / "d")
    copy.part_record(lambda part: part.update(geometry_hash=OTHER_HASH))
    status = main(["drawing", "check", str(copy.drawing), str(copy.part), "--json"])
    told = json.loads(capsys.readouterr().out)
    assert status == told["exit_status"] == EXIT_STALE
    assert [c["verdict"] for c in told["checks"]] == ["stale", *["passes"] * 4]
    assert "fit to manufacture" in told["left_out"]


def _tree_of(root: Path) -> dict[str, tuple[str, int]]:
    return {
        str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_check_writes_nothing(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    copy = Copy(tmp_path / "d")
    before = _tree_of(tmp_path)
    main(["drawing", "check", str(copy.drawing), str(copy.part)])
    main(["drawing", "check", str(copy.drawing), str(copy.part), "--json"])
    capsys.readouterr()
    assert _tree_of(tmp_path) == before


def test_check_refuses_a_record_it_cannot_read(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = Copy(tmp_path / "d")
    copy.part_record(lambda part: part.update(kind="pair"))
    assert main(["drawing", "check", str(copy.drawing), str(copy.part)]) == EXIT_REFUSED
    out, err = capsys.readouterr()
    assert out == "" and "not one the geometry helper writes" in json.loads(err)["error"]
    assert main(["drawing", "check", str(tmp_path / "none.json"), str(copy.part)]) == EXIT_REFUSED


def _module_with_step(root: Path, step: bytes, named: bytes) -> Path:
    module = root / "module"
    (module / "exports").mkdir(parents=True)
    (module / "exports" / "plate.step").write_bytes(step)
    part = json.loads((Copy(root / "fixture").part).read_text(encoding="utf-8"))
    part["exports"] = [
        {
            "file": "exports/plate.step",
            "size": {"value": len(named), "unit": "byte"},
            "sha256": hashlib.sha256(named).hexdigest(),
        }
    ]
    path = module / "plate.result.json"
    path.write_text(json.dumps(part), encoding="utf-8")
    return path


def test_make_refuses_a_step_file_that_is_not_the_part_s_before_the_kernel_is_asked(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    part = _module_with_step(tmp_path, b"ISO-10303-21; changed", b"ISO-10303-21; recorded")
    out = tmp_path / "out"
    # The tool environment named is no environment at all: the refusal comes before it is used.
    tree = tmp_path / "no-environment"
    argv = ["drawing", "make", str(part), "--out", str(out), "--tool-environment", str(tree)]
    status = main(argv)
    assert status == EXIT_REFUSED
    error = json.loads(capsys.readouterr().err)["error"]
    assert "is not the file the part's record names" in error and "sha256" in error
    assert not out.exists()


def test_make_refuses_without_a_provisioned_tool_environment(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    part = _module_with_step(tmp_path, b"ISO-10303-21; same", b"ISO-10303-21; same")
    out = tmp_path / "out"
    monkeypatch.delenv(ENVIRONMENT_VARIABLE, raising=False)
    assert main(["drawing", "make", str(part), "--out", str(out)]) == EXIT_REFUSED
    assert "--tool-environment" in json.loads(capsys.readouterr().err)["error"]
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv(ENVIRONMENT_VARIABLE, str(empty))
    assert main(["drawing", "make", str(part), "--out", str(out)]) == EXIT_REFUSED
    assert "not a provisioned tool environment" in json.loads(capsys.readouterr().err)["error"]
    assert not out.exists()


@pytest.mark.parametrize("length", ["10", "500", "nan"])
def test_example_part_refuses_a_length_outside_its_range(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, length: str
) -> None:
    module = tmp_path / "module"
    argv = ["drawing", "example-part", str(module), "--length", length]
    assert main([*argv, "--tool-environment", str(tmp_path)]) == EXIT_REFUSED
    assert "the plate's length is from 20 to 400 mm" in json.loads(capsys.readouterr().err)["error"]
    assert not module.exists()
