"""``physgate knowledge promote``, wired through the real top-level command."""

from __future__ import annotations

from pathlib import Path

import pytest

from physgate.cli import main
from physgate.knowledge import staging


class _Stdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_the_command_is_registered_under_the_top_level_parser() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["knowledge", "promote"])  # missing the required candidate_id
    assert exc.value.code == 2  # argparse's own usage error, not a crash


def test_promote_through_the_command_defaults_by_to_the_os_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("getpass.getuser", lambda: "the-os-user")
    candidate_id_path = staging.append("skill", "content\n", "ep-1", domain="control")
    candidate_id = candidate_id_path.stem
    code = main(["knowledge", "promote", candidate_id])
    out = capsys.readouterr().out
    assert code == 0
    assert "the-os-user" in out
    assert (tmp_path / "knowledge" / "control" / "skill.md").read_text() == "content\n"


def test_promote_through_the_command_honours_an_explicit_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    candidate_id_path = staging.append("skill", "content\n", "ep-1", domain="control")
    candidate_id = candidate_id_path.stem
    code = main(["knowledge", "promote", candidate_id, "--by", "yasin"])
    assert code == 0
    assert "yasin" in capsys.readouterr().out


def test_promote_through_the_command_refuses_non_interactively_and_prints_why(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin", _Stdin(tty=False))
    candidate_id_path = staging.append("skill", "content\n", "ep-1", domain="control")
    candidate_id = candidate_id_path.stem
    code = main(["knowledge", "promote", candidate_id, "--by", "yasin"])
    assert code == 1
    assert "refused" in capsys.readouterr().out
    assert staging.candidates("skill") != ()  # still staged, nothing promoted
