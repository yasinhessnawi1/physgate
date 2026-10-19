"""The orchestrator's second line: a quantity named by a misspelling of a relation's is refused.

The hook refuses it as the session writes it; the orchestrator refuses it again when it reads
the attempt's proposals from the commit, with a role the session could not choose, so a file
that reached the commit by any other route is refused all the same. Every other uncatalogued
name is read and written, and the gate records it as unchecked. The store itself does not
refuse such names: a corpus written straight into a store is unaffected.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from physgate.orchestrator.apply import ProposalRefusedError, read_proposals

_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _node(name: str) -> dict[str, Any]:
    return {
        "id": "electrical.driver",
        "kind": "component",
        "domain": "electrical",
        "owner_role": "electrical",
        "quantities": {
            name: {"value": 1, "unit": "A", "source": "datasheet", "written_by": "electrical"}
        },
        "requirements": [],
        "constrains": [],
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-19T00:00:00Z",
        "no_change_justified": {},
    }


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    base = _commit(repo, {"m.txt": "one\n"}, "one")
    (tmp_path / "graph").mkdir()
    return repo, base


def test_a_proposal_with_a_catalogued_name_is_read(repo: tuple[Path, str], tmp_path: Path) -> None:
    root, base = repo
    path = ".physgate/proposals/electrical.driver.json"
    commit = _commit(root, {path: json.dumps(_node("current_limit"))}, "proposal")
    (found,) = read_proposals(root, base, commit, tmp_path / "graph")
    assert found["id"] == "electrical.driver"


def test_a_proposal_naming_an_uncatalogued_quantity_that_shadows_none_is_read(
    repo: tuple[Path, str], tmp_path: Path
) -> None:
    root, base = repo
    path = ".physgate/proposals/electrical.driver.json"
    commit = _commit(root, {path: json.dumps(_node("logic_voltage"))}, "proposal")
    (found,) = read_proposals(root, base, commit, tmp_path / "graph")
    assert "logic_voltage" in found["quantities"]


@pytest.mark.parametrize(
    ("name", "shadowed"),
    [
        ("currentlimit", "current_limit"),
        ("stall_currnt", "stall_current"),
        ("mess", "mass"),
        ("moss", "mass"),
        ("mask", "mass"),
    ],
)
def test_a_proposal_naming_a_near_spelling_of_a_relation_s_quantity_is_refused(
    repo: tuple[Path, str], tmp_path: Path, name: str, shadowed: str
) -> None:
    root, base = repo
    path = ".physgate/proposals/electrical.driver.json"
    commit = _commit(root, {path: json.dumps(_node(name))}, "proposal")
    with pytest.raises(ProposalRefusedError, match=f"{name} shadows {shadowed}"):
        read_proposals(root, base, commit, tmp_path / "graph")


def test_a_proposal_naming_a_misspelt_relation_quantity_is_refused_naming_both(
    repo: tuple[Path, str], tmp_path: Path
) -> None:
    root, base = repo
    path = ".physgate/proposals/electrical.driver.json"
    commit = _commit(root, {path: json.dumps(_node("supported_mas"))}, "proposal")
    with pytest.raises(ProposalRefusedError, match="supported_mas") as caught:
        read_proposals(root, base, commit, tmp_path / "graph")
    assert "shadows supported_mass" in str(caught.value)  # the relation's quantity, named
    assert caught.value.subject == "electrical.driver"


@pytest.mark.parametrize(
    "name", ["motor_current", "no_load_current", "idle_current", "max", "dry_mass"]
)
def test_a_different_name_is_read_and_written(
    repo: tuple[Path, str], tmp_path: Path, name: str
) -> None:
    root, base = repo
    path = ".physgate/proposals/electrical.driver.json"
    commit = _commit(root, {path: json.dumps(_node(name))}, "proposal")
    (found,) = read_proposals(root, base, commit, tmp_path / "graph")
    assert name in found["quantities"]
