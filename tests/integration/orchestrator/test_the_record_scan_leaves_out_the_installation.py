"""The end-of-run scan counts addresses in the run's records, not in its installation.

A driver builds the reviewer's ``physgate`` into ``install/`` under its output
directory: a virtual environment whose third-party packages carry their authors'
public addresses by the thousand. Counted as the run's, they buried the addresses the
run itself wrote (1610 counted, none written by the run). The address count and any
export of the records leave ``install/`` out. A credential is still looked for
everywhere, the installation included: leaving it out of that search would only hide
one.
"""

from __future__ import annotations

from pathlib import Path

from record_scan import INSTALL_DIRNAME, record_files, scan


def _tree(root: Path) -> None:
    metadata = root / INSTALL_DIRNAME / "lib" / "pkg" / "METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("Author-email: someone@example.org, other@example.net\n")
    record = root / "sessions" / "s" / "stdout.jsonl"
    record.parent.mkdir(parents=True)
    record.write_text('{"text": "Author: t <t@example.invalid>"}\n')
    nested = root / "made" / "a" / INSTALL_DIRNAME / "note.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("reach me at n@example.invalid\n")


def test_the_address_count_leaves_out_the_installation(tmp_path: Path) -> None:
    _tree(tmp_path)
    # The stream's address and the one under a deeper directory of that name are the run's.
    assert scan(tmp_path, "not-a-token")["emails_found"] == 2


def test_a_credential_is_still_looked_for_in_the_installation(tmp_path: Path) -> None:
    _tree(tmp_path)
    leaked = tmp_path / INSTALL_DIRNAME / "bin" / "activate"
    leaked.parent.mkdir(parents=True)
    leaked.write_text("TOKEN=the-run-token sk-ant-x oat01-y\n")
    counts = scan(tmp_path, "the-run-token")
    assert (counts["token"], counts["sk-ant-"], counts["oat01"]) == (1, 1, 1)


def test_an_export_of_the_records_holds_no_file_of_the_installation(tmp_path: Path) -> None:
    _tree(tmp_path)
    exported = {p.relative_to(tmp_path).as_posix() for p in record_files(tmp_path)}
    assert exported == {"sessions/s/stdout.jsonl", "made/a/install/note.txt"}
