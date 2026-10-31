"""What the tool environment's programs answer is read bounded, parsed as data, and held to print.

The interpreter's probe answer and each native tool's version line are the only output of the
environment the harness itself reads. An answer past the bound is no answer, one that is not a
single JSON object is refused, and no name or version holding a control character is recorded.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from physgate.toolenv.exceptions import ToolEnvironmentError
from physgate.toolenv.record import (
    MAX_ANSWER_BYTES,
    Distribution,
    NativeTool,
    measure,
    run_program,
)

TEN_MB = 10 * 1024 * 1024


def test_an_answer_past_the_bound_is_no_answer() -> None:
    assert MAX_ANSWER_BYTES < TEN_MB
    small = run_program([sys.executable, "-I", "-c", "print('x' * 1000)"])
    assert small is not None and small.strip() == "x" * 1000
    big = run_program([sys.executable, "-I", "-c", f"import sys; sys.stdout.write('x' * {TEN_MB})"])
    assert big is None


def test_an_answer_that_is_not_text_is_no_answer() -> None:
    raw = run_program(
        [sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"]
    )
    assert raw is None


@pytest.mark.parametrize("bad", ["3.12\x00", "numpy\x1b[2J", "a\nb", "\x7f"])
def test_no_name_or_version_with_a_control_character_is_recorded(bad: str) -> None:
    with pytest.raises(ValidationError):
        Distribution(name=bad, version="1")
    with pytest.raises(ValidationError):
        Distribution(name="numpy", version=bad)
    with pytest.raises(ValidationError):
        NativeTool(name="gcc", path="/e/bin/gcc", resolved="/e/bin/gcc", version=bad)
    Distribution(name="numpy", version="2.1.2")


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "env"
    (root / "bin").mkdir(parents=True)
    python = root / "bin" / "python3"
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    return root, python


@pytest.mark.parametrize(
    "answer",
    [
        "x" * TEN_MB,
        '{"version": "3.12\\u0000", "prefix": "ROOT", "physgate": false, "distributions": []}',
        '{"version": "3.12.9", "prefix": "ROOT", "physgate": false,'
        ' "distributions": [["np\\u001b", "1"]]}',
        '{"version": "3.12.9", "prefix": "ROOT", "physgate": false, "distributions": "all"}',
        "[" * 100_000,
        json.dumps(
            {
                "version": "3.12.9",
                "prefix": "ROOT",
                "physgate": False,
                "distributions": [["d" + str(i), "1"] for i in range(80_000)],
            }
        ),
    ],
)
def test_a_hostile_probe_answer_is_refused_cleanly(tmp_path: Path, answer: str) -> None:
    root, python = _tree(tmp_path)
    text = answer.replace("ROOT", str(root))

    def run(argv: Sequence[str]) -> str | None:
        return text

    try:
        measure(str(python), [str(root)], native={}, forbidden={}, runner=run)
    except Exception as exc:  # noqa: BLE001 - the test asserts what it was
        raised: BaseException | None = exc
    else:
        raised = None
    assert isinstance(raised, ToolEnvironmentError), raised


def test_a_well_formed_probe_answer_is_recorded(tmp_path: Path) -> None:
    root, python = _tree(tmp_path)
    answer = {"version": "3.12.9", "prefix": str(root), "physgate": False, "distributions": []}

    def run(argv: Sequence[str]) -> str | None:
        return json.dumps(answer)

    env = measure(str(python), [str(root)], native={}, forbidden={}, runner=run)
    assert env.python_version == "3.12.9"
