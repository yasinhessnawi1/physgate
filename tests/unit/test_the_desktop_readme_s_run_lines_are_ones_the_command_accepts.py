"""The two lines the desktop README gives for making a run are ones ``physgate`` accepts.

No screen of the app shows a command, so the README is where a developer finds how a run is
made by hand. Each ``physgate`` line in it is parsed by the real command's own parser, with its
placeholders filled in: a flag that was renamed or became required turns this red.
"""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

import pytest

from physgate.cli import main

README = Path(__file__).resolve().parents[2] / "desktop" / "README.md"


class _CapturedError(Exception):
    """Raised in place of parsing, carrying the parser the command built."""

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__()
        self.parser = parser


def _parser(monkeypatch: pytest.MonkeyPatch) -> argparse.ArgumentParser:
    def capture(self: argparse.ArgumentParser, *args: object, **kwargs: object) -> None:
        raise _CapturedError(self)

    with monkeypatch.context() as patched:
        patched.setattr(argparse.ArgumentParser, "parse_args", capture)
        with pytest.raises(_CapturedError) as caught:
            main([])
    return caught.value.parser


def _readme_lines() -> list[str]:
    return [
        line.strip()
        for line in README.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*physgate (decompose|run) ", line)
    ]


def _filled(line: str) -> list[str]:
    """The line's words with each placeholder given a value of the kind it stands for."""
    line = line.replace("<seed>", "7")
    return shlex.split(re.sub(r"<[^>]+>", "x", line))[1:]


def test_the_readme_gives_both_lines() -> None:
    verbs = [line.split()[1] for line in _readme_lines()]
    assert verbs == ["decompose", "run"]


@pytest.mark.parametrize("line", _readme_lines())
def test_each_line_parses_with_the_command_s_own_parser(
    monkeypatch: pytest.MonkeyPatch, line: str
) -> None:
    parser = _parser(monkeypatch)
    parsed = parser.parse_args(_filled(line))
    assert parsed.command == line.split()[1]


def test_a_line_missing_a_required_flag_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = _parser(monkeypatch)
    run = next(line for line in _readme_lines() if line.startswith("physgate run "))
    without = re.sub(r"--review-root \S+", "", run)
    with pytest.raises(SystemExit):
        parser.parse_args(_filled(without))
