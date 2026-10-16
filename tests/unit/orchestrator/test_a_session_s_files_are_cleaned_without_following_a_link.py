"""The harness's end-of-session writes never follow a link a session's process planted.

At every session's end, and for every session at a resume, the harness removes the session's
credential files and redacts its captured stream. A process the session left running can
replace the session's directories and files with links before that happens. Before, the
removal followed a ``config`` link and deleted the login file wherever it led (on a real
machine, possibly its owner's own), and the redaction rewrote whatever ``stdout.jsonl`` led to.

Every file here is an inert stand-in in the test's own directory: a "login file" that is a line
of text, a "key" that is not one. No real credential path is named or touched.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from physgate.orchestrator.credentials import KEY_FILE, KEY_HELPER, LOGIN_FILE, remove_secrets
from physgate.orchestrator.dispatch import REDACTED, redact, write_record
from physgate.orchestrator.exceptions import InvocationError

SECRET = "inert-stand-in-not-a-credential"


def _session(tmp_path: Path) -> Path:
    """A session directory as the dispatcher lays it out, with stand-in credential files."""
    sdir = tmp_path / "run" / "sessions" / "s-1"
    (sdir / "state").mkdir(parents=True)
    (sdir / "config").mkdir()
    (sdir / "state" / KEY_FILE).write_text(SECRET)
    (sdir / "state" / KEY_HELPER).write_text("#!/bin/sh\necho stand-in\n")
    (sdir / "config" / LOGIN_FILE).write_text("stand-in login\n")
    (sdir / "stdout.jsonl").write_text(f'{{"t": "{SECRET}"}}\n')
    return sdir


def _elsewhere(tmp_path: Path) -> Path:
    """A directory outside the session, holding stand-ins under the credential files' names."""
    victim = tmp_path / "elsewhere"
    victim.mkdir()
    for name in (KEY_FILE, KEY_HELPER, LOGIN_FILE):
        (victim / name).write_text("not the session's\n")
    return victim


def test_a_session_s_own_credential_files_are_removed_and_its_stream_redacted(
    tmp_path: Path,
) -> None:
    sdir = _session(tmp_path)
    remove_secrets(sdir / "state", sdir / "config")
    redact(sdir / "stdout.jsonl", SECRET)
    assert not (sdir / "state" / KEY_FILE).exists()
    assert not (sdir / "state" / KEY_HELPER).exists()
    assert not (sdir / "config" / LOGIN_FILE).exists()
    data = (sdir / "stdout.jsonl").read_bytes()
    assert SECRET.encode() not in data and REDACTED in data


@pytest.mark.parametrize("directory", ["config", "state"])
def test_a_credential_directory_replaced_by_a_link_is_never_followed(
    tmp_path: Path, directory: str
) -> None:
    sdir = _session(tmp_path)
    victim = _elsewhere(tmp_path)
    (sdir / directory).rename(sdir / f"{directory}.moved")
    (sdir / directory).symlink_to(victim)
    with pytest.raises(InvocationError, match="not followed"):
        remove_secrets(sdir / "state", sdir / "config")
    assert sorted(p.name for p in victim.iterdir()) == sorted((KEY_FILE, KEY_HELPER, LOGIN_FILE))


def test_a_session_directory_replaced_by_a_link_is_never_followed(tmp_path: Path) -> None:
    sdir = _session(tmp_path)
    victim = tmp_path / "elsewhere-session"
    sdir.rename(victim)
    sdir.symlink_to(victim)
    with pytest.raises(InvocationError, match="not followed"):
        remove_secrets(sdir / "state", sdir / "config")
    with pytest.raises(InvocationError, match="not followed"):
        redact(sdir / "stdout.jsonl", SECRET)
    assert (victim / "config" / LOGIN_FILE).exists()
    assert SECRET in (victim / "stdout.jsonl").read_text()


def test_a_credential_file_replaced_by_a_link_removes_the_link_alone(tmp_path: Path) -> None:
    sdir = _session(tmp_path)
    victim = _elsewhere(tmp_path)
    (sdir / "config" / LOGIN_FILE).unlink()
    (sdir / "config" / LOGIN_FILE).symlink_to(victim / LOGIN_FILE)
    remove_secrets(sdir / "state", sdir / "config")
    assert not (sdir / "config" / LOGIN_FILE).is_symlink()
    assert (victim / LOGIN_FILE).read_text() == "not the session's\n"


def test_a_stream_replaced_by_a_link_is_never_written_through(tmp_path: Path) -> None:
    sdir = _session(tmp_path)
    victim = tmp_path / "elsewhere.txt"
    victim.write_text(f"{SECRET} stays where it is\n")
    (sdir / "stdout.jsonl").unlink()
    (sdir / "stdout.jsonl").symlink_to(victim)
    with pytest.raises(InvocationError, match="not written through"):
        redact(sdir / "stdout.jsonl", SECRET)
    assert victim.read_text() == f"{SECRET} stays where it is\n"


def test_an_end_record_is_never_written_into_a_session_directory_replaced_by_a_link(
    tmp_path: Path,
) -> None:
    sdir = _session(tmp_path)
    victim = tmp_path / "elsewhere-session"
    sdir.rename(victim)
    sdir.symlink_to(victim)
    with pytest.raises(OSError):  # noqa: PT011 - a link, refused by the kernel as ELOOP or ENOTDIR
        write_record(sdir.parent, sdir.name, {"exit": 0}, "ended.json")
    assert not (victim / "ended.json").exists()
    assert os.path.islink(sdir)
